"""The decision-router cascade (ADR-0047, R4): gate, state,
router cache keyed on the model revision, the backend chain under the deadline, the
circuit breaker, the approval check and the spend guard for hosted backends, the
confidence gate, and the overhead measurement. SYNTHETIC text, fakes only."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fixtures.synthetic import contract_examples as ex

from metis_auto.adapters.routers import FakeDecisionBackend
from metis_auto.adapters.system import FakeClock, InMemorySpendLedger
from metis_auto.adapters.tokenizers import ApproxCharsTokenizer
from metis_auto.application.measurement import Fingerprinter
from metis_auto.application.pipeline import SpendGuard
from metis_auto.application.routing import (
    CascadeConfig,
    CircuitBreaker,
    RouterCascade,
    RouterResultCache,
)
from metis_auto.contracts import (
    AttachmentRef,
    AvailabilityReason,
    BackendAvailability,
    Component,
    ComponentState,
    CostBasis,
    CostStatus,
    DecisionFailureReason,
    DecisionSkipReason,
    DecisionStatus,
    ErrorClass,
    Language,
    Modality,
    QuestionLanguage,
    Request,
    RequestFeatures,
    Role,
    Turn,
)
from metis_auto.contracts.events import CircuitState
from metis_auto.settings import load_settings

S = "[SYNTHETIC]"
QUESTIONS = load_settings(
    environ={}, dotenv=None, runtime=None
).reference.router_questions.get("routing_qs_v1", QuestionLanguage.ENGLISH)
CHEAP = {
    "complexity": 0.0,
    "needs_reasoning": 0.1,
    "cheap_model_ok": 0.9,
    "intent": "chitchat",
    "depends_on_history": 0.2,
}


def request(message: str = f"{S} ساعت کاری فروشگاه چیست؟", **kw) -> Request:
    base = dict(
        message=message,
        history=Component.present(
            (
                Turn(role=Role.USER, text=f"{S} سلام"),
                Turn(role=Role.ASSISTANT, text=f"{S} بفرمایید"),
            )
        ),
        instructions=Component.present(f"{S} INSTRUCTIONS-NEVER-IN-STATE"),
        retrieved=Component.absent(),
        attachments=Component.absent(),
        structured_input=Component.absent(),
        session_ref="sess-cascade",
    )
    base.update(kw)
    return Request(**base)


def features(**kw) -> RequestFeatures:
    base = dict(
        feature_set_version="fs-test",
        language=Language.PERSIAN,
        message_chars=30,
        length_bucket=0,
        is_greeting=False,
        has_code=False,
        has_coding_intent=False,
        attachment_count=0,
        instructions_state=ComponentState.PRESENT,
        retrieved_state=ComponentState.ABSENT,
        structured_input_state=ComponentState.ABSENT,
        traffic_source_state=ComponentState.UNKNOWN,
        turn_depth=1,
    )
    base.update(kw)
    return RequestFeatures(**base)


def cascade(
    backends: dict,
    clock: FakeClock,
    *,
    guard: SpendGuard | None = None,
    **config,
) -> RouterCascade:
    cfg = CascadeConfig(
        mode=config.pop("mode", "local"),
        chain=tuple(backends),
        timeouts_ms={n: config.pop("timeout_ms", 60.0) for n in backends},
        deadline_ms=config.pop("deadline_ms", 60.0),
        **config,
    )
    return RouterCascade(
        cfg,
        backends=backends,
        questions=QUESTIONS,
        clock=clock,
        fingerprinter=Fingerprinter(ex.SYNTHETIC_TEST_KEY),
        tokenizer=ApproxCharsTokenizer(),
        spend_guard=guard,
    )


def local(clock, name="local1", **kw) -> FakeDecisionBackend:
    kw.setdefault("script", CHEAP)
    return FakeDecisionBackend(clock, name=name, **kw)


def hosted(clock, name="hosted1", **kw) -> FakeDecisionBackend:
    kw.setdefault("script", CHEAP)
    kw.setdefault("cost", ex.computed("0.0004"))
    return FakeDecisionBackend(clock, name=name, kind="hosted", **kw)


def guard(cap: str = "1.00") -> tuple[SpendGuard, InMemorySpendLedger]:
    ledger = InMemorySpendLedger(ex.usd(cap))
    return SpendGuard(ledger), ledger


@pytest.fixture
def clock():
    return FakeClock(ex.NOW)


# --- gate and state ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("feats", "rule"),
    [
        ({"is_greeting": True}, "gate.greeting"),
        ({"has_code": True}, "gate.code"),
        ({"attachment_count": 1}, "gate.attachment"),
        ({"message_chars": 5000}, "gate.long_message"),
    ],
)
def test_a_decisive_gate_rule_skips_the_backends(clock, feats, rule):
    backend = local(clock)
    step = cascade({"local1": backend}, clock).decide(request(), features(**feats))
    assert step.outcome.status == DecisionStatus.SKIPPED
    assert step.outcome.skip_reason == DecisionSkipReason.RULES_DECISIVE
    assert step.outcome.rule_id == rule
    assert backend.calls == 0 and step.measurement.cost is None


def test_an_attachment_only_message_has_no_state(clock):
    r = request(
        message=" ",
        attachments=Component.present((AttachmentRef(modality=Modality.IMAGE),)),
    )
    step = cascade(
        {"local1": local(clock)}, clock, gate={"attachment_tier": None}
    ).decide(r, features(attachment_count=0))
    assert step.outcome.skip_reason == DecisionSkipReason.INELIGIBLE_STATE


def test_a_local_answer_is_recorded_with_zero_local_cost(clock):
    backend = local(clock, latency_ms=12)
    step = cascade({"local1": backend}, clock).decide(request(), features())
    o = step.outcome
    assert o.status == DecisionStatus.ANSWERED and not o.result.cache_hit
    assert o.result.state_fingerprint.startswith("fp1:")
    assert [a.answered for a in o.attempts] == [True]
    assert step.measurement.measurement == "decision"
    assert step.measurement.backend == "local1@0.0.0-synthetic"
    assert step.measurement.duration_ms >= 12
    cost = step.measurement.cost
    assert cost.status == CostStatus.COMPUTED and cost.amount.amount == 0
    assert cost.basis == CostBasis.LOCAL_COMPUTE
    assert [c.state for c in step.circuits] == [CircuitState.CLOSED]


# --- router cache and model revision --------------------------------------------------


def test_the_same_state_is_served_from_the_router_cache(clock):
    backend = local(clock)
    c = cascade({"local1": backend}, clock)
    first = c.decide(request(), features())
    again = c.decide(request(), features())
    assert backend.calls == 1
    assert again.outcome.result.cache_hit and again.outcome.attempts == ()
    assert again.outcome.result.answers == first.outcome.result.answers
    assert again.measurement.cost.amount.amount == 0
    # Folded text shares the entry (Arabic yeh vs Persian yeh).
    c.decide(request(message=f"{S} ساعت كاري فروشگاه چيست؟"), features())
    assert backend.calls == 1 and c.cache.hits == 2


def test_a_new_model_revision_drops_that_backends_cache(clock):
    v1 = local(clock, version="rev-1")
    c = cascade({"local1": v1}, clock)
    c.decide(request(), features())
    assert len(c.cache) == 1
    # The alias moved to a new release: same name, new revision reported.
    v2 = local(clock, version="rev-2")
    c._backends["local1"] = v2
    c.decide(request(message=f"{S} سوال دیگر"), features())
    assert [(x.previous, x.current) for x in c.cache.revision_changes] == [
        ("rev-1", "rev-2")
    ]
    assert len(c.cache) == 1  # only the rev-2 entry is left
    c.decide(request(), features())  # the old entry is gone: called again
    assert v2.calls == 2


def test_the_cache_honours_ttl_and_size(clock):
    cache = RouterResultCache(clock, max_entries=2, ttl_s=1)
    step = cascade({"local1": local(clock)}, clock).decide(request(), features())
    result = step.outcome.result
    for key in ("fp1:" + "a" * 64, "fp1:" + "b" * 64, "fp1:" + "c" * 64):
        cache.put("local1", key, result)
    assert len(cache) == 2 and cache.get("local1", "fp1:" + "a" * 64) is None
    clock.advance(1001)
    assert cache.get("local1", "fp1:" + "c" * 64) is None


# --- chain, deadline, breaker ---------------------------------------------------------


def test_a_failing_backend_falls_through_to_the_next(clock):
    first = local(clock, name="a", failures=[ErrorClass.UNAVAILABLE])
    second = local(clock, name="b")
    step = cascade({"a": first, "b": second}, clock).decide(request(), features())
    o = step.outcome
    assert o.status == DecisionStatus.ANSWERED and o.result.backend.name == "b"
    assert [(a.answered, a.failure_reason) for a in o.attempts] == [
        (False, DecisionFailureReason.ERROR),
        (True, None),
    ]
    assert o.attempts[0].error_class == ErrorClass.UNAVAILABLE


def test_a_slow_backend_times_out_and_leaves_no_time_for_the_rest(clock):
    slow = local(clock, name="slow", latency_ms=200)
    later = local(clock, name="later")
    c = cascade({"slow": slow, "later": later}, clock, deadline_ms=60)
    o = c.decide(request(), features()).outcome
    assert o.status == DecisionStatus.FAILED
    assert o.failure_reason == DecisionFailureReason.TIMEOUT
    assert o.attempts[0].overran_deadline and o.attempts[0].latency_ms == 200
    assert later.calls == 0 and o.attempts[1].latency_ms == 0


def test_the_request_deadline_tightens_the_step(clock):
    # 35 - 10 = 25 ms for the step; 25 + 10 ms grace = 35 ms at most.
    backend = local(clock, latency_ms=40)
    c = cascade({"local1": backend}, clock, deadline_ms=60, reserved_pipeline_ms=10)
    o = c.decide(request(), features(deadline_ms=35)).outcome
    assert o.failure_reason == DecisionFailureReason.TIMEOUT
    within = local(clock, latency_ms=40)
    o = cascade({"local1": within}, clock, deadline_ms=60).decide(request(), features())
    assert o.outcome.status == DecisionStatus.ANSWERED


def test_a_small_overrun_within_grace_is_kept_and_flagged(clock):
    backend = local(clock, latency_ms=65)
    c = cascade({"local1": backend}, clock, deadline_ms=60, deadline_grace_ms=10)
    o = c.decide(request(), features()).outcome
    assert o.status == DecisionStatus.ANSWERED and o.attempts[0].overran_deadline


def test_the_circuit_opens_after_repeated_failures_and_recovers(clock):
    failing = local(clock, name="a", failures=[ErrorClass.UNAVAILABLE] * 3)
    c = cascade(
        {"a": failing},
        clock,
        circuit_failure_threshold=3,
        circuit_window_s=60,
        circuit_cooldown_s=30,
        cache_enabled=False,
    )
    for _ in range(3):
        c.decide(request(), features())
    step = c.decide(request(), features())
    assert step.circuits[0].state == CircuitState.OPEN
    assert step.outcome.failure_reason == DecisionFailureReason.CIRCUIT_OPEN
    assert failing.calls == 3
    clock.advance(30_001)
    step = c.decide(request(), features())  # half-open trial succeeds
    assert step.circuits[0].state == CircuitState.HALF_OPEN
    assert step.outcome.status == DecisionStatus.ANSWERED
    assert c.breaker.state("a") == CircuitState.CLOSED


def test_the_breaker_forgets_failures_outside_its_window(clock):
    breaker = CircuitBreaker(clock, failure_threshold=2, window_s=1, cooldown_s=5)
    breaker.record_failure("x")
    clock.advance(1500)
    breaker.record_failure("x")
    assert breaker.state("x") == CircuitState.CLOSED
    breaker.record_failure("x")
    assert breaker.state("x") == CircuitState.OPEN


def test_an_unavailable_backend_is_skipped_without_counting_a_failure(clock):
    missing = local(
        clock,
        name="a",
        availability=BackendAvailability.unavailable(AvailabilityReason.MISSING_ASSETS),
    )
    c = cascade({"a": missing}, clock)
    o = c.decide(request(), features()).outcome
    assert o.failure_reason == DecisionFailureReason.UNAVAILABLE
    assert missing.calls == 0 and c.breaker.state("a") == CircuitState.CLOSED


def test_an_invalid_response_counts_as_a_failure(clock):
    bad = local(clock, name="a", failures=["invalid_response"])
    c = cascade({"a": bad}, clock)
    o = c.decide(request(), features()).outcome
    assert o.failure_reason == DecisionFailureReason.INVALID_RESPONSE


def test_answers_for_another_question_set_are_refused(clock):
    from metis_auto.domain.routing.decision import check_result

    step = cascade({"a": local(clock, name="a")}, clock).decide(request(), features())
    result = step.outcome.result
    assert check_result(result, QUESTIONS) is None
    wrong = result.model_copy(update={"question_set_version": "other"})
    assert check_result(wrong, QUESTIONS) == "question_set_version"
    missing = result.model_copy(update={"answers": result.answers[1:]})
    assert check_result(missing, QUESTIONS) == "missing_answer"


# --- confidence gate ----------------------------------------------------------------


def test_low_confidence_answers_fail_and_are_kept_only_as_soft_signals(clock):
    c = cascade({"a": local(clock, name="a")}, clock, min_confidence=0.8)
    o = c.decide(request(), features()).outcome  # the fake reports 0.7
    assert o.status == DecisionStatus.FAILED
    assert o.failure_reason == DecisionFailureReason.LOW_CONFIDENCE
    assert o.soft_result is None
    kept = cascade(
        {"a": local(clock, name="a")}, clock, min_confidence=0.8, keep_soft_signals=True
    ).decide(request(), features())
    assert kept.outcome.soft_result is not None


# --- hosted: approval and spend guard -------------------------------------------------


def test_hosted_backends_need_a_spend_guard(clock):
    with pytest.raises(ValueError, match="spend guard"):
        cascade({"h": hosted(clock, name="h")}, clock)


def test_a_dataset_derived_state_never_reaches_a_hosted_backend(clock):
    g, ledger = guard()
    remote = hosted(clock, name="h")
    fallback = local(clock, name="l")
    c = cascade(
        {"h": remote, "l": fallback}, clock, guard=g, mode="hybrid_hosted_first"
    )
    o = c.decide(request(), features()).outcome  # states_dataset_derived defaults True
    assert remote.calls == 0
    assert o.attempts[0].failure_reason == DecisionFailureReason.REAL_DATA_NOT_APPROVED
    assert o.result.backend.name == "l"
    assert ledger.remaining().amount == Decimal("1.00")


def test_an_approved_or_synthetic_hosted_call_is_charged_to_the_ledger(clock):
    g, ledger = guard()
    remote = hosted(clock, name="h")
    c = cascade(
        {"h": remote}, clock, guard=g, mode="hosted", states_dataset_derived=False
    )
    step = c.decide(request(), features())
    assert step.outcome.status == DecisionStatus.ANSWERED and remote.calls == 1
    assert ledger.remaining().amount == Decimal("0.9996")
    assert step.measurement.cost.amount.amount == Decimal("0.0004")
    assert step.measurement.cost.basis == CostBasis.ACTUAL


def test_the_spend_guard_blocks_a_hosted_call_over_the_cap(clock):
    g, _ = guard("0.0001")
    remote = hosted(clock, name="h")
    c = cascade(
        {"h": remote}, clock, guard=g, mode="hosted", states_dataset_derived=False
    )
    o = c.decide(request(), features()).outcome
    assert (
        o.failure_reason == DecisionFailureReason.BUDGET_BLOCKED and remote.calls == 0
    )


def test_an_unpriced_hosted_backend_is_refused_unless_allowed(clock):
    g, _ = guard()
    unpriced = FakeDecisionBackend(clock, name="h", kind="hosted", script=CHEAP)
    c = cascade(
        {"h": unpriced}, clock, guard=g, mode="hosted", states_dataset_derived=False
    )
    o = c.decide(request(), features()).outcome
    assert o.failure_reason == DecisionFailureReason.BUDGET_BLOCKED
    allowed = cascade(
        {"h": unpriced},
        clock,
        guard=g,
        mode="hosted",
        states_dataset_derived=False,
        allow_unpriced=True,
        cache_enabled=False,
    )
    step = allowed.decide(request(), features())
    assert step.outcome.status == DecisionStatus.ANSWERED
    assert step.measurement.cost.status == CostStatus.NOT_COMPUTED  # never zero
    assert g.stopped is not None  # one unpriced call, then the guard stops
    again = allowed.decide(request(), features()).outcome
    assert again.failure_reason == DecisionFailureReason.BUDGET_BLOCKED


def test_a_hosted_error_charges_the_estimate_and_stops_router_calls(clock):
    g, ledger = guard()
    remote = hosted(clock, name="h", failures=[ErrorClass.UNAVAILABLE])
    c = cascade(
        {"h": remote}, clock, guard=g, mode="hosted", states_dataset_derived=False
    )
    step = c.decide(request(), features())
    assert step.outcome.failure_reason == DecisionFailureReason.ERROR
    assert ledger.remaining().amount == Decimal("0.9996")
    assert step.measurement.cost.status == CostStatus.NOT_COMPUTED
    assert c.guard_stopped is not None
    # The stop holds for the rest of the run: no further hosted call (R6
    # follow-up; the live check gives each diagnostic call its own guard, A-116).
    calls = remote.calls
    later = c.decide(request(), features()).outcome
    assert later.failure_reason == DecisionFailureReason.BUDGET_BLOCKED
    assert remote.calls == calls


# --- privacy --------------------------------------------------------------------------


def test_the_state_carries_no_instructions_and_the_step_no_text(clock):
    seen = []

    class Spy(FakeDecisionBackend):
        def decide(self, state, questions, *, timeout_ms):
            seen.append(state)
            return super().decide(state, questions, timeout_ms=timeout_ms)

    c = cascade({"a": Spy(clock, name="a", script=CHEAP)}, clock)
    step = c.decide(request(), features())
    assert seen and seen[0].dataset_derived is True
    dumped = seen[0].model_dump_json()
    assert "INSTRUCTIONS-NEVER-IN-STATE" not in dumped
    for part in (step.outcome, step.measurement, *step.circuits):
        text = part.model_dump_json()
        assert S not in text and "سلام" not in text


# --- A-103 option and A-105 condition (owner, 2026-11-02) -------------------------


def test_escalation_on_low_confidence_asks_the_next_backend(clock):
    first = local(clock, name="a")  # reports 0.7
    second = local(clock, name="b")
    off = cascade({"a": first, "b": second}, clock, min_confidence=0.8)
    assert off.decide(request(), features()).outcome.failure_reason == (
        DecisionFailureReason.LOW_CONFIDENCE
    )
    assert second.calls == 0  # default: the chain ends (A-103)

    class Sure(FakeDecisionBackend):
        def decide(self, state, questions, *, timeout_ms):
            r = super().decide(state, questions, timeout_ms=timeout_ms)
            answers = tuple(
                a.model_copy(update={"confidence": 0.95})
                if a.confidence is not None
                else a
                for a in r.answers
            )
            return r.model_copy(update={"answers": answers})

    sure = Sure(clock, name="b", script=CHEAP)
    on = cascade(
        {"a": local(clock, name="a"), "b": sure},
        clock,
        min_confidence=0.8,
        escalate_on_low_confidence=True,
    )
    o = on.decide(request(), features()).outcome
    assert o.status == DecisionStatus.ANSWERED and o.result.backend.name == "b"
    assert [a.answered for a in o.attempts] == [True, True]
    assert len(on.cache) == 1  # only the confident answer is cached


def test_escalation_with_no_better_answer_stays_low_confidence(clock):
    c = cascade(
        {
            "a": local(clock, name="a"),
            "b": local(clock, name="b", failures=[ErrorClass.UNAVAILABLE]),
        },
        clock,
        min_confidence=0.8,
        escalate_on_low_confidence=True,
        keep_soft_signals=True,
    )
    o = c.decide(request(), features()).outcome
    assert o.failure_reason == DecisionFailureReason.LOW_CONFIDENCE
    assert o.soft_result is not None and o.soft_result.backend.name == "a"
    assert len(c.cache) == 0


def test_no_reported_confidence_passes_the_gate_but_never_makes_tier_0(clock):
    """A-105: not gated, and unknown never satisfies tau_conf (P-6)."""
    from metis_auto.domain.routing import DecisionRouterPolicy
    from metis_auto.wiring.from_settings import pipeline_config

    class Silent(FakeDecisionBackend):
        def decide(self, state, questions, *, timeout_ms):
            r = super().decide(state, questions, timeout_ms=timeout_ms)
            answers = tuple(
                a.model_copy(update={"confidence": None}) for a in r.answers
            )
            return r.model_copy(update={"answers": answers})

    step = cascade({"a": Silent(clock, name="a", script=CHEAP)}, clock).decide(
        request(), features()
    )
    assert step.outcome.status == DecisionStatus.ANSWERED
    config = pipeline_config(load_settings(environ={}, dotenv=None, runtime=None))
    from metis_auto.domain.routing import DecisionRouterConfig, RuleBasedConfig

    policy = DecisionRouterPolicy(
        config.routing.decision_router or DecisionRouterConfig(),
        config.routing.rule_based or RuleBasedConfig(),
        config.catalogue,
        config.prices,
    )
    decided = policy.decide_tier(features(decision=step.outcome))
    # cheap_model_ok is 0.9 (>= tau_ok) but its confidence is unknown.
    assert decided.reason != "decision.tier0.cheap_ok"
    assert "tau_conf" not in decided.fired
