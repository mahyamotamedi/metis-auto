"""The answer loop: one fresh, independent call per record (ADR-0030).

Resumable and idempotent: a record already answered in this run, or failed for a
reason that is not worth retrying, is skipped, so a crash never repeats or loses a
paid call. Each result is written to the local backup before the database. Only
retryable errors (timeout, rate limit, server error, connection) are retried, with
backoff; content filter, context overflow and an unknown model are recorded as
failures. Reserves are never swapped in: a failure is a recorded failure.

No cache, routing, compression, escalation or shared conversation: each call gets
only its own parts. Calls the live client, the store and the spend guard through
ports; knows no database and no provider.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from metis_auto.contracts import (
    AttemptKind,
    CatalogueEntry,
    Cost,
    CostBasis,
    CostEstimate,
    CostStatus,
    ErrorClass,
    FinishReason,
    InputPart,
    ModelError,
    ModelInvocation,
    ModelNoAnswer,
    ModelResponse,
    PriceTable,
    TokenCount,
)
from metis_auto.domain.accounting.cost import cost_of, pre_call_estimate
from metis_auto.evaluation.golden_answers.config import RETRYABLE, AnswerSettings
from metis_auto.ports import Clock, ModelClient


@dataclass(frozen=True)
class Task:
    """One record's request. ``strata`` holds opaque labels only, never text."""

    record_id: str
    parts: tuple[InputPart, ...]
    caveats: tuple[str, ...]
    fingerprint: str
    input_tokens: TokenCount
    strata: Mapping[str, str]


@dataclass(frozen=True)
class AnswerRow:
    run_id: str
    record_id: str
    model_id: str
    effort: str | None
    max_output_tokens: int
    settings_hash: str
    prompt_fingerprint: str
    status: str
    """``answered`` or ``failed``."""
    answer: str | None
    answer_chars: int | None
    answer_language_group: str | None
    finish_reason: str | None
    error_class: str | None
    attempts: int
    provider_model_version: str | None
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    cost_usd: Decimal | None
    cost_state: str
    latency_ms: float | None
    caveats: tuple[str, ...]


class AnswerStore(Protocol):
    def terminal(self, run_id: str) -> Mapping[str, tuple[str, str | None]]:
        """record_id → (status, error_class) for every stored record of the run."""
        ...

    def save(self, row: AnswerRow) -> None: ...


class Spend(Protocol):
    """The spend guard and its ledger, as the loop needs them."""

    @property
    def stopped(self) -> str | None: ...

    def allows(self, estimate: CostEstimate) -> bool: ...

    def charge_actual(self, cost: Cost, estimate: CostEstimate) -> None: ...

    def charge_estimate(self, estimate: CostEstimate) -> None:
        """A call that may have been billed without usable usage (a timeout)."""
        ...


@dataclass(frozen=True)
class Halt:
    reason: str
    record_id: str | None = None


@dataclass
class RunReport:
    answered: int = 0
    failed: int = 0
    skipped: int = 0
    calls: int = 0
    halts: list[Halt] = field(default_factory=list)
    charged_usd: Decimal = Decimal(0)


def run_answers(
    tasks: Sequence[Task],
    *,
    run_id: str,
    client: ModelClient,
    entry: CatalogueEntry,
    prices: PriceTable,
    settings: AnswerSettings,
    store: AnswerStore,
    spend: Spend,
    clock: Clock,
    classify_language: Callable[[str], str],
    backup: Callable[[AnswerRow], None] = lambda row: None,
    limit: int | None = None,
    halt_after_failed_records: int = 5,
) -> RunReport:
    """Answer ``tasks`` in the given order, at most ``limit`` new records."""
    report = RunReport()
    stored = store.terminal(run_id)
    consecutive_failed = 0
    started_records = 0
    for task in tasks:
        status = stored.get(task.record_id)
        if status is not None and (
            status[0] == "answered" or status[1] not in RETRYABLE
        ):
            report.skipped += 1
            continue
        if limit is not None and started_records >= limit:
            break
        estimate = pre_call_estimate(
            entry, task.input_tokens, settings.max_output_tokens, prices
        )
        if not spend.allows(estimate):
            report.halts.append(
                Halt(spend.stopped or "cap_would_be_exceeded", task.record_id)
            )
            break
        started_records += 1
        row = _answer_one(
            task, run_id, client, entry, prices, settings, spend, clock, estimate,
            classify_language, report,
        )  # fmt: skip
        backup(row)
        store.save(row)
        if row.status == "answered":
            report.answered += 1
            consecutive_failed = 0
        else:
            report.failed += 1
            consecutive_failed += 1
            if consecutive_failed >= halt_after_failed_records:
                report.halts.append(Halt("consecutive_failures", task.record_id))
                break
        if spend.stopped:
            report.halts.append(Halt(spend.stopped, task.record_id))
            break
    return report


def _answer_one(
    task: Task,
    run_id: str,
    client: ModelClient,
    entry: CatalogueEntry,
    prices: PriceTable,
    settings: AnswerSettings,
    spend: Spend,
    clock: Clock,
    estimate: CostEstimate,
    classify_language: Callable[[str], str],
    report: RunReport,
) -> AnswerRow:
    invocation = ModelInvocation(
        request_id=_ident("req", run_id, task.record_id),
        attempt_id=_ident("att", run_id, task.record_id),
        attempt_kind=AttemptKind.PRIMARY,
        model_id=settings.model_id,
        parts=task.parts,
        max_output_tokens=settings.max_output_tokens,
        effort=settings.reasoning_effort,
    )
    result = None
    attempts = 0
    for attempt in range(1, settings.retry_max_attempts + 1):
        if attempt > 1:
            clock.sleep_ms(settings.backoff_seconds[attempt - 2] * 1000)
            if not spend.allows(estimate):
                break
        attempts = attempt
        began = clock.monotonic_ms()
        result = client.invoke(invocation)
        wall = clock.monotonic_ms() - began
        report.calls += 1
        if isinstance(result, ModelError):
            if result.error_class == ErrorClass.TIMEOUT:
                spend.charge_estimate(estimate)  # may have generated and been billed
            if result.error_class.value in RETRYABLE:
                continue
        break
    base = _base(task, run_id, settings, attempts)
    if isinstance(result, ModelResponse):
        return _from_response(
            base, result, wall, entry, prices, spend, estimate, classify_language
        )
    error = (
        result.error_class.value
        if isinstance(result, ModelError)
        else ("no_answer" if isinstance(result, ModelNoAnswer) else "budget_stopped")
    )
    return AnswerRow(
        **base, status="failed", answer=None, answer_chars=None,
        answer_language_group=None, finish_reason=None, error_class=error,
        provider_model_version=None, input_tokens=None, cached_input_tokens=None,
        output_tokens=None, reasoning_tokens=None, cost_usd=None,
        cost_state="error", latency_ms=None,
    )  # fmt: skip


def _from_response(
    base, result: ModelResponse, wall_ms, entry, prices, spend, estimate, classify
) -> AnswerRow:
    usage = result.usage
    cost = cost_of(usage, entry, prices, CostBasis.ACTUAL)
    spend.charge_actual(cost, estimate)
    computed = cost.status == CostStatus.COMPUTED and cost.amount is not None
    text = result.text
    if result.finish_reason == FinishReason.CONTENT_FILTER:
        status, error = "failed", ErrorClass.CONTENT_FILTERED.value
    elif not text.strip():
        status, error = "failed", "empty_answer"
    else:
        status, error = "answered", None
    kept = status == "answered"
    return AnswerRow(
        **base,
        status=status,
        answer=text if kept else None,
        answer_chars=len(text) if kept else None,
        answer_language_group=classify(text) if kept else None,
        finish_reason=result.finish_reason.value,
        error_class=error,
        provider_model_version=result.provider_model_version,
        input_tokens=usage.input.tokens if usage else None,
        cached_input_tokens=usage.cached_input.tokens
        if usage and usage.cached_input
        else None,
        output_tokens=usage.output.tokens if usage and usage.output else None,
        reasoning_tokens=usage.reasoning.tokens if usage and usage.reasoning else None,
        cost_usd=cost.amount.amount if computed and cost.amount else None,
        cost_state="reported" if computed else "not_computed",
        latency_ms=result.provider_latency_ms
        if result.provider_latency_ms is not None
        else wall_ms,
    )


def _base(task: Task, run_id: str, settings: AnswerSettings, attempts: int) -> dict:
    return {
        "run_id": run_id,
        "record_id": task.record_id,
        "model_id": settings.model_id,
        "effort": settings.reasoning_effort,
        "max_output_tokens": settings.max_output_tokens,
        "settings_hash": settings.settings_hash,
        "prompt_fingerprint": task.fingerprint,
        "attempts": attempts,
        "caveats": task.caveats,
    }


def _ident(kind: str, run_id: str, record_id: str) -> str:
    digest = hashlib.sha256(f"{run_id}|{record_id}".encode()).hexdigest()[:16]
    return f"{kind}-{digest}"


def select_pilot(tasks: Sequence[Task], size: int, seed: str) -> list[Task]:
    """``size`` records covering as many strata values as possible: each pick is
    the one adding the most unseen (key, value) pairs, ties broken by a seeded
    hash. Deterministic; independent of input order."""

    def rank(t: Task) -> str:
        return hashlib.blake2b(
            f"{seed}|{t.record_id}".encode(), digest_size=16
        ).hexdigest()

    pool = sorted(tasks, key=lambda t: (rank(t), t.record_id))
    seen: set[tuple[str, str]] = set()
    picked: list[Task] = []
    while pool and len(picked) < size:
        best = max(
            pool,
            key=lambda t: (len(set(t.strata.items()) - seen), -pool.index(t)),
        )
        picked.append(best)
        seen |= set(best.strata.items())
        pool.remove(best)
    return picked
