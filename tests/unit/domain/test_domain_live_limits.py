"""Stage 7.5 domain knobs: the generation-limit cap and the diagnostic
unknown-window switch (FR-ROUTE-05 stays the default). Offline, synthetic."""

from fixtures.synthetic import contract_examples as ex

from metis_auto.contracts import ExclusionReason, Limit
from metis_auto.domain.context import ContextConfig, reserved_output
from metis_auto.domain.routing.eligibility import EligibilityConfig, filter_eligible


def _entry(output_limit=None, window=8_000):
    entry = ex.model_catalogue().entries[0]
    return entry.model_copy(
        update={
            "max_output_tokens": Limit(value=output_limit, evidence=ex.SOURCE)
            if output_limit
            else Limit(),
            "context_window": Limit(value=window, evidence=ex.SOURCE)
            if window
            else Limit(),
        }
    )


def test_cap_lowers_a_large_model_limit():
    config = ContextConfig(max_output_tokens_cap=4096)
    assert reserved_output(_entry(128_000), config) == 4096
    assert reserved_output(_entry(1_000), config) == 1_000


def test_no_cap_keeps_the_model_limit_or_the_default():
    assert reserved_output(_entry(128_000), ContextConfig()) == 128_000
    config = ContextConfig(default_reserved_output_tokens=512)
    assert reserved_output(_entry(None), config) == 512


def test_unknown_window_is_excluded_unless_the_diagnostic_switch_is_on():
    catalogue = ex.model_catalogue().model_copy(
        update={"entries": (_entry(window=None),)}
    )
    features = ex.request_features()
    eligible, excluded = filter_eligible(features, catalogue, EligibilityConfig())
    assert not eligible
    assert excluded[0].reason == ExclusionReason.CONTEXT_LIMIT_UNKNOWN
    eligible, _ = filter_eligible(
        features, catalogue, EligibilityConfig(allow_unknown_context_window=True)
    )
    assert len(eligible) == 1
