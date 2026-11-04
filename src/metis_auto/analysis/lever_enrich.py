"""Fill a lever result's missing slices and its session-clustered interval.

Sprint final Stage 1 ("make every candidate comparable"): the plan asks every
result for the slices ``llm_only``, ``traffic_weighted``, ``lang:<label>``,
``over_8k`` and ``tenant_rank:<n>`` and for a session-clustered interval
(``stats.cluster_bootstrap_ratio``). Several versions wrote only some of them.
``enrich`` adds what is missing from the same ``before`` / ``after`` frames a
version's ``lever_result`` was built from; slices and an interval the result
already has are kept as they are.

Rules (the ones the complete results already follow, ADR-0032, ADR-0036):

- every slice counts LLM requests only and sums cost over LLM rows with a known
  cost (``levers._slice``), so workflow rows add nothing and unknown is never 0;
- a slice keeps only the blocks the result itself reports: a repriced result
  (no ``fees`` key) gets no fee keys, and a result whose ``saving`` is empty
  ("saving unknown", ADR-0037 item 7, ADR-0039 item 2) gets baseline keys only
  and no interval;
- ``over_8k``: effective input (``baselines_full.token_counts``) above 8,000;
- ``lang:<label>``: ``u_lang``, a missing label is ``unknown``;
- ``tenant_rank:<n>``: the ``TOP_TENANTS`` largest tenants (``user_id``) by LLM
  requests, with ``share`` of LLM requests; ranks only, never IDs;
- ``traffic_weighted``: ``saving_share`` is the per-bot saving share weighted by
  each bot's LLM requests (R-C3's definition); ``bot_mean_saving_share`` is the
  unweighted mean over bots (R-A3's extra key);
- the interval is the ratio of row savings to row baselines over the result's
  ``llm_only`` rows, clustered by ``session_id``, seeded by the manifest seed. It
  is refused when the rows do not reproduce the result's own share.

Pure pandas. Imports ``analysis`` modules only (ADR-0009). Traces: plan
"Slices, always", FR-EVAL-06, QA-REPRO.
"""

from __future__ import annotations

import math
from decimal import Decimal

import pandas as pd

from .baselines_full import token_counts
from .lever_result import LeverResult
from .levers import BLOCKS, _llm_mask, _slice, block_column
from .stats import cluster_bootstrap_ratio

OVER_TOKENS = 8000
TOP_TENANTS = 10
SHARE_TOLERANCE = 1e-6
TOKEN_COLUMNS = (
    "a_bill_inputTokens",
    "a_bill_cachedInputTokens",
    "a_bill_outputTokens",
    "bot_provider_model",
)
ENRICH_NOTE = (
    "Missing slices (language, over 8,000 tokens, tenant ranks, traffic-weighted) "
    "and the session-clustered interval were added from the same frames "
    "(sprint final Stage 1, analysis.lever_enrich)."
)
ENRICH_RULE = (
    "Added slices count LLM requests with a known cost; the traffic-weighted "
    "share weights each bot's saving share by its LLM requests."
)
FAMILY_TEXT = {
    "over_8k": "over 8,000 tokens",
    "lang:<label>": "language",
    "tenant_rank:<n>": "tenant ranks",
    "traffic_weighted": "traffic-weighted",
    "interval": "session-clustered interval",
}


def _decimal(value: float) -> Decimal:
    return Decimal(f"{value + 0.0:.9f}")


def _label(value: object) -> str:
    text = "unknown" if value is None or pd.isna(value) else str(value).lower()
    clean = "".join(c if c.isalnum() or c in "_.-" else "_" for c in text)
    return clean if clean and clean[0].isalnum() else f"x{clean}"


def _keep(result: LeverResult, s: dict[str, Decimal]) -> dict[str, Decimal]:
    """Only the blocks the result itself reports (units, ADR-0036)."""
    out: dict[str, Decimal] = {}
    for key, value in s.items():
        kind, _, block = key.partition(":")
        if kind == "baseline" and block not in result.baseline_cost:
            continue
        if kind == "saving" and block not in result.saving:
            continue
        if key == "saving_share" and not result.saving:
            continue
        out[key] = value
    return out


def _row_totals(
    before: pd.DataFrame, after: pd.DataFrame, rows: pd.Series
) -> tuple[pd.Series, pd.Series]:
    cols = [block_column(b) for b in BLOCKS]
    base = before.loc[rows, cols].sum(axis=1)
    return base, base - after.loc[rows, cols].sum(axis=1)


def _traffic_weighted(
    result: LeverResult,
    before: pd.DataFrame,
    after: pd.DataFrame,
    req: pd.DataFrame,
    known: pd.Series,
) -> dict[str, Decimal]:
    llm = _llm_mask(before)
    out: dict[str, Decimal] = {"n_requests": Decimal(int(llm.sum()))}
    if not result.saving:
        return out
    base, save = _row_totals(before, after, known)
    frame = pd.DataFrame({"b": base, "s": save, "bot": req.loc[known, "bot_id"]})
    groups = frame.groupby(frame["bot"].astype(str))
    sums = groups[["b", "s"]].sum()
    n = req.loc[llm, "bot_id"].astype(str).value_counts().reindex(sums.index)
    sums, n = sums[sums["b"] > 0], n[sums["b"] > 0]
    if len(sums) and n.sum() > 0:
        share = sums["s"] / sums["b"]
        out["saving_share"] = _decimal(float((share * n).sum() / n.sum()))
        out["bot_mean_saving_share"] = _decimal(float(share.mean()))
    return out


def _interval(
    result: LeverResult, before: pd.DataFrame, after: pd.DataFrame, req, known
) -> tuple[float | None, float | None]:
    if not result.saving or "saving_share" not in result.slices["llm_only"]:
        return None, None
    base, save = _row_totals(before, after, known)
    if base.sum() <= 0:
        return None, None
    want = float(result.slices["llm_only"]["saving_share"])
    est, lo, hi = cluster_bootstrap_ratio(
        save.to_numpy(dtype=float),
        base.to_numpy(dtype=float),
        req.loc[known, "session_id"].astype(str).to_numpy(),
        seed=result.manifest.seed,
    )
    if not math.isclose(est, want, rel_tol=0, abs_tol=SHARE_TOLERANCE):
        raise ValueError(
            f"{result.lever_id}: the rows do not reproduce the result's share "
            f"({est:.9f} against {want:.9f}); no interval attached"
        )
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return None, None
    return round(lo, 9), round(hi, 9)


def enrich(
    result: LeverResult,
    before: pd.DataFrame,
    after: pd.DataFrame,
    req: pd.DataFrame,
    *,
    cached_separately: frozenset[str] = frozenset(),
) -> LeverResult:
    """``result`` with its missing slices and interval added (module docstring).

    ``before`` / ``after`` are the per-baseline frames the result was built from
    (``block_fees``, ``block_token_cost``, ``llm_request``); ``req`` carries
    ``u_lang``, ``user_id``, ``bot_id``, ``session_id`` and the token columns
    on the same index."""
    if not (before.index.equals(after.index) and before.index.equals(req.index)):
        raise ValueError("before, after and req must share an index")
    llm = _llm_mask(before)
    cols = [block_column(b) for b in BLOCKS]
    known = llm & before[cols].notna().all(axis=1)
    hits = (
        after["served_from_cache"].fillna(False).astype(bool)
        if "served_from_cache" in after
        else pd.Series(False, index=after.index)
    )

    def block(mask: pd.Series) -> dict[str, Decimal]:
        return _keep(result, _slice(before, after, mask & llm, hits))

    new: dict[str, dict[str, Decimal]] = {}
    notes: list[str] = []

    def needs(family: str, *columns: str) -> bool:
        missing = [c for c in columns if c not in req]
        if missing:
            notes.append(
                f"Slice {FAMILY_TEXT[family]} not computed: the replay frame lacks "
                "a required column (lever_enrich)."
            )
        return not missing

    if needs("over_8k", *TOKEN_COLUMNS):
        tokens = token_counts(req, cached_separately)["input"]
        new["over_8k"] = block(tokens.gt(OVER_TOKENS).fillna(False))
    if needs("lang:<label>", "u_lang"):
        lang = req["u_lang"].map(_label)
        for label in sorted(lang[llm].unique()):
            new[f"lang:{label}"] = block(lang.eq(label))
    if needs("tenant_rank:<n>", "user_id"):
        users = req["user_id"].astype(object).where(req["user_id"].notna(), "unknown")
        order = users[llm].value_counts(sort=True).index[:TOP_TENANTS]
        for rank, user in enumerate(order, start=1):
            s = block(users.eq(user))
            s["share"] = _decimal(float(s["n_requests"]) / float(llm.sum()))
            new[f"tenant_rank:{rank}"] = s
    if needs("traffic_weighted", "bot_id"):
        new["traffic_weighted"] = _traffic_weighted(result, before, after, req, known)

    slices = dict(result.slices)
    added = [k for k in new if k not in slices and not _has_family(slices, k)]
    for key in added:
        slices[key] = new[key]
    update: dict[str, object] = {"slices": slices}
    if result.ci_low is None and result.ci_high is None:
        if needs("interval", "session_id"):
            lo, hi = _interval(result, before, after, req, known)
            update["ci_low"], update["ci_high"] = lo, hi
    notes = [n for n in notes if n not in result.assumptions]
    if added or update.get("ci_low") is not None or notes:
        extra = tuple(
            n for n in (ENRICH_NOTE, ENRICH_RULE) if n not in result.assumptions
        )
        update["assumptions"] = (*result.assumptions, *extra, *notes)
    # model_copy does not validate; re-validate so every field rule still holds
    return LeverResult.model_validate({**dict(result), **update})


def _has_family(slices: dict[str, object], key: str) -> bool:
    """A result that already has some ``lang:*`` or ``tenant_rank:*`` slices keeps
    its own set; the family is not mixed with a second definition."""
    family = key.split(":", 1)[0]
    return ":" in key and any(k.startswith(f"{family}:") for k in slices)
