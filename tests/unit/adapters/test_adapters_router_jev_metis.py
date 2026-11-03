"""Jev via the Metis TypeSafe wrapper (ADR-0047 points
1-2 and 6; R6), over httpx.MockTransport: the endpoint, the Bearer header, the wire
body, typed answers, the reported version, the cost from the router price table
(never TypeSafe's own price), the pre-call estimate as an upper bound, and every
expected failure returned, never raised. SYNTHETIC text; no network, no key."""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
from fixtures.synthetic import contract_examples as ex
from pydantic import SecretStr

from metis_auto.adapters.routers.jev_metis import JevMetisBackend, price_amounts
from metis_auto.adapters.system import FakeClock
from metis_auto.contracts import (
    AvailabilityReason,
    Component,
    ComponentState,
    CostStatus,
    DecisionError,
    DecisionResult,
    DecisionState,
    ErrorClass,
    Language,
    LastAssistantTurnKind,
    QuestionLanguage,
)
from metis_auto.settings import load_settings

LOADED = load_settings(environ={}, dotenv=None, runtime=None)
QUESTIONS = LOADED.reference.router_questions.get(
    "routing_qs_v1", QuestionLanguage.ENGLISH
)
ANSWERS = {
    "complexity": {"type": "score", "score": 1.0, "confidence": 0.7},
    "needs_reasoning": {"type": "noul", "noul": 0.2, "confidence": 0.8},
    "cheap_model_ok": {"type": "noul", "noul": 0.8, "confidence": 0.8},
    "intent": {"type": "choice", "choice": "factual_qa", "confidence": 0.8},
    "depends_on_history": {"type": "noul", "noul": 0.1, "confidence": 0.9},
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


PRICES = LOADED.reference.router_prices
KEY = SecretStr("sk-SYNTHETIC-not-a-key")


def backend(handler, *, key=KEY, price_ref="metis-jev-latest"):
    seen = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    b = JevMetisBackend(
        FakeClock(ex.NOW),
        name="jev_metis",
        base_url="https://api.metisai.ir/typesafe",
        model="jev-latest",
        api_key=key,
        prices=PRICES,
        price_ref=price_ref,
        questions=QUESTIONS,
        transport=httpx.MockTransport(wrapped),
    )
    return b, seen


def ok(_request):
    return httpx.Response(
        200,
        json={
            "model": "jev-1.13.0",
            "answers": ANSWERS,
            "usage": {"input_tokens": 431, "output_tokens": 0},
        },
    )


def test_the_committed_price_is_the_metis_pricing_page_row():
    assert price_amounts(PRICES, "metis-jev-latest")[:2] == (
        Decimal("0.0462"),
        Decimal("0.0000"),
    )
    assert price_amounts(PRICES, "no-such-row") is None


def test_request_shape_header_and_typed_answers():
    b, seen = backend(ok)
    out = b.decide(state(), QUESTIONS, timeout_ms=1500)
    assert isinstance(out, DecisionResult)
    req = seen[0]
    assert str(req.url) == "https://api.metisai.ir/typesafe/v1/systemone"
    assert req.headers["Authorization"] == "Bearer sk-SYNTHETIC-not-a-key"
    body = json.loads(req.content)
    assert body["model"] == "jev-latest" and set(body["questions"]) == {
        q.id for q in QUESTIONS.questions
    }
    assert isinstance(body["state"], str) and "Message:" in body["state"]
    assert out.backend_kind.value == "hosted" and out.model_revision == "jev-1.13.0"
    assert b.last_reported_model == "jev-1.13.0"
    assert out.usage.input.tokens == 431 and out.usage.output.tokens == 0
    assert out.cost.status == CostStatus.COMPUTED
    assert out.cost.amount.amount == Decimal(431) * Decimal("0.0462") / 1_000_000
    assert out.cost.price_refs == ("metis-jev-latest",)
    assert out.calibrated is False


def test_the_estimate_is_an_upper_bound_including_the_questions():
    b, _ = backend(ok)
    est = b.estimate_cost(50)
    assert est.cost.status == CostStatus.COMPUTED
    assert est.input_tokens.tokens > 50 + 300  # the questions' text is counted
    # The first live call (2026-11-03) billed 699 input tokens for a 60-token
    # state bound: the estimate must cover it.
    assert backend(ok)[0].estimate_cost(60).input_tokens.tokens >= 699
    actual = Decimal(431) * Decimal("0.0462") / 1_000_000
    assert est.cost.amount.amount >= actual


def test_no_key_is_unavailable_and_never_calls():
    b, seen = backend(ok, key=None)
    assert b.available().reason == AvailabilityReason.NOT_CONFIGURED
    out = b.decide(state(), QUESTIONS, timeout_ms=1500)
    assert isinstance(out, DecisionError) and seen == []


def test_no_price_row_means_not_computed_never_zero():
    b, _ = backend(ok, price_ref=None)
    assert b.estimate_cost(10).cost.status == CostStatus.NOT_COMPUTED
    out = b.decide(state(), QUESTIONS, timeout_ms=1500)
    assert out.cost.status == CostStatus.NOT_COMPUTED


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, ErrorClass.AUTH),
        (402, ErrorClass.AUTH),
        (429, ErrorClass.RATE_LIMITED),
        (400, ErrorClass.INVALID_REQUEST),
        (503, ErrorClass.UNAVAILABLE),
    ],
)
def test_http_errors_are_returned_with_their_class(status, kind):
    b, _ = backend(lambda _r: httpx.Response(status, json={"error": "x"}))
    out = b.decide(state(), QUESTIONS, timeout_ms=1500)
    assert isinstance(out, DecisionError) and out.error_class == kind
    assert out.provider_error_code == f"http_{status}"


def test_transport_failures_and_bad_bodies_are_returned():
    def timeout(_r):
        raise httpx.ReadTimeout("slow")

    out = backend(timeout)[0].decide(state(), QUESTIONS, timeout_ms=10)
    assert out.error_class == ErrorClass.TIMEOUT
    bad = backend(lambda _r: httpx.Response(200, json={"answers": {}}))[0]
    assert bad.decide(state(), QUESTIONS, timeout_ms=10).invalid_response


def test_the_key_never_appears_in_results_or_errors():
    b, _ = backend(lambda _r: httpx.Response(401))
    out = b.decide(state(), QUESTIONS, timeout_ms=10)
    assert "SYNTHETIC-not-a-key" not in out.model_dump_json()
    assert "SYNTHETIC-not-a-key" not in repr(b.ref)
