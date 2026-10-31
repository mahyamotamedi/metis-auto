"""Long-context price tiers (E3 review of the E2 condition 4). SYNTHETIC token
counts; the price table is the repo's historical snapshot (g55, saved
2026-10-18), not re-verified.

The tier is chosen by the call's INPUT tokens and then prices every token type
of the call: uncached input, cached input and output (ADR-0020). The page labels
the tier "<= 270K context"; the code reads "context" as input tokens, with the
bound at 270,000 and an uncertain extension to 276,480 (K = 1,024), priced as the
long tier with a caveat. Whether "context" also counts output tokens is NOT
resolved by the source; the last test pins today's behavior, it does not settle
the question."""

from decimal import Decimal

import pytest

from metis_auto.contracts import (
    CostBasis,
    CostCaveat,
    CostStatus,
    Fidelity,
    TokenCount,
    TokenUsage,
)
from metis_auto.domain.accounting.cost import cost_of
from metis_auto.settings import repo_root
from metis_auto.settings.reference import read_catalogue, read_prices

CONFIG = repo_root() / "config" / "reference"
PRICES = read_prices(CONFIG / "prices-metis-2026-10-18-g55.toml")
CATALOGUE = {
    e.model_id: e for e in read_catalogue(CONFIG / "catalogue-metis-test.toml").entries
}
M = Decimal(1_000_000)


def usage(model, input_tokens, output_tokens, cached=0):
    def count(n):
        return TokenCount(tokens=n, fidelity=Fidelity.EXACT_LOCAL, method="t@1")

    return TokenUsage(
        model_id=model,
        input=count(input_tokens),
        output=count(output_tokens),
        cached_input=count(cached) if cached else None,
    )


def priced(model, input_tokens, output_tokens, cached=0):
    return cost_of(
        usage(model, input_tokens, output_tokens, cached),
        CATALOGUE[model],
        PRICES,
        CostBasis.PRE_CALL_ESTIMATE,
    )


# gpt-5.5 rows: standard (<= 270,000) 5.5 input / 0.55 cached / 33.0 output;
# long (>= 270,001) 11.0 / 1.1 / 49.5, USD per 1M tokens.
def expected(input_tokens, output_tokens, cached, rates):
    r_in, r_cached, r_out = (Decimal(x) for x in rates)
    return (
        Decimal(input_tokens - cached) * r_in
        + Decimal(cached) * r_cached
        + Decimal(output_tokens) * r_out
    ) / M


STANDARD = ("5.5", "0.55", "33.0")
LONG = ("11.0", "1.1", "49.5")
CASES = [
    # input tokens, tier, boundary caveat expected
    (270_000, STANDARD, False),
    (270_001, LONG, True),  # inside the uncertain extension: priced as long
    (276_480, LONG, True),  # the last token of the 1,024-reading's standard tier
    (276_481, LONG, False),  # long under both readings
]


@pytest.mark.parametrize("tokens, rates, caveat", CASES)
def test_the_tier_prices_input_cached_input_and_output_together(tokens, rates, caveat):
    cost = priced("gpt-5.5", tokens, 1_000, cached=100_000)
    assert cost.status == CostStatus.COMPUTED
    assert cost.amount.amount == expected(tokens, 1_000, 100_000, rates)
    assert cost.price_tier == ("standard" if rates == STANDARD else "long")
    assert (CostCaveat.CONTEXT_TIER_BOUNDARY_UNCERTAIN in cost.caveats) is caveat


def test_crossing_the_boundary_roughly_doubles_the_bill_by_construction():
    below = priced("gpt-5.5", 270_000, 1_000, cached=100_000).amount.amount
    above = priced("gpt-5.5", 270_001, 1_000, cached=100_000).amount.amount
    assert below == Decimal("1.023")
    assert above == Decimal("2.029511")
    assert 1.9 < above / below < 2.0


def test_output_is_priced_at_the_tier_chosen_by_input_not_by_its_own_size():
    small_output = priced("gpt-5.5", 300_000, 1, cached=0).amount.amount
    large_output = priced("gpt-5.5", 300_000, 5_000, cached=0).amount.amount
    assert large_output - small_output == Decimal(4_999) * Decimal("49.5") / M
    standard = priced("gpt-5.5", 100_000, 5_000, cached=0).amount.amount
    assert standard == expected(100_000, 5_000, 0, STANDARD)


def test_the_other_tiered_model_has_the_same_boundary_shape():
    at = priced("gpt-5.4", 270_000, 1_000)
    over = priced("gpt-5.4", 270_001, 1_000)
    assert at.price_tier == "standard" and over.price_tier == "long"
    assert at.amount.amount == expected(270_000, 1_000, 0, ("2.875", "0.2875", "17.25"))
    assert over.amount.amount == expected(
        270_001, 1_000, 0, ("5.75", "0.575", "25.875")
    )


def test_untiered_models_have_no_tier_and_no_boundary_caveat():
    cost = priced("gpt-5-nano", 400_000, 1_000)
    assert cost.price_tier is None
    assert CostCaveat.CONTEXT_TIER_BOUNDARY_UNCERTAIN not in cost.caveats


def test_today_the_tier_ignores_output_tokens_which_the_source_does_not_settle():
    """Input 269,000 + output 5,000 exceeds 270,000 in total, but is priced as the
    standard tier because only input selects the tier. If the provider's "context"
    includes output, this call would be billed at the long tier; that is open."""
    cost = priced("gpt-5.5", 269_000, 5_000)
    assert cost.price_tier == "standard"
