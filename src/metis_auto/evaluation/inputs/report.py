"""Full-prompt input cost report (Stage E3; evaluation framework §2.1, §0.1).

Per slice (Persian first, then the other languages separately, then the
other strata, then overall labelled "dominated_by_persian"): n cases and, per
catalogue model, token statistics, tokens per character, the instruction
share of input, **input-only uncached cost** (a lower bound: no output and no
provider-cache discount, through ``evaluate_scenarios`` and the price table, so
tiers apply), and the number of cases in the long price tier. Then the
tokenizer question: models ranked by mean input cost with their exact counts
versus the chars/4 reference, and the pairs whose order flips. Models counted
only by approximation are left out of the ranking (stated).

A slice is ``rankable`` only if its n meets the configured minimum; an unset
minimum, or a smaller n, makes it ``descriptive``: the numbers are still
computed from this sample, but no ranking claim is made. Provider-cache
discounts are **not** computed: no cache scenario is set (E2). What is reported
instead is composition, which needs no hit rate: the instruction share of the
input (the most a prefix cache could ever cover), and how often the same
instruction text recurs across cases in the sample (descriptive, literal
equality; not a hit rate, and ignoring the provider's unknown minimum prefix).

``compression_break_even`` gives, without any hit-rate assumption, the cached
fraction above which a compression that changes a prefix component costs more
in lost cache discount than it saves in tokens. Pure.
Status: provisional (Stage E3). Sample-derived values are provisional (ADR-0008).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from metis_auto.contracts import (
    CatalogueEntry,
    CostBasis,
    CostStatus,
    Fidelity,
    PriceTable,
    TokenCount,
    TokenUsage,
)
from metis_auto.domain.accounting.cost import cost_of
from metis_auto.evaluation.comparison.types import (
    PRIMARY_LANGUAGE,
    Estimate,
    not_measured,
    sufficient,
)
from metis_auto.evaluation.costing import (
    PriceAge,
    ScenarioConfig,
    ScenarioCost,
    empirical_quantile,
    evaluate_scenarios,
    min_n_for_quantile,
    price_table_age,
)
from metis_auto.evaluation.lengths import (
    BucketTokenReport,
    LengthSample,
    bucket_token_report,
)

from .composition import ORDER, CaseInputs

EXACT = (
    Fidelity.EXACT_LOCAL.value,
    Fidelity.PROVIDER_REPORTED.value,
    Fidelity.COUNTING_API.value,
)
COST_LABEL = "lower_bound_input_only_uncached"
PROVENANCE = "estimated"
OVERALL_LABEL = "dominated_by_persian"


@dataclass(frozen=True)
class InstructionReuse:
    cases_with_instructions: int
    distinct_instruction_texts: int
    cases_sharing_instructions: int
    """Cases whose literal instruction text appears in at least one other case."""
    share_sharing: float | None


@dataclass(frozen=True)
class ModelSliceStats:
    model_id: str
    n: int
    content_fidelity: str
    tokens_mean: float
    tokens_median: float
    tokens_p90: float | None
    tokens_p95: float | None
    tokens_max: int
    tokens_per_char: float | None
    instruction_share_of_input_mean: float | None
    input_cost_usd_total: Decimal | None
    input_cost_usd_mean: Decimal | None
    cases_in_long_tier: int | None
    cost_label: str = COST_LABEL
    provenance: str = PROVENANCE


@dataclass(frozen=True)
class SliceReport:
    dimension: str
    value: str
    n: int
    label: str
    """``rankable`` or ``descriptive``."""
    label_reason: str | None
    note: str | None
    models: Mapping[str, ModelSliceStats]
    exact_ranking: tuple[str, ...]
    reference_ranking: tuple[str, ...]
    flipped_pairs: tuple[tuple[str, str], ...]
    excluded_from_ranking: tuple[str, ...]
    instruction_reuse: InstructionReuse


@dataclass(frozen=True)
class InputCostReport:
    cases: int
    models: tuple[str, ...]
    slices: tuple[SliceReport, ...]
    length_buckets: Mapping[str, BucketTokenReport]
    """Bucket-versus-token report per language (Persian first)."""
    price_age: PriceAge
    scenario_status: Mapping[str, int]
    """Counts of scenario rows by reason: what stays ``not_evaluated`` and why."""
    assumptions: tuple[str, ...] = field(default_factory=tuple)


# --- helpers ----------------------------------------------------------------


def _long_threshold(entry: CatalogueEntry, prices: PriceTable) -> int | None:
    floors = [
        p.min_input_tokens
        for p in prices.entries
        if p.price_ref == entry.price_ref and p.min_input_tokens
    ]
    return min(floors) if floors else None


def _input_costs(
    models: Sequence[CatalogueEntry],
    prices: PriceTable,
    token_lists: Mapping[str, Sequence[int]],
    fidelity: Fidelity,
) -> tuple[dict[str, list[Decimal]], list[ScenarioCost]]:
    rows = evaluate_scenarios(
        ScenarioConfig(),
        catalogue={e.model_id: e for e in models},
        prices=prices,
        inputs=token_lists,
        input_fidelity=fidelity,
    )
    costs = {
        r.model_id: list(r.per_request_usd)
        for r in rows
        if r.output_scenario == "input_only" and r.state == "computed"
    }
    return costs, rows


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    return sum(values, Decimal(0)) / len(values) if values else None


def _ranking(means: Mapping[str, Decimal]) -> tuple[str, ...]:
    return tuple(sorted(means, key=lambda m: (means[m], m)))


def _flips(
    exact: tuple[str, ...], reference: tuple[str, ...]
) -> tuple[tuple[str, str], ...]:
    pos_e = {m: i for i, m in enumerate(exact)}
    pos_r = {m: i for i, m in enumerate(reference)}
    names = sorted(pos_e)
    return tuple(
        (a, b)
        for i, a in enumerate(names)
        for b in names[i + 1 :]
        if (pos_e[a] < pos_e[b]) != (pos_r[a] < pos_r[b])
    )


def _reuse(cases: Sequence[CaseInputs]) -> InstructionReuse:
    groups = Counter(c.instructions_group for c in cases if c.instructions_group)
    with_instructions = sum(groups.values())
    sharing = sum(n for n in groups.values() if n > 1)
    return InstructionReuse(
        cases_with_instructions=with_instructions,
        distinct_instruction_texts=len(groups),
        cases_sharing_instructions=sharing,
        share_sharing=sharing / with_instructions if with_instructions else None,
    )


def slice_report(
    dimension: str,
    value: str,
    cases: Sequence[CaseInputs],
    *,
    models: Sequence[CatalogueEntry],
    prices: PriceTable,
    min_n: int | None,
    note: str | None = None,
) -> SliceReport:
    n = len(cases)
    ok, reason = sufficient(n, min_n)
    totals = {
        m.model_id: [c.per_model[m.model_id].total_tokens for c in cases]
        for m in models
    }
    content = {
        m.model_id: [c.per_model[m.model_id].content_tokens for c in cases]
        for m in models
    }
    reference = {
        m.model_id: [c.reference.content_tokens for c in cases] for m in models
    }
    fidelities = {
        m.model_id: _worst({c.per_model[m.model_id].content_fidelity for c in cases})
        for m in models
    }
    total_chars = sum(sum(c.chars.values()) for c in cases)
    totals_cost, _ = _input_costs(models, prices, totals, Fidelity.EXACT_LOCAL)
    exact_cost, _ = _input_costs(models, prices, content, Fidelity.EXACT_LOCAL)
    ref_cost, _ = _input_costs(models, prices, reference, Fidelity.APPROXIMATION)
    stats: dict[str, ModelSliceStats] = {}
    for entry in models:
        mid = entry.model_id
        t = [float(x) for x in totals[mid]]
        shares = [
            c.per_model[mid].components.get(ORDER[0], 0) / c.per_model[mid].total_tokens
            for c in cases
            if c.per_model[mid].total_tokens
        ]
        threshold = _long_threshold(entry, prices)
        costs = totals_cost.get(mid)
        stats[mid] = ModelSliceStats(
            model_id=mid,
            n=n,
            content_fidelity=fidelities[mid],
            tokens_mean=sum(t) / n if n else 0.0,
            tokens_median=empirical_quantile(t, 0.5) or 0.0,
            tokens_p90=empirical_quantile(t, 0.9)
            if n >= min_n_for_quantile(0.9)
            else None,
            tokens_p95=empirical_quantile(t, 0.95)
            if n >= min_n_for_quantile(0.95)
            else None,
            tokens_max=int(max(t)) if t else 0,
            tokens_per_char=(sum(t) / total_chars) if total_chars else None,
            instruction_share_of_input_mean=sum(shares) / len(shares)
            if shares
            else None,
            input_cost_usd_total=sum(costs, Decimal(0)) if costs else None,
            input_cost_usd_mean=_mean(costs) if costs else None,
            cases_in_long_tier=(
                sum(1 for x in totals[mid] if x >= threshold) if threshold else None
            ),
        )
    ranked = [
        m.model_id
        for m in models
        if fidelities[m.model_id] in EXACT and exact_cost.get(m.model_id)
    ]
    excluded = tuple(m.model_id for m in models if m.model_id not in ranked)
    exact_means = {m: _mean(exact_cost[m]) for m in ranked}
    ref_means = {m: _mean(ref_cost[m]) for m in ranked if ref_cost.get(m)}
    exact_order = _ranking({m: v for m, v in exact_means.items() if v is not None})
    ref_order = _ranking({m: v for m, v in ref_means.items() if v is not None})
    flips = _flips(exact_order, ref_order) if set(exact_order) == set(ref_order) else ()
    return SliceReport(
        dimension=dimension,
        value=value,
        n=n,
        label="rankable" if ok else "descriptive",
        label_reason=reason,
        note=note,
        models=stats,
        exact_ranking=exact_order,
        reference_ranking=ref_order,
        flipped_pairs=flips,
        excluded_from_ranking=excluded,
        instruction_reuse=_reuse(cases),
    )


_BETTER_FIRST = [
    Fidelity.PROVIDER_REPORTED,
    Fidelity.EXACT_LOCAL,
    Fidelity.COUNTING_API,
    Fidelity.APPROXIMATION,
]


def _worst(values: set[str]) -> str:
    for f in reversed(_BETTER_FIRST):
        if f.value in values:
            return f.value
    return "unknown"


# --- the whole report -------------------------------------------------------


def build_report(
    cases: Sequence[CaseInputs],
    *,
    models: Sequence[CatalogueEntry],
    prices: PriceTable,
    min_n: int | None,
    as_of: date,
    max_age_days: int | None,
    char_bounds: Sequence[int],
) -> InputCostReport:
    by_dim: dict[str, dict[str, list[CaseInputs]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for case in cases:
        for dim, value in case.strata.items():
            by_dim[dim][value].append(case)
    # category values are opaque IDs (possibly keyed fingerprints): report them
    # as numbered strata, never as the IDs themselves
    if "category" in by_dim:
        ranked = sorted(by_dim["category"].items(), key=lambda kv: (-len(kv[1]), kv[0]))
        by_dim["category"] = {f"category_{i + 1}": v for i, (_, v) in enumerate(ranked)}
    slices: list[SliceReport] = []
    languages = by_dim.get("language", {})
    for value in sorted(languages, key=lambda v: (v != PRIMARY_LANGUAGE, v)):
        note = (
            "primary slice"
            if value == PRIMARY_LANGUAGE
            else "separate slice, never pooled into Persian"
        )
        slices.append(
            slice_report(
                "language",
                value,
                languages[value],
                models=models,
                prices=prices,
                min_n=min_n,
                note=note,
            )
        )
    for dim in sorted(d for d in by_dim if d != "language"):
        for value in sorted(by_dim[dim]):
            slices.append(
                slice_report(
                    dim,
                    value,
                    by_dim[dim][value],
                    models=models,
                    prices=prices,
                    min_n=min_n,
                )
            )
    slices.append(
        slice_report(
            "all",
            "all",
            cases,
            models=models,
            prices=prices,
            min_n=min_n,
            note=OVERALL_LABEL,
        )
    )
    lengths = {}
    for value in sorted(languages, key=lambda v: (v != PRIMARY_LANGUAGE, v)):
        samples = [
            LengthSample(
                chars=c.chars["message"],
                tokens={
                    m.model_id: c.per_model[m.model_id].components["message"]
                    for m in models
                },
            )
            for c in languages[value]
        ]
        lengths[value] = bucket_token_report(
            samples, char_bounds, [m.model_id for m in models]
        )
    _, rows = _input_costs(
        models, prices, {m.model_id: [0] for m in models}, Fidelity.EXACT_LOCAL
    )
    status = Counter(r.reason for r in rows if r.state == "not_evaluated")
    return InputCostReport(
        cases=len(cases),
        models=tuple(m.model_id for m in models),
        slices=tuple(slices),
        length_buckets=lengths,
        price_age=price_table_age(prices, as_of=as_of, max_age_days=max_age_days),
        scenario_status=dict(status),
        assumptions=(
            "assumed input: instructions, history, retrieved, message; no compression, "
            "attachments or structured input (A-16)",
            "component order for prefix reasoning follows request_roles (A-55)",
            "language is the placeholder detector (A-43), not validated",
            "token counts are local estimates, not billed tokens; template framing is "
            "an approximation",
            "costs are input-only, uncached lower bounds; no output, reasoning or "
            "cache scenario is set (E2)",
            "sample-derived values are provisional (ADR-0008); no real recorded usage "
            "exists",
        ),
    )


# --- compression versus prefix caching --------------------------------------


def input_prices(
    entry: CatalogueEntry, prices: PriceTable, input_tokens: int
) -> tuple[Decimal, Decimal] | str:
    """(uncached input, cached input) price per token at the tier that
    ``input_tokens`` selects; a string is the reason it cannot be computed."""

    def cost(cached: int) -> Decimal | str:
        usage = TokenUsage(
            model_id=entry.model_id,
            input=TokenCount(
                tokens=input_tokens, fidelity=Fidelity.EXACT_LOCAL, method="e3@1"
            ),
            output=TokenCount(tokens=0, fidelity=Fidelity.EXACT_LOCAL, method="e3@1"),
            cached_input=(
                TokenCount(tokens=cached, fidelity=Fidelity.EXACT_LOCAL, method="e3@1")
                if cached
                else None
            ),
        )
        result = cost_of(usage, entry, prices, CostBasis.PRE_CALL_ESTIMATE)
        if result.status != CostStatus.COMPUTED or result.amount is None:
            return result.reason.value if result.reason else "not_computed"
        return result.amount.amount

    if input_tokens <= 0:
        return "no_input_tokens"
    none, all_cached = cost(0), cost(input_tokens)
    if isinstance(none, str):
        return none
    if isinstance(all_cached, str):
        return all_cached
    return none / input_tokens, all_cached / input_tokens


def compression_break_even(
    before: Mapping[str, int],
    after: Mapping[str, int],
    *,
    changed: Sequence[str],
    cached_components: Sequence[str],
    price_input: Decimal,
    price_cached: Decimal,
) -> Estimate:
    """Cached fraction ``f`` above which a compression costs more than it saves.

    Tokens saved: ``sum(before) - sum(after)``. A prefix cache matches from the
    start, so changing a component loses the cache for itself and everything
    after it. ``P`` is the tokens (before) of ``cached_components`` at or after
    the first changed component in ``ORDER``. If a fraction ``f`` of ``P`` would
    have been cached, the lost discount is ``f * P * (price_input - price_cached)``
    and the saving is ``saved * price_input``; break-even ``f = saved *
    price_input / (P * (price_input - price_cached))``. Above 1 the compression
    pays even if all of ``P`` were cached; with ``P = 0`` it never loses
    discount. No hit rate is assumed: ``f`` is the unknown, and the answer is the
    threshold."""
    saved = sum(before.values()) - sum(after.values())
    if saved <= 0:
        return not_measured("undefined", "no_tokens_saved", 0, PROVENANCE)
    if price_input <= price_cached:
        return not_measured("undefined", "no_cached_discount", 0, PROVENANCE)
    unknown = [c for c in (*changed, *cached_components) if c not in ORDER]
    if unknown:
        raise ValueError(f"unknown components {unknown}; known: {ORDER}")
    if not changed:
        return not_measured("undefined", "nothing_changed", 0, PROVENANCE)
    first = min(ORDER.index(c) for c in changed)
    lost_prefix = sum(
        before.get(c, 0) for c in cached_components if ORDER.index(c) >= first
    )
    if lost_prefix == 0:
        return Estimate(
            "measured",
            0,
            PROVENANCE,
            value=float("inf"),
            method="break_even_cached_fraction",
            extra={
                "tokens_saved": float(saved),
                "cached_tokens_exposed": 0.0,
                "reading": "never_loses_discount",
            },
        )
    f = float(
        Decimal(saved)
        * price_input
        / (Decimal(lost_prefix) * (price_input - price_cached))
    )
    return Estimate(
        "measured",
        0,
        PROVENANCE,
        value=f,
        method="break_even_cached_fraction",
        extra={
            "tokens_saved": float(saved),
            "cached_tokens_exposed": float(lost_prefix),
            "reading": "pays_even_if_fully_cached"
            if f > 1
            else "net_negative_above_this_fraction",
        },
    )
