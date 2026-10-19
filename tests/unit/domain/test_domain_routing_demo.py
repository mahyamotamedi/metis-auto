"""Rule-based and sticky routing v1 (Demo milestone; owner brief §7,
routing_plan §3 and §5). Pure policies over the real Metis test catalogue and
price table (configuration, read offline); features are built by hand
(SYNTHETIC, no text needed)."""

from pathlib import Path

import pytest

from metis_auto.contracts import (
    CACHE_PRODUCER,
    ComponentState,
    Fidelity,
    Language,
    RequestFeatures,
    TokenCount,
    TurnFeatures,
)
from metis_auto.domain.routing import (
    CostModel,
    EligibilityConfig,
    Rule,
    RuleBasedConfig,
    RuleBasedPolicy,
    RuleCondition,
    StickyConfig,
    StickyMode,
    StickyPolicy,
    effective_cost,
    filter_eligible,
    rank_by_cost,
    reconstruct_anchor,
    route,
)
from metis_auto.domain.routing.policy import RoutingConfig
from metis_auto.settings import load_settings
from metis_auto.settings.model import ReferenceSettings
from metis_auto.settings.reference import load_reference

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
REF = load_reference(CONFIG_DIR, ReferenceSettings())
CATALOGUE, PRICES = REF.catalogue, REF.prices
ENTRIES = {e.model_id: e for e in CATALOGUE.entries}
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
    rules=(
        Rule(id="code", when=RuleCondition(has_code=True), tier=1),
        Rule(id="intent", when=RuleCondition(has_coding_intent=True), tier=1),
        Rule(id="long", when=RuleCondition(length_bucket_min=2), tier=1),
    ),
    default_tier=0,
    cost_model=COST,
)


def feats(
    *,
    language=Language.PERSIAN,
    code=False,
    intent=False,
    bucket=0,
    greeting=False,
    attachments=0,
    history=(),
    tokens=60,
) -> RequestFeatures:
    return RequestFeatures(
        feature_set_version="test",
        language=language,
        message_chars=20,
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
    )


def turn(
    producer,
    *,
    language=Language.PERSIAN,
    code=False,
    intent=False,
    bucket=0,
    greeting=False,
):
    state = ComponentState.PRESENT if producer else ComponentState.UNKNOWN
    return TurnFeatures(
        language=language,
        has_code=code,
        has_coding_intent=intent,
        length_bucket=bucket,
        is_greeting=greeting,
        producer_state=state,
        producer=producer,
    )


def eligible(f: RequestFeatures):
    entries, _ = filter_eligible(f, CATALOGUE, EligibilityConfig())
    return entries


def sticky(mode=StickyMode.STICKY_V1) -> StickyPolicy:
    return StickyPolicy(StickyConfig(mode=mode), RULES, CATALOGUE, PRICES)


# --- effective cost: hidden reasoning counts (routing plan §3) ---------------


def test_nominal_price_would_pick_gpt5_nano_but_reasoning_changes_the_order():
    tier0 = [ENTRIES[m] for m in ("gpt-5-nano", "gpt-4.1-nano", "mimo-v2.5")]
    nominal = CostModel(assumed_output_tokens=0, default_reasoning_tokens=0)
    assert rank_by_cost(tier0, PRICES, 1000, nominal)[0].model_id == "gpt-5-nano"
    ranked = [e.model_id for e in rank_by_cost(tier0, PRICES, 1000, COST)]
    assert ranked[-1] == "gpt-5-nano"  # 300 visible + 150 hidden at 0.44 / 1M


def test_unlisted_reasoning_model_never_assumes_zero():
    model = CostModel(assumed_output_tokens=0, default_reasoning_tokens=256)
    with_default = effective_cost(ENTRIES["gpt-5-nano"], PRICES, 0, model)
    assert with_default is not None and with_default > 0  # 256 × 0.44 / 1M


def test_thinking_off_removes_deepseek_reasoning_from_settings_cost_model():
    from metis_auto.wiring.from_settings import pipeline_config

    loaded = load_settings(
        overrides={"model_options.deepseek-v4-flash.thinking": "disabled"},
        runtime=None,
        dotenv=None,
        environ={},
    )
    model = pipeline_config(loaded).routing.rule_based.cost_model
    assert model.expected_reasoning_tokens["deepseek-v4-flash"] == 0
    assert model.expected_reasoning_tokens["gpt-5-nano"] > 0


# --- rule_based -----------------------------------------------------------------


def test_rules_choose_a_tier_and_its_cheapest_effective_model():
    policy = RuleBasedPolicy(RULES, CATALOGUE, PRICES)
    plain = feats()
    choice = policy.choose(plain, eligible(plain))
    assert choice.reason_code == "rule.default"
    assert TIERS[choice.model_id] == 0 and choice.model_id != "gpt-5-nano"
    assert choice.chain and TIERS[choice.chain[0]] == 1

    code = feats(code=True)
    choice = policy.choose(code, eligible(code))
    assert choice.reason_code == "rule.code" and TIERS[choice.model_id] == 1
    assert choice.chain == ()  # nothing above tier 1 is enabled

    intent = feats(intent=True)  # asks for code, none present (A-71)
    choice = policy.choose(intent, eligible(intent))
    assert choice.reason_code == "rule.intent" and TIERS[choice.model_id] == 1


def test_a_tier_without_eligible_models_falls_back_up_then_down():
    policy = RuleBasedPolicy(RULES, CATALOGUE, PRICES)
    f = feats()
    only_tier1 = tuple(e for e in eligible(f) if e.tier == 1)
    choice = policy.choose(f, only_tier1)
    assert choice.reason_code == "rule.default.tier_fallback"
    assert TIERS[choice.model_id] == 1


def test_unknown_features_never_satisfy_a_condition():
    condition = RuleCondition(has_code=True)
    assert condition.holds(feats(code=True))
    assert not condition.holds(feats(code=False))
    assert not condition.holds(feats().model_copy(update={"has_code": None}))


def test_route_records_the_policy_chain_and_anchor():
    f = feats(history=[turn("gpt-4o-mini")])
    decision = route(f, CATALOGUE, sticky(), RoutingConfig())
    assert decision.reason_code == "sticky.stay"
    assert decision.target_model_id == "gpt-4o-mini"
    assert decision.anchor_model_id == "gpt-4o-mini"
    assert decision.target_model_id not in decision.chain


# --- sticky v1 ------------------------------------------------------------------


def choose(f, mode=StickyMode.STICKY_V1):
    return sticky(mode).choose(f, eligible(f))


def cheapest_overall(f):
    return RuleBasedPolicy(RULES, CATALOGUE, PRICES).cheapest(f, eligible(f)).model_id


def test_greeting_goes_to_the_cheapest_model_and_never_anchors():
    f = feats(greeting=True)
    choice = choose(f)
    assert choice.reason_code == "sticky.greeting"
    assert choice.model_id == cheapest_overall(f)
    history = (turn(choice.model_id, greeting=True),)
    assert reconstruct_anchor(history, TIERS, StickyConfig()) is None


def test_greeting_in_an_anchored_session_stays_on_the_anchor():
    # Q-41 (owner, 2026-10-19): keeps the provider's prefix cache warm.
    f = feats(greeting=True, history=[turn("gpt-4o-mini")])
    choice = choose(f)
    assert choice.reason_code == "sticky.greeting.stay"
    assert choice.model_id == "gpt-4o-mini" != cheapest_overall(f)
    assert choice.anchor_model_id == "gpt-4o-mini"
    # The greeting itself never anchors: the anchor is still the earlier turn.
    history = (turn("gpt-4o-mini"), turn("gpt-4o-mini", greeting=True))
    anchor = reconstruct_anchor(history, TIERS, StickyConfig())
    assert anchor.model_id == "gpt-4o-mini" and not anchor.escalated


def test_greeting_with_an_ineligible_anchor_goes_to_the_cheapest():
    f = feats(greeting=True, history=[turn("gpt-4o-mini")])
    without = tuple(e for e in eligible(f) if e.model_id != "gpt-4o-mini")
    choice = sticky().choose(f, without)
    assert choice.reason_code == "sticky.greeting"
    assert choice.model_id == cheapest_overall(f)


def test_first_substantive_message_anchors_then_similar_messages_stay():
    first = choose(feats())
    assert first.reason_code == "sticky.first_substantive.rule.default"
    assert first.anchor_model_id is None
    later = choose(feats(history=[turn(first.model_id)]))
    assert later.reason_code == "sticky.stay"
    assert later.model_id == first.model_id


def test_cache_hits_and_unknown_producers_do_not_anchor():
    history = [turn(CACHE_PRODUCER), turn(None)]
    assert reconstruct_anchor(tuple(history), TIERS, StickyConfig()) is None
    assert choose(feats(history=history)).reason_code.startswith(
        "sticky.first_substantive"
    )


@pytest.mark.parametrize(
    ("current", "anchor_turn", "why"),
    [
        (dict(code=True), dict(), "code_appeared"),
        (dict(code=False), dict(code=True), "code_disappeared"),
        (dict(intent=True), dict(), "coding_intent_appeared"),
        (dict(attachments=1), dict(), "attachment"),
        (dict(language=Language.ENGLISH), dict(), "language_switch"),
        (dict(bucket=2), dict(bucket=0), "length_jump"),
    ],
)
def test_very_different_messages_reroute_and_reanchor(current, anchor_turn, why):
    history = [turn("gpt-4.1-nano", **anchor_turn)]
    f = feats(history=history, **current)
    # Eligibility of a plain request: no test model has a verified image
    # capability, so a real attachment would leave nothing eligible.
    choice = sticky().choose(f, eligible(feats()))
    assert choice.reason_code.startswith(f"sticky.reroute.{why}.")
    assert choice.anchor_model_id == "gpt-4.1-nano"


def test_coding_intent_counts_only_when_it_appears():
    # Anchored on a coding request: a follow-up without the intent stays (A-71).
    history = [turn("gpt-4o-mini", intent=True)]
    assert choose(feats(history=history)).reason_code == "sticky.stay"
    # Still asking for code: similar, stays.
    assert choose(feats(history=history, intent=True)).reason_code == "sticky.stay"
    # Anchored on code itself: the intent is not new, and code disappearing
    # already re-routes (to the code-related tier by the rules).
    coded = [turn("gpt-4o-mini", code=True)]
    choice = choose(feats(history=coded, intent=True))
    assert choice.reason_code == "sticky.reroute.code_disappeared.rule.intent"
    assert TIERS[choice.model_id] == 1


def test_coding_intent_appearing_reroutes_to_the_stronger_tier():
    history = [turn("mimo-v2.5")]
    choice = choose(feats(history=history, intent=True))
    assert choice.reason_code == "sticky.reroute.coding_intent_appeared.rule.intent"
    assert TIERS[choice.model_id] == 1 and choice.anchor_model_id == "mimo-v2.5"
    # The next request sees that turn and re-anchors on its producer.
    later = (*history, turn(choice.model_id, intent=True))
    anchor = reconstruct_anchor(later, TIERS, StickyConfig())
    assert anchor.model_id == choice.model_id and anchor.profile.has_coding_intent


def test_unknown_coding_intent_never_satisfies_a_rule():
    condition = RuleCondition(has_coding_intent=True)
    assert condition.holds(feats(intent=True))
    assert not condition.holds(feats().model_copy(update={"has_coding_intent": None}))


def test_a_one_bucket_change_or_undetermined_language_is_not_different():
    history = [turn("gpt-4.1-nano", bucket=0)]
    assert choose(feats(history=history, bucket=1)).reason_code == "sticky.stay"
    f = feats(history=history, language=Language.UNDETERMINED)
    assert choose(f).reason_code == "sticky.stay"


def test_reanchoring_is_reconstructed_from_history():
    history = (
        turn("gpt-4.1-nano"),
        turn("gpt-4o-mini", code=True),  # very different: re-anchored
        turn("gpt-4o-mini", code=True),
    )
    anchor = reconstruct_anchor(history, TIERS, StickyConfig())
    assert anchor.model_id == "gpt-4o-mini" and anchor.profile.has_code


def test_escalation_raises_the_anchor_only_up_never_down():
    up = (turn("gpt-4.1-nano"), turn("gpt-4o-mini"))  # similar, higher tier
    anchor = reconstruct_anchor(up, TIERS, StickyConfig())
    assert anchor.model_id == "gpt-4o-mini" and anchor.escalated
    assert choose(feats(history=list(up))).reason_code == "sticky.stay.escalated"

    down = (*up, turn("gpt-4.1-nano"))  # e.g. served in per_request mode
    assert reconstruct_anchor(down, TIERS, StickyConfig()).model_id == "gpt-4o-mini"


def test_an_ineligible_anchor_reroutes():
    f = feats(history=[turn("gpt-4o-mini")])
    without = tuple(e for e in eligible(f) if e.model_id != "gpt-4o-mini")
    choice = sticky().choose(f, without)
    assert choice.reason_code.startswith("sticky.reroute.anchor_ineligible.")


def test_per_request_mode_ignores_history_and_greetings():
    f = feats(greeting=True, history=[turn("gpt-4o-mini")])
    choice = choose(f, StickyMode.PER_REQUEST)
    assert choice.reason_code == "per_request.rule.default"
    assert choice.anchor_model_id is None
    assert TIERS[choice.model_id] == 0
