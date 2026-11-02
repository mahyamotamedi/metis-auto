"""Routing base: which candidate models may serve a request, the failover chain,
and the free cost replay of every candidate (final plan R-0, shared by R-A3,
R-B3, R-C3 and J-3; FR-ROUTE-01, FR-ROUTE-05, FR-FAIL-01..04; Review Focus 3).

Decision record: ADR-0045,
``docs/adr/0045-routing-base-eligibility-and-failover.md``. The rules are
Pipeline B's interim rules (EXP-ROUTE-011 ``eligibility_interim.py``), promoted
unchanged in meaning (owner decision 2026-11-03), plus the long-context price
cliff and the retiring replacement.

**Candidates** (``candidate_list``): ``rules["candidates"]`` then
``rules["candidates_jev"]``, in that order; a candidate in ``rules["retiring"]``
is replaced in place by its ``replacement`` (none: it drops out). ``rules`` is
``sprint.toml [routing]`` as loaded (``retiring`` entries may also be plain
model IDs, B's shape).

**Rules**, in the order they are checked. A request's first failing reason is the
rule at which its last candidate fell (``REASONS`` order). One line each: why.

Request level (every candidate falls):

- ``workflow``: workflow bots have no billing and are outside every saving.
- ``unknown_tokens``: without input and output tokens neither fit nor price can
  be checked; unknown is never eligible.
- ``attachments`` / ``attachments_unknown``: no catalogue model has a
  **verified** image or file capability, and unverified counts as unsupported
  (FR-ROUTE-05), so vision requests stay on their incumbent. An unknown count
  counts as attachments (unknown is never eligible).
- ``functions`` / ``functions_unknown``: no tool-calling capability is verified
  either, so a bot with configured functions keeps its model.

Candidate level:

- ``not_in_catalogue``: a model the catalogue does not describe has no limits
  and no price.
- ``disabled``: disabled models are never called (the premium baseline and the
  replay-only logged models are disabled).
- ``retiring``: a retiring model must not take new traffic.
- ``unpriced``: no price means "cheaper" cannot be checked; never priced as 0.
- ``unknown_limit``: an unknown context window or output limit excludes the
  model (FR-ROUTE-05).
- ``over_context_window``: effective input plus logged output must fit the
  window.
- ``over_output_limit``: the logged output must fit the output limit.
- ``long_context_tier``: with ``avoid_long_context_tier`` (required, no
  default), a model is excluded if this input falls into a price row with
  ``min_input_tokens > 0``, a long-context tier that would cost more per token.
- ``no_price_for_input``: no price row of the model covers this input (a gap
  between tiers): the price is unknown.

Effective input follows ``baselines_full``: cached tokens are added back for the
logged models that report them separately (Review Focus 3). Tokens are assumed
model-independent (tokenizers differ; per-candidate tokenisation is a follow-up),
so fit and cost are a *simulation*.

**Failover** (``failover``): the same model on another provider (same
``provider_model_name``; **none exists in the catalogue today**), then other
models of the same ``equivalence_group``, then models one ``tier`` up;
catalogue order inside each step. Never the model itself, a disabled or a
retiring model. ``tier`` and ``equivalence_group`` are catalogue
**PLACEHOLDERS** (A-48), not measured capability. The tier-up step is
escalation in FR-FAIL-02's terms: callers record it as such.

**Cost replay** (``candidate_costs``): per-row price-file cost of each candidate
through ``baselines_full.model_row_costs``, NaN where the candidate is not
eligible. Its sums equal ``baselines_full``'s repricing of the same rows.

Not here: per-candidate Persian tokenisation (plan R-0 "also tokenize"; follow-up).

Layer: pure pandas over injected data. No settings, no files.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from metis_auto.analysis.baselines_full import model_row_costs, token_counts
from metis_auto.analysis.levers import ReplayContext

REASON_COLUMN = "first_failing_reason"
REQUEST_REASONS = (
    "workflow",
    "unknown_tokens",
    "attachments",
    "attachments_unknown",
    "functions",
    "functions_unknown",
)
CANDIDATE_REASONS = (
    "not_in_catalogue",
    "disabled",
    "retiring",
    "unpriced",
    "unknown_limit",
    "over_context_window",
    "over_output_limit",
    "long_context_tier",
    "no_price_for_input",
)
REASONS = REQUEST_REASONS + CANDIDATE_REASONS
_RANK = {r: i for i, r in enumerate(REASONS)}
_ELIGIBLE = len(REASONS)


@dataclass(frozen=True)
class _Spec:
    model: str
    static: str | None  # first failing catalogue-level reason
    window: float
    max_out: float
    tiers: tuple[tuple[float, float], ...]  # (min, max) input per price row


def candidate_list(rules: Mapping[str, Any]) -> tuple[str, ...]:
    """Candidates then JEV candidates; a retiring one replaced in place."""
    retiring, replacement = _retiring(rules.get("retiring", ()))
    out: list[str] = []
    for model in [*rules["candidates"], *rules.get("candidates_jev", ())]:
        model = str(model)
        if model in retiring:
            model = replacement.get(model)
            if model is None:
                continue
        if model not in out:
            out.append(model)
    if not out:
        raise ValueError("no routing candidates in the rules")
    return tuple(out)


def eligible_models(
    row: Mapping[str, Any],
    catalogue: Mapping[str, Any] | pd.DataFrame,
    prices: Mapping[str, Any] | pd.DataFrame,
    rules: Mapping[str, Any],
) -> tuple[str, ...]:
    """Eligible candidates for one request, in ``candidate_list`` order.

    ``row`` carries ``input_tokens`` (effective, ``baselines_full`` rule),
    ``output_tokens``, ``u_att_n`` and ``bot_n_functions``; a missing key is
    unknown. ``llm_request`` is optional (absent: the caller scoped to LLM rows).
    """
    specs = _specs(catalogue, prices, rules)

    def one(key: str) -> np.ndarray:
        return np.array([_num(row.get(key))])

    llm = np.array([bool(row.get("llm_request", True))])
    codes = _codes(
        specs,
        _avoid(rules),
        llm,
        one("input_tokens"),
        one("output_tokens"),
        one("u_att_n"),
        one("bot_n_functions"),
    )
    return tuple(
        s.model for s, c in zip(specs, codes, strict=True) if c[0] == _ELIGIBLE
    )


def eligibility_frame(
    req: pd.DataFrame,
    ctx: ReplayContext,
    *,
    rules: Mapping[str, Any],
    cached_separately: frozenset[str],
    reasons: bool = False,
) -> pd.DataFrame:
    """One bool column per candidate (``candidate_list`` order) and
    ``REASON_COLUMN`` (None where some candidate is eligible), same index.

    Vectorised ``eligible_models`` over the requests frame (row-by-row equal,
    tested). Needs ``llm_request`` (the scope step), the ``a_bill_*`` tokens,
    ``bot_provider_model``, ``u_att_n`` and ``bot_n_functions``. With
    ``reasons``, also ``reason:<model>``: each candidate's first failing rule.
    """
    if "llm_request" not in req or req["llm_request"].isna().any():
        raise ValueError("llm_request is missing or unknown; run the scope step first")
    specs = _specs(ctx.catalogue, ctx.price_table, rules)
    tok = token_counts(req, cached_separately)

    def col(name: str) -> np.ndarray:
        return pd.to_numeric(req[name], errors="coerce").to_numpy(dtype=float)

    codes = _codes(
        specs,
        _avoid(rules),
        req["llm_request"].to_numpy(dtype=bool),
        tok["input"].to_numpy(dtype=float),
        tok["output"].to_numpy(dtype=float),
        col("u_att_n"),
        col("bot_n_functions"),
    )
    out = pd.DataFrame(
        {s.model: c == _ELIGIBLE for s, c in zip(specs, codes, strict=True)},
        index=req.index,
    )
    worst = np.max(codes, axis=0)
    names = np.array([*REASONS, None], dtype=object)
    out[REASON_COLUMN] = _labels(names[worst], req.index)
    if reasons:
        for s, c in zip(specs, codes, strict=True):
            out[f"reason:{s.model}"] = _labels(names[c], req.index)
    return out


def _labels(values: np.ndarray, index: pd.Index) -> pd.Series:
    """Reason strings, None (not NaN) where eligible."""
    return pd.Series(values.tolist(), index=index, dtype=object)


def candidate_costs(
    req: pd.DataFrame,
    ctx: ReplayContext,
    candidates: Sequence[str],
    *,
    rules: Mapping[str, Any],
    cached_separately: frozenset[str],
) -> pd.DataFrame:
    """Per-row price-file cost of each candidate; NaN where it is not eligible
    (which includes unpriced, unknown tokens and workflow rows)."""
    allowed = candidate_list(rules)
    for model in candidates:
        if model not in allowed:
            raise ValueError(f"{model} is not a routing candidate in the rules")
    elig = eligibility_frame(req, ctx, rules=rules, cached_separately=cached_separately)
    tokens = token_counts(req, cached_separately)
    out = pd.DataFrame(index=req.index)
    for model in candidates:
        if elig[model].any():
            cost = model_row_costs(
                req, ctx, model, cached_separately=cached_separately, tokens=tokens
            )
            out[model] = cost.where(elig[model])
        else:
            out[model] = np.nan
    return out


def failover(
    model: str,
    catalogue: Mapping[str, Any] | pd.DataFrame,
    *,
    retiring: Collection[Any],
) -> tuple[str, ...]:
    """Failover chain for ``model`` (module docstring). ``retiring`` takes
    ``sprint.toml [routing] retiring`` as loaded, or plain model IDs."""
    entries = _models(catalogue)
    target = next((m for m in entries if str(m["model_id"]) == model), None)
    if target is None:
        raise ValueError(f"model {model} is not in the catalogue")
    gone, _ = _retiring(retiring)

    def usable(m: Mapping[str, Any]) -> bool:
        mid = str(m["model_id"])
        return mid != model and mid not in gone and bool(m.get("enabled", False))

    def same(m: Mapping[str, Any], key: str) -> bool:
        a, b = target.get(key), m.get(key)
        return not _missing(a) and not _missing(b) and a == b

    def tier_up(m: Mapping[str, Any]) -> bool:
        a, b = target.get("tier"), m.get("tier")
        return not _missing(a) and not _missing(b) and int(b) == int(a) + 1

    steps = (
        lambda m: same(m, "provider_model_name") and not same(m, "provider"),
        lambda m: same(m, "equivalence_group"),
        tier_up,
    )
    out: list[str] = []
    for step in steps:
        for m in entries:
            if usable(m) and step(m) and str(m["model_id"]) not in out:
                out.append(str(m["model_id"]))
    return tuple(out)


def _codes(
    specs: Sequence[_Spec],
    avoid: bool,
    llm: np.ndarray,
    inp: np.ndarray,
    out: np.ndarray,
    att: np.ndarray,
    fn: np.ndarray,
) -> list[np.ndarray]:
    """Per candidate, the rank of its first failing reason (``_ELIGIBLE`` if none)."""
    request = np.full(len(inp), _ELIGIBLE)
    for reason, fails in (
        ("workflow", ~llm),
        ("unknown_tokens", np.isnan(inp) | np.isnan(out)),
        ("attachments", att > 0),
        ("attachments_unknown", np.isnan(att)),
        ("functions", fn > 0),
        ("functions_unknown", np.isnan(fn)),
    ):
        request = np.where((request == _ELIGIBLE) & fails, _RANK[reason], request)
    codes = []
    for s in specs:
        code = request.copy()
        if s.static is not None:
            code[code == _ELIGIBLE] = _RANK[s.static]
            codes.append(code)
            continue
        covered = [(inp >= lo) & (inp <= hi) for lo, hi in s.tiers]
        long_tier = [c for c, (lo, _) in zip(covered, s.tiers, strict=True) if lo > 0]
        cliff = np.zeros(len(inp), dtype=bool)
        if avoid and long_tier:
            cliff = np.any(long_tier, axis=0)
        checks = (
            ("over_context_window", inp + out > s.window),
            ("over_output_limit", out > s.max_out),
            ("long_context_tier", cliff),
            ("no_price_for_input", ~np.any(covered, axis=0)),
        )
        for reason, fails in checks:
            code = np.where((code == _ELIGIBLE) & fails, _RANK[reason], code)
        codes.append(code)
    return codes


def _specs(
    catalogue: Mapping[str, Any] | pd.DataFrame,
    prices: Mapping[str, Any] | pd.DataFrame,
    rules: Mapping[str, Any],
) -> list[_Spec]:
    entries = {str(m["model_id"]): m for m in _models(catalogue)}
    tiers = _tiers(prices)
    retiring, _ = _retiring(rules.get("retiring", ()))
    specs = []
    for model in candidate_list(rules):
        m = entries.get(model)
        window = max_out = np.nan
        static = None
        if m is None:
            static = "not_in_catalogue"
        elif not bool(m.get("enabled", False)):
            static = "disabled"
        elif model in retiring:
            static = "retiring"
        elif str(m.get("price_ref")) not in tiers:
            static = "unpriced"
        else:
            window = _limit(m, "context_window")
            max_out = _limit(m, "max_output_tokens")
            if np.isnan(window) or np.isnan(max_out):
                static = "unknown_limit"
        ref_tiers = () if static else tiers[str(m["price_ref"])]
        specs.append(_Spec(model, static, window, max_out, ref_tiers))
    return specs


def _tiers(
    prices: Mapping[str, Any] | pd.DataFrame,
) -> dict[str, tuple[tuple[float, float], ...]]:
    rows = (
        prices.to_dict("records")
        if isinstance(prices, pd.DataFrame)
        else list(prices.get("prices", []))
    )
    out: dict[str, list[tuple[float, float]]] = {}
    for p in rows:
        lo, hi = _num(p.get("min_input_tokens")), _num(p.get("max_input_tokens"))
        out.setdefault(str(p["price_ref"]), []).append(
            (0.0 if np.isnan(lo) else lo, np.inf if np.isnan(hi) else hi)
        )
    return {ref: tuple(t) for ref, t in out.items()}


def _retiring(entries: Collection[Any]) -> tuple[frozenset[str], dict[str, str]]:
    """Retiring model IDs and their replacements (``sprint.toml`` tables or IDs)."""
    ids, replacement = set(), {}
    for e in entries:
        if isinstance(e, Mapping):
            ids.add(str(e["model_id"]))
            if e.get("replacement"):
                replacement[str(e["model_id"])] = str(e["replacement"])
        else:
            ids.add(str(e))
    return frozenset(ids), replacement


def _avoid(rules: Mapping[str, Any]) -> bool:
    value = rules.get("avoid_long_context_tier")
    if not isinstance(value, bool):
        raise ValueError(
            "rules need avoid_long_context_tier (true or false; no default): "
            "sprint.toml [routing]"
        )
    return value


def _models(catalogue: Mapping[str, Any] | pd.DataFrame) -> list[Mapping[str, Any]]:
    if isinstance(catalogue, pd.DataFrame):
        return catalogue.to_dict("records")
    return list(catalogue.get("models", []))


def _limit(entry: Mapping[str, Any], name: str) -> float:
    value = entry.get(name)
    if isinstance(value, Mapping):
        value = value.get("value")
    return _num(value)


def _num(value: Any) -> float:
    """A float; None, NaN and pandas NA become NaN (unknown)."""
    if _missing(value):
        return np.nan
    return float(value)


def _missing(value: Any) -> bool:
    return value is None or (pd.api.types.is_scalar(value) and bool(pd.isna(value)))
