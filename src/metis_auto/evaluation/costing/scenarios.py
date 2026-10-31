"""Cost scenarios with nothing assumed by default (Stage E2; framework §2.3).

``ScenarioConfig`` is what the owner supplies (TOML under an experiment): a
price-table maximum age, output-length scenarios, and cache scenarios. Each
section may be absent; an absent or unusable scenario yields a row that says
``not_evaluated`` and why, never a number.

- Output scenarios: ``recorded_quantile`` (a quantile of recorded, provider-
  reported output tokens, through an estimator) or ``documented_assumption``
  (explicit tokens per model with a mandatory note).
- Cache scenarios: ``measured`` (the cached share found in recorded usage) or
  ``sensitivity_range`` (an explicit, labelled hypothetical share, reported as
  ``simulated``, never as a hit rate).

What is always computed, with no scenario values: input cost with no cached
discount and no output (a lower bound, ``output_not_included``), the cost line
(fixed cost plus a price per output token), and break-even output tokens
between two models. Costs go through ``domain.accounting.cost_of`` and the
price table, so tiers, caveats and "price unknown" behave as everywhere else.
Pure. Status: provisional (Stage E2). No scenario value is set anywhere.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from pydantic import model_validator

from metis_auto.contracts import (
    CatalogueEntry,
    ContractModel,
    CostBasis,
    CostStatus,
    Fidelity,
    PriceTable,
    TokenCount,
    TokenUsage,
)
from metis_auto.domain.accounting.cost import cost_of
from metis_auto.evaluation.comparison.types import Estimate, not_measured

from .estimators import OutputTokenEstimator, RequestFeatures
from .usage import UsageRecord, empirical_quantile, min_n_for_quantile

METHOD = "e2-scenario@1"


class OutputScenario(ContractModel):
    name: str
    source: Literal["recorded_quantile", "documented_assumption"]
    quantile: float | None = None
    """Probability in (0, 1). Required for ``recorded_quantile``."""
    estimator: str | None = None
    """Name of the estimator used (a key of the estimators passed in)."""
    output_tokens_per_request: Mapping[str, int] | None = None
    """Billed output tokens per request (including reasoning), per model_id.
    Required for ``documented_assumption``."""
    assumption_note: str | None = None
    """Why these numbers; required and non-empty for ``documented_assumption``."""

    @model_validator(mode="after")
    def _check(self) -> OutputScenario:
        if self.source == "recorded_quantile":
            if self.quantile is None or not 0 < self.quantile < 1:
                raise ValueError("recorded_quantile needs a quantile in (0, 1)")
            if not self.estimator:
                raise ValueError("recorded_quantile needs an estimator name")
            if self.output_tokens_per_request or self.assumption_note:
                raise ValueError("recorded_quantile takes no assumed values")
        else:
            if not self.output_tokens_per_request:
                raise ValueError(
                    "documented_assumption needs output_tokens_per_request"
                )
            if not (self.assumption_note or "").strip():
                raise ValueError("documented_assumption needs an assumption_note")
            if any(v < 0 for v in self.output_tokens_per_request.values()):
                raise ValueError("output tokens must not be negative")
            if self.quantile is not None or self.estimator:
                raise ValueError("documented_assumption takes no quantile or estimator")
        return self


class CacheScenario(ContractModel):
    name: str
    source: Literal["measured", "sensitivity_range"]
    cached_input_share: float | None = None
    """Share of billed input tokens read from the provider cache, in [0, 1].
    Only for ``sensitivity_range``; ``measured`` derives it from usage."""
    label: str | None = None
    """Required for ``sensitivity_range``: states that it is hypothetical."""

    @model_validator(mode="after")
    def _check(self) -> CacheScenario:
        if self.source == "measured":
            if self.cached_input_share is not None or self.label:
                raise ValueError("a measured cache scenario takes no assumed value")
        else:
            share = self.cached_input_share
            if share is None or not 0 <= share <= 1:
                raise ValueError("sensitivity_range needs cached_input_share in [0, 1]")
            if not (self.label or "").strip():
                raise ValueError(
                    "sensitivity_range needs a label saying it is hypothetical"
                )
        return self


class ScenarioConfig(ContractModel):
    """Everything optional, nothing defaulted to a value."""

    max_age_days: int | None = None
    """Maximum price-table age, in days; unset = staleness not evaluated."""
    output: tuple[OutputScenario, ...] = ()
    cache: tuple[CacheScenario, ...] = ()

    @model_validator(mode="after")
    def _names_unique(self) -> ScenarioConfig:
        for group in (self.output, self.cache):
            names = [s.name for s in group]
            if len(set(names)) != len(names):
                raise ValueError("scenario names must be unique")
        return self


def parse_scenario_config(raw: Mapping[str, object]) -> ScenarioConfig:
    return ScenarioConfig.model_validate(dict(raw))


@dataclass(frozen=True)
class ScenarioCost:
    model_id: str
    effort: str | None
    output_scenario: str | None
    cache_scenario: str | None
    state: str
    """``computed`` or ``not_evaluated``."""
    reason: str | None
    provenance: str | None
    n: int
    total_usd: Decimal | None = None
    per_request_usd: tuple[Decimal, ...] = ()
    caveats: tuple[str, ...] = ()
    details: Mapping[str, str | float] = field(default_factory=dict)


def _skip(
    model_id: str,
    effort: str | None,
    out: str | None,
    cache: str | None,
    reason: str,
    n: int = 0,
) -> ScenarioCost:
    return ScenarioCost(model_id, effort, out, cache, "not_evaluated", reason, None, n)


def _price(
    entry: CatalogueEntry,
    prices: PriceTable,
    inputs: Sequence[int],
    fidelity: Fidelity,
    output_tokens: int,
    cached_share: float,
) -> tuple[list[Decimal], set[str]] | str:
    costs: list[Decimal] = []
    caveats: set[str] = set()
    for tokens in inputs:
        cached = round(tokens * cached_share)
        usage = TokenUsage(
            model_id=entry.model_id,
            input=TokenCount(tokens=tokens, fidelity=fidelity, method=METHOD),
            output=TokenCount(
                tokens=output_tokens, fidelity=Fidelity.APPROXIMATION, method=METHOD
            ),
            cached_input=(
                TokenCount(tokens=cached, fidelity=fidelity, method=METHOD)
                if cached
                else None
            ),
        )
        cost = cost_of(usage, entry, prices, CostBasis.PRE_CALL_ESTIMATE)
        if cost.status != CostStatus.COMPUTED or cost.amount is None:
            return cost.reason.value if cost.reason else "not_computed"
        costs.append(cost.amount.amount)
        caveats.update(c.value for c in cost.caveats)
    return costs, caveats


def _recorded_share(
    usage: Sequence[UsageRecord], model_id: str, effort: str | None
) -> tuple[float | None, str | None]:
    rows = [r for r in usage if r.model_id == model_id and r.effort == effort]
    if not rows:
        return None, "no_recorded_usage"
    if any(r.cached_input_tokens is None for r in rows):
        return None, "cached_tokens_not_reported"
    total = sum(r.input_tokens for r in rows)
    if total == 0:
        return None, "no_recorded_input_tokens"
    return sum(r.cached_input_tokens or 0 for r in rows) / total, None


def evaluate_scenarios(
    config: ScenarioConfig,
    *,
    catalogue: Mapping[str, CatalogueEntry],
    prices: PriceTable,
    inputs: Mapping[str, Sequence[int]],
    input_fidelity: Fidelity,
    usage: Sequence[UsageRecord] = (),
    estimators: Mapping[str, OutputTokenEstimator] | None = None,
    efforts: Sequence[str | None] = (None,),
) -> list[ScenarioCost]:
    """One row per model, effort, output scenario and cache scenario, plus the
    always-computable input-only row per model. ``inputs`` is billed input
    tokens per request per model (from E3-style counting, or recorded usage)."""
    estimators = estimators or {}
    rows: list[ScenarioCost] = []
    for model_id, tokens in inputs.items():
        entry = catalogue.get(model_id)
        if entry is None:
            rows.append(_skip(model_id, None, None, None, "model_not_in_catalogue"))
            continue
        base = _price(entry, prices, tokens, input_fidelity, 0, 0.0)
        if isinstance(base, str):
            rows.append(
                _skip(model_id, None, "input_only", "uncached", base, len(tokens))
            )
        else:
            costs, caveats = base
            rows.append(
                ScenarioCost(
                    model_id,
                    None,
                    "input_only",
                    "uncached",
                    "computed",
                    None,
                    "estimated",
                    len(costs),
                    sum(costs, Decimal(0)),
                    tuple(costs),
                    tuple(sorted(caveats | {"output_not_included"})),
                )
            )
        if not config.output:
            rows.append(
                _skip(model_id, None, None, None, "no_output_scenarios_configured")
            )
        if not config.cache:
            rows.append(
                _skip(model_id, None, None, None, "no_cache_scenarios_configured")
            )
        for effort in efforts:
            for out in config.output:
                out_tokens, out_prov, out_reason = _output_tokens(
                    out, model_id, effort, estimators
                )
                for cache in (None, *config.cache):
                    cname = cache.name if cache is not None else "uncached"
                    if out_tokens is None:
                        rows.append(
                            _skip(
                                model_id,
                                effort,
                                out.name,
                                cname,
                                out_reason or "output_unavailable",
                                len(tokens),
                            )
                        )
                        continue
                    if cache is None:
                        share, share_prov, share_reason = 0.0, "estimated", None
                    else:
                        share, share_prov, share_reason = _cache_share(
                            cache, usage, model_id, effort
                        )
                    if share is None:
                        rows.append(
                            _skip(
                                model_id,
                                effort,
                                out.name,
                                cname,
                                share_reason or "cache_unavailable",
                                len(tokens),
                            )
                        )
                        continue
                    priced = _price(
                        entry, prices, tokens, input_fidelity, round(out_tokens), share
                    )
                    if isinstance(priced, str):
                        rows.append(
                            _skip(
                                model_id, effort, out.name, cname, priced, len(tokens)
                            )
                        )
                        continue
                    costs, caveats = priced
                    provenance = (
                        "simulated"
                        if "simulated" in (out_prov, share_prov)
                        else "estimated"
                    )
                    rows.append(
                        ScenarioCost(
                            model_id,
                            effort,
                            out.name,
                            cname,
                            "computed",
                            None,
                            provenance,
                            len(costs),
                            sum(costs, Decimal(0)),
                            tuple(costs),
                            tuple(sorted(caveats)),
                            {
                                "output_tokens_per_request": float(out_tokens),
                                "cached_input_share": share,
                            },
                        )
                    )
    return rows


def _output_tokens(
    scenario: OutputScenario,
    model_id: str,
    effort: str | None,
    estimators: Mapping[str, OutputTokenEstimator],
) -> tuple[float | None, str, str | None]:
    if scenario.source == "documented_assumption":
        assert scenario.output_tokens_per_request is not None
        value = scenario.output_tokens_per_request.get(model_id)
        if value is None:
            return None, "simulated", "model_not_in_scenario"
        return float(value), "simulated", None
    estimator = estimators.get(scenario.estimator or "")
    if estimator is None:
        return None, "estimated", "estimator_not_provided"
    assert scenario.quantile is not None
    est = estimator.estimate(model_id, effort, RequestFeatures(), scenario.quantile)
    if est.value is None:
        return None, "estimated", est.reason or "estimate_unavailable"
    return est.value, "estimated", None


def _cache_share(
    scenario: CacheScenario,
    usage: Sequence[UsageRecord],
    model_id: str,
    effort: str | None,
) -> tuple[float | None, str, str | None]:
    if scenario.source == "sensitivity_range":
        return scenario.cached_input_share, "simulated", None
    share, reason = _recorded_share(usage, model_id, effort)
    return share, "estimated", reason


# --- always computable, no scenario values ----------------------------------


def cost_quantiles(
    costs: Sequence[Decimal], quantiles: Sequence[float], provenance: str
) -> dict[float, Estimate]:
    """Per-request cost quantiles; a quantile below its arithmetic floor is
    ``insufficient`` (a p99 from fewer than 100 values is just the maximum)."""
    out: dict[float, Estimate] = {}
    values = [float(c) for c in costs]
    for q in quantiles:
        floor = min_n_for_quantile(q)
        if len(values) < floor:
            out[q] = not_measured(
                "insufficient", "quantile_not_identifiable", len(values), provenance
            )
        else:
            value = empirical_quantile(values, q)
            assert value is not None
            out[q] = Estimate("measured", len(values), provenance, value=value)
    return out


@dataclass(frozen=True)
class CostLine:
    """cost = fixed_usd + per_output_token_usd × output tokens, for one
    request (uncached input); no assumption about output length."""

    model_id: str
    fixed_usd: Decimal
    per_output_token_usd: Decimal


def cost_line(
    entry: CatalogueEntry, prices: PriceTable, input_tokens: int, fidelity: Fidelity
) -> CostLine | str:
    """The line for one request size, from the price table (the output price
    is read as the cost difference of 1,000,000 output tokens); a string is
    the reason it cannot be computed."""
    zero = _price(entry, prices, [input_tokens], fidelity, 0, 0.0)
    big = _price(entry, prices, [input_tokens], fidelity, 1_000_000, 0.0)
    if isinstance(zero, str):
        return zero
    if isinstance(big, str):
        return big
    return CostLine(entry.model_id, zero[0][0], (big[0][0] - zero[0][0]) / 1_000_000)


def breakeven_equal_output_tokens(a: CostLine, b: CostLine) -> Estimate:
    """Output tokens per request at which ``a`` and ``b`` cost the same *if
    both emit the same number*; it ignores that models differ in verbosity and
    reasoning, so it is a reading aid, not a prediction."""
    slope = a.per_output_token_usd - b.per_output_token_usd
    if slope == 0:
        return not_measured("undefined", "equal_output_prices", 0, "estimated")
    tokens = float((b.fixed_usd - a.fixed_usd) / slope)
    if tokens < 0:
        return not_measured("undefined", "no_non_negative_breakeven", 0, "estimated")
    return Estimate(
        "measured", 0, "estimated", value=tokens, method="equal_output_tokens"
    )
