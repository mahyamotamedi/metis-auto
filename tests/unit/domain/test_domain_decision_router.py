"""The decision router's pure parts (ADR-0047): gate, state
builder, answer mapping, paths, criteria, reasoning effort, the tier helper, and the
sticky interplay with hysteresis. Real Metis test catalogue and prices (offline config);
every text is SYNTHETIC."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from metis_auto.contracts import (
    BackendAttempt,
    BackendKind,
    Capability,
    Component,
    ComponentState,
    Cost,
    CostBasis,
    CostStatus,
    DecisionAnswer,
    DecisionFailureReason,
    DecisionLatencySource,
    DecisionOutcome,
    DecisionQuestionType,
    DecisionResult,
    DecisionSkipReason,
    DecisionStatus,
    ErrorClass,
    Fidelity,
    Language,
    LastAssistantTurnKind,
    Money,
    PolicyRef,
    Request,
    RetrievedContext,
    RetrievedItem,
    Role,
    RouterPath,
    Sourced,
    TokenCount,
    Turn,
    TurnFeatures,
)
from metis_auto.domain.routing import (
    CriteriaConfig,
    DecisionRouterConfig,
    DecisionRouterPolicy,
    EffortConfig,
    EligibilityConfig,
    GateConfig,
    MappingConfig,
    Rule,
    RuleBasedConfig,
    RuleCondition,
    StateConfig,
    StickyConfig,
    StickyPolicy,
    build_state,
    filter_eligible,
    needs_decision,
    route,
)
from metis_auto.domain.routing.base import PolicyChoice
from metis_auto.domain.routing.policy import RoutingConfig
from metis_auto.domain.routing.rule_based import CostModel
from metis_auto.settings.model import ReferenceSettings
from metis_auto.settings.reference import load_reference

MARKER = "[SYNTHETIC]"
CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
REF = load_reference(CONFIG_DIR, ReferenceSettings())
CATALOGUE, PRICES = REF.catalogue, REF.prices
TIERS = {e.model_id: e.tier for e in CATALOGUE.entries}
COST = CostModel(
    assumed_output_tokens=300,
    expected_reasoning_tokens={
        "gpt-5-nano": 150,
        "deepseek-v4-flash": 30,
        "mimo-v2.5": 12,
    },
)
RULES = RuleBasedConfig(
    version="t",
    rules=(Rule(id="long", when=RuleCondition(length_bucket_min=3), tier=1),),
    default_tier=0,
    cost_model=COST,
)
LOCAL = PolicyRef(name="thx01", version="rev-synthetic")
HOSTED = PolicyRef(name="jev_metis", version="jev-1.13.0")


def feats(
    *,
    greeting=False,
    code=False,
    intent=False,
    attachments=0,
    chars=40,
    bucket=1,
    tokens=200,
    decision=None,
    history=(),
    deadline=None,
    language=Language.PERSIAN,
):
    from metis_auto.contracts import RequestFeatures

    return RequestFeatures(
        feature_set_version="test",
        language=language,
        message_chars=chars,
        known_input_tokens=TokenCount(
            tokens=tokens, fidelity=Fidelity.APPROXIMATION, method="test"
        ),
        has_code=code,
        has_coding_intent=intent,
        length_bucket=bucket,
        is_greeting=greeting,
        attachment_count=attachments,
        turn_depth=len(history),
        instructions_state=ComponentState.PRESENT,
        retrieved_state=ComponentState.ABSENT,
        structured_input_state=ComponentState.ABSENT,
        traffic_source_state=ComponentState.UNKNOWN,
        history_turns=tuple(history),
        decision=decision,
        deadline_ms=deadline,
    )


def result(
    *,
    complexity=1.0,
    confidence=0.8,
    reasoning=0.2,
    ok=0.5,
    intent="factual_qa",
    history=0.1,
    kind=BackendKind.LOCAL,
    cache_hit=False,
) -> DecisionResult:
    answers = [
        DecisionAnswer(
            question_id="complexity",
            type=DecisionQuestionType.SCORE,
            score=complexity,
            confidence=confidence,
        ),
        DecisionAnswer(
            question_id="needs_reasoning",
            type=DecisionQuestionType.NOUL,
            p_yes=reasoning,
        ),
        DecisionAnswer(
            question_id="cheap_model_ok", type=DecisionQuestionType.NOUL, p_yes=ok
        ),
        DecisionAnswer(
            question_id="intent", type=DecisionQuestionType.CHOICE, choice=intent
        ),
        DecisionAnswer(
            question_id="depends_on_history",
            type=DecisionQuestionType.NOUL,
            p_yes=history,
        ),
    ]
    local = kind == BackendKind.LOCAL
    return DecisionResult(
        answers=tuple(answers),
        backend=LOCAL if local else HOSTED,
        backend_kind=kind,
        model_revision="rev",
        question_set_version="routing_qs_v1",
        latency_ms=0.0 if cache_hit else 20.0,
        latency_source=DecisionLatencySource.MEASURED_LOCAL
        if local
        else DecisionLatencySource.MEASURED_REMOTE,
        cost=Cost(
            status=CostStatus.COMPUTED,
            basis=CostBasis.LOCAL_COMPUTE,
            amount=Money(amount=Decimal("0"), currency="USD"),
        ),
        cache_hit=cache_hit,
        calibrated=True,
    )


def answered(**kw) -> DecisionOutcome:
    r = result(**kw)
    attempts = (
        ()
        if r.cache_hit
        else (BackendAttempt(backend=r.backend, answered=True, latency_ms=20.0),)
    )
    return DecisionOutcome(
        status=DecisionStatus.ANSWERED,
        question_set_version="routing_qs_v1",
        result=r,
        attempts=attempts,
    )


FAILED = DecisionOutcome(
    status=DecisionStatus.FAILED,
    failure_reason=DecisionFailureReason.ERROR,
    error_class=ErrorClass.TIMEOUT,
)


def policy(**changes) -> DecisionRouterPolicy:
    return DecisionRouterPolicy(
        DecisionRouterConfig(**changes), RULES, CATALOGUE, PRICES
    )


def eligible(f):
    entries, _ = filter_eligible(f, CATALOGUE, EligibilityConfig())
    return entries


def decide(p: DecisionRouterPolicy, f):
    return route(f, CATALOGUE, p, RoutingConfig(policy="decision_router"))


# --- gate ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kw", "rule", "tier"),
    [
        ({"greeting": True}, "gate.greeting", 0),
        ({"code": True}, "gate.code", 1),
        ({"intent": True}, "gate.coding_intent", 1),
        ({"attachments": 1}, "gate.attachment", 1),
        ({"chars": 2500}, "gate.long_message", 1),
    ],
)
def test_gate_rules_decide_from_cheap_features(kw, rule, tier):
    gate = needs_decision(feats(**kw), GateConfig())
    assert gate is not None and (gate.rule_id, gate.tier) == (rule, tier)


def test_gate_leaves_ordinary_messages_to_the_model_and_ignores_unknowns():
    assert needs_decision(feats(), GateConfig()) is None
    unknown = feats().model_copy(
        update={"is_greeting": None, "has_code": None, "attachment_count": None}
    )
    assert needs_decision(unknown, GateConfig()) is None  # P-6
    assert needs_decision(feats(greeting=True), GateConfig(greeting_tier=None)) is None


# --- state builder -------------------------------------------------------------------


def request(
    message, *, history=None, instructions=None, retrieved=None, structured=None
):
    kw = {}
    if history is not None:
        kw["history"] = history
    if structured is not None:
        kw["structured_input"] = structured
    return Request(
        message=message,
        instructions=Component.present(instructions)
        if instructions
        else Component.absent(),
        retrieved=Component.present(
            RetrievedContext(items=(RetrievedItem(text=retrieved),))
        )
        if retrieved
        else Component.absent(),
        **kw,
    )


HISTORY = Component.present(
    (
        Turn(role=Role.USER, text=f"{MARKER} سفارشم کجاست؟ " + "و" * 400),
        Turn(role=Role.ASSISTANT, text=f"{MARKER} assistant reply"),
    )
)


def test_state_truncates_and_never_carries_instructions_or_retrieved_text():
    secret_ins = f"{MARKER} INSTRUCTION-TEXT"
    secret_rag = f"{MARKER} RETRIEVED-TEXT"
    req = request(
        f"{MARKER} " + "x" * 1500,
        history=HISTORY,
        instructions=secret_ins,
        retrieved=secret_rag,
    )
    f = feats(
        history=(
            TurnFeatures(
                language=Language.PERSIAN,
                has_code=False,
                length_bucket=1,
                is_greeting=False,
                producer_state=ComponentState.UNKNOWN,
            ),
        )
    )
    state = build_state(req, f, StateConfig(), dataset_derived=True)
    assert len(state.message) == 1000 and state.message_truncated
    assert state.previous_user_turn.state == ComponentState.PRESENT
    assert (
        len(state.previous_user_turn.value) <= 300
        and state.previous_user_turn_truncated
    )
    assert state.last_assistant_turn_kind == LastAssistantTurnKind.ANSWER
    dumped = state.model_dump_json()
    assert "INSTRUCTION-TEXT" not in dumped and "RETRIEVED-TEXT" not in dumped
    assert state.dataset_derived is True


@pytest.mark.parametrize(
    "message",
    [
        f"{MARKER} سلام، ساعت کاری؟",
        f"{MARKER} what are your hours?",
        f"{MARKER} سلام hours?",
    ],
)
def test_state_for_persian_english_and_mixed_first_turns(message):
    req = request(message, history=Component.absent())
    state = build_state(req, feats(), StateConfig(), dataset_derived=False)
    assert state.message == message
    assert state.previous_user_turn.state == ComponentState.ABSENT
    assert state.last_assistant_turn_kind == LastAssistantTurnKind.NONE
    assert not state.message_truncated


def test_unknown_history_and_widget_and_attachment_only():
    unknown_depth = feats().model_copy(update={"turn_depth": None})
    unknown = build_state(
        request(f"{MARKER} ok"), unknown_depth, StateConfig(), dataset_derived=False
    )
    assert unknown.previous_user_turn.state == ComponentState.UNKNOWN
    assert unknown.last_assistant_turn_kind == LastAssistantTurnKind.UNKNOWN
    widget = build_state(
        request(
            f"{MARKER} ok",
            history=HISTORY,
            structured=Component.unknown("widget_definition_not_loaded"),
        ),
        unknown_depth,
        StateConfig(),
        dataset_derived=False,
    )
    assert widget.last_assistant_turn_kind == LastAssistantTurnKind.STRUCTURED_INPUT
    plain = build_state(
        request(f"{MARKER} ok", history=HISTORY),
        unknown_depth,
        StateConfig(),
        dataset_derived=False,
    )
    assert plain.last_assistant_turn_kind == LastAssistantTurnKind.ANSWER
    from metis_auto.contracts import AttachmentRef, Modality

    only_image = Request(
        message="  ",
        attachments=Component.present((AttachmentRef(modality=Modality.IMAGE),)),
    )
    assert (
        build_state(only_image, feats(), StateConfig(), dataset_derived=False) is None
    )


def test_previous_turn_can_be_switched_off_and_text_folded():
    no_prev = build_state(
        request(f"{MARKER} ok", history=HISTORY),
        feats(),
        StateConfig(max_previous_turn_chars=0),
        dataset_derived=False,
    )
    assert no_prev.previous_user_turn.state == ComponentState.ABSENT
    folded = build_state(
        request(f"{MARKER} كيك", history=Component.absent()),
        feats(),
        StateConfig(fold="persian_fold_v1"),
        dataset_derived=False,
    )
    assert "ک" in folded.message and "ي" not in folded.message
    with pytest.raises(ValueError):
        build_state(
            request("x"), feats(), StateConfig(fold="nope"), dataset_derived=False
        )


# --- mapping and paths ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("kw", "reason", "tier"),
    [
        ({"complexity": 2.5}, "decision.tier1.complex", 1),
        ({"reasoning": 0.8}, "decision.tier1.needs_reasoning", 1),
        ({"ok": 0.9, "confidence": 0.9}, "decision.tier0.cheap_ok", 0),
        ({"intent": "code"}, "decision.tier1.intent.code", 1),
    ],
)
def test_answers_map_to_tiers_on_the_slow_local_path(kw, reason, tier):
    decision = decide(policy(), feats(decision=answered(**kw)))
    assert decision.reason_code.startswith(reason)
    assert decision.tier == tier
    summary = decision.router_summary
    assert summary.path == RouterPath.SLOW_LOCAL and summary.backend == LOCAL
    assert summary.mapped_tier == tier


def test_cheap_ok_without_a_known_confidence_never_fires():
    out = answered(ok=0.95, confidence=0.9)
    no_conf = out.model_copy(
        update={
            "result": out.result.model_copy(
                update={
                    "answers": tuple(
                        a.model_copy(update={"confidence": None})
                        if a.question_id == "complexity"
                        else a
                        for a in out.result.answers
                    )
                }
            )
        }
    )
    decision = decide(policy(), feats(decision=no_conf))
    assert decision.router_summary.path == RouterPath.FALLBACK_SAFE_TIER  # P-6


def test_paths_for_hosted_cache_failure_and_no_decision():
    hosted = decide(
        policy(), feats(decision=answered(complexity=3, kind=BackendKind.HOSTED))
    )
    assert hosted.router_summary.path == RouterPath.SLOW_HOSTED
    cached = decide(policy(), feats(decision=answered(complexity=3, cache_hit=True)))
    assert cached.router_summary.path == RouterPath.FAST_CACHE
    failed = decide(policy(), feats(decision=FAILED))
    assert failed.router_summary.path == RouterPath.FALLBACK_SAFE_TIER
    assert failed.reason_code == "decision.fallback.safe_tier"
    assert failed.tier == 1
    skipped = DecisionOutcome(
        status=DecisionStatus.SKIPPED, skip_reason=DecisionSkipReason.MODE_OFF
    )
    rules = decide(policy(), feats(bucket=3, decision=skipped))
    assert rules.reason_code.startswith("decision.fallback.rules.long")
    assert rules.router_summary.path == RouterPath.FALLBACK_RULES
    default = decide(policy(undetermined="rules_default"), feats())
    assert default.reason_code.startswith("decision.fallback.rules.default")
    assert default.tier == 0


def test_gate_wins_over_answers_and_low_confidence_soft_signals_are_opt_in():
    gated = decide(policy(), feats(greeting=True, decision=answered(complexity=3)))
    assert gated.reason_code.startswith("decision.gate.greeting")
    assert gated.router_summary.path == RouterPath.FAST_RULES and gated.tier == 0
    soft = DecisionOutcome(
        status=DecisionStatus.FAILED,
        failure_reason=DecisionFailureReason.LOW_CONFIDENCE,
        soft_result=result(complexity=3),
    )
    assert decide(policy(), feats(decision=soft)).router_summary.path == (
        RouterPath.FALLBACK_SAFE_TIER
    )
    on = policy(mapping=MappingConfig(use_soft_signals=True))
    assert decide(on, feats(decision=soft)).reason_code.startswith("decision.tier1")


# --- criteria and effort ------------------------------------------------------


def test_long_context_raises_and_max_tier_clamps():
    raised = decide(policy(), feats(tokens=40_000, decision=answered(ok=0.9)))
    assert raised.tier == 1
    assert "criteria.long_context" in raised.router_summary.thresholds_fired
    clamped = decide(
        policy(criteria=CriteriaConfig(max_tier=0)),
        feats(decision=answered(complexity=3)),
    )
    assert (
        clamped.tier == 0
        and "criteria.max_tier" in clamped.router_summary.thresholds_fired
    )


def test_latency_prefers_verified_low_latency_models_only():
    p = policy(criteria=CriteriaConfig(fast_model_deadline_ms=3000))
    tight = feats(deadline=2000, decision=answered(ok=0.9))
    plain = decide(p, tight)
    assert "criteria.low_latency_unavailable" in plain.router_summary.thresholds_fired
    fast = Capability(
        name="low_latency",
        verified=True,
        evidence=Sourced(source="synthetic test", checked_on="2026-11-02"),
    )
    entries = list(CATALOGUE.entries)
    i = next(k for k, e in enumerate(entries) if e.model_id == "gpt-4.1-nano")
    entries[i] = entries[i].model_copy(
        update={"capabilities": (*entries[i].capabilities, fast)}
    )
    catalogue = CATALOGUE.model_copy(update={"entries": tuple(entries)})
    p2 = DecisionRouterPolicy(
        DecisionRouterConfig(criteria=CriteriaConfig(fast_model_deadline_ms=3000)),
        RULES,
        catalogue,
        PRICES,
    )
    chosen = route(tight, catalogue, p2, RoutingConfig())
    assert chosen.target_model_id == "gpt-4.1-nano"
    assert "criteria.low_latency" in chosen.router_summary.thresholds_fired


def test_cost_cap_is_flagged_not_forced():
    p = policy(
        criteria=CriteriaConfig(max_effective_cost_per_answer=Decimal("0.0000001"))
    )
    d = decide(p, feats(decision=answered(complexity=3)))
    assert "criteria.cost_cap_exceeded" in d.router_summary.thresholds_fired
    assert d.target_model_id is not None


def test_low_reasoning_sets_an_effort_only_for_listed_models():
    low = feats(decision=answered(ok=0.9, reasoning=0.1))
    plain = decide(policy(), low)  # target is not gpt-5-nano: no hint
    assert plain.target_model_id != "gpt-5-nano"
    assert plain.router_summary.reasoning_effort is None
    everyone = policy(effort=EffortConfig(models=tuple(TIERS)))
    hinted = decide(everyone, low)
    assert hinted.router_summary.reasoning_effort == "minimal"
    assert "effort.minimal" in hinted.router_summary.thresholds_fired
    assert (
        decide(everyone, feats(decision=FAILED)).router_summary.reasoning_effort is None
    )
    high = decide(everyone, feats(decision=answered(reasoning=0.9)))
    assert high.router_summary.reasoning_effort is None  # high_effort unset: default


def test_expected_reasoning_tokens_follow_the_effort():
    p = policy(effort=EffortConfig(reasoning_tokens={"gpt-5-nano": {"minimal": 0}}))
    ranker = p._ranker("minimal")
    assert ranker.config.cost_model.expected_reasoning_tokens["gpt-5-nano"] == 0
    assert (
        p._ranker(None).config.cost_model.expected_reasoning_tokens["gpt-5-nano"] == 150
    )


# --- the tier helper in route() -----------------------------------------------


class TierOnly:
    ref = PolicyRef(name="tier_only", version="0")

    def choose(self, features, eligible):
        return PolicyChoice(reason_code="tier_only", tier=0)


def test_cheapest_in_tier_with_and_without_prices():
    f = feats()
    with_prices = route(f, CATALOGUE, TierOnly(), RoutingConfig(), prices=PRICES)
    assert with_prices.tier == 0 and with_prices.target_model_id in TIERS
    without = route(f, CATALOGUE, TierOnly(), RoutingConfig())
    first_priced = next(
        e.model_id
        for e in CATALOGUE.entries
        if e.tier == 0 and e.enabled and e.price_ref is not None
    )
    assert without.target_model_id == first_priced


# --- sticky interplay ----------------------------------------------------------


def turn(producer, *, code=False, bucket=1, greeting=False):
    return TurnFeatures(
        language=Language.PERSIAN,
        has_code=code,
        has_coding_intent=False,
        length_bucket=bucket,
        is_greeting=greeting,
        producer_state=ComponentState.PRESENT,
        producer=producer,
    )


def sticky() -> StickyPolicy:
    return StickyPolicy(
        StickyConfig(inner="decision_router"),
        RULES,
        CATALOGUE,
        PRICES,
        decision_router=policy(),
    )


def stick(f):
    return route(f, CATALOGUE, sticky(), RoutingConfig(policy="sticky"))


def test_the_decision_inner_needs_its_policy():
    with pytest.raises(ValueError):
        StickyPolicy(StickyConfig(inner="decision_router"), RULES, CATALOGUE, PRICES)


def test_upgrade_happens_at_once():
    f = feats(history=(turn("gpt-4.1-nano"),), decision=answered(complexity=3))
    d = stick(f)
    assert d.reason_code.startswith("sticky.upgrade.decision.tier1")
    assert d.tier == 1 and d.anchor_model_id == "gpt-4.1-nano"
    assert "hysteresis.upgrade" in d.router_summary.thresholds_fired


def test_history_dependent_follow_up_stays_on_the_anchor():
    f = feats(
        history=(turn("gpt-4o-mini"), turn("gpt-4o-mini")),
        decision=answered(ok=0.9, history=0.9),
    )
    d = stick(f)
    assert d.reason_code == "sticky.stay.history" and d.target_model_id == "gpt-4o-mini"


def test_downgrade_only_after_n_low_turns():
    low = feats(
        history=(turn("gpt-4o-mini"), turn("gpt-4o-mini")),
        decision=answered(ok=0.9, history=0.1),
    )
    down = stick(low)
    assert (
        down.reason_code.startswith("sticky.downgrade.decision.tier0")
        and down.tier == 0
    )
    busy = feats(
        history=(turn("gpt-4o-mini"), turn("gpt-4o-mini", bucket=2)),
        decision=answered(ok=0.9, history=0.1),
    )
    stay = stick(busy)
    assert stay.reason_code == "sticky.stay.hysteresis" and stay.tier == 1


def test_a_fallback_decision_never_moves_an_anchored_session():
    f = feats(history=(turn("gpt-4.1-nano"),), decision=FAILED)
    d = stick(f)
    assert d.reason_code == "sticky.stay" and d.target_model_id == "gpt-4.1-nano"


def test_greetings_still_never_anchor():
    g = stick(feats(greeting=True, decision=answered(complexity=3)))
    assert g.reason_code == "sticky.greeting"
    later = stick(
        feats(
            history=(turn("gpt-4.1-nano", greeting=True),),
            decision=answered(complexity=3),
        )
    )
    assert later.reason_code.startswith("sticky.first_substantive")


def test_result_confidence_can_be_limited_to_the_mapping_questions():
    """Q-61: a low-confidence intent answer gates only when every answer counts."""
    from metis_auto.contracts import (
        BackendKind,
        DecisionAnswer,
        DecisionLatencySource,
        DecisionQuestionType,
        DecisionResult,
        PolicyRef,
    )
    from metis_auto.domain.routing.decision import (
        QuestionIds,
        mapping_question_ids,
        result_confidence,
    )

    def noul(qid, c):
        return DecisionAnswer(
            question_id=qid, type=DecisionQuestionType.NOUL, p_yes=0.5, confidence=c
        )

    result = DecisionResult(
        answers=(
            noul("needs_reasoning", 0.9),
            noul("cheap_model_ok", 0.8),
            DecisionAnswer(
                question_id="intent",
                type=DecisionQuestionType.CHOICE,
                choice="other",
                confidence=0.2,
            ),
        ),
        backend=PolicyRef(name="fake", version="1"),
        backend_kind=BackendKind.LOCAL,
        model_revision="1",
        question_set_version="routing_qs_v1",
        latency_ms=1.0,
        latency_source=DecisionLatencySource.MEASURED_LOCAL,
        cost=Cost(
            status=CostStatus.COMPUTED,
            basis=CostBasis.LOCAL_COMPUTE,
            amount=Money(amount=Decimal("0"), currency="USD"),
        ),
        calibrated=False,
    )
    ids = mapping_question_ids(QuestionIds())
    assert result_confidence(result) == 0.2
    assert result_confidence(result, ids) == 0.8
    assert result_confidence(result, ("depends_on_history",)) is None
