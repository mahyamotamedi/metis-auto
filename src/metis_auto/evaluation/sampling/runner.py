"""The shared sampling run: plan, estimate, guard, execute (Stage E4; framework
§5; ADR-0003, ADR-0014, ADR-0018).

One run serves cost calibration (provider-reported usage per call) and quality
evaluation (the answers, recorded by the recording decorator the caller wraps
around its clients; this module holds no answer text). It is a plain loop over
planned calls through injected ``ModelClient``s: it never builds a live client,
reads no key, and ``execute`` refuses to start (before any call) unless:
a model list, a hard cap, a generation limit and an order seed are configured;
every input size is known; and any **live** client is covered by an explicit
``LiveApproval`` (who, which run, a USD cap, and sample-conversation approval
when the units come from the sample). The cap is then enforced per call
against a worst case: realized charge so far plus the call's cost at
``max_output_tokens``; a call whose usage is not reported is charged at that
worst case.

Estimates are never presented as measurements: ``lower_bound_usd`` (input only),
``assumed_usd`` (only with a documented output assumption; simulated) and
``ceiling_usd`` (generation-limit worst case). Stop rules (failure and
truncation share per model, cost overrun) apply only when configured. Provenance:
live and recorded sources are ``measured``, anything else ``simulated``.
No call retries (ADR-0013); the retry count is 0. The effort label rides on the
invocation and time to first token on the response (Stage E6 fields); a client
that does not measure it gives ``not_reported``.
Pure apart from the injected clients and clock. Status: provisional (Stage E4);
exercised with fakes only.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from metis_auto.contracts import (
    AnswerSource,
    CatalogueEntry,
    CostBasis,
    CostStatus,
    Fidelity,
    FinishReason,
    ModelError,
    ModelInvocation,
    ModelNoAnswer,
    ModelResponse,
    PriceTable,
    TokenCount,
    TokenUsage,
)
from metis_auto.domain.accounting.cost import cost_of
from metis_auto.ports import Clock, ModelClient

from .allocation import SamplingUnit
from .config import LiveApproval, RunConfig

PROVENANCE = {
    AnswerSource.LIVE: "measured",
    AnswerSource.RECORDED: "measured",
}


class RunRefused(Exception):
    """The run did not start; ``reason`` says why. No call was made."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class PlannedCall:
    case_id: str
    session_ref: str
    model_id: str
    effort: str | None
    repeat_index: int


def plan_calls(
    selected_ids: Sequence[str],
    units: Mapping[str, SamplingUnit],
    config: RunConfig,
) -> list[PlannedCall]:
    """Models × efforts for every selected unit, the repeat subset repeated, in
    a seeded shuffled order. Needs ``models`` and ``order_seed``."""
    if not config.models:
        raise RunRefused("models_unset")
    if not config.order_seed:
        raise RunRefused("order_seed_unset")
    calls: list[PlannedCall] = []
    repeats = 1 + (config.repeat_count or 0)
    for position, case_id in enumerate(selected_ids):
        unit = units[case_id]
        in_repeat_subset = (
            config.repeat_units is not None and position < config.repeat_units
        )
        for repeat in range(repeats if in_repeat_subset else 1):
            for model in config.models:
                for effort in config.efforts.get(model, (None,)):
                    calls.append(
                        PlannedCall(case_id, unit.session_ref, model, effort, repeat)
                    )
    random.Random(config.order_seed).shuffle(calls)
    return calls


def partition_image_calls(
    calls: Sequence[PlannedCall],
    units: Mapping[str, SamplingUnit],
    *,
    vision_models: frozenset[str] | None,
) -> tuple[list[PlannedCall], dict[str, int]]:
    """Drop calls on attachment-bearing turns to models not known to see images
    (FR-EVAL-08). ``vision_models`` is config: unset means no model is assumed
    to see images. Returns the kept calls and the excluded count per reason, so
    the exclusion is reported, never silent."""
    kept: list[PlannedCall] = []
    excluded: dict[str, int] = {}
    for call in calls:
        if units[call.case_id].strata.get("attachments") != "yes":
            kept.append(call)
            continue
        if vision_models is None:
            reason = "vision_capability_unset"
        elif call.model_id not in vision_models:
            reason = "model_not_vision"
        else:
            kept.append(call)
            continue
        excluded[reason] = excluded.get(reason, 0) + 1
    return kept, excluded


# --- estimates ---------------------------------------------------------------


@dataclass(frozen=True)
class RunEstimate:
    calls: int
    lower_bound_usd: Decimal | None
    """Input only, no output, no cache discount: cannot overstate the bill."""
    assumed_usd: Decimal | None
    """With the documented output assumption; simulated. None without one."""
    ceiling_usd: Decimal | None
    """Every call at ``max_output_tokens``: the worst case the cap guards."""
    reasons: Mapping[str, str] = field(default_factory=dict)


def _price(
    entry: CatalogueEntry, prices: PriceTable, input_tokens: int, output_tokens: int
) -> Decimal | str:
    usage = TokenUsage(
        model_id=entry.model_id,
        input=TokenCount(
            tokens=input_tokens, fidelity=Fidelity.EXACT_LOCAL, method="e4@1"
        ),
        output=TokenCount(
            tokens=output_tokens, fidelity=Fidelity.APPROXIMATION, method="e4@1"
        ),
    )
    cost = cost_of(usage, entry, prices, CostBasis.PRE_CALL_ESTIMATE)
    if cost.status != CostStatus.COMPUTED or cost.amount is None:
        return cost.reason.value if cost.reason else "not_computed"
    return cost.amount.amount


def estimate_run(
    calls: Sequence[PlannedCall],
    *,
    input_tokens: Mapping[tuple[str, str], int],
    catalogue: Mapping[str, CatalogueEntry],
    prices: PriceTable,
    config: RunConfig,
) -> RunEstimate:
    reasons: dict[str, str] = {}
    totals = {"lower": Decimal(0), "assumed": Decimal(0), "ceiling": Decimal(0)}
    ok = {
        "lower": True,
        "assumed": config.output_tokens_assumption is not None,
        "ceiling": config.max_output_tokens is not None,
    }
    if not ok["assumed"]:
        reasons["assumed_usd"] = "output_assumption_unset"
    if not ok["ceiling"]:
        reasons["ceiling_usd"] = "max_output_tokens_unset"
    for call in calls:
        entry = catalogue.get(call.model_id)
        tokens = input_tokens.get((call.case_id, call.model_id))
        if entry is None or tokens is None:
            for key in ok:
                ok[key] = False
            reasons["lower_bound_usd"] = "model_or_input_size_unknown"
            continue
        lower = _price(entry, prices, tokens, 0)
        if isinstance(lower, str):
            reasons["lower_bound_usd"] = lower
            ok["lower"] = False
        else:
            totals["lower"] += lower
        if ok["assumed"]:
            assumed_tokens = (config.output_tokens_assumption or {}).get(call.model_id)
            if assumed_tokens is None:
                ok["assumed"] = False
                reasons["assumed_usd"] = f"assumption_missing_for:{call.model_id}"
            else:
                value = _price(entry, prices, tokens, assumed_tokens)
                if isinstance(value, str):
                    ok["assumed"] = False
                    reasons["assumed_usd"] = value
                else:
                    totals["assumed"] += value
        if ok["ceiling"]:
            assert config.max_output_tokens is not None
            value = _price(entry, prices, tokens, config.max_output_tokens)
            if isinstance(value, str):
                ok["ceiling"] = False
                reasons["ceiling_usd"] = value
            else:
                totals["ceiling"] += value
    return RunEstimate(
        len(calls),
        totals["lower"] if ok["lower"] else None,
        totals["assumed"] if ok["assumed"] else None,
        totals["ceiling"] if ok["ceiling"] else None,
        reasons,
    )


# --- the live guard ------------------------------------------------------------


def _require_bool(value: object) -> None:
    """``uses_sample_conversations`` must be True or False, stated by the caller:
    a missing or truthy-looking value (None, 0, "") could otherwise skip the
    sample-conversation approval."""
    if not isinstance(value, bool):
        raise TypeError(
            "uses_sample_conversations must be True or False, stated explicitly"
        )


def check_live(
    sources: Sequence[AnswerSource],
    *,
    approval: LiveApproval | None,
    uses_sample_conversations: bool,
    hard_cap_usd: Decimal,
) -> Decimal:
    """The effective cap. A ``live`` source needs an approval; without any
    live source the run's own cap applies."""
    _require_bool(uses_sample_conversations)
    if AnswerSource.LIVE not in sources:
        return hard_cap_usd
    if approval is None:
        raise RunRefused("live_run_needs_owner_approval")
    if uses_sample_conversations and not approval.sample_conversations_approved:
        raise RunRefused("sample_conversations_need_per_run_approval")
    return min(hard_cap_usd, approval.cap_usd)


# --- records and execution ---------------------------------------------------


@dataclass(frozen=True)
class CallRecord:
    """Content-free record of one call (no text; the answer lives only in the
    recorded store)."""

    case_id: str
    session_ref: str
    model_id: str
    effort: str | None
    repeat_index: int
    source: str
    provenance: str
    outcome: str
    """``response``, ``error`` or ``no_answer``."""
    error_class: str | None
    finish_reason: str | None
    truncated: bool
    input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    cached_input_tokens: int | None
    cache_write_tokens: int | None
    answer_chars: int | None
    latency_ms: float | None
    latency_source: str | None
    ttft_ms: float | None
    ttft_state: str
    provider_model_version: str | None
    retry_count: int
    cost_usd: Decimal | None
    cost_state: str
    """``reported`` (from provider usage), or why not (``usage_not_reported``…)."""


@dataclass(frozen=True)
class Halt:
    model_id: str | None
    """None halts the whole run."""
    reason: str
    after_call: int


@dataclass(frozen=True)
class RunResult:
    records: tuple[CallRecord, ...]
    halts: tuple[Halt, ...]
    planned_calls: int
    executed_calls: int
    skipped_calls: int
    realized_usd: Decimal
    """Sum of costs computed from reported usage."""
    unreported_cost_calls: int
    charged_usd: Decimal
    """What the cap saw: realized cost, or the worst case where usage was not
    reported."""
    cap_usd: Decimal
    estimate: RunEstimate
    stop_rules: Mapping[str, str]
    sources: tuple[str, ...]


def _stop_rule_status(config: RunConfig, estimate: RunEstimate) -> dict[str, str]:
    def share(value: float | None) -> str:
        if value is None:
            return "unset"
        return (
            "active"
            if config.stop_rule_min_calls
            else "inactive_stop_rule_min_calls_unset"
        )

    overrun = "unset"
    if (
        config.overrun_factor is not None
        and config.overrun_check_at_progress is not None
    ):
        overrun = (
            "active"
            if estimate.assumed_usd is not None
            else "inactive_no_assumed_estimate"
        )
    elif (
        config.overrun_factor is not None
        or config.overrun_check_at_progress is not None
    ):
        overrun = "inactive_incomplete_configuration"
    return {
        "failure_share": share(config.max_failure_share),
        "truncation_share": share(config.max_truncation_share),
        "cost_overrun": overrun,
    }


def execute(
    calls: Sequence[PlannedCall],
    *,
    client_for: Callable[[str, str | None], ModelClient],
    build_invocation: Callable[[str, str], ModelInvocation],
    config: RunConfig,
    catalogue: Mapping[str, CatalogueEntry],
    prices: PriceTable,
    input_tokens: Mapping[tuple[str, str], int],
    clock: Clock,
    uses_sample_conversations: bool,
    approval: LiveApproval | None = None,
) -> RunResult:
    # stated explicitly by the caller, never assumed: a live run on sample
    # conversations needs per-run approval (ADR-0018)
    _require_bool(uses_sample_conversations)
    if config.hard_cap_usd is None:
        raise RunRefused("hard_cap_unset")
    if config.max_output_tokens is None:
        raise RunRefused("max_output_tokens_unset")
    missing = sorted(
        {
            (c.case_id, c.model_id)
            for c in calls
            if (c.case_id, c.model_id) not in input_tokens
        }
    )
    if missing or any(c.model_id not in catalogue for c in calls):
        raise RunRefused("input_size_or_model_unknown")
    clients = {(c.model_id, c.effort): client_for(c.model_id, c.effort) for c in calls}
    cap = check_live(
        [cl.source for cl in clients.values()],
        approval=approval,
        uses_sample_conversations=uses_sample_conversations,
        hard_cap_usd=config.hard_cap_usd,
    )
    estimate = estimate_run(
        calls,
        input_tokens=input_tokens,
        catalogue=catalogue,
        prices=prices,
        config=config,
    )
    status = _stop_rule_status(config, estimate)
    records: list[CallRecord] = []
    halts: list[Halt] = []
    halted: set[str] = set()
    per_model = {
        m: {"calls": 0, "failures": 0, "truncations": 0} for m in config.models
    }
    realized = Decimal(0)
    charged = Decimal(0)
    unreported = 0
    skipped = 0
    overrun_checked = False
    for index, call in enumerate(calls):
        if call.model_id in halted:
            skipped += 1
            continue
        entry = catalogue[call.model_id]
        tokens = input_tokens[(call.case_id, call.model_id)]
        worst = _price(entry, prices, tokens, config.max_output_tokens)
        if isinstance(worst, str):
            halts.append(Halt(None, f"worst_case_cost_unknown:{worst}", index))
            skipped += len(calls) - index
            break
        if charged + worst > cap:
            halts.append(Halt(None, "cap_would_be_exceeded", index))
            skipped += len(calls) - index
            break
        client = clients[(call.model_id, call.effort)]
        invocation = build_invocation(call.case_id, call.model_id).model_copy(
            update={
                "max_output_tokens": config.max_output_tokens,
                "effort": call.effort,
            }
        )
        started = clock.monotonic_ms()
        result = client.invoke(invocation)
        wall = clock.monotonic_ms() - started
        record = _record(call, client.source, result, wall, entry, prices)
        records.append(record)
        stats = per_model.setdefault(
            call.model_id, {"calls": 0, "failures": 0, "truncations": 0}
        )
        stats["calls"] += 1
        stats["failures"] += record.outcome != "response"
        stats["truncations"] += record.truncated
        if record.cost_usd is not None:
            realized += record.cost_usd
            charged += record.cost_usd
        else:
            unreported += 1
            charged += worst
        _apply_stop_rules(config, status, call.model_id, stats, index, halts, halted)
        progress = (index + 1) / len(calls)
        if (
            status["cost_overrun"] == "active"
            and not overrun_checked
            and config.overrun_check_at_progress is not None
            and progress >= config.overrun_check_at_progress
        ):
            overrun_checked = True
            assert (
                estimate.assumed_usd is not None and config.overrun_factor is not None
            )
            if realized > Decimal(
                str(config.overrun_factor)
            ) * estimate.assumed_usd * Decimal(str(progress)):
                halts.append(Halt(None, "cost_overrun", index))
                skipped += len(calls) - index - 1
                break
    return RunResult(
        records=tuple(records),
        halts=tuple(halts),
        planned_calls=len(calls),
        executed_calls=len(records),
        skipped_calls=skipped,
        realized_usd=realized,
        unreported_cost_calls=unreported,
        charged_usd=charged,
        cap_usd=cap,
        estimate=estimate,
        stop_rules=status,
        sources=tuple(sorted({cl.source.value for cl in clients.values()})),
    )


def _apply_stop_rules(
    config: RunConfig,
    status: Mapping[str, str],
    model_id: str,
    stats: Mapping[str, int],
    index: int,
    halts: list[Halt],
    halted: set[str],
) -> None:
    if model_id in halted or not config.stop_rule_min_calls:
        return
    if stats["calls"] < config.stop_rule_min_calls:
        return
    for rule, limit, count in (
        ("failure_share", config.max_failure_share, stats["failures"]),
        ("truncation_share", config.max_truncation_share, stats["truncations"]),
    ):
        if (
            status[rule] == "active"
            and limit is not None
            and count / stats["calls"] > limit
        ):
            halts.append(Halt(model_id, f"{rule}_exceeded", index))
            halted.add(model_id)
            return


def _record(
    call: PlannedCall,
    source: AnswerSource,
    result: ModelResponse | ModelError | ModelNoAnswer,
    wall_ms: float,
    entry: CatalogueEntry,
    prices: PriceTable,
) -> CallRecord:
    provenance = PROVENANCE.get(source, "simulated")
    base = {
        "case_id": call.case_id,
        "session_ref": call.session_ref,
        "model_id": call.model_id,
        "effort": call.effort,
        "repeat_index": call.repeat_index,
        "source": source.value,
        "provenance": provenance,
        "retry_count": 0,
        "ttft_ms": None,
        "ttft_state": "not_reported",
    }
    empty = {
        "error_class": None,
        "finish_reason": None,
        "truncated": False,
        "input_tokens": None,
        "output_tokens": None,
        "reasoning_tokens": None,
        "cached_input_tokens": None,
        "cache_write_tokens": None,
        "answer_chars": None,
        "latency_ms": None,
        "latency_source": None,
        "provider_model_version": None,
        "cost_usd": None,
    }
    if isinstance(result, ModelNoAnswer):
        return CallRecord(
            **base, **empty, outcome="no_answer", cost_state=result.reason.value
        )
    if isinstance(result, ModelError):
        fields = {**empty, "error_class": result.error_class.value}
        fields["latency_ms"] = (
            result.provider_latency_ms
            if result.provider_latency_ms is not None
            else wall_ms
        )
        fields["latency_source"] = (
            "provider" if result.provider_latency_ms is not None else "measured_wall"
        )
        return CallRecord(**base, **fields, outcome="error", cost_state="error")
    usage = result.usage
    cost = cost_of(usage, entry, prices, CostBasis.ACTUAL) if usage else None
    computed = (
        cost is not None
        and cost.status == CostStatus.COMPUTED
        and cost.amount is not None
    )
    fields = {
        "error_class": None,
        "finish_reason": result.finish_reason.value,
        "truncated": result.finish_reason == FinishReason.LENGTH,
        "input_tokens": usage.input.tokens if usage else None,
        "output_tokens": usage.output.tokens if usage and usage.output else None,
        "reasoning_tokens": usage.reasoning.tokens
        if usage and usage.reasoning
        else None,
        "cached_input_tokens": usage.cached_input.tokens
        if usage and usage.cached_input
        else None,
        "cache_write_tokens": usage.cache_write.tokens
        if usage and usage.cache_write
        else None,
        "answer_chars": len(result.text),
        "latency_ms": result.provider_latency_ms
        if result.provider_latency_ms is not None
        else wall_ms,
        "latency_source": "provider"
        if result.provider_latency_ms is not None
        else "measured_wall",
        "provider_model_version": result.provider_model_version,
        "cost_usd": cost.amount.amount if computed and cost and cost.amount else None,
    }
    state = (
        "reported"
        if computed
        else ("usage_not_reported" if usage is None else "not_computed")
    )
    return CallRecord(
        **{
            **base,
            "ttft_ms": result.time_to_first_token_ms,
            "ttft_state": "reported"
            if result.time_to_first_token_ms is not None
            else "not_reported",
        },
        **fields,
        outcome="response",
        cost_state=state,
    )
