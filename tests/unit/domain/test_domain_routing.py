"""Routing: shared eligibility filter and the fixed_model policy (routing.md)."""

from fixtures.synthetic import contract_examples as ex

from metis_auto.contracts import (
    Capability,
    ExclusionReason,
    Modality,
    ModelCatalogue,
    Sourced,
    TokenCount,
)
from metis_auto.contracts.routing import NO_ELIGIBLE_MODEL
from metis_auto.domain.routing import (
    EligibilityConfig,
    FixedModelConfig,
    FixedModelPolicy,
    RoutingConfig,
    filter_eligible,
    route,
)

CATALOGUE = ex.model_catalogue()  # synthetic-small (tier 0), synthetic-large (tier 1)


def _config(model: str, chain=()) -> RoutingConfig:
    return RoutingConfig(fixed_model=FixedModelConfig(model_id=model), chain=chain)


def _policy(model: str) -> FixedModelPolicy:
    return FixedModelPolicy(FixedModelConfig(model_id=model))


def test_fixed_model_routes_to_the_configured_model():
    decision = route(
        ex.request_features(),
        CATALOGUE,
        _policy(ex.MODEL),
        _config(ex.MODEL, chain=(ex.MODEL_LARGE,)),
    )
    assert decision.target_model_id == ex.MODEL
    assert decision.tier == 0 and decision.equivalence_group == ex.GROUP
    assert decision.chain == (ex.MODEL_LARGE,)
    assert decision.policy.name == "fixed_model"


def test_unverified_capability_excludes_the_model():
    # Both synthetic models declare image_input as unverified (FR-ROUTE-05).
    feats = ex.request_features().model_copy(
        update={"attachment_modalities": (Modality.IMAGE,)}
    )
    decision = route(feats, CATALOGUE, _policy(ex.MODEL), _config(ex.MODEL))
    assert decision.target_model_id is None
    assert decision.reason_code == NO_ELIGIBLE_MODEL
    assert {e.reason for e in decision.exclusions} == {
        ExclusionReason.CAPABILITY_UNVERIFIED
    }


def test_verified_capability_is_eligible():
    source = Sourced(source="SYNTHETIC", checked_on=ex.NOW.date())
    entry = CATALOGUE.entries[0].model_copy(
        update={
            "capabilities": (
                Capability(name="image_input", verified=True, evidence=source),
            )
        }
    )
    feats = ex.request_features().model_copy(
        update={"attachment_modalities": (Modality.IMAGE,)}
    )
    catalogue = ModelCatalogue(version="v", entries=(entry,))
    eligible, _ = filter_eligible(feats, catalogue, EligibilityConfig())
    assert [e.model_id for e in eligible] == [ex.MODEL]


def test_context_fit_uses_the_known_input_estimate():
    big = TokenCount(tokens=10_000, fidelity="approximation", method="x@1")
    feats = ex.request_features().model_copy(update={"known_input_tokens": big})
    _, exclusions = filter_eligible(feats, CATALOGUE, EligibilityConfig())
    assert {e.reason for e in exclusions} == {ExclusionReason.CONTEXT_TOO_SMALL}


def test_disabled_fixed_model_means_no_target_never_a_fallback():
    entries = (CATALOGUE.entries[0].model_copy(update={"enabled": False}),)
    catalogue = ModelCatalogue(version="v", entries=(*entries, CATALOGUE.entries[1]))
    decision = route(
        ex.request_features(), catalogue, _policy(ex.MODEL), _config(ex.MODEL)
    )
    assert decision.target_model_id is None
    assert decision.eligible == (ex.MODEL_LARGE,)
