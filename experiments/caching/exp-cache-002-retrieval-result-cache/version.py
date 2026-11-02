"""R-B1 retrieval-result cache: reuse an earlier lookup's chunks for the same
query (final plan R-B1; H-3, FR-XCACHE-01, FR-XCACHE-04, QA-PRIV;
ADR-0037).

A **retrieval** cache is not an answer cache. A reused lookup avoids only that
lookup's recorded fee; answer generation still runs and still costs input,
output and cached tokens. So ``apply`` lowers only ``block_fees``, never sets
``served_from_cache`` and never touches ``block_token_cost``. Context and
routing versions still apply to these rows. It adds the B-owned columns
``retrieval_reused``, ``retrieval_lookups_skipped`` and ``retrieval_fee_avoided``
(ADR-0037, pending the S-1 owner's confirmation).

Evidence: **measured potential**, conditional on Metis-Auto being able to
intercept retrieval. A hit is a *candidate* reuse. Agreement with the later real
lookup is measured offline, and production correctness is not measured.

**Lookups frame** (one row per logged query lookup; built by the run script,
kept in memory, never written to a tracked file):

- ``req``: label of the request row in the requests frame;
- ``pos``: position of the query in its message;
- ``t_arrive`` (lookup time, the user message) and ``t_done`` (result available,
  the logged answer time: the log has no retrieval latency, so this is the
  conservative choice). Timestamps are naive (Q-06);
- ``tenant``, ``bot``: the reuse scope. Equal query text in another tenant or bot
  never matches;
- ``corpus_version``: ``None`` when unknown (true for the whole dataset today);
- ``settings``: retrieval settings as one string, ``None`` when unknown;
- ``query_key``: ``query_key(text)``, a fingerprint of text normalised only with
  ``normalize_safe``; ``None`` when the query is missing or empty;
- ``chunks``: tuple of ``(chunk_id, content_hash)``, hash ``None`` when unknown;
- ``fee``: the recorded fee of this lookup (``attribute_fees``), NaN when it
  cannot be attributed.

**Replay.** Lookups run in ``t_arrive`` order. Ties keep the frame's order, which
the loader sets to request order, then ``pos``. The store is read before the
current lookup is inserted. An entry becomes visible only when its ``t_done`` is
strictly before the lookup's ``t_arrive``, so a lookup never sees itself, its own
request or the future. The store starts empty at the start of the frame (cold
start; the first lookup of every key is a miss). A miss, an expired entry, a
guard block and an ineligible lookup all perform the real lookup and insert its
result. A hit inserts nothing (the lookup was skipped). ``ttl`` expires entries
``ttl`` after insertion.

**Eligibility** (checked before the store; failing lookups are ``ineligible``
and are performed): a query (``no_query``), a tenant and bot (``no_scope``),
settings (``no_settings``), an attributable fee (``fee_unattributed``), and
freshness evidence. ``ttl=None`` means *no backstop expiry*. It is allowed only
for lookups with a known corpus version. Without a version and without a TTL
nothing bounds staleness, so the lookup is ineligible
(``no_freshness_evidence``). With a TTL and no version a hit has
``basis="ttl_only"``. It is never reported as version-checked.

**Guard.** ``ctx.guard.refusal`` (or ``allows``) is called on the versioned key
before a hit counts. A refused candidate is a ``guard_block``. There is no hit
without a guard.

**Agreement metric** (declared before any run): content-consistent Jaccard
overlap between the cached chunk set and the later real lookup's chunk set, over
``(chunk_id, content_hash)`` pairs. Order and duplicates are ignored. The same ID
with a changed hash is in the union twice and in the intersection never, so it
counts as disagreement. Any unknown hash on either side makes the agreement
unknown (never 1). Both sets empty is unknown (not evaluable). One side empty is
0. Aggregate: mean over evaluable hits, plus the share of hits at or above 0.9.
The decision rule "agreement >= 0.9" refers to that mean, on evaluable hits, with
the unknown count beside it.

**Shadow check.** ``guard.shadow_sample`` selects hit rows at ``shadow_rate``
(no default: the script passes ``[cache_guard] shadow_rate`` from
``config/evaluation/sprint.toml``). Offline, a selected hit's later
real lookup is the logged lookup itself. The result is ``agree`` (>= 0.9),
``disagree`` or ``unknown`` (no evaluable agreement).
"""

from __future__ import annotations

import heapq
import json
import math
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import pandas as pd

from metis_auto.analysis.cache_guard import versioned_key
from metis_auto.analysis.text_features import fingerprint, normalize_safe

Chunk = tuple[str, str | None]

LOOKUP_COLUMNS = (
    "req",
    "pos",
    "t_arrive",
    "t_done",
    "tenant",
    "bot",
    "corpus_version",
    "settings",
    "query_key",
    "chunks",
    "fee",
)
UNKNOWN_CORPUS = "corpus-version-unknown"
NO_CHUNK_ID = "<no-chunk-id>"
AGREEMENT_PASS = 0.9
_SEP = "\x1f"


def _missing(value: object) -> bool:
    if value is None or value is pd.NA:
        return True
    return isinstance(value, float) and math.isnan(value)


def query_key(text: str | None) -> str | None:
    """Fingerprint of ``normalize_safe(text)``; ``None`` for missing or blank."""
    if not isinstance(text, str):
        return None
    norm = normalize_safe(text)
    return fingerprint(norm) if norm else None


def lookup_key(
    tenant: object,
    bot: object,
    corpus_version: object,
    settings: object,
    query: object,
) -> str | None:
    """The cache key body: tenant + bot + corpus version + settings + query.

    ``None`` when any part except the corpus version is missing. An unknown
    corpus version gets an explicit marker, so it never equals a known one.
    """
    if any(_missing(v) for v in (tenant, bot, settings, query)):
        return None
    version = UNKNOWN_CORPUS if _missing(corpus_version) else str(corpus_version)
    parts = ("tenant", str(tenant), "bot", str(bot), "corpus", version)
    parts += ("settings", str(settings), "query", str(query))
    return fingerprint(_SEP.join(parts))


def lookups_from_rag(
    raw: str | None,
) -> list[tuple[int, str | None, tuple[Chunk, ...]]]:
    """``(pos, query_key, chunks)`` per logged query of one message's ``rag``
    JSON, with no text kept: the query becomes ``query_key`` and each chunk
    ``(chunk_id, fingerprint(content.strip()))`` (the derived chunk table's
    ``h_exact`` rule). Missing content or ID gives an unknown hash. Missing,
    malformed or non-list JSON gives no lookups; non-dict entries are skipped.
    """
    if not isinstance(raw, str) or not raw:
        return []
    try:
        items = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(items, list):
        return []
    out = []
    for pos, item in enumerate(i for i in items if isinstance(i, dict)):
        chunks = []
        for ch in item.get("relevantChunks") or []:
            ch = ch if isinstance(ch, dict) else {}
            cid, content = ch.get("id"), ch.get("content")
            if not isinstance(cid, str) or not cid:
                chunks.append((NO_CHUNK_ID, None))
            elif isinstance(content, str) and content.strip():
                chunks.append((cid, fingerprint(content.strip())))
            else:
                chunks.append((cid, None))
        out.append((pos, query_key(item.get("query")), tuple(chunks)))
    return out


def attribute_fees(
    n_lookups: int, per_call_amounts: Sequence[float]
) -> tuple[float, ...] | None:
    """Recorded fee per lookup of one message, or ``None`` if unsupported.

    Supported only when the message has exactly one per-call billing item per
    logged query and all its per-call amounts are equal, so each lookup's fee is
    that recorded amount and no item is counted twice. Billing items do not say
    which query they belong to, so unequal amounts cannot be mapped.
    """
    amounts = [float(a) for a in per_call_amounts]
    if n_lookups != len(amounts) or any(math.isnan(a) for a in amounts):
        return None
    if amounts and max(amounts) != min(amounts):
        return None
    return tuple(amounts)


def agreement(cached: Iterable[Chunk], real: Iterable[Chunk]) -> float | None:
    """The declared agreement metric (module docstring)."""
    a, b = set(cached), set(real)
    if any(h is None for _, h in a | b):
        return None
    if not a and not b:
        return None
    return len(a & b) / len(a | b)


def _key_of(row: Any) -> str | None:
    return lookup_key(
        row.tenant, row.bot, row.corpus_version, row.settings, row.query_key
    )


def _ineligible(row: Any, ttl: pd.Timedelta | None) -> str | None:
    if _missing(row.query_key):
        return "no_query"
    if _missing(row.tenant) or _missing(row.bot):
        return "no_scope"
    if _missing(row.settings):
        return "no_settings"
    if _missing(row.fee):
        return "fee_unattributed"
    if ttl is None and _missing(row.corpus_version):
        return "no_freshness_evidence"
    return None


def _refusal(guard: Any, key: str, bot: str) -> str | None:
    if hasattr(guard, "refusal"):
        return guard.refusal(key, bot)
    return None if guard.allows(key, bot) else "refused"


class RetrievalResultCache:
    """``StepVersion``-shaped retrieval-result cache (``step = "cache"``)."""

    step = "cache"

    def __init__(
        self,
        ttl: pd.Timedelta | None,
        *,
        lookups: pd.DataFrame,
        shadow_rate: float,
    ) -> None:
        if ttl is not None and ttl <= pd.Timedelta(0):
            raise ValueError("ttl must be positive or None")
        missing = [c for c in LOOKUP_COLUMNS if c not in lookups]
        if missing and len(lookups):
            raise ValueError(f"lookups lack columns {missing}")
        self.ttl = ttl
        self.lookups = lookups
        self.shadow_rate = shadow_rate
        days = "none" if ttl is None else f"{ttl / pd.Timedelta(days=1):g}d"
        self.name = f"retrieval_result_cache.ttl_{days}"

    def replay(self, ctx: Any, requests: pd.Index | None = None) -> pd.DataFrame:
        """Per-lookup outcomes (index = the lookups' index): ``status`` (``hit``,
        ``miss``, ``guard_block``, ``ineligible``), ``reason``, ``basis``,
        ``agreement``, ``fee_avoided``, ``shadow``, ``shadow_result``.

        ``requests`` restricts the replay to lookups of those request labels;
        other lookups neither look up nor insert.
        """
        guard = getattr(ctx, "guard", None)
        if guard is None:
            raise ValueError("a cache guard is required before any hit counts")
        lk = self.lookups
        if requests is not None and len(lk):
            lk = lk[lk["req"].isin(requests)]
        lk = lk.sort_values("t_arrive", kind="stable") if len(lk) else lk
        n = len(lk)
        status = ["miss"] * n
        reason: list[str | None] = [None] * n
        basis: list[str | None] = [None] * n
        agree: list[float | None] = [None] * n
        fee_avoided = [0.0] * n
        hit_keys: list[str | None] = [None] * n
        pending: list[tuple[pd.Timestamp, int, str, tuple[Chunk, ...]]] = []
        store: dict[str, tuple[pd.Timestamp, tuple[Chunk, ...]]] = {}
        for i, row in enumerate(lk.itertuples(index=False)):
            while pending and pending[0][0] < row.t_arrive:
                t_done, _, key, chunks = heapq.heappop(pending)
                store[key] = (t_done, chunks)
            key = _key_of(row)
            chunks = tuple(row.chunks)
            why = _ineligible(row, self.ttl)
            served = False
            if why is not None:
                status[i], reason[i] = "ineligible", why
            else:
                assert key is not None
                entry = store.get(key)
                if entry is None:
                    reason[i] = "cold"
                elif self.ttl is not None and row.t_arrive - entry[0] > self.ttl:
                    reason[i] = "expired"
                else:
                    guarded = versioned_key(guard.key_version, key)
                    refused = _refusal(guard, guarded, row.bot)
                    if refused is not None:
                        status[i], reason[i] = "guard_block", refused
                    else:
                        served = True
                        status[i] = "hit"
                        known = not _missing(row.corpus_version)
                        basis[i] = "version" if known else "ttl_only"
                        agree[i] = agreement(entry[1], chunks)
                        fee_avoided[i] = float(row.fee)
                        hit_keys[i] = guarded
            if not served and key is not None:
                heapq.heappush(pending, (row.t_done, i, key, chunks))
        out = pd.DataFrame(
            {
                "req": lk["req"].to_numpy() if n else [],
                "status": status,
                "reason": pd.Series(reason, dtype=object),
                "basis": pd.Series(basis, dtype=object),
                "agreement": pd.Series(agree, dtype=object),
                "fee_avoided": fee_avoided,
            },
        )
        out.index = lk.index
        keys = pd.Series(hit_keys, index=lk.index, dtype=object)
        out["shadow"] = guard.shadow_sample(keys, self.shadow_rate, ctx.seed)
        out["shadow_result"] = pd.Series(
            [
                _shadow_result(a) if s else None
                for a, s in zip(out["agreement"], out["shadow"], strict=True)
            ],
            index=out.index,
            dtype=object,
        )
        return out.reindex(self.lookups.index.intersection(out.index, sort=False))

    def apply(self, req: pd.DataFrame, ctx: Any) -> pd.DataFrame:
        """A copy of ``req`` (same index) with the fee block lowered by the
        recorded fee of skipped lookups on LLM rows; workflow rows unchanged."""
        if "llm_request" not in req:
            raise ValueError("llm_request is missing; run the scope step first")
        if req["llm_request"].isna().any():
            raise ValueError("llm_request has unknown rows; unknown is not False")
        active = req.index[req["llm_request"].astype(bool).to_numpy()]
        outcomes = self.replay(ctx, requests=active)
        hits = outcomes[outcomes["status"] == "hit"]
        skipped = hits.groupby("req").size()
        avoided = hits.groupby("req")["fee_avoided"].agg(
            lambda s: math.fsum(s.to_numpy(dtype=float))
        )
        out = req.copy()
        out["retrieval_lookups_skipped"] = (
            skipped.reindex(out.index).fillna(0).astype(int)
        )
        out["retrieval_reused"] = out["retrieval_lookups_skipped"] > 0
        out["retrieval_fee_avoided"] = avoided.reindex(out.index).fillna(0.0)
        if "block_fees" in out:
            after = out["block_fees"] - out["retrieval_fee_avoided"]
            if (after < -1e-12).any():
                raise ValueError(
                    "fee avoided exceeds the recorded fee block on some rows; "
                    "the fee block and the lookup fees must come from one source"
                )
            out["block_fees"] = after.where(after.isna() | (after > 0), 0.0)
        return out


def _shadow_result(value: object) -> str:
    if _missing(value):
        return "unknown"
    return "agree" if float(value) >= AGREEMENT_PASS else "disagree"


def summarise(outcomes: pd.DataFrame) -> dict[str, Any]:
    """Content-free counts of a replay: statuses, reasons, bases, fee avoided,
    the agreement distribution and the shadow-check result."""
    hits = outcomes[outcomes["status"] == "hit"]
    values = np.array([float(a) for a in hits["agreement"] if not _missing(a)])
    agreement_summary: dict[str, Any] = {
        "n_hits": len(hits),
        "n_evaluable": len(values),
        "n_unknown": len(hits) - len(values),
    }
    if len(values):
        agreement_summary.update(
            mean=float(values.mean()),
            share_at_least_0_9=float((values >= AGREEMENT_PASS).mean()),
            p10=float(np.percentile(values, 10)),
            p50=float(np.percentile(values, 50)),
            share_exact=float((values == 1.0).mean()),
            share_zero=float((values == 0.0).mean()),
        )
    shadow = outcomes[outcomes["shadow"].astype(bool)]
    counts = Counter(shadow["shadow_result"])
    return {
        "n_lookups": len(outcomes),
        "status": dict(Counter(outcomes["status"])),
        "reasons": dict(Counter(r for r in outcomes["reason"] if r is not None)),
        "basis": dict(Counter(b for b in hits["basis"] if b is not None)),
        "fee_avoided": math.fsum(outcomes["fee_avoided"].to_numpy(dtype=float)),
        "agreement": agreement_summary,
        "shadow": {
            "sampled": len(shadow),
            "agree": counts.get("agree", 0),
            "disagree": counts.get("disagree", 0),
            "unknown": counts.get("unknown", 0),
        },
    }


def repeat_rates(
    lookups: pd.DataFrame,
    windows_days: Sequence[int],
    scored: pd.Index | None = None,
) -> dict[int, float]:
    """Free check: share of keyed lookups whose key was already looked up and
    completed (``t_done`` strictly before this ``t_arrive``) within each window.

    The key is ``lookup_key`` with the unknown-corpus marker where no version
    is known. Lookups without a key are left out of the denominator. Every
    lookup is history; with ``scored`` (request labels) only those requests'
    lookups are in the denominator. Run it on tune-period data only: it sets
    the TTL.
    """
    if not len(lookups):
        return {w: float("nan") for w in windows_days}
    lk = lookups.sort_values("t_arrive", kind="stable")
    latest: dict[str, pd.Timestamp] = {}
    pending: list[tuple[pd.Timestamp, int, str]] = []
    gaps: list[pd.Timedelta | None] = []
    for i, row in enumerate(lk.itertuples(index=False)):
        while pending and pending[0][0] < row.t_arrive:
            t_done, _, k = heapq.heappop(pending)
            if k not in latest or latest[k] < t_done:
                latest[k] = t_done
        key = _key_of(row)
        if key is None:
            continue
        if scored is None or row.req in scored:
            prev = latest.get(key)
            gaps.append(None if prev is None else row.t_arrive - prev)
        heapq.heappush(pending, (row.t_done, i, key))
    if not gaps:
        return {w: float("nan") for w in windows_days}
    return {
        w: sum(g is not None and g <= pd.Timedelta(days=w) for g in gaps) / len(gaps)
        for w in windows_days
    }


def chunk_churn(lookups: pd.DataFrame) -> pd.DataFrame:
    """Free check: per bot, distinct chunk IDs, IDs seen with more than one
    known content hash (``n_changed``) and IDs with an unknown hash. Sets the
    freshness rule; run it on tune data only."""
    rows = [
        (bot, cid, h)
        for bot, chunks in zip(lookups["bot"], lookups["chunks"], strict=True)
        for cid, h in chunks
    ]
    frame = pd.DataFrame(rows, columns=["bot", "chunk_id", "hash"])
    if frame.empty:
        return pd.DataFrame(
            columns=["bot", "n_chunk_ids", "n_changed", "n_hash_unknown"]
        )
    known = frame.dropna(subset=["hash"])
    distinct = known.groupby(["bot", "chunk_id"])["hash"].nunique()
    changed = (distinct > 1).groupby(level="bot").sum()
    unknown = frame[frame["hash"].isna()].groupby("bot")["chunk_id"].nunique()
    out = frame.groupby("bot")["chunk_id"].nunique().rename("n_chunk_ids").to_frame()
    out["n_changed"] = changed.reindex(out.index).fillna(0).astype(int)
    out["n_hash_unknown"] = unknown.reindex(out.index).fillna(0).astype(int)
    out["share_changed"] = out["n_changed"] / out["n_chunk_ids"]
    return out.reset_index()
