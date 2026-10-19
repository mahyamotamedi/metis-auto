"""Adapters conform to their ports and behave as documented (offline)."""

from decimal import Decimal

import pytest
from fixtures.synthetic import contract_examples as ex

from metis_auto.adapters.embedders import FakeEmbedder
from metis_auto.adapters.judges import FakeJudge
from metis_auto.adapters.providers import (
    FakeModelClient,
    FaultInjectingClient,
    ProxyModelClient,
    Quality,
    QualityInjectingClient,
)
from metis_auto.adapters.sinks import InMemoryEventSink, JsonLinesEventSink
from metis_auto.adapters.stores import InMemoryCacheStore, InMemoryVectorIndex
from metis_auto.adapters.system import (
    FakeClock,
    InMemorySpendLedger,
    SequentialIdSource,
    SystemClock,
    UuidIdSource,
)
from metis_auto.adapters.tokenizers import ApproxCharsTokenizer
from metis_auto.contracts import (
    AnswerSource,
    ErrorClass,
    Event,
    Fidelity,
    FinishReason,
    ModelError,
    ModelNoAnswer,
    ModelResponse,
)
from metis_auto.ports import (
    CacheStore,
    Clock,
    Embedder,
    EventSink,
    IdSource,
    Judge,
    ModelClient,
    SpendLedger,
    Tokenizer,
    VectorIndex,
)


@pytest.mark.parametrize(
    "adapter, port",
    [
        (FakeModelClient(), ModelClient),
        (ProxyModelClient(), ModelClient),
        (InMemoryCacheStore(), CacheStore),
        (InMemoryVectorIndex(), VectorIndex),
        (ApproxCharsTokenizer(), Tokenizer),
        (FakeEmbedder(), Embedder),
        (InMemoryEventSink(), EventSink),
        (FakeJudge(), Judge),
        (SystemClock(), Clock),
        (FakeClock(ex.NOW), Clock),
        (UuidIdSource(), IdSource),
        (SequentialIdSource(), IdSource),
        (InMemorySpendLedger(None), SpendLedger),
    ],
    ids=lambda x: type(x).__name__,
)
def test_adapters_satisfy_their_ports(adapter, port):
    assert isinstance(adapter, port)


def test_fake_client_is_deterministic_and_synthetic():
    a, b = FakeModelClient(), FakeModelClient()
    inv = ex.model_invocation()
    assert a.invoke(inv) == b.invoke(inv)
    assert ex.MARKER in a.invoke(inv).text


def test_injecting_decorators_follow_their_script():
    error = ModelError(
        error_class=ErrorClass.TIMEOUT, retryable=True, source=AnswerSource.FAKE
    )
    faulty = FaultInjectingClient(FakeModelClient(), [error, None])
    inv = ex.model_invocation()
    assert faulty.invoke(inv) == error
    assert isinstance(faulty.invoke(inv), ModelResponse)
    degraded = QualityInjectingClient(
        FakeModelClient(), [Quality.TRUNCATED, Quality.EMPTY]
    )
    assert degraded.invoke(inv).finish_reason == FinishReason.LENGTH
    assert degraded.invoke(inv).text == ""
    assert isinstance(ProxyModelClient().invoke(inv), ModelNoAnswer)


def test_approximation_is_labelled():
    count = ApproxCharsTokenizer().count("[SYNTHETIC] abcd")
    assert count.fidelity == Fidelity.APPROXIMATION and count.tokens == 4


def test_vector_index_partitions_by_key_and_embedder():
    index, embedder = InMemoryVectorIndex(), FakeEmbedder()
    v = embedder.embed("[SYNTHETIC] x")
    index.add("e1", ex.FP_MESSAGE, v)
    assert index.query(ex.FP_MESSAGE, v, 3)[0].entry_id == "e1"
    assert index.query(ex.FP_INSTRUCTIONS, v, 3) == ()
    other = FakeEmbedder(dimensions=4).embed("[SYNTHETIC] x")
    assert index.query(ex.FP_MESSAGE, other, 3) == ()


def test_ledger_tracks_the_cap():
    ledger = InMemorySpendLedger(ex.usd("1.00"))
    ledger.charge(ex.usd("0.25"))
    assert ledger.remaining().amount == Decimal("0.75")
    with pytest.raises(RuntimeError):
        InMemorySpendLedger(None).charge(ex.usd("0.01"))


def test_jsonl_sink_round_trips_events(tmp_path):
    sink = JsonLinesEventSink(tmp_path / "runs" / "events.jsonl")
    for event in ex.events():
        sink.emit(event)
    sink.close()
    lines = (
        (tmp_path / "runs" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert [Event.model_validate_json(x) for x in lines] == list(ex.events())


def test_clocks_and_ids():
    clock = FakeClock(ex.NOW)
    clock.sleep_ms(1500)
    assert (clock.now() - ex.NOW).total_seconds() == 1.5
    ids = SequentialIdSource("run-1")
    assert ids.new_id("req") == "run-1.req-000001"
