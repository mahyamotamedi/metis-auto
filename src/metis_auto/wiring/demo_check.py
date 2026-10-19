"""Live check of the Demo A flow (owner-approved 2026-10-19; ADR-0023 amendment 1).

Responsibility: drive one scripted ``ChatSession`` through the demo's
decisions, with SYNTHETIC messages written for this check: the first
substantive message, a greeting after anchoring (Q-41; the unanchored greeting
is covered offline), a code message (re-route), a
bot-level cache hit for a second user (no call), DeepSeek with thinking
disabled over two turns (that mode's chat template, A-68, including a history
turn), and LLMLingua-2 compression of a retrieved document. Generation limit
512 tokens.

``plan`` makes **no call**: it runs the same script with a planning fake whose
answers are about 512 tokens long (the limit, so later turns' history is not
underestimated) and returns the spend guard's pre-call estimate for every call
that would be made, plus the worst case if each could escalate once. ``run``
makes the live calls through the real pipeline, spend guard, persistent
ledger, and recording decorator, and returns content-free results (no answer
text): routing reason, served by, model, provider-reported model, finish
reason, reported vs locally counted tokens, cost, decomposition, compression.
Called by: ``scripts/demo_live_check.py``, tests (mocked HTTP).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from metis_auto.adapters.providers import FakeModelClient
from metis_auto.contracts import (
    AnswerSource,
    CostStatus,
    FinishReason,
    ModelInvocation,
    ModelResponse,
    ModelResult,
    ServedBy,
    SpanName,
)
from metis_auto.ports import ModelClient
from metis_auto.settings import LoadedSettings

from .chat import (
    ChatSession,
    ClientFactory,
    CompressionMode,
    RoutingMode,
    SettingsLoader,
)
from .live import build_live_client

OUTPUT_CAP = 512
MAX_TOTAL_ESTIMATE = Decimal("0.0021")
"""Refuse above this summed upper bound (USD): the owner's approval."""
INSTRUCTIONS = (
    "[SYNTHETIC] You are the assistant of a demo shop in a test. "
    "Answer in one or two short sentences."
)
DOCUMENT = (
    "[SYNTHETIC] Returns are accepted within 14 days of delivery if the item is "
    "unused and in its original packaging. To start a return, the customer opens "
    "the order page, chooses the item, and selects a reason; a courier collects "
    "the parcel within two working days. Refunds go to the original payment "
    "method within five working days after the warehouse checks the item. Sale "
    "items and gift cards cannot be returned."
)
SAME_QUESTION = "ساعت کاری فروشگاه چیست؟"

STEPS: tuple[tuple[str, str, str | None], ...] = (
    ("first_substantive", "ask", "سفارشم کی می‌رسه؟"),
    ("greeting_anchored", "ask", "مرسی"),
    (
        "code_reroute",
        "ask",
        "def total(items):\n    return sum(items) / len(items)\n"
        "Why does this fail for an empty list?",
    ),
    ("bot_cache_on", "botcache", None),
    ("user_2", "newuser", None),
    ("bot_cache_first_user", "ask", SAME_QUESTION),
    ("user_3", "newuser", None),
    ("bot_cache_hit", "ask", SAME_QUESTION),
    ("user_4", "newuser", None),
    ("deepseek_thinking_off", "thinking_off", None),
    ("deepseek_fixed", "model", "deepseek-v4-flash"),
    ("deepseek_turn_1", "ask", "آدرس فروشگاه کجاست؟"),
    ("deepseek_turn_2_with_history", "ask", "و شماره تلفن پشتیبانی؟"),
    ("user_5", "newuser", None),
    ("sticky_again", "mode", "sticky_v1"),
    ("retrieved_document", "retrieved", DOCUMENT),
    ("compression_on", "compress", None),
    ("compressed_retrieved", "ask", "Can I return a sale item?"),
)
"""Every message is SYNTHETIC, written for this check (no inline marker: the
Latin marker would change the language and greeting detectors)."""


def _loader(settings_loader: SettingsLoader) -> SettingsLoader:
    """Generation limit 512, and the run cap lowered to the approved total, so
    the spend guard itself enforces the approval (an escalation that would
    exceed it is blocked)."""
    return lambda o: settings_loader(
        {
            **o,
            "pipeline.context.max_output_tokens_cap": OUTPUT_CAP,
            "budget.run_cap": str(MAX_TOTAL_ESTIMATE),
        }
    )


class _Capture:
    """Keeps every raw ``ModelResult`` of the current step (diagnostic tap)."""

    def __init__(self, inner: ModelClient, sink: list[ModelResult]) -> None:
        self._inner = inner
        self._sink = sink

    @property
    def source(self) -> AnswerSource:
        return self._inner.source

    def invoke(self, invocation: ModelInvocation) -> ModelResult:
        result = self._inner.invoke(invocation)
        self._sink.append(result)
        return result


class _PlanningFake(FakeModelClient):
    """Answers of about ``OUTPUT_CAP`` o200k tokens (" word" is one token)."""

    def invoke(self, invocation: ModelInvocation) -> ModelResult:
        return ModelResponse(
            text="[SYNTHETIC]" + " word" * OUTPUT_CAP,
            finish_reason=FinishReason.COMPLETE,
            source=AnswerSource.FAKE,
        )


def _execute(
    session: ChatSession,
    on_ask: Callable[[str, str, Any, Any], bool],
    compression: CompressionMode,
) -> None:
    for name, action, arg in STEPS:
        if action == "ask":
            assert arg is not None
            request = session.request_for(arg)
            response, report = session.ask(arg)
            if not on_ask(name, arg, (request, response), report):
                return
        elif action == "botcache":
            session.set_bot_cache(True)
        elif action == "newuser":
            session.new_user()
        elif action == "thinking_off":
            session.set_deepseek_thinking(False)
        elif action == "model":
            assert arg is not None
            session.switch_model(arg)
        elif action == "mode":
            session.set_routing(RoutingMode(arg))
        elif action == "retrieved":
            session.retrieved = (arg,) if arg else ()
        elif action == "compress":
            session.set_compression(compression)


@dataclass(frozen=True)
class PlanRow:
    step: str
    reason_code: str
    served_by: str
    model_id: str | None
    estimate: Decimal | None
    escalation_model: str | None
    escalation_estimate: Decimal | None


def plan(settings_loader: SettingsLoader) -> tuple[list[PlanRow], Decimal, Decimal]:
    """Pre-call estimates of every call the check would make (no call):
    (rows, total, total if every call escalated once)."""
    session = ChatSession(
        live=False,
        instructions=INSTRUCTIONS,
        settings_loader=_loader(settings_loader),
        client_factory=lambda _l, _r: _PlanningFake(),
        run_id="demo-check-plan",
    )
    rows: list[PlanRow] = []

    def estimate(request, model_id: str | None) -> Decimal | None:
        if model_id is None:
            return None
        cost = session.accounting.pre_call_estimate(request, model_id, OUTPUT_CAP).cost
        computed = cost.status == CostStatus.COMPUTED and cost.amount is not None
        return cost.amount.amount if computed else None

    def on_ask(name, _message, pair, report) -> bool:
        request, response = pair
        decision = session.last_trace.decision
        called = response.metadata.served_by == ServedBy.MODEL
        model = decision.target_model_id if called else None
        up = decision.chain[0] if called and decision.chain else None
        rows.append(
            PlanRow(
                step=name,
                reason_code=decision.reason_code,
                served_by=report.served_by,
                model_id=model,
                # The full (uncompressed) request: an upper bound.
                estimate=estimate(request, model) if called else Decimal(0),
                escalation_model=up,
                escalation_estimate=estimate(request, up) if up else Decimal(0),
            )
        )
        return True

    _execute(session, on_ask, CompressionMode.FAKE)
    total = sum((r.estimate or Decimal(0) for r in rows), Decimal(0))
    worst = total + sum((r.escalation_estimate or Decimal(0) for r in rows), Decimal(0))
    if any(r.served_by == "model" and r.estimate is None for r in rows):
        raise ValueError("an estimate is not computed")
    return rows, total, worst


def run(
    settings_loader: SettingsLoader,
    *,
    client_factory: ClientFactory = build_live_client,
    compressor_factory=None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """The live check. Content-free results (no answer text)."""
    stamp = datetime.now(UTC)
    run_id = run_id or f"demo-check-{stamp:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    results: list[ModelResult] = []

    def factory(loaded: LoadedSettings, rid: str) -> ModelClient:
        return _Capture(client_factory(loaded, rid), results)

    session = ChatSession(
        live=True,
        instructions=INSTRUCTIONS,
        settings_loader=_loader(settings_loader),
        client_factory=factory,
        compressor_factory=compressor_factory,
        run_id=run_id,
    )
    rows: list[dict[str, Any]] = []
    session_terms: dict[str, str] = {}

    def on_ask(name, _message, pair, report) -> bool:
        _request, response = pair
        session_terms.clear()
        session_terms.update(dict(report.session_decomposition))
        trace = session.last_trace
        meta = response.metadata
        row: dict[str, Any] = {
            "step": name,
            "reason_code": trace.decision.reason_code if trace.decision else None,
            "decision": report.routing.get("decision"),
            "served_by": report.served_by,
            "model_id": report.model_id,
            "provider_model": report.provider_model,
            "attempts": len(meta.attempt_ids),
            "escalations": meta.escalations,
            "finish_reasons": [
                r.finish_reason.value for r in results if isinstance(r, ModelResponse)
            ],
            "failure": report.failure,
            "features": report.features,
            "cache": list(report.cache),
            "tokens_reported": report.tokens,
            "cost": report.cost,
            "cost_caveats": list(report.cost_caveats),
            "premium_estimate": report.premium_estimate,
            "decomposition": dict(report.decomposition),
            "compression": report.compression or None,
            "model_call_ms": [
                round(s.duration_ms, 1)
                for s in meta.spans
                if s.span == SpanName.MODEL_CALL
            ],
            "overhead_ms": round(report.overhead_ms or 0, 1),
            "settings": report.settings,
        }
        usage = meta.answer_usage
        if (
            meta.served_by == ServedBy.MODEL
            and usage is not None
            and response.answer is not None
            and trace.sent_request is not None
            and meta.final_model_id is not None
        ):
            counted = session.accounting.account(
                trace.sent_request, meta.final_model_id, response.answer
            ).usage
            row["input_reported_vs_counted"] = {
                "reported": usage.input.tokens,
                "counted": counted.input.tokens,
                "counted_framing": counted.template_overhead.tokens
                if counted.template_overhead
                else None,
            }
        rows.append(row)
        results.clear()
        return not report.live_stopped

    _execute(session, on_ask, CompressionMode.LLMLINGUA2)
    return {
        "check": "metis-demo-a-live-check",
        "date": stamp.date().isoformat(),
        "time_utc": stamp.isoformat(timespec="seconds"),
        "run_id": run_id,
        "output_cap": OUTPUT_CAP,
        "synthetic_input": {
            "note": "All messages SYNTHETIC, written for this check.",
            "instructions": INSTRUCTIONS,
            "document": DOCUMENT,
            "steps": [[n, a, m] for n, a, m in STEPS],
        },
        "config": session.loaded.reference.versions(),
        "results": rows,
        "session_decomposition": session_terms,
        "budget_after": session.budget(),
    }
