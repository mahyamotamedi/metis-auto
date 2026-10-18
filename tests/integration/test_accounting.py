"""Accounting end to end (Stage 7): the real pipeline, priced SYNTHETIC
models, and the accounting service. A miss and an exact hit are decomposed
into the brief's savings terms, which must sum exactly; the premium estimate
never calls a model. Plus the accounting service on the real Metis catalogue.
"""

from decimal import Decimal

import pytest
from fixtures.synthetic import contract_examples as ex

from metis_auto.adapters.providers import FakeModelClient
from metis_auto.adapters.sinks import InMemoryEventSink
from metis_auto.adapters.stores import InMemoryCacheStore
from metis_auto.adapters.system import FakeClock, SequentialIdSource
from metis_auto.adapters.tokenizers import ApproxCharsTokenizer
from metis_auto.application.accounting import AccountingService
from metis_auto.application.measurement import Fingerprinter, MeasurementService
from metis_auto.contracts import (
    CostBasis,
    CostCaveat,
    CostStatus,
    DecompositionTerm,
    Fidelity,
    ModelCatalogue,
    PriceEntry,
    PriceTable,
    RunMode,
    ServedBy,
    TokenType,
)
from metis_auto.domain.accounting import sum_decompositions
from metis_auto.settings import load_settings
from metis_auto.wiring.from_settings import build_accounting_service
from metis_auto.wiring.pipeline import build_pipeline
from metis_auto.wiring.walking_skeleton import demo_requests, skeleton_config

T = DecompositionTerm
PREMIUM = "synthetic-large"
TEMPLATES = {"approx-chars-div-4": ex.chat_template()}


def priced_config():
    """The skeleton's synthetic catalogue, every model priced (SYNTHETIC)."""
    config = skeleton_config()
    entries = tuple(
        e.model_copy(update={"price_ref": f"price-{e.model_id}"})
        for e in config.catalogue.entries
    )
    rates = {"synthetic-small-a": ("1", "4"), "synthetic-small-b": ("1", "4")}
    prices = []
    for e in entries:
        inp, out = rates.get(e.model_id, ("10", "40"))
        for token_type, amount in ((TokenType.INPUT, inp), (TokenType.OUTPUT, out)):
            prices.append(
                PriceEntry(
                    price_ref=e.price_ref,
                    token_type=token_type,
                    amount=Decimal(amount),
                    per_tokens=1_000_000,
                    currency="USD",
                    evidence=ex.SOURCE,
                )
            )
    return config.model_copy(
        update={
            "catalogue": ModelCatalogue(
                version="cat-synthetic-priced", entries=entries
            ),
            "prices": PriceTable(version="prices-synthetic-priced", entries=prices),
        }
    )


def test_miss_and_hit_decompose_exactly():
    config = priced_config()
    pipeline = build_pipeline(
        config,
        model_client=FakeModelClient(),
        cache_store=InMemoryCacheStore(),
        sink=InMemoryEventSink(),
        fingerprint_key=ex.SYNTHETIC_TEST_KEY,
        run_id="run-accounting",
        run_mode=RunMode.SIMULATED,
        clock=FakeClock(ex.NOW, step_ms=0.5),
        ids=SequentialIdSource("run-accounting"),
        templates=TEMPLATES,
    )
    service = AccountingService(
        MeasurementService(
            Fingerprinter(ex.SYNTHETIC_TEST_KEY),
            FakeClock(ex.NOW),
            ApproxCharsTokenizer(),
            templates=TEMPLATES,
        ),
        config.catalogue,
        config.prices,
    )
    first, again, _ = demo_requests()
    miss = pipeline.handle(first)
    hit = pipeline.handle(again)
    assert miss.metadata.served_by == ServedBy.MODEL
    assert hit.metadata.served_by == ServedBy.CACHE

    # The pipeline's own counted usage includes the template overhead.
    usage = miss.metadata.answer_usage
    assert usage.template_overhead is not None and usage.template_overhead.tokens > 0
    assert usage.input.tokens == (
        service.content_tokens(first, usage.model_id).tokens
        + usage.template_overhead.tokens
    )

    d_miss = service.decompose(first, miss, premium_model_id=PREMIUM)
    d_hit = service.decompose(again, hit, premium_model_id=PREMIUM)
    for d in (d_miss, d_hit):
        assert all(t.status == CostStatus.COMPUTED for t in d.terms)
        assert CostCaveat.ANSWER_LENGTH_ASSUMED in d.baseline_caveats
    v = {t.term: t.amount.amount for t in d_miss.terms}
    # Same counting on both sides: nothing unexplained, nothing compressed.
    assert v[T.COMPRESSION_SAVING] == v[T.EXTRA_COST] == v[T.CACHE_SAVING] == 0
    assert v[T.ROUTING_SAVING] > 0  # premium is 10x the price
    assert v[T.ACTUALLY_PAID] == miss.metadata.total_cost.amount.amount
    h = {t.term: t.amount.amount for t in d_hit.terms}
    assert h[T.ACTUALLY_PAID] == 0  # served from cache: no model call
    assert h[T.CACHE_SAVING] == v[T.ACTUALLY_PAID]  # the call that was avoided

    session = sum_decompositions([d_miss, d_hit])
    assert (session.messages, session.cache_hits) == (2, 1)
    s = {t.term: t.amount.amount for t in session.terms}
    assert s[T.PREMIUM_BASELINE] == v[T.PREMIUM_BASELINE] + h[T.PREMIUM_BASELINE]


def test_accounting_service_on_the_metis_catalogue():
    loaded = load_settings(environ={}, dotenv=None, runtime=None)
    service = build_accounting_service(loaded)
    request = demo_requests()[0]
    answer = "[SYNTHETIC] ساعت کاری فروشگاه از ۹ تا ۱۷ است."
    for model in ("gpt-5-nano", "gpt-4.1-nano", "gpt-4o-mini", "deepseek-v4-flash"):
        result = service.account(request, model, answer)
        assert result.cost.status == CostStatus.COMPUTED
        assert result.usage.total.tokens == (
            result.usage.input.tokens + result.usage.output.tokens
        )
        # Counted, so the framing (an approximation) bounds the input fidelity.
        assert result.usage.input.fidelity == Fidelity.APPROXIMATION
    nano = service.account(request, "gpt-5-nano", answer)
    assert CostCaveat.REASONING_NOT_COUNTED in nano.cost.caveats
    grok = service.account(request, "grok-4-1-fast", answer)
    assert grok.usage.template_overhead is None  # not modelled for Grok
    assert grok.usage.output.fidelity == Fidelity.APPROXIMATION

    premium = service.premium_estimate(request, answer, "gpt-5.4")
    assert premium.cost.basis == CostBasis.BASELINE_ESTIMATE
    assert premium.cost.price_tier == "standard"
    assert premium.cost.caveats[0] == CostCaveat.ANSWER_LENGTH_ASSUMED
    cheap = service.account(request, "gpt-4o-mini", answer)
    assert premium.cost.amount.amount > 10 * cheap.cost.amount.amount


def test_unknown_model_is_an_error():
    service = build_accounting_service(
        load_settings(environ={}, dotenv=None, runtime=None)
    )
    with pytest.raises(KeyError):
        service.account(demo_requests()[0], "no-such-model", "[SYNTHETIC]")
