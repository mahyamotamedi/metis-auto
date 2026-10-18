"""Stage 7 accounting (pure): tiered prices, cached input and cache writes,
caveats, chat-template overhead, the premium-baseline estimate, and the
savings decomposition (brief §5–§6). Prices are the real configured Metis
prices where a test is about them; everything else is SYNTHETIC."""

from decimal import Decimal

import pytest
from fixtures.synthetic.contract_examples import SOURCE, chat_template

from metis_auto.contracts import (
    CatalogueEntry,
    ChatTemplate,
    Cost,
    CostBasis,
    CostCaveat,
    CostStatus,
    DecompositionTerm,
    Fidelity,
    Limit,
    Money,
    NotComputedReason,
    PriceEntry,
    PriceTable,
    SavingsDecomposition,
    TermValue,
    TokenCount,
    TokenType,
    TokenUsage,
)
from metis_auto.domain import accounting
from metis_auto.settings import load_settings

T = DecompositionTerm


@pytest.fixture(scope="module")
def ref():
    return load_settings(environ={}, dotenv=None, runtime=None).reference


def entry(ref, model_id: str) -> CatalogueEntry:
    return next(e for e in ref.catalogue.entries if e.model_id == model_id)


def n(tokens: int, fidelity: Fidelity = Fidelity.EXACT_LOCAL) -> TokenCount:
    return TokenCount(tokens=tokens, fidelity=fidelity, method="synthetic@1")


def usage(model: str, inp: int, out: int, **parts) -> TokenUsage:
    return TokenUsage(model_id=model, input=n(inp), output=n(out), **parts)


def amount(cost: Cost) -> Decimal:
    assert cost.status == CostStatus.COMPUTED, cost
    return cost.amount.amount


# --- prices ----------------------------------------------------------------------


def test_uncached_cached_and_output_prices(ref):
    target = entry(ref, "gpt-4o-mini")  # 0.165 / 0.0825 cached / 0.66 per 1M
    cost = accounting.cost_of(
        usage("gpt-4o-mini", 1_000_000, 1_000_000, cached_input=n(400_000)),
        target,
        ref.prices,
    )
    expected = (
        Decimal("0.6") * Decimal("0.165")
        + Decimal("0.4") * Decimal("0.0825")
        + Decimal("0.66")
    )
    assert amount(cost) == expected
    assert cost.price_tier is None and cost.caveats == ()


@pytest.mark.parametrize(
    ("input_tokens", "tier", "uncertain"),
    [
        (270_000, "standard", False),
        (270_001, "long", True),
        (276_480, "long", True),
        (276_481, "long", False),
    ],
)
def test_gpt_5_4_tier_is_chosen_by_input_and_prices_the_whole_call(
    ref, input_tokens, tier, uncertain
):
    target = entry(ref, "gpt-5.4")
    u = usage("gpt-5.4", input_tokens, 1_000, reasoning=n(0))
    cost = accounting.cost_of(u, target, ref.prices)
    prices = {"standard": ("2.875", "17.25"), "long": ("5.75", "25.875")}[tier]
    expected = (
        Decimal(input_tokens) * Decimal(prices[0]) + 1_000 * Decimal(prices[1])
    ) / 1_000_000
    assert amount(cost) == expected
    assert cost.price_tier == tier
    assert (CostCaveat.CONTEXT_TIER_BOUNDARY_UNCERTAIN in cost.caveats) is uncertain


def test_missing_price_for_a_used_token_type_is_not_computed():
    table = PriceTable(
        version="synthetic",
        entries=tuple(
            PriceEntry(
                price_ref="p",
                token_type=t,
                amount=Decimal("1"),
                per_tokens=1_000_000,
                currency="USD",
                evidence=SOURCE,
            )
            for t in (TokenType.INPUT, TokenType.OUTPUT)
        ),
    )
    target = synthetic_entry("p")
    ok = accounting.cost_of(usage("m", 10, 5), target, table)
    assert ok.status == CostStatus.COMPUTED
    cached = accounting.cost_of(usage("m", 10, 5, cached_input=n(4)), target, table)
    assert cached.reason == NotComputedReason.PRICE_UNKNOWN


def test_cache_writes_use_the_matching_variant():
    def price(t, a, ttl=None):
        return PriceEntry(
            price_ref="p",
            token_type=t,
            amount=Decimal(a),
            per_tokens=1_000_000,
            currency="USD",
            evidence=SOURCE,
            cache_ttl=ttl,
        )

    table = PriceTable(
        version="synthetic",
        entries=(
            price(TokenType.INPUT, "1"),
            price(TokenType.OUTPUT, "5"),
            price(TokenType.CACHE_WRITE, "1.25", "ttl-5m"),
            price(TokenType.CACHE_WRITE, "2", "ttl-1h"),
        ),
    )
    u = usage("m", 1_000_000, 0, cache_write=n(1_000_000), cache_write_ttl="ttl-1h")
    assert amount(accounting.cost_of(u, synthetic_entry("p"), table)) == 2
    unknown = u.model_copy(update={"cache_write_ttl": "ttl-24h"})
    cost = accounting.cost_of(unknown, synthetic_entry("p"), table)
    assert cost.reason == NotComputedReason.PRICE_UNKNOWN


def test_reasoning_caveat_only_when_hidden_reasoning_is_not_reported(ref):
    nano = entry(ref, "gpt-5-nano")
    counted = TokenUsage(
        model_id="gpt-5-nano",
        input=n(100),
        output=n(20, Fidelity.EXACT_LOCAL),
    )
    cost = accounting.cost_of(counted, nano, ref.prices)
    assert CostCaveat.REASONING_NOT_COUNTED in cost.caveats
    reported = TokenUsage(
        model_id="gpt-5-nano",
        input=n(100, Fidelity.PROVIDER_REPORTED),
        output=n(220, Fidelity.PROVIDER_REPORTED),
        reasoning=n(200, Fidelity.PROVIDER_REPORTED),
        cached_input=n(0, Fidelity.PROVIDER_REPORTED),
    )
    assert accounting.cost_of(reported, nano, ref.prices).caveats == ()
    mini = entry(ref, "gpt-4o-mini")  # not a reasoning model
    plain = counted.model_copy(update={"model_id": "gpt-4o-mini"})
    assert accounting.cost_of(plain, mini, ref.prices).caveats == ()


def test_unreported_cached_input_is_flagged(ref):
    u = TokenUsage(
        model_id="gpt-4o-mini",
        input=n(100, Fidelity.PROVIDER_REPORTED),
        output=n(10, Fidelity.PROVIDER_REPORTED),
    )
    cost = accounting.cost_of(u, entry(ref, "gpt-4o-mini"), ref.prices)
    assert cost.caveats == (CostCaveat.CACHED_INPUT_NOT_REPORTED,)


def test_provider_cache_discount_is_exact(ref):
    target = entry(ref, "deepseek-v4-flash")  # input 0.165, cached 0.0033
    u = usage("deepseek-v4-flash", 1_000_000, 0, cached_input=n(500_000))
    discount = accounting.provider_cache_discount(u, target, ref.prices)
    assert amount(discount) == Decimal("0.5") * (Decimal("0.165") - Decimal("0.0033"))
    none = accounting.provider_cache_discount(
        usage("deepseek-v4-flash", 10, 1), target, ref.prices
    )
    assert amount(none) == 0


def test_usage_parts_cannot_exceed_their_whole():
    with pytest.raises(ValueError, match="exceed input"):
        usage("m", 10, 1, cached_input=n(8), cache_write=n(3))
    with pytest.raises(ValueError, match="reasoning"):
        usage("m", 10, 1, reasoning=n(2))


def test_price_rows_validate_tier_bounds():
    base = {
        "price_ref": "p",
        "token_type": TokenType.INPUT,
        "per_tokens": 1,
        "currency": "USD",
    }
    with pytest.raises(ValueError, match="tier name"):
        PriceEntry(**base, max_input_tokens=10)
    with pytest.raises(ValueError, match="exceed the bound"):
        PriceEntry(
            **base, tier="s", max_input_tokens=10, max_input_tokens_uncertain_up_to=5
        )
    with pytest.raises(ValueError, match="cache_write"):
        PriceEntry(**base, cache_ttl="ttl-5m")


# --- chat-template overhead and the pre-call estimate ------------------------------


def test_template_overhead_counts_framing_per_role():
    template = chat_template()  # start 1, reply 2, user 1, assistant 2+1
    roles = ["instructions", "user", "assistant", "user"]
    overhead = accounting.template_overhead(template, roles)
    assert overhead.tokens == 1 + 2 + 0 + 1 + 3 + 1
    assert overhead.fidelity == Fidelity.APPROXIMATION
    assert accounting.template_overhead(None, roles) is None
    with pytest.raises(ValueError, match="lacks roles"):
        accounting.template_overhead(template, ["tool"])


def test_configured_templates_match_their_sources(ref):
    """OpenAI cookbook: 3 per message + 1 role token, 3 reply priming.
    DeepSeek V4 chat mode: BOS, <User>, <Assistant></think> … <EOS>."""
    templates: dict[str, ChatTemplate] = {
        t.ref: t.template for t in ref.tokenizers.tokenizers if t.template
    }
    one_turn = ["instructions", "user"]
    assert (
        accounting.template_overhead(templates["openai-o200k-base"], one_turn).tokens
        == 11
    )
    assert accounting.template_overhead(templates["deepseek-v4"], one_turn).tokens == 4


def test_pre_call_estimate_adds_overhead(ref):
    target = entry(ref, "gpt-4o-mini")
    plain = accounting.pre_call_estimate(target, n(1000), 100, ref.prices)
    framed = accounting.pre_call_estimate(target, n(1000), 100, ref.prices, n(11))
    assert framed.input_tokens.tokens == 1011
    assert amount(framed.cost) > amount(plain.cost)


# --- premium baseline (brief §5) ---------------------------------------------------


def test_premium_estimate_is_labelled_with_its_caveats(ref):
    premium = entry(ref, "gpt-5.4")
    estimate = accounting.baseline_estimate(
        "premium", premium, n(2_000), n(11, Fidelity.APPROXIMATION), n(300), ref.prices
    )
    assert estimate.baseline == "premium"
    assert estimate.cost.basis == CostBasis.BASELINE_ESTIMATE
    assert estimate.usage.input.tokens == 2_011
    assert estimate.usage.input.fidelity == Fidelity.APPROXIMATION  # worst part
    assert (
        amount(estimate.cost)
        == (Decimal(2_011) * Decimal("2.875") + 300 * Decimal("17.25")) / 1_000_000
    )
    assert estimate.cost.caveats == (
        CostCaveat.ANSWER_LENGTH_ASSUMED,
        CostCaveat.REASONING_NOT_COUNTED,
        CostCaveat.TEMPLATE_OVERHEAD_APPROXIMATED,
    )


# --- savings decomposition (brief §6) ----------------------------------------------


def usd(value: str, basis: CostBasis = CostBasis.ACTUAL) -> Cost:
    return Cost(
        status=CostStatus.COMPUTED,
        basis=basis,
        amount=Money(amount=Decimal(value), currency="USD"),
        price_table_version="synthetic",
    )


def values(d: SavingsDecomposition) -> dict[DecompositionTerm, Decimal | None]:
    return {t.term: t.amount.amount if t.amount else None for t in d.terms}


def test_miss_with_provider_cache_sums_exactly():
    d = accounting.decompose_message(
        premium=usd("0.0100"),
        chosen_full=usd("0.0010"),
        chosen_sent=usd("0.0008"),
        served_from_cache=False,
        provider_cache_discount=usd("0.0002"),
        actually_paid=usd("0.0007"),  # e.g. a retry or overhead on top
    )
    v = values(d)
    assert v == {
        T.PREMIUM_BASELINE: Decimal("0.0100"),
        T.ROUTING_SAVING: Decimal("0.0090"),
        T.COMPRESSION_SAVING: Decimal("0.0002"),
        T.CACHE_SAVING: Decimal("0"),
        T.PROVIDER_CACHE_SAVING: Decimal("0.0002"),
        T.EXTRA_COST: Decimal("0.0001"),
        T.ACTUALLY_PAID: Decimal("0.0007"),
    }


def test_cache_hit_saves_the_whole_routed_call():
    d = accounting.decompose_message(
        premium=usd("0.0100"),
        chosen_full=usd("0.0010"),
        chosen_sent=usd("0.0010"),
        served_from_cache=True,
        provider_cache_discount=usd("0.0005"),  # ignored on a hit
        actually_paid=usd("0"),
    )
    v = values(d)
    assert v[T.CACHE_SAVING] == Decimal("0.0010")
    assert v[T.PROVIDER_CACHE_SAVING] == 0 and v[T.EXTRA_COST] == 0
    assert d.cache_hits == 1


def test_unknown_inputs_make_dependent_terms_not_computed():
    unknown = Cost(
        status=CostStatus.NOT_COMPUTED,
        basis=CostBasis.BASELINE_ESTIMATE,
        reason=NotComputedReason.PRICE_UNKNOWN,
    )
    d = accounting.decompose_message(
        premium=unknown,
        chosen_full=usd("0.001"),
        chosen_sent=usd("0.001"),
        served_from_cache=False,
        provider_cache_discount=usd("0"),
        actually_paid=usd("0.001"),
    )
    status = {t.term: t.status for t in d.terms}
    for term in (T.PREMIUM_BASELINE, T.ROUTING_SAVING, T.EXTRA_COST):
        assert status[term] == CostStatus.NOT_COMPUTED
    assert d.term(T.COMPRESSION_SAVING).amount.amount == 0
    assert d.term(T.ACTUALLY_PAID).amount.amount == Decimal("0.001")


def test_session_total_is_the_sum_of_messages_and_still_exact():
    miss = accounting.decompose_message(
        premium=usd("0.0100"),
        chosen_full=usd("0.0010"),
        chosen_sent=usd("0.0008"),
        served_from_cache=False,
        provider_cache_discount=usd("0.0002"),
        actually_paid=usd("0.0007"),
    )
    hit = accounting.decompose_message(
        premium=usd("0.0050"),
        chosen_full=usd("0.0005"),
        chosen_sent=usd("0.0005"),
        served_from_cache=True,
        provider_cache_discount=None,
        actually_paid=usd("0"),
    )
    session = accounting.sum_decompositions([miss, hit])
    assert session.scope == "session" and session.messages == 2
    assert session.cache_hits == 1
    assert values(session)[T.PREMIUM_BASELINE] == Decimal("0.0150")
    assert values(session)[T.ACTUALLY_PAID] == Decimal("0.0007")


def test_a_decomposition_that_does_not_sum_is_rejected():
    amounts = ["1", "0.5", "0", "0", "0", "0", "0.4"]
    with pytest.raises(ValueError, match="does not sum"):
        SavingsDecomposition(
            scope="message",
            messages=1,
            cache_hits=0,
            terms=tuple(
                TermValue(
                    term=t,
                    status=CostStatus.COMPUTED,
                    amount=Money(amount=Decimal(a), currency="USD"),
                )
                for t, a in zip(DecompositionTerm, amounts, strict=True)
            ),
        )


def synthetic_entry(price_ref: str) -> CatalogueEntry:
    return CatalogueEntry(
        model_id="m",
        provider="synthetic",
        provider_model_name="m-synthetic",
        tier=0,
        equivalence_group="g",
        context_window=Limit(),
        max_output_tokens=Limit(),
        price_ref=price_ref,
        enabled=True,
    )
