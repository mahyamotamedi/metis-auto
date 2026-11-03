"""The router live check (R6, J-4 remapped), with no network and no key: the plan's
estimates and the run-cap rule (calls dropped from the end until the total fits),
the strict JSON schema of the probe, and a run over fake backends and an in-memory
ledger: each call charged through its own spend guard, one failure not stopping the
others, a refused call when the cap is spent, and content-free output."""

from __future__ import annotations

import json
from decimal import Decimal

from fixtures.synthetic import contract_examples as ex

from metis_auto.adapters.routers import FakeDecisionBackend
from metis_auto.adapters.system import FakeClock, InMemorySpendLedger
from metis_auto.contracts import (
    DecisionError,
    ErrorClass,
    Money,
    QuestionLanguage,
)
from metis_auto.settings import load_settings
from metis_auto.wiring import router_live_check as lc

LOADED = load_settings(environ={}, dotenv=None, runtime=None)
QUESTIONS = LOADED.reference.router_questions.get(
    "routing_qs_v1", QuestionLanguage.ENGLISH
)


def test_the_plan_fits_the_approved_cap_and_drops_from_the_end():
    p = lc.plan(LOADED, QUESTIONS)
    assert p["fits"] and p["kept"] == [c.label for c in lc.CALLS]
    assert Decimal(p["total_upper_bound_usd"]) < Decimal("0.005")
    tight = lc.plan(LOADED, QUESTIONS, run_cap=Decimal("0.0004"))
    assert tight["kept"][0] == "jev" and len(tight["kept"]) < len(lc.CALLS)
    assert Decimal(tight["total_upper_bound_usd"]) <= Decimal("0.0004")


def test_the_probe_schema_is_strict_and_names_every_question():
    schema = lc.answers_schema(QUESTIONS)["json_schema"]
    assert schema["strict"] is True
    answers = schema["schema"]["properties"]["answers"]
    assert set(answers["required"]) == {q.id for q in QUESTIONS.questions}
    intent = answers["properties"]["intent"]["properties"]["choice"]
    assert len(intent["enum"]) == 10


class Priced(FakeDecisionBackend):
    """A fake that is hosted and priced like a tiny call."""

    def __init__(self, clock, *, fail: bool = False, **kw):
        super().__init__(clock, kind="hosted", **kw)
        self._fail = fail

    def estimate_cost(self, state_tokens):
        est = lc._backend(lc.CALLS[1], LOADED, QUESTIONS, lc._no_client)
        return est.estimate_cost(state_tokens)

    def decide(self, state, questions, *, timeout_ms):
        if self._fail:
            return DecisionError(
                backend=self.ref,
                error_class=ErrorClass.INVALID_REQUEST,
                provider_error_code="model_not_found",
                latency_ms=1.0,
            )
        return super().decide(state, questions, timeout_ms=timeout_ms)


def test_a_run_charges_each_call_and_one_failure_does_not_stop_the_rest():
    ledger = InMemorySpendLedger(Money(amount=Decimal("0.05"), currency="USD"))
    clock = FakeClock(ex.NOW)

    def make(call):
        return Priced(clock, name=call.label, fail=call.label == "mimo-v2.5")

    out = lc.run(
        LOADED,
        QUESTIONS,
        ledger,
        keep=tuple(c.label for c in lc.CALLS),
        backends=make,
    )
    by = {r["call"]: r for r in out["results"]}
    assert "gpt-4.1-nano" not in by  # gone on Metis (TODO-17): not called again
    assert by["mimo-v2.5"]["outcome"] == "error:invalid_request"
    assert by["mimo-v2.5"]["provider_error_code"] == "model_not_found"
    assert by["json_schema_probe"]["outcome"] in {"answered", "invalid_response"}
    assert Decimal(out["ledger_remaining_usd"]) < Decimal("0.05")
    text = json.dumps(out, ensure_ascii=False)
    assert lc.SYNTHETIC_STATE.message not in text and "[SYNTHETIC]" not in text


def test_a_spent_cap_refuses_the_call():
    ledger = InMemorySpendLedger(Money(amount=Decimal("0.0000001"), currency="USD"))
    out = lc.run(
        LOADED,
        QUESTIONS,
        ledger,
        keep=("gpt-4o-mini",),
        backends=lambda call: Priced(FakeClock(ex.NOW), name=call.label),
    )
    assert out["results"][0]["outcome"] == "refused_by_spend_guard"
    assert isinstance(lc.plan(LOADED, QUESTIONS)["calls"][0]["estimate_usd"], str)


class _Client:
    """A scripted live client: errors for the listed models, else a reply."""

    def __init__(self, failing, options=None):
        self.failing = failing
        self.options = options
        self.seen = []

    @property
    def source(self):
        from metis_auto.contracts import AnswerSource

        return AnswerSource.LIVE

    def invoke(self, invocation):
        from metis_auto.contracts import (
            AnswerSource,
            Fidelity,
            FinishReason,
            ModelError,
            ModelResponse,
            TokenCount,
            TokenUsage,
        )

        self.seen.append(invocation)
        if invocation.model_id in self.failing:
            return ModelError(
                error_class=ErrorClass.INVALID_REQUEST,
                retryable=False,
                provider_error_code="http_400:400",
                source=AnswerSource.LIVE,
            )
        n = TokenCount(tokens=20, fidelity=Fidelity.PROVIDER_REPORTED, method="x")
        return ModelResponse(
            text="OK",
            finish_reason=FinishReason.COMPLETE,
            usage=TokenUsage(model_id=invocation.model_id, input=n, output=n),
            provider_model_version=invocation.model_id,
            source=AnswerSource.LIVE,
        )


def _diagnose(failing, extra_options=None):
    ledger = InMemorySpendLedger(Money(amount=Decimal("0.05"), currency="USD"))
    made = []

    def clients(options):
        c = _Client(failing, options)
        made.append(c)
        return c

    out = lc.diagnose(
        LOADED,
        QUESTIONS,
        ledger,
        clients=clients,
        backends=lambda call: Priced(FakeClock(ex.NOW), name=call.label),
    )
    return out, made


def test_diagnose_a_refused_mimo_tries_thinking_off_then_calls_it_gone():
    out, made = _diagnose({"mimo-v2.5"})
    labels = [r["call"] for r in out["results"]]
    assert labels == [
        "mimo_user_only",
        "mimo_user_only_thinking_disabled",
        "json_schema_probe_4o_mini",
    ]
    assert made[1].options == {"mimo-v2.5": {"thinking": {"type": "disabled"}}}
    assert "Q-42" in out["mimo_verdict"]
    assert Decimal(out["ledger_remaining_usd"]) < Decimal("0.05")
    sent = made[0].seen[0]
    assert [p.role.value for p in sent.parts] == ["user"]
    assert "[SYNTHETIC]" in sent.parts[0].text and sent.max_output_tokens == 64


def test_diagnose_a_working_mimo_then_checks_the_system_message():
    out, made = _diagnose(set())
    labels = [r["call"] for r in out["results"]]
    assert labels[:2] == ["mimo_user_only", "mimo_with_system_message"]
    assert [p.role.value for p in made[1].seen[0].parts] == ["instructions", "user"]
    assert out["mimo_verdict"].startswith("model works")
    text = json.dumps(out)
    assert "Reply with" not in text  # content-free
