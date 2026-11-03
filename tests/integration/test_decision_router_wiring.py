"""The decision_router policy builds from the committed defaults through wiring,
alone and as the sticky inner router (ADR-0047). With the
router off it routes by the rules and then the safe tier: no decision answers exist."""

from metis_auto.contracts import RouterPath
from metis_auto.settings import load_settings
from metis_auto.wiring.from_settings import pipeline_config
from metis_auto.wiring.pipeline import ROUTING_POLICIES


def build(policy: str, **overrides):
    loaded = load_settings(
        environ={},
        dotenv=None,
        runtime=None,
        overrides={"pipeline.routing.policy": policy, **overrides},
    )
    config = pipeline_config(loaded)
    return config, ROUTING_POLICIES[policy](config)


def test_decision_router_builds_from_the_defaults():
    config, policy = build("decision_router")
    assert policy.ref.name == "decision_router"
    dr = config.routing.decision_router
    assert dr.mapping.tau_ok == 0.7 and dr.safe_tier == 1
    assert dr.gate.greeting_tier == 0 and dr.hysteresis.downgrade_after_n == 2


def test_sticky_can_use_the_decision_router_inside():
    _, policy = build("sticky", **{"pipeline.routing.sticky.inner": "decision_router"})
    assert policy.ref.version.endswith("+dr-0.1.0")
    _, plain = build("sticky")
    assert "+dr-" not in plain.ref.version


def test_without_answers_the_policy_falls_back():
    from metis_auto.contracts import ComponentState, Language, RequestFeatures
    from metis_auto.domain.routing import EligibilityConfig, filter_eligible

    config, policy = build("decision_router")
    f = RequestFeatures(
        feature_set_version="t",
        language=Language.PERSIAN,
        message_chars=20,
        length_bucket=0,
        is_greeting=False,
        has_code=False,
        has_coding_intent=False,
        attachment_count=0,
        instructions_state=ComponentState.PRESENT,
        retrieved_state=ComponentState.ABSENT,
        structured_input_state=ComponentState.ABSENT,
        traffic_source_state=ComponentState.UNKNOWN,
    )
    eligible, _ = filter_eligible(f, config.catalogue, EligibilityConfig())
    choice = policy.choose(f, eligible)
    assert choice.router_summary.path in (
        RouterPath.FALLBACK_RULES,
        RouterPath.FALLBACK_SAFE_TIER,
    )
