"""A local /v1/systemone server as a decision backend
(ADR-0047; R5), over httpx.MockTransport: the request
shape, typed answers, health caching and every expected failure returned (never raised).
SYNTHETIC text; no network."""

from __future__ import annotations

import json

import httpx
import pytest
from fixtures.synthetic import contract_examples as ex

from metis_auto.adapters.routers.systemone_http import SystemOneHttpBackend
from metis_auto.adapters.system import FakeClock
from metis_auto.contracts import (
    AvailabilityReason,
    Component,
    ComponentState,
    DecisionError,
    DecisionResult,
    DecisionState,
    ErrorClass,
    Language,
    LastAssistantTurnKind,
    QuestionLanguage,
)
from metis_auto.settings import load_settings

QUESTIONS = load_settings(
    environ={}, dotenv=None, runtime=None
).reference.router_questions.get("routing_qs_v1", QuestionLanguage.ENGLISH)


def state() -> DecisionState:
    return DecisionState(
        message="[SYNTHETIC] What are your opening hours?",
        previous_user_turn=Component[str].absent(),
        last_assistant_turn_kind=LastAssistantTurnKind.NONE,
        retrieved_state=ComponentState.ABSENT,
        language=Language.ENGLISH,
        turn_depth=0,
    )


ANSWERS = {
    "complexity": {
        "type": "score",
        "score": 1.2,
        "probabilities": {"0": 0.2, "1": 0.5, "2": 0.2, "3": 0.1},
        "confidence": 0.4,
    },
    "needs_reasoning": {"type": "noul", "noul": 0.2},
    "cheap_model_ok": {"type": "noul", "noul": 0.8},
    "intent": {
        "type": "choice",
        "choice": "factual_qa",
        "probabilities": {"factual_qa": 0.9, "other": 0.1},
        "confidence": 0.8,
    },
    "depends_on_history": {"type": "noul", "noul": 0.1},
}


def make(handler, clock=None):
    clock = clock or FakeClock(ex.NOW)
    return (
        SystemOneHttpBackend(
            clock,
            name="mizan_http",
            base_url="http://127.0.0.1:8080",
            model="mizan-1.5-4b-q4_k_m",
            transport=httpx.MockTransport(handler),
        ),
        clock,
    )


def test_a_valid_answer_is_parsed_with_the_reported_model(tmp_path):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "model": "mizan-1.5-4b@b11443",
                "answers": ANSWERS,
                "usage": {"input_tokens": 212},
            },
        )

    b, _ = make(handler)
    out = b.decide(state(), QUESTIONS, timeout_ms=400)
    assert isinstance(out, DecisionResult)
    assert out.model_revision == "mizan-1.5-4b@b11443" and out.calibrated is False
    assert out.usage.input.tokens == 212
    request = seen[0]
    assert request.method == "POST" and request.url.path == "/v1/systemone"
    body = json.loads(request.content)
    assert set(body) == {"model", "state", "questions"}
    assert body["questions"]["intent"]["criteria"]["factual_qa"]
    assert "Message:" in body["state"]


@pytest.mark.parametrize(
    ("status", "kind", "code"),
    [
        (429, ErrorClass.RATE_LIMITED, "http_429"),
        (503, ErrorClass.UNAVAILABLE, "http_503"),
        (400, ErrorClass.INVALID_REQUEST, "http_400"),
    ],
)
def test_http_errors_are_returned_with_a_code_only(status, kind, code):
    b, _ = make(lambda r: httpx.Response(status, text="server said something"))
    out = b.decide(state(), QUESTIONS, timeout_ms=400)
    assert isinstance(out, DecisionError)
    assert out.error_class == kind and out.provider_error_code == code
    assert "server said" not in out.model_dump_json()


def test_timeouts_connection_errors_and_bad_bodies():
    def timeout(r):
        raise httpx.ReadTimeout("slow", request=r)

    def refused(r):
        raise httpx.ConnectError("refused", request=r)

    assert (
        make(timeout)[0].decide(state(), QUESTIONS, timeout_ms=1).error_class
        == ErrorClass.TIMEOUT
    )
    assert (
        make(refused)[0].decide(state(), QUESTIONS, timeout_ms=1).error_class
        == ErrorClass.CONNECTION
    )
    for body in ("not json", json.dumps({"answers": {"intent": ANSWERS["intent"]}})):
        out = make(lambda r, body=body: httpx.Response(200, text=body))[0].decide(
            state(), QUESTIONS, timeout_ms=400
        )
        assert isinstance(out, DecisionError) and out.invalid_response


def test_health_is_checked_at_most_once_per_ttl():
    calls = []

    def handler(r):
        calls.append(r.url.path)
        return httpx.Response(200 if len(calls) == 1 else 503)

    b, clock = make(handler)
    assert b.available().available
    assert b.available().available and calls == ["/health"]  # cached
    clock.advance(6000)
    assert b.available().reason == AvailabilityReason.SERVER_UNREACHABLE
