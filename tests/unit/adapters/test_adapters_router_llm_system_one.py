"""LLM-as-System-One, the Mode 1 backup (ADR-0047
point 2; R6), built through wiring with a scripted answering client: the prompt
(instructions + state, no dataset text in tests), JSON answers parsed into typed
answers, the cost from the catalogue's price row, the pre-call estimate as an
upper bound, uncalibrated results, and every failure returned. SYNTHETIC text."""

from __future__ import annotations

import json

from fixtures.synthetic import contract_examples as ex

from metis_auto.adapters.system import FakeClock
from metis_auto.contracts import (
    AnswerSource,
    AvailabilityReason,
    Component,
    ComponentState,
    CostStatus,
    DecisionError,
    DecisionResult,
    DecisionState,
    ErrorClass,
    Fidelity,
    FinishReason,
    Language,
    LastAssistantTurnKind,
    ModelError,
    ModelResponse,
    PartRole,
    QuestionLanguage,
    TokenCount,
    TokenUsage,
)
from metis_auto.domain.routing import DecisionRouterConfig
from metis_auto.settings import LlmSystemOneBackendSettings, load_settings
from metis_auto.wiring.routers import backend_builder

LOADED = load_settings(environ={}, dotenv=None, runtime=None)
QUESTIONS = LOADED.reference.router_questions.get(
    "routing_qs_v1", QuestionLanguage.ENGLISH
)
REPLY = {
    "answers": {
        "complexity": {"type": "score", "score": 1, "confidence": 0.7},
        "needs_reasoning": {"type": "noul", "noul": 0.2, "confidence": 0.8},
        "cheap_model_ok": {"type": "noul", "noul": 0.9, "confidence": 0.9},
        "intent": {"type": "choice", "choice": "factual_qa", "confidence": 0.6},
        "depends_on_history": {"type": "noul", "noul": 0.1, "confidence": 0.9},
    }
}


def state() -> DecisionState:
    return DecisionState(
        message="[SYNTHETIC] What are your opening hours?",
        previous_user_turn=Component[str].absent(),
        last_assistant_turn_kind=LastAssistantTurnKind.NONE,
        retrieved_state=ComponentState.ABSENT,
        language=Language.ENGLISH,
        turn_depth=0,
        dataset_derived=False,
    )


class Scripted:
    def __init__(self, text: str | None = None, error: ModelError | None = None):
        self.text = text
        self.error = error
        self.seen = []

    @property
    def source(self):
        return AnswerSource.LIVE

    def invoke(self, invocation):
        self.seen.append(invocation)
        if self.error is not None:
            return self.error
        usage = TokenUsage(
            model_id=invocation.model_id,
            input=TokenCount(
                tokens=900, fidelity=Fidelity.PROVIDER_REPORTED, method="t"
            ),
            output=TokenCount(
                tokens=120, fidelity=Fidelity.PROVIDER_REPORTED, method="t"
            ),
        )
        return ModelResponse(
            text=self.text,
            finish_reason=FinishReason.COMPLETE,
            usage=usage,
            provider_model_version="gpt-4.1-nano-2025-04-14",
            source=AnswerSource.LIVE,
        )


def build(client: Scripted):
    make = backend_builder(
        "llm_system_one",
        LlmSystemOneBackendSettings(enabled=True),
        DecisionRouterConfig(),
        assets=None,
        assets_root=LOADED.path("data/routers"),
        loaded=LOADED,
        questions=QUESTIONS,
        model_client=lambda: client,
    )
    return make(FakeClock(ex.NOW))


def test_answers_cost_and_prompt():
    client = Scripted("```json\n" + json.dumps(REPLY) + "\n```")
    b = build(client)
    assert b.kind == "hosted" and b.available().available
    out = b.decide(state(), QUESTIONS, timeout_ms=2000)
    assert isinstance(out, DecisionResult) and out.calibrated is False
    by = {a.question_id: a for a in out.answers}
    assert by["cheap_model_ok"].p_yes == 0.9 and by["complexity"].score == 1
    assert out.cost.status == CostStatus.COMPUTED and out.cost.amount.amount > 0
    assert out.model_revision == "gpt-4.1-nano-2025-04-14"
    inv = client.seen[0]
    assert inv.model_id == "gpt-4o-mini" and inv.max_output_tokens == 300
    assert [p.role for p in inv.parts] == [PartRole.INSTRUCTIONS, PartRole.USER]
    assert "complexity" in inv.parts[0].text and "[SYNTHETIC]" in inv.parts[1].text


def test_the_estimate_bounds_the_scripted_call():
    client = Scripted(json.dumps(REPLY))
    b = build(client)
    out = b.decide(state(), QUESTIONS, timeout_ms=2000)
    est = b.estimate_cost(50)
    assert est.cost.status == CostStatus.COMPUTED
    assert est.cost.amount.amount >= out.cost.amount.amount


def test_prose_or_missing_answers_are_an_invalid_response():
    for text in ("I think it is simple.", json.dumps({"answers": {}})):
        out = build(Scripted(text)).decide(state(), QUESTIONS, timeout_ms=2000)
        assert isinstance(out, DecisionError) and out.invalid_response


def test_a_model_error_is_returned_with_its_class():
    err = ModelError(
        error_class=ErrorClass.INVALID_REQUEST,
        retryable=False,
        provider_error_code="model_not_found",
        source=AnswerSource.LIVE,
    )
    out = build(Scripted(error=err)).decide(state(), QUESTIONS, timeout_ms=2000)
    assert isinstance(out, DecisionError)
    assert out.error_class == ErrorClass.INVALID_REQUEST
    assert out.provider_error_code == "model_not_found"


def test_without_a_client_it_is_not_configured():
    from metis_auto.adapters.routers.llm_system_one import LlmSystemOneBackend

    b = LlmSystemOneBackend(
        FakeClock(ex.NOW),
        name="x",
        client=None,
        model_id="gpt-4.1-nano",
        cost=None,
        estimate=None,
    )
    assert b.available().reason == AvailabilityReason.NOT_CONFIGURED
