"""EXP-CACHE-004: session memo + greeting skip gate, a cache ``StepVersion``
(final plan R-C1; FR-REQ-06, FR-XCACHE-01, FR-ACCT-02, H-3, X1; Review Focus 1
and 4; ADR-0036, ADR-0037, ADR-0038, ADR-0039).

Two rules decide, per LLM retrieval turn of a session (in ``turn`` order), whether
the turn's lookup runs:

- **Greeting skip gate** (*heuristic*). The user message is phatic when its
  ``u_h_norm`` equals ``fingerprint(normalize_safe(p))`` for a word ``p`` of the
  list, or of ``p`` plus one trailing mark from ``PHATIC_MARKS``. Exact match
  only. Turn 0, a message with attachments (or unknown attachments) and a
  workflow request are never skipped. A skipped lookup sends no chunks: it saves
  its recorded fees and its chunk tokens (every chunk row's characters x
  ``tokens_per_char``, uncached input only, ADR-0038).
- **Session memo** (*simulation*). The memo holds the query fingerprints and the
  chunks of the session's **last lookup that actually ran** (owner decision
  2026-11-02; a reused or skipped turn never updates it). Trigger: Jaccard
  between this turn's set of normalised query fingerprints and the memo's set,
  reuse when it is ``>= overlap_threshold``. The decision uses only what exists
  before this turn's lookup (FR-REQ-06): the turn's own queries, never its
  chunks. Reused chunks are still sent, so a reuse saves fees only (ADR-0037
  item 1).

A lookup is skippable only when its fee is attributable (ADR-0037 item 3: one
recorded per-call item per logged query, all equal); otherwise it runs
(``fee_unattributed``) and updates the memo. With ``ctx.guard`` set, a refused
key also runs (``guard_block``). ``served_from_cache`` is never set: the answer
is still generated, so context and routing still apply.

Agreement (ADR-0037 item 5): Jaccard over ``(chunk_id, h_exact)`` between the
reused chunks and the turn's real logged chunks; an unknown hash or two empty
sets is unknown. A changed text under one chunk ID is a disagreement (Review
Focus 4). The greeting gate has no chunk agreement; the share of skipped turns
whose logged answer cited a source (``a_citation_n > 0``) is a *proxy* risk
indicator. Hits are *candidate* hits.

Candidate code: loaded by file path only (scripts, tests); ``metis_auto`` never
imports it.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from metis_auto.analysis.baselines_full import (
    REPRICED_KEYS,
    best_single_cheap_model,
    lower_uncached_input,
    repriced_row_costs,
    token_counts,
)
from metis_auto.analysis.cache_guard import versioned_key
from metis_auto.analysis.lever_result import LeverResult, Manifest
from metis_auto.analysis.levers import (
    BLOCKS,
    ReplayContext,
    Step,
    block_column,
    summarise_slices,
)
from metis_auto.analysis.stats import cluster_bootstrap_ratio
from metis_auto.analysis.text_features import fingerprint, normalize_safe

VERSION_ID = "cache.session_memo_gate"
EVIDENCE = "simulation"
PHATIC_MARKS = ("!", ".", "?", "؟")
THRESHOLDS = (0.5, 0.8, 1.0)
AGREEMENT_PASS = 0.9
NO_CHUNK_ID = "<no-chunk-id>"
_SEP = "\x1f"

STATUSES = (
    "no_lookup",
    "performed",
    "reused",
    "skipped_phatic",
    "fee_unattributed",
    "guard_block",
)
SKIPPED = ("reused", "skipped_phatic")
SAVED_TOKENS = "memo_saved_input_tokens"
SAVING_KNOWN = "memo_saving_known"
SAVING_UNKNOWN = "memo_saving_unknown"
DECISION_COLUMNS = (
    "memo_status",
    "memo_overlap",
    "memo_agreement",
    "memo_lookups_skipped",
    "memo_fee_avoided",
    "memo_saved_chars",
)


def phatic_keys(words: Iterable[str]) -> frozenset[str]:
    """``u_h_norm`` values of the phatic words, bare or with one trailing mark."""
    texts = [w + m for w in words for m in ("", *PHATIC_MARKS)]
    return frozenset(fingerprint(normalize_safe(t)) for t in texts if t.strip())


def attribute_fees(
    n_lookups: int, amounts: Sequence[float]
) -> tuple[float, ...] | None:
    """Recorded fee per lookup, or ``None`` when it cannot be attributed
    (ADR-0037 item 3: one per-call item per logged query, all amounts equal)."""
    values = [float(a) for a in amounts]
    if n_lookups <= 0 or n_lookups != len(values) or any(map(math.isnan, values)):
        return None
    if max(values) != min(values):
        return None
    return tuple(values)


def agreement(cached: Iterable[tuple], real: Iterable[tuple]) -> float | None:
    """Jaccard over ``(chunk_id, h_exact)``; unknown hash or both empty: None."""
    a, b = set(cached), set(real)
    if any(h is None for _, h in a | b) or not (a or b):
        return None
    return len(a & b) / len(a | b)


def fee_blocks(req: pd.DataFrame, per_call: pd.DataFrame) -> pd.DataFrame:
    """``block_fees`` = the message's recorded per-call sum (0 with none),
    ``block_token_cost`` = recorded total minus that (ADR-0037 item 2). Both
    unknown when the total is unknown."""
    out = req.copy()
    fee = per_call.groupby("message_id")["amount"].agg(
        lambda s: math.fsum(s.to_numpy(dtype=float))
    )
    total = out["a_bill_totalCost"]
    fees = out["ai_message_id"].map(fee).fillna(0.0).where(total.notna())
    if ((total - fees) < -1e-9).any():
        raise ValueError("per-call fees exceed the recorded total on some rows")
    out[block_column("fees")] = fees
    out[block_column("token_cost")] = (total - fees).clip(lower=0.0)
    return out


def build_lookups(
    req: pd.DataFrame,
    query_fps: pd.DataFrame,
    chunks: pd.DataFrame,
    per_call: pd.DataFrame,
) -> pd.DataFrame:
    """One row per request with a logged lookup (``a_rag_n_queries > 0``),
    indexed by ``ai_message_id``: ``query_fps`` (a tuple, ``None`` when any query
    has no fingerprint), ``chunks`` (``(chunk_id, h_exact)`` tuples, hash
    ``None`` when unknown), ``chunk_chars`` (every chunk row, copies included)
    and ``fees`` (``attribute_fees``)."""
    rag = req.loc[req["a_rag_n_queries"] > 0, ["ai_message_id", "a_rag_n_queries"]]
    rag = rag.drop_duplicates("ai_message_id").set_index("ai_message_id")
    fps = dict(zip(query_fps["message_id"], query_fps["query_fps"], strict=True))
    ch = chunks[chunks["message_id"].isin(rag.index)]
    pairs = pd.Series(
        list(
            zip(
                ch["chunk_id"]
                .astype(object)
                .where(ch["chunk_id"].notna(), NO_CHUNK_ID),
                ch["h_exact"].astype(object).where(ch["h_exact"].notna(), None),
                strict=True,
            )
        ),
        index=ch.index,
        dtype=object,
    )
    by_msg = pairs.groupby(ch["message_id"]).agg(tuple).to_dict()
    chars = ch["n_chars"].fillna(0).groupby(ch["message_id"]).sum().to_dict()
    amounts = per_call.groupby("message_id")["amount"].agg(list).to_dict()
    rows = []
    for msg, n in rag["a_rag_n_queries"].items():
        q = fps.get(msg)
        q = tuple(q) if q is not None and len(q) == n else None
        rows.append(
            (
                msg,
                q,
                by_msg.get(msg, ()),
                int(chars.get(msg, 0)),
                attribute_fees(int(n), amounts.get(msg, [])),
            )
        )
    return pd.DataFrame(
        rows, columns=["message_id", "query_fps", "chunks", "chunk_chars", "fees"]
    ).set_index("message_id")


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def _refusal(guard: Any, key: str, bot: object) -> str | None:
    if guard is None:
        return None
    guarded = versioned_key(guard.key_version, fingerprint(key))
    if hasattr(guard, "refusal"):
        return guard.refusal(guarded, str(bot))
    return None if guard.allows(guarded, str(bot)) else "refused"


class SessionMemo:
    """Cache version: skip phatic lookups and reuse the session's last lookup.

    ``overlap_threshold`` has no default; ``None`` refuses to run. ``lookups``
    comes from ``build_lookups``. With ``tokens_per_char`` a skipped turn's
    chunk characters become saved uncached input tokens; with
    ``input_rate_per_m`` (recorded units per 1M input tokens, per model) they
    also lower ``block_token_cost`` (``as_logged``). No rate: the saving is
    unknown (``SAVING_KNOWN`` False), never zero.
    """

    step: Step = "cache"

    def __init__(
        self,
        overlap_threshold: float | None,
        phatic_words: frozenset[str],
        *,
        lookups: pd.DataFrame,
        tokens_per_char: float | None = None,
        input_rate_per_m: Mapping[str, float] | None = None,
        cached_separately: frozenset[str] = frozenset(),
    ) -> None:
        t = overlap_threshold
        if t is None or isinstance(t, bool) or not 0.0 < float(t) <= 1.0:
            raise ValueError(
                "overlap_threshold has no default: pass a value in (0, 1] chosen "
                "on the tune split"
            )
        if input_rate_per_m is not None and tokens_per_char is None:
            raise ValueError("input_rate_per_m needs tokens_per_char")
        self.overlap_threshold = float(t)
        self.phatic_words = frozenset(phatic_words)
        self._keys = phatic_keys(self.phatic_words)
        self._lookups = lookups.to_dict("index")
        self._tokens_per_char = tokens_per_char
        self._rates = input_rate_per_m
        self._cached_separately = cached_separately
        self.name = f"exp-cache-004-session-memo-gate.t{self.overlap_threshold:g}"

    def _phatic(self, row: Any) -> bool:
        att = row.u_att_n
        return (
            row.turn != 0
            and not pd.isna(att)
            and att == 0
            and isinstance(row.u_h_norm, str)
            and row.u_h_norm in self._keys
        )

    def decide(self, req: pd.DataFrame, guard: Any = None) -> pd.DataFrame:
        """``DECISION_COLUMNS`` per row of ``req`` (same index). Workflow rows
        get no status. Sessions replay in ``turn`` (then ``a_order``) order."""
        order = [c for c in ("session_id", "turn", "a_order") if c in req]
        rows = req.sort_values(order, kind="stable")
        bots = rows["bot_id"] if "bot_id" in rows else pd.Series("", index=rows.index)
        out: dict[object, tuple] = {}
        session, memo = object(), None
        for label, row, bot in zip(
            rows.index, rows.itertuples(index=False), bots, strict=True
        ):
            if row.session_id != session:
                session, memo = row.session_id, None
            if not bool(row.llm_request):
                out[label] = (None, np.nan, np.nan, 0, 0.0, 0)
                continue
            lk = self._lookups.get(row.ai_message_id)
            if lk is None:
                out[label] = ("no_lookup", np.nan, np.nan, 0, 0.0, 0)
                continue
            queries = None if lk["query_fps"] is None else frozenset(lk["query_fps"])
            fees = lk["fees"]
            overlap, status = np.nan, "performed"
            if self._phatic(row):
                status = "skipped_phatic"
                key = f"phatic{_SEP}{row.u_h_norm}"
            elif memo is not None and queries and memo[0]:
                overlap = _jaccard(queries, memo[0])
                if overlap >= self.overlap_threshold:
                    status = "reused"
                    key = _SEP.join(("memo", str(row.session_id), *sorted(queries)))
            if status in SKIPPED:
                if fees is None:
                    status = "fee_unattributed"
                elif _refusal(guard, key, bot) is not None:
                    status = "guard_block"
            if status == "reused":
                agree = agreement(memo[1], lk["chunks"])
                out[label] = (status, overlap, agree, len(fees), math.fsum(fees), 0)
            elif status == "skipped_phatic":
                chars = lk["chunk_chars"]
                out[label] = (
                    status,
                    overlap,
                    np.nan,
                    len(fees),
                    math.fsum(fees),
                    chars,
                )
            else:
                memo = (queries, lk["chunks"])
                out[label] = (status, overlap, np.nan, 0, 0.0, 0)
        frame = pd.DataFrame.from_dict(out, orient="index", columns=DECISION_COLUMNS)
        frame = frame.reindex(req.index)
        frame["memo_status"] = frame["memo_status"].astype(object)
        frame["memo_agreement"] = frame["memo_agreement"].astype(float)
        return frame

    def apply(self, req: pd.DataFrame, ctx: ReplayContext) -> pd.DataFrame:
        """A copy of ``req`` (same index): ``DECISION_COLUMNS``, ``block_fees``
        lowered by the fees avoided, and for skipped phatic turns the chunk
        tokens (``SAVED_TOKENS``) and their recorded cost."""
        if "llm_request" not in req or req["llm_request"].isna().any():
            raise ValueError("llm_request is missing or unknown; run the scope step")
        out = req.copy()
        decided = self.decide(req, getattr(ctx, "guard", None))
        for col in DECISION_COLUMNS:
            out[col] = decided[col]
        avoided = out["memo_fee_avoided"].fillna(0.0)
        if block_column("fees") in out:
            after = out[block_column("fees")] - avoided
            if (after < -1e-12).any():
                raise ValueError("fee avoided exceeds the recorded fee block")
            out[block_column("fees")] = after.where(after.isna() | (after > 0), 0.0)
        if self._tokens_per_char is None:
            return out
        wanted = out["memo_saved_chars"].fillna(0).astype(float) * self._tokens_per_char
        tokens = token_counts(req, self._cached_separately)
        saved = lower_uncached_input(tokens, wanted)["saved"]
        out[SAVED_TOKENS] = saved.where(wanted > 0, 0.0)
        if self._rates is None:
            return out
        rate = req["bot_provider_model"].map(self._rates).astype(float)
        col = block_column("token_cost")
        cut = np.minimum(out[SAVED_TOKENS] * rate / 1e6, out[col])
        out[SAVING_KNOWN] = out[SAVED_TOKENS].eq(0) | cut.notna()
        out[col] = out[col] - cut.where(out[SAVED_TOKENS] > 0, 0.0).fillna(0.0)
        return out


def baseline_frames(
    req: pd.DataFrame,
    out: pd.DataFrame,
    ctx: ReplayContext,
    *,
    baseline: str,
    premium_model: str,
    cached_separately: frozenset[str] = frozenset(),
    cheap_model: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Before and after cost blocks of one baseline, for ``summarise_slices``.

    ``as_logged``: the recorded blocks; a row whose token saving is unknown (no
    implied rate) leaves both sides. Repriced baselines: the token part only
    (logged tokens, and tokens less ``SAVED_TOKENS``, repriced); ``block_fees``
    is 0 on both sides only so the slices can be summed: the fee part is not
    priced, and ``lever_result`` reports no saving for these baselines
    (ADR-0037 item 7, ADR-0039).
    """
    llm = req["llm_request"].astype(bool)
    before = req[["llm_request"]].copy()
    after = before.copy()
    saved = out[SAVED_TOKENS]
    cols = [block_column(b) for b in BLOCKS]
    if baseline == "as_logged":
        if SAVING_KNOWN not in out:
            raise ValueError("as_logged needs input_rate_per_m in the version")
        unknown = ~out[SAVING_KNOWN].fillna(True).astype(bool)
        base_known = req[cols].notna().all(axis=1)
        for col in cols:
            before[col] = req[col].where(~unknown)
            after[col] = out[col].where(~unknown)
    elif baseline in REPRICED_KEYS:
        tokens = token_counts(req, cached_separately)
        if cheap_model is None:
            cheap_model = best_single_cheap_model(
                req, ctx, cached_separately=cached_separately
            )
        lowered = tokens.assign(input=tokens["input"] - saved.fillna(0.0))
        costs = [
            repriced_row_costs(
                req,
                ctx,
                premium_model=premium_model,
                cached_separately=cached_separately,
                tokens=t,
                cheap_model=cheap_model,
            )[baseline]
            for t in (tokens, lowered)
        ]
        base_known = costs[0].notna()
        unknown = costs[1].isna()
        for frame, cost in zip((before, after), costs, strict=True):
            cost = cost.where(~unknown)
            frame[cols[0]] = (cost * 0.0).where(cost.notna())
            frame[cols[1]] = cost
    else:
        raise ValueError(f"unknown baseline {baseline}")
    after[SAVED_TOKENS] = saved
    after[SAVING_UNKNOWN] = llm & base_known & unknown
    return before, after


def _decimal(value: float) -> Decimal:
    """Fixed nine-decimal Decimal (and no negative zero), as in ``levers``."""
    return Decimal(f"{value + 0.0:.9f}")


def summarise(out: pd.DataFrame, scored: pd.Series | None = None) -> dict[str, Any]:
    """Content-free counts of a replay over the ``scored`` rows (default all).

    Numerators count LLM rows only; rates are given over all requests and over
    LLM requests. ``fee_avoided`` is in recorded units. ``n_skipped_cited``
    (skipped phatic turns whose logged answer had citations) is a proxy.
    """
    keep = (
        pd.Series(True, index=out.index)
        if scored is None
        else scored.reindex(out.index, fill_value=False).astype(bool)
    )
    rows = out[keep]
    llm = rows["llm_request"].astype(bool)
    status = rows["memo_status"].where(llm)
    retrieval = status.notna() & (status != "no_lookup")
    reused = status == "reused"
    skipped = status == "skipped_phatic"
    agree = rows.loc[reused, "memo_agreement"].dropna()
    n_all, n_llm = len(rows), int(llm.sum())
    s: dict[str, Any] = {
        "n_requests_all": n_all,
        "n_requests_llm": n_llm,
        "n_retrieval_turns": int(retrieval.sum()),
        **{f"n_{k}": int((status == k).sum()) for k in STATUSES[1:]},
        "n_lookups_skipped": int(rows.loc[llm, "memo_lookups_skipped"].sum()),
        "n_evaluable": len(agree),
        "agreement_mean": float(agree.mean()) if len(agree) else None,
        "agreement_share_at_least_0_9": (
            float((agree >= AGREEMENT_PASS).mean()) if len(agree) else None
        ),
        "fee_avoided": math.fsum(rows.loc[llm, "memo_fee_avoided"].fillna(0.0)),
    }
    if "a_citation_n" in rows:
        s["n_skipped_cited"] = int((skipped & (rows["a_citation_n"] > 0)).sum())
    for k in ("reused", "skipped_phatic"):
        n = s[f"n_{k}"]
        s[f"{k}_share_all"] = n / n_all if n_all else None
        s[f"{k}_share_llm"] = n / n_llm if n_llm else None
        s[f"{k}_share_retrieval"] = (
            n / s["n_retrieval_turns"] if s["n_retrieval_turns"] else None
        )
    return s


def choose_threshold(by_threshold: Mapping[float, Mapping[str, Any]]) -> float | None:
    """The lowest threshold whose reuses have mean agreement >= 0.9 with at least
    half of them evaluable (owner rule, tune split only); ``None`` if none."""
    for t in sorted(by_threshold):
        s = by_threshold[t]
        n, mean = s["n_reused"], s["agreement_mean"]
        if n and mean is not None and mean >= AGREEMENT_PASS:
            if s["n_evaluable"] >= 0.5 * n:
                return t
    return None


def chunk_overlap_shares(
    req: pd.DataFrame,
    lookups: pd.DataFrame,
    thresholds: Sequence[float] = THRESHOLDS,
    scored: pd.Series | None = None,
) -> dict[str, Any]:
    """Free check (diagnostic only, never the trigger): Jaccard of each LLM
    retrieval turn's chunk set with the previous LLM retrieval turn's set in the
    same session (``agreement``). Shares over all scored retrieval turns."""
    rag = req[
        req["llm_request"].astype(bool) & req["ai_message_id"].isin(lookups.index)
    ]
    order = [c for c in ("session_id", "turn", "a_order") if c in rag]
    rag = rag.sort_values(order, kind="stable")
    chunks = lookups["chunks"]
    prev_msg = rag.groupby("session_id")["ai_message_id"].shift(1)
    keep = (
        pd.Series(True, index=rag.index)
        if scored is None
        else scored.reindex(rag.index, fill_value=False).astype(bool)
    )
    values = [
        agreement(chunks[p], chunks[m]) if isinstance(p, str) else np.nan
        for m, p in zip(rag["ai_message_id"], prev_msg, strict=True)
    ]
    ov = pd.Series(values, index=rag.index, dtype=float)[keep]
    has_prev = prev_msg[keep].notna()
    n = len(ov)
    out: dict[str, Any] = {
        "n_retrieval_turns": n,
        "n_with_previous": int(has_prev.sum()),
        "n_overlap_unknown": int((has_prev & ov.isna()).sum()),
    }
    for t in thresholds:
        out[f"share_at_least_{t:g}"] = float((ov >= t).sum() / n) if n else None
    return out


def phatic_share(
    req: pd.DataFrame,
    lookups: pd.DataFrame,
    words: Iterable[str],
    scored: pd.Series | None = None,
) -> dict[str, Any]:
    """Free check: LLM retrieval turns whose user message matches the phatic
    keys at all, and the subset the gate may skip (turn > 0, no attachments)."""
    keys = phatic_keys(words)
    keep = (
        pd.Series(True, index=req.index)
        if scored is None
        else scored.reindex(req.index, fill_value=False).astype(bool)
    )
    rows = req[keep & req["llm_request"].astype(bool)]
    rag = rows["ai_message_id"].isin(lookups.index)
    match = rows["u_h_norm"].isin(keys) & rag
    gate = match & (rows["turn"] != 0) & rows["u_att_n"].eq(0)
    n = int(rag.sum())
    return {
        "n_retrieval_turns": n,
        "n_phatic_match": int(match.sum()),
        "n_gate_eligible": int(gate.sum()),
        "phatic_share": float(match.sum() / n) if n else None,
        "gate_eligible_share": float(gate.sum() / n) if n else None,
    }


def lever_result(
    before: pd.DataFrame,
    after: pd.DataFrame,
    out: pd.DataFrame,
    *,
    baseline: str,
    manifest: Manifest,
    assumptions: Sequence[str] = (),
) -> LeverResult:
    """One ``LeverResult`` from ``baseline_frames`` and the applied frame ``out``.

    ``as_logged``: ``baseline_cost`` and ``saving`` with ``fees``,
    ``token_cost`` and ``total``, and a session-clustered interval of the
    saving share. Repriced: ``baseline_cost`` ``token_cost`` and ``total``,
    **empty** ``saving`` (the fee part is not priced, so the total is unknown and
    never ranked); the known token part is ``token_saving_lower_bound`` in slice
    ``session_memo``. Recorded fees never appear in a repriced result.
    """
    slices = summarise_slices(before, after)
    llm = before["llm_request"].astype(bool)
    cols = [block_column(b) for b in BLOCKS]
    known = before[cols].notna().all(axis=1) & llm
    saved = after[SAVED_TOKENS].fillna(0.0)
    repriced = baseline in REPRICED_KEYS
    for name, rows in (("all", pd.Series(True, index=llm.index)), ("llm_only", llm)):
        s = slices[name]
        s["n_saving_unknown"] = Decimal(int((rows & after[SAVING_UNKNOWN]).sum()))
        s["saved_input_tokens"] = _decimal(
            math.fsum(saved[rows & known].to_numpy(dtype=float))
        )
    stats = summarise(out)
    memo = {
        k: Decimal(int(stats[k]))
        for k in (
            "n_retrieval_turns",
            "n_performed",
            "n_reused",
            "n_skipped_phatic",
            "n_fee_unattributed",
            "n_guard_block",
            "n_lookups_skipped",
            "n_evaluable",
            "n_skipped_cited",
        )
        if k in stats
    }
    if stats["agreement_mean"] is not None:
        memo["agreement_mean"] = _decimal(stats["agreement_mean"])
    top = slices["llm_only"]
    ci_low = ci_high = None
    if repriced:
        memo["token_saving_lower_bound"] = top["saving:token_cost"]
        for s in (slices["all"], slices["llm_only"]):
            for k in [k for k in s if k.startswith("saving") or k == "baseline:fees"]:
                del s[k]
        baseline_cost = {k: top[f"baseline:{k}"] for k in ("token_cost", "total")}
        saving: dict[str, Decimal] = {}
    else:
        memo["fee_avoided"] = _decimal(stats["fee_avoided"])
        names = (*BLOCKS, "total")
        baseline_cost = {b: top[f"baseline:{b}"] for b in names}
        saving = {b: top[f"saving:{b}"] for b in names}
        den = before.loc[known, cols].sum(axis=1).to_numpy(dtype=float)
        num = den - after.loc[known, cols].sum(axis=1).to_numpy(dtype=float)
        _, lo, hi = cluster_bootstrap_ratio(
            num, den, out.loc[known, "session_id"].to_numpy(), seed=manifest.seed
        )
        if math.isfinite(lo) and math.isfinite(hi):
            ci_low, ci_high = lo, hi
    slices["session_memo"] = memo
    return LeverResult(
        lever_id=f"{VERSION_ID}.{baseline}",
        step="cache",
        version=VERSION_ID,
        n_requests=len(before),
        n_eligible=int(stats["n_retrieval_turns"]),
        baseline=baseline,
        baseline_cost=baseline_cost,
        saving=saving,
        ci_low=ci_low,
        ci_high=ci_high,
        slices=slices,
        evidence_class=EVIDENCE,
        correctness_state="unmeasured",
        assumptions=tuple(assumptions),
        manifest=manifest,
    )


def to_json(summary: Mapping[str, Any]) -> str:
    """Stable JSON of an aggregate summary (counts and shares only)."""
    return json.dumps(summary, sort_keys=True, indent=2, default=float) + "\n"
