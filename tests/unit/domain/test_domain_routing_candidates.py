"""The routing candidate set (demo selection, ADR-XXXX (demo-sprint-winners)):
``RoutingConfig.candidates`` restricts every policy to the sprint's primary
models. Empty = every enabled model (the serving default). Pure, offline;
features are SYNTHETIC."""

from pathlib import Path

from metis_auto.contracts import (
    ComponentState,
    ExclusionReason,
    Fidelity,
    Language,
    RequestFeatures,
    TokenCount,
)
from metis_auto.domain.routing import EligibilityConfig, filter_eligible
from metis_auto.settings.model import ReferenceSettings
from metis_auto.settings.reference import load_reference

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
CATALOGUE = load_reference(CONFIG_DIR, ReferenceSettings()).catalogue
SPRINT = ("gpt-5-nano", "gpt-4o-mini", "deepseek-v4-flash")


def feats() -> RequestFeatures:
    return RequestFeatures(
        feature_set_version="test",
        language=Language.ENGLISH,
        message_chars=20,
        known_input_tokens=TokenCount(
            tokens=60, fidelity=Fidelity.APPROXIMATION, method="test"
        ),
        has_code=False,
        has_coding_intent=False,
        length_bucket=0,
        is_greeting=False,
        attachment_count=0,
        turn_depth=0,
        instructions_state=ComponentState.PRESENT,
        retrieved_state=ComponentState.ABSENT,
        structured_input_state=ComponentState.ABSENT,
        traffic_source_state=ComponentState.UNKNOWN,
        history_turns=(),
    )


def test_no_candidates_keeps_every_enabled_model():
    eligible, _ = filter_eligible(feats(), CATALOGUE, EligibilityConfig())
    assert eligible == tuple(e for e in CATALOGUE.entries if e.enabled)


def test_candidates_keep_only_the_named_models_in_catalogue_order():
    eligible, exclusions = filter_eligible(
        feats(), CATALOGUE, EligibilityConfig(), candidates=SPRINT
    )
    assert {e.model_id for e in eligible} <= set(SPRINT)
    assert [e.model_id for e in eligible] == [
        e.model_id for e in CATALOGUE.entries if e.model_id in SPRINT and e.enabled
    ]
    out = {x.model_id: x.reason for x in exclusions}
    assert out["gpt-4.1-nano"] == ExclusionReason.NOT_A_CANDIDATE
    assert out["mimo-v2.5"] == ExclusionReason.NOT_A_CANDIDATE


def test_a_disabled_candidate_stays_disabled():
    _, exclusions = filter_eligible(
        feats(), CATALOGUE, EligibilityConfig(), candidates=("grok-4-1-fast",)
    )
    out = {x.model_id: x.reason for x in exclusions}
    assert out["grok-4-1-fast"] == ExclusionReason.DISABLED
