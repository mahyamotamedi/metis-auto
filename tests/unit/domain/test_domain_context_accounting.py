"""Features, pass-through context, and accounting (FR-FEAT, FR-CTX, FR-ACCT)."""

from datetime import date
from decimal import Decimal

from fixtures.synthetic import contract_examples as ex

from metis_auto.contracts import (
    ComponentName,
    ComponentState,
    ComponentTokens,
    CostBasis,
    CostStatus,
    Fidelity,
    Language,
    NotComputedReason,
    OverflowOutcome,
    PartRole,
    PriceEntry,
    PriceTable,
    Sourced,
    TargetTokenCounts,
    TokenType,
)
from metis_auto.domain.accounting import (
    AccountingConfig,
    cost_of,
    pre_call_estimate,
    sum_counts,
    total_cost,
)
from metis_auto.domain.context import ContextConfig, OverflowRule, PassThroughStrategy
from metis_auto.domain.features import FeatureConfig, extract_features

TARGET = ex.model_catalogue().entries[0]  # window 8,000; output limit unknown


def test_features_keep_unknown_as_none():
    feats = extract_features(ex.request(), ex.request_measurements(), FeatureConfig())
    # The synthetic message mixes the Latin "[SYNTHETIC]" marker with Persian.
    assert feats.language in (Language.PERSIAN, Language.MIXED)
    assert feats.is_greeting is False  # no phrases in the default config
    assert feats.turn_depth == 1
    assert feats.structured_input_state == ComponentState.UNKNOWN
    assert feats.instructions_group == ex.FP_INSTRUCTIONS
    assert feats.known_input_tokens.fidelity == Fidelity.APPROXIMATION


def _counts(message_tokens: int) -> TargetTokenCounts:
    return TargetTokenCounts(
        model_id=TARGET.model_id,
        components=(
            ComponentTokens(
                component=ComponentName.MESSAGE, total=ex.tokens(message_tokens)
            ),
        ),
    )


def test_pass_through_orders_parts_and_records_without_content():
    plan = PassThroughStrategy().build(
        ex.request(),
        ex.request_measurements(),
        _counts(12),
        TARGET,
        ContextConfig(),
        False,
    )
    roles = [p.role for p in plan.parts]
    assert roles[0] == PartRole.INSTRUCTIONS and roles[-1] == PartRole.USER
    assert PartRole.RETRIEVED in roles
    assert plan.record.overflow == OverflowOutcome.FITS
    assert ex.MARKER not in plan.record.model_dump_json()


def test_overflow_rule():
    big = _counts(9_000)
    reroute = PassThroughStrategy().build(
        ex.request(), ex.request_measurements(), big, TARGET, ContextConfig(), False
    )
    assert reroute.record.overflow == OverflowOutcome.REROUTE_REQUESTED
    once = PassThroughStrategy().build(
        ex.request(), ex.request_measurements(), big, TARGET, ContextConfig(), True
    )
    assert once.record.overflow == OverflowOutcome.REJECTED
    reject = ContextConfig(overflow_rule=OverflowRule.REJECT)
    plan = PassThroughStrategy().build(
        ex.request(), ex.request_measurements(), big, TARGET, reject, False
    )
    assert plan.record.overflow == OverflowOutcome.REJECTED


SOURCE = Sourced(source="SYNTHETIC test price, not real", checked_on=date(2026, 10, 18))
PRICED = PriceTable(
    version="prices-synthetic",
    entries=tuple(
        PriceEntry(
            price_ref="synthetic-small-price",
            token_type=t,
            amount=Decimal(a),
            per_tokens=1_000_000,
            currency="USD",
            evidence=SOURCE,
        )
        for t, a in ((TokenType.INPUT, "1"), (TokenType.OUTPUT, "2"))
    ),
)


def _usage():
    return ex.model_results()[0].usage  # 120 in (provider_reported), 30 out


def test_cost_from_usage_and_prices():
    cost = cost_of(_usage(), TARGET, PRICED)
    assert cost.status == CostStatus.COMPUTED
    expected = Decimal(_usage().input.tokens) * 1 + Decimal(_usage().output.tokens) * 2
    assert cost.amount.amount == expected / 1_000_000
    assert cost.price_table_version == "prices-synthetic"


def test_unknown_price_or_usage_is_not_computed_never_zero():
    assert cost_of(_usage(), TARGET, ex.price_table()).reason == (
        NotComputedReason.PRICE_UNKNOWN
    )
    assert cost_of(None, TARGET, PRICED).reason == NotComputedReason.USAGE_UNKNOWN
    unknown = cost_of(None, TARGET, PRICED)
    total = total_cost(
        [cost_of(_usage(), TARGET, PRICED), unknown],
        CostBasis.ACTUAL,
        PRICED,
        AccountingConfig(),
    )
    assert total.reason == NotComputedReason.COMPONENT_NOT_COMPUTED


def test_pre_call_estimate_and_token_sums():
    estimate = pre_call_estimate(TARGET, ex.tokens(100), 50, PRICED)
    assert estimate.cost.basis == CostBasis.PRE_CALL_ESTIMATE
    assert estimate.cost.status == CostStatus.COMPUTED
    mixed = sum_counts([ex.tokens(1), ex.tokens(2, Fidelity.PROVIDER_REPORTED)])
    assert (mixed.tokens, mixed.fidelity) == (3, Fidelity.APPROXIMATION)
