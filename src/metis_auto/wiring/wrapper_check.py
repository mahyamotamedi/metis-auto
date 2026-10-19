"""The tiny live wrapper check (Stage 7.5; brief §3, TODO-12, A-46, A-54, A-56).

Responsibility: send ONE tiny synthetic message (short instructions plus a
mixed Persian/English message) to each test model through the real pipeline,
with the spend guard, the persistent ledger, and the recording decorator, and
compare what the Metis wrapper reports with what we count locally: input
tokens (content and chat framing), output tokens vs the visible answer,
whether cached and reasoning tokens are reported, the finish reason, the
provider-reported model, and the cost. Results are content-free (no answer
text) and dated.

``plan`` makes no call: it returns the spend guard's pre-call estimate per
model. ``run`` makes the live calls; the script asks the owner first.
Called by: ``scripts/live_wrapper_check.py``, tests (mocked HTTP).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from metis_auto.contracts import (
    AnswerSource,
    Component,
    CostStatus,
    ModelError,
    ModelInvocation,
    ModelResponse,
    ModelResult,
    Request,
)
from metis_auto.domain.context import reserved_output
from metis_auto.ports import ModelClient
from metis_auto.settings import LoadedSettings

from .chat import ChatSession, ClientFactory, SettingsLoader
from .from_settings import build_accounting_service, pipeline_config
from .live import build_live_client, live_overrides

CHECK_MODELS: tuple[str, ...] = (
    "gpt-5-nano",
    "gpt-4.1-nano",
    "gpt-4o-mini",
    "deepseek-v4-flash",
    "mimo-v2.5",
)
"""The five test models. Until Q-32 (2026-10-18) the fifth was grok-4-1-fast:
the first check's JSON records that list."""
INSTRUCTIONS = "[SYNTHETIC] You are a test assistant. Reply in one short sentence."
MESSAGE = "[SYNTHETIC] سلام! Please reply with the word OK."
MAX_TOTAL_ESTIMATE = Decimal("0.05")
"""Owner's limit for the whole check (USD), on the pre-call estimates."""


def check_request() -> Request:
    return Request(
        message=MESSAGE,
        instructions=Component.present(INSTRUCTIONS),
        history=Component.absent(),
        retrieved=Component.absent(),
        attachments=Component.absent(),
        structured_input=Component.absent(),
    )


@dataclass(frozen=True)
class PlanRow:
    model_id: str
    input_tokens: int
    output_limit: int
    estimate: Decimal | None
    currency: str


def plan(
    loaded: LoadedSettings,
    models: Sequence[str] = CHECK_MODELS,
    request: Request | None = None,
) -> tuple[list[PlanRow], Decimal | None]:
    """Pre-call estimates (counted input + framing + the generation limit as
    output) for one call per model: an upper bound on what the calls can cost,
    if counts hold. The total is None if any estimate is not computed."""
    accounting = build_accounting_service(loaded)
    context = pipeline_config(loaded).context
    request = request or check_request()
    rows, total = [], Decimal(0)
    for model_id in models:
        entry = accounting.entry(model_id)
        limit = reserved_output(entry, context)
        estimate = accounting.pre_call_estimate(request, model_id, limit)
        amount = estimate.cost.amount
        computed = estimate.cost.status == CostStatus.COMPUTED and amount
        rows.append(
            PlanRow(
                model_id=model_id,
                input_tokens=estimate.input_tokens.tokens,
                output_limit=limit,
                estimate=amount.amount if computed else None,
                currency=amount.currency if computed else "USD",
            )
        )
        if total is not None and computed:
            total += amount.amount
        else:
            total = None
    return rows, total


class _Capture:
    """Keeps the last raw ``ModelResult`` (wiring-local diagnostic tap)."""

    def __init__(self, inner: ModelClient) -> None:
        self._inner = inner
        self.last: ModelResult | None = None

    @property
    def source(self) -> AnswerSource:
        return self._inner.source

    def invoke(self, invocation: ModelInvocation) -> ModelResult:
        self.last = self._inner.invoke(invocation)
        return self.last


def run(
    settings_loader: SettingsLoader,
    *,
    models: Sequence[str] = CHECK_MODELS,
    client_factory: ClientFactory = build_live_client,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Make the live calls (one per model) and return the content-free
    results. Each model gets one attempt: no retry, no failover, so every row
    describes exactly the model it names."""
    stamp = datetime.now(UTC)
    run_id = run_id or f"wrapper-check-{stamp:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    taps: dict[str, _Capture] = {}

    def factory(loaded: LoadedSettings, rid: str) -> ModelClient:
        tap = _Capture(client_factory(loaded, rid))
        taps["current"] = tap
        return tap

    rows = []
    session: ChatSession | None = None
    for model_id in models:
        session = ChatSession(
            model_id,
            live=True,
            instructions=INSTRUCTIONS,
            allow_unknown_window=True,
            single_attempt=True,
            settings_loader=settings_loader,
            client_factory=factory,
            run_id=run_id,
        )
        request = session.request_for(MESSAGE)
        response, report = session.ask(MESSAGE)
        rows.append(
            _row(session, request, response.answer, report, taps["current"].last)
        )
        if report.live_stopped:
            break  # the guard stopped live calls: do not go on
    return {
        "check": "metis-wrapper-live-check",
        "date": stamp.date().isoformat(),
        "time_utc": stamp.isoformat(timespec="seconds"),
        "run_id": run_id,
        "synthetic_input": {"instructions": INSTRUCTIONS, "message": MESSAGE},
        "message_layout": "A-55: instructions as a system message, then the user "
        "message",
        "config": session.loaded.reference.versions() if session else {},
        "results": rows,
        "budget_after": session.budget() if session else {},
    }


def _row(
    session: ChatSession,
    request: Request,
    answer: str | None,
    report,
    result: ModelResult | None,
) -> dict[str, Any]:
    model_id = session.model_id
    row: dict[str, Any] = {"model_id": model_id, "status": report.status}
    if result is None:
        row["outcome"] = "no call (blocked before the call)"
        row["failure"] = report.failure
        return row
    if isinstance(result, ModelError):
        row |= {
            "outcome": "error",
            "error_class": result.error_class.value,
            "provider_error_code": result.provider_error_code,
            "latency_ms": _round(result.provider_latency_ms),
            "charged": report.budget.get("run_spent"),
            "live_stopped": report.live_stopped,
        }
        return row
    assert isinstance(result, ModelResponse)
    accounting = session.accounting
    content = accounting.content_tokens(request, model_id)
    counted = accounting.account(request, model_id, answer or "").usage
    usage = result.usage
    row |= {
        "outcome": "response",
        "provider_model": result.provider_model_version,
        "finish_reason": result.finish_reason.value,
        "answer_chars": len(answer or ""),
        "latency_ms": _round(result.provider_latency_ms),
        "local": {
            "content_input": content.tokens,
            "content_fidelity": content.fidelity.value,
            "content_method": content.method,
            "template_overhead": counted.template_overhead.tokens
            if counted.template_overhead
            else None,
            "counted_input": counted.input.tokens,
            "visible_answer_tokens": counted.output.tokens if counted.output else None,
        },
        "reported": _usage(usage),
        "cost": report.cost,
        "cost_caveats": list(report.cost_caveats),
    }
    if usage is not None:
        visible = counted.output.tokens if counted.output else 0
        reasoning = usage.reasoning.tokens if usage.reasoning else 0
        out = usage.output.tokens if usage.output else 0
        row["comparison"] = {
            "input_reported_minus_counted": usage.input.tokens - counted.input.tokens,
            "input_reported_minus_content": usage.input.tokens - content.tokens,
            "output_reported_minus_visible": out - visible,
            "output_unexplained": out - visible - reasoning,
        }
    return row


def _usage(usage) -> dict[str, Any] | None:
    if usage is None:
        return None

    def c(count):
        return (
            None if count is None else {"tokens": count.tokens, "field": count.method}
        )

    return {
        "input": c(usage.input),
        "output": c(usage.output),
        "cached_input": c(usage.cached_input),
        "reasoning": c(usage.reasoning),
    }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


# --- Stage 7.5 follow-up probe (Q-33 b, Q-32, Q-34; owner decisions 2026-10-18)

PROBE_MAX_TOTAL = Decimal("0.02")
"""Owner's limit for the whole probe (USD), on the pre-call estimates."""
CACHE_OUTPUT_CAP = 512
"""Generation limit of the cache-probe calls: room for some hidden reasoning,
small enough to keep the bound low."""
CACHE_MESSAGES = (
    "[SYNTHETIC] Using the rules above, reply with the word OK.",
    "[SYNTHETIC] Using the rules above, reply with the word YES.",
)
"""Two different messages after the same long instructions: Metis's own exact
cache misses (the message is in its key), while the provider can reuse the
shared prefix."""
THINKING_OFF = {"model_options.deepseek-v4-flash.thinking": "disabled"}


def long_instructions(rules: int = 30) -> str:
    """Deterministic SYNTHETIC instructions, above 1,024 tokens for every test
    model's tokenizer (provider caches need a long shared prefix)."""
    lines = ["[SYNTHETIC] Shop policy for a fictional test store. Rules:"]
    for i in range(1, rules + 1):
        lines.append(
            f"[SYNTHETIC] Rule {i}: orders with code T-{i * 7:04d} ship within "
            f"{i % 5 + 1} working days; سفارش با کد T-{i * 7:04d} ظرف "
            f"{i % 5 + 1} روز کاری ارسال می‌شود."
        )
    return "\n".join(lines)


def cache_request(message: str = CACHE_MESSAGES[0]) -> Request:
    return Request(
        message=message,
        instructions=Component.present(long_instructions()),
        history=Component.absent(),
        retrieved=Component.absent(),
        attachments=Component.absent(),
        structured_input=Component.absent(),
    )


@dataclass(frozen=True)
class ProbeStep:
    name: str
    rows: list[PlanRow]
    calls_per_model: int


def probe_plan(
    settings_loader: SettingsLoader,
) -> tuple[list[ProbeStep], Decimal | None]:
    """Upper-bound estimates for the three probe steps; no call."""
    steps = []
    cache_loaded = settings_loader(
        {
            **live_overrides(),
            "pipeline.context.max_output_tokens_cap": CACHE_OUTPUT_CAP,
        }
    )
    rows, _ = plan(cache_loaded, CHECK_MODELS, cache_request())
    steps.append(ProbeStep("provider cache: long prompt, twice", rows, 2))
    loaded = settings_loader(live_overrides())
    rows, _ = plan(loaded, ("mimo-v2.5",))
    steps.append(ProbeStep("mimo-v2.5 tiny check", rows, 1))
    rows, _ = plan(
        settings_loader({**live_overrides(), **THINKING_OFF}), ("deepseek-v4-flash",)
    )
    steps.append(ProbeStep("deepseek-v4-flash, thinking disabled", rows, 1))
    total: Decimal | None = Decimal(0)
    for step in steps:
        for row in step.rows:
            if row.estimate is None or total is None:
                total = None
            else:
                total += row.estimate * step.calls_per_model
    return steps, total


def probe_run(
    settings_loader: SettingsLoader,
    *,
    client_factory: ClientFactory = build_live_client,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Make the probe's live calls (12) and return content-free results. One
    run ID, so the per-run cap covers the whole probe; it stops at the first
    step whose guard stops live calls."""
    stamp = datetime.now(UTC)
    run_id = run_id or f"wrapper-probe-{stamp:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    taps: dict[str, _Capture] = {}

    def factory(loaded: LoadedSettings, rid: str) -> ModelClient:
        tap = _Capture(client_factory(loaded, rid))
        taps["current"] = tap
        return tap

    def with_overrides(extra: dict[str, Any]) -> SettingsLoader:
        return lambda o: settings_loader({**o, **extra})

    cache_rows: list[dict[str, Any]] = []
    session: ChatSession | None = None
    stopped = False
    for model_id in CHECK_MODELS:
        session = ChatSession(
            model_id,
            live=True,
            instructions=long_instructions(),
            single_attempt=True,
            settings_loader=with_overrides(
                {"pipeline.context.max_output_tokens_cap": CACHE_OUTPUT_CAP}
            ),
            client_factory=factory,
            run_id=run_id,
        )
        for call, message in enumerate(CACHE_MESSAGES, 1):
            session.reset()  # same long prefix, no history
            request = session.request_for(message)
            response, report = session.ask(message)
            row = _row(session, request, response.answer, report, taps["current"].last)
            row["call"] = call
            row["provider_cache_saving"] = dict(report.decomposition).get(
                "provider_cache_saving"
            )
            cache_rows.append(row)
            if report.live_stopped:
                stopped = True
                break
        if stopped:
            break

    mimo = (
        {}
        if stopped
        else run(
            settings_loader,
            models=("mimo-v2.5",),
            client_factory=client_factory,
            run_id=run_id,
        )
    )
    thinking_off = (
        {}
        if stopped or _stopped(mimo)
        else run(
            with_overrides(THINKING_OFF),
            models=("deepseek-v4-flash",),
            client_factory=client_factory,
            run_id=run_id,
        )
    )
    last = session.budget() if session else {}
    for part in (mimo, thinking_off):
        last = part.get("budget_after", last) or last
    return {
        "check": "metis-wrapper-live-probe",
        "date": stamp.date().isoformat(),
        "time_utc": stamp.isoformat(timespec="seconds"),
        "run_id": run_id,
        "synthetic_input": {
            "cache_instructions": "long_instructions() in "
            "metis_auto.wiring.wrapper_check (30 synthetic rules)",
            "cache_messages": list(CACHE_MESSAGES),
            "tiny_check": {"instructions": INSTRUCTIONS, "message": MESSAGE},
        },
        "config": session.loaded.reference.versions() if session else {},
        "provider_cache": cache_rows,
        "mimo_tiny_check": mimo.get("results", []),
        "deepseek_thinking_disabled": thinking_off.get("results", []),
        "budget_after": last,
    }


def _stopped(part: dict[str, Any]) -> bool:
    return any(r.get("live_stopped") for r in part.get("results", []))
