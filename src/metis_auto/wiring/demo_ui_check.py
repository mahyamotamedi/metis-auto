"""Live smoke test of the Demo B UI (owner-approved 2026-10-19; ADR-0024).

Responsibility: the steps, limits, and content-free results of one scripted
pass through the demo page with the SYNTHETIC English FAQ preset: bot-level
cache on, a greeting (unanchored), the first substantive question (anchors),
a similar follow-up (stays; the provider's prompt cache may hit), a coding
request (re-routes), then a second user's greeting (a bot-level cache hit, no
call). Generation limit 512 tokens; the run's spend cap is the approved
total, so the spend guard itself enforces the approval.

``plan`` makes **no call**: it runs the same messages through ``ChatSession``
with a planning fake whose answers are about 512 tokens long (so later turns'
history is not underestimated) and returns the spend guard's pre-call
estimate for every call, plus the worst case if each escalated once.
``result_row`` turns a ``TurnReport`` into a content-free row (no answer
text). The page itself is driven by ``scripts/demo_ui_live_check.py``
(Streamlit stays out of the package).
Called by: scripts/demo_ui_live_check.py, tests. Calls: wiring.{chat,
demo_ui}, adapters (fake client), contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
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
)

from .chat import ChatSession, SettingsLoader, TurnReport
from .demo_ui import cost_view, load_presets, routing_kind

OUTPUT_CAP = 512
APPROVED_TOTAL = Decimal("0.02")
"""The owner's approval (USD): refuse a plan above it; also the run's cap."""
PRESET = "en_faq"
STEPS: tuple[tuple[str, str], ...] = (
    ("greeting", "hi"),
    ("first_substantive", "How do I export my notes to PDF?"),
    ("similar_follow_up", "Does the Team plan include SSO?"),
    ("coding_request", "write a python function that lists all my notes with the API"),
    ("new_user", ""),
    ("second_user_greeting", "hi"),
)
"""SYNTHETIC messages (the preset's suggested messages). ``new_user`` is the
page's "New user (same bot)" button."""


def loader(settings_loader: SettingsLoader) -> SettingsLoader:
    """Generation limit 512 and the run cap lowered to the approval."""
    return lambda o: settings_loader(
        {
            **o,
            "pipeline.context.max_output_tokens_cap": OUTPUT_CAP,
            "budget.run_cap": str(APPROVED_TOTAL),
        }
    )


class _PlanningFake(FakeModelClient):
    """Answers of about ``OUTPUT_CAP`` o200k tokens (" word" is one token)."""

    def invoke(self, invocation: ModelInvocation) -> ModelResult:
        return ModelResponse(
            text="[SYNTHETIC]" + " word" * OUTPUT_CAP,
            finish_reason=FinishReason.COMPLETE,
            source=AnswerSource.FAKE,
        )


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
    """Pre-call estimates of every call the smoke test would make (no call):
    (rows, total, total if every call escalated once)."""
    preset = next(p for p in load_presets() if p.key == PRESET)
    session = ChatSession(
        live=False,
        instructions=preset.instructions,
        retrieved=preset.documents,
        bot_cache=True,
        settings_loader=loader(settings_loader),
        client_factory=lambda _l, _r: _PlanningFake(),
        run_id="demo-ui-check-plan",
    )

    def estimate(request, model_id: str | None) -> Decimal | None:
        if model_id is None:
            return None
        cost = session.accounting.pre_call_estimate(request, model_id, OUTPUT_CAP).cost
        computed = cost.status == CostStatus.COMPUTED and cost.amount is not None
        return cost.amount.amount if computed else None

    rows: list[PlanRow] = []
    for step, message in STEPS:
        if step == "new_user":
            session.new_user()
            continue
        request = session.request_for(message)
        response, _report = session.ask(message)
        decision = session.last_trace.decision
        called = response.metadata.served_by == ServedBy.MODEL
        model = decision.target_model_id if called else None
        up = decision.chain[0] if called and decision.chain else None
        rows.append(
            PlanRow(
                step=step,
                reason_code=decision.reason_code,
                served_by=response.metadata.served_by.value,
                model_id=model,
                estimate=estimate(request, model) if called else Decimal(0),
                escalation_model=up,
                escalation_estimate=estimate(request, up) if up else Decimal(0),
            )
        )
    if any(r.served_by == "model" and r.estimate is None for r in rows):
        raise ValueError("an estimate is not computed")
    total = sum((r.estimate or Decimal(0) for r in rows), Decimal(0))
    worst = total + sum((r.escalation_estimate or Decimal(0) for r in rows), Decimal(0))
    return rows, total, worst


def result_row(step: str, report: TurnReport) -> dict[str, Any]:
    """One step's content-free result (no answer text)."""
    view = cost_view(report.parts)
    return {
        "step": step,
        "badge": routing_kind(report),
        "reason_code": report.routing.get("reason_code"),
        "served_by": report.served_by,
        "model_id": report.model_id,
        "provider_model": report.provider_model,
        "failure": report.failure,
        "live_stopped": report.live_stopped,
        "features": report.features,
        "cache": list(report.cache),
        "tokens": report.tokens,
        "cost": report.cost,
        "cost_caveats": list(report.cost_caveats),
        "premium_estimate": report.premium_estimate,
        "saved": f"{view.saved_fraction:.1%}"
        if view and view.saved_fraction is not None
        else None,
        "decomposition": dict(report.decomposition),
        "overhead_ms": round(report.overhead_ms or 0, 1),
    }


__all__ = [
    "APPROVED_TOTAL",
    "OUTPUT_CAP",
    "PRESET",
    "STEPS",
    "PlanRow",
    "loader",
    "plan",
    "result_row",
]
