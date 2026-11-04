"""Within-message dedup and the bot-level cache in the live demo, offline
(ADR-XXXX (demo-sprint-winners)): the real configuration and pipeline with the
fake model client and the fake compressor. No network, no key, no spend;
config/local.toml and .env are not read. All text is SYNTHETIC."""

from decimal import Decimal
from pathlib import Path

import pytest

from metis_auto.adapters.providers import FakeModelClient
from metis_auto.contracts import DecompositionTerm, ServedBy
from metis_auto.contracts.events import ContextBuilt, ContextCompressed, ContextDeduped
from metis_auto.settings import load_settings
from metis_auto.wiring.chat import ChatSession, CompressionMode, RoutingMode

BOT = "[SYNTHETIC] You are a demo shop assistant."
D1 = "[SYNTHETIC] ارسال رایگان برای سفارش‌های بالای یک میلیون تومان است. " * 3
D2 = "[SYNTHETIC] Returns are accepted within 7 days of delivery. " * 3
D3 = "[SYNTHETIC] مهلت بازگشت 7 روز / return window 7 days. " * 3
DUPED = [D1, D2, D1, D3, D2, D1]
CLEAN = [D1, D2, D3]
Q = "[SYNTHETIC] سفارش من کی می‌رسد؟"
MODEL = "gpt-4o-mini"


class CountingFake(FakeModelClient):
    calls = 0
    last = None

    def invoke(self, invocation):
        CountingFake.calls += 1
        CountingFake.last = invocation
        return super().invoke(invocation)


@pytest.fixture
def loader(tmp_path):
    def load(overrides):
        return load_settings(
            overrides={
                **overrides,
                "paths.spend_ledger": str(tmp_path / "spend" / "ledger.jsonl"),
                "paths.recorded_dir": str(tmp_path / "recorded"),
            },
            runtime=None,
            dotenv=None,
            environ={},
        )

    return load


def session(loader, **kw) -> ChatSession:
    CountingFake.calls = 0
    kw.setdefault("settings_loader", loader)
    return ChatSession(
        live=False,
        instructions=BOT,
        client_factory=lambda _l, _r: CountingFake(),
        **kw,
    )


def payloads(chat, kind):
    return [e.payload for e in chat._sink.events if isinstance(e.payload, kind)]


def sent_parts():
    return [(p.role, p.component.value, p.text) for p in CountingFake.last.parts]


def retrieved_texts(parts):
    return [t for _, c, t in parts if c == "retrieved"]


def not_retrieved(parts):
    return [p for p in parts if p[1] != "retrieved"]


def test_dedup_is_off_by_default_and_changes_nothing(loader):
    plain = session(loader, retrieved=DUPED, model_id=MODEL)
    _, report = plain.ask(Q)
    base = sent_parts()
    assert plain.settings()["dedup"] == "off"
    config = plain.pipeline._config.context
    assert (config.strategy, config.dedup.enabled) == ("pass_through", False)
    assert report.dedup == {}

    def with_strategy(overrides):
        return loader(
            {**overrides, "pipeline.context.strategy": "within_message_dedup"}
        )

    inert = session(
        loader, retrieved=DUPED, model_id=MODEL, settings_loader=with_strategy
    )
    inert.ask(Q)
    assert sent_parts() == base  # strategy chosen, dedup.enabled still false
    assert not payloads(inert, ContextDeduped)
    assert len(retrieved_texts(base)) == len(DUPED)


def test_dedup_removes_exact_duplicates_keeps_first_and_order(loader):
    session(loader, retrieved=DUPED, model_id=MODEL).ask(Q)
    base = sent_parts()
    chat = session(loader, retrieved=DUPED, model_id=MODEL, dedup=True)
    assert chat.settings()["dedup"] == "on [DEMO]"
    _, report = chat.ask(Q)
    now = sent_parts()
    assert retrieved_texts(now) == CLEAN
    assert not_retrieved(now) == not_retrieved(base)  # instructions, history, message
    assert report.dedup["items_total"] == "6"
    assert report.dedup["items_removed"] == "3"
    rows = payloads(chat, ContextBuilt)[0].record.components
    row = next(r for r in rows if r.component.value == "retrieved")
    assert (row.action.value, row.items_total, row.items_kept) == ("deduplicated", 6, 3)


def test_the_event_and_span_are_content_free_and_overhead(loader):
    chat = session(loader, retrieved=DUPED, model_id=MODEL, dedup=True)
    chat.ask(Q)
    (event,) = payloads(chat, ContextDeduped)
    assert (event.items_total, event.items_removed) == (6, 3)
    assert event.chars_removed == 2 * len(D1) + len(D2)
    assert "SYNTHETIC" not in event.model_dump_json()
    spans = [e.span.value for e in chat._sink.events if e.span is not None]
    assert "context.dedup" in spans


def test_removed_tokens_reach_the_context_term_and_the_sum_holds(loader):
    _, base = session(loader, retrieved=DUPED, model_id=MODEL).ask(Q)
    chat = session(loader, retrieved=DUPED, model_id=MODEL, dedup=True)
    request = chat.request_for(Q)  # before the turn: the history is still empty
    _, report = chat.ask(Q)
    tokens = int(report.dedup["tokens_removed"].split()[0])
    sent = chat.last_trace.sent_request
    counted = chat.accounting.content_tokens
    delta = counted(request, MODEL).tokens - counted(sent, MODEL).tokens
    assert tokens > 0
    assert tokens == delta  # the difference in the request actually sent
    a = {t.term: t.amount.amount for t in report.parts.terms}
    T = DecompositionTerm
    saving = Decimal(report.dedup["saving"].split()[0])
    assert a[T.COMPRESSION_SAVING] > 0
    assert saving == a[T.COMPRESSION_SAVING].quantize(Decimal("0.000001"))
    base_context = {t.term: t.amount.amount for t in base.parts.terms}
    assert base_context[T.COMPRESSION_SAVING] == 0
    assert (
        a[T.PREMIUM_BASELINE]
        - a[T.ROUTING_SAVING]
        - a[T.COMPRESSION_SAVING]
        - a[T.CACHE_SAVING]
        - a[T.PROVIDER_CACHE_SAVING]
        + a[T.EXTRA_COST]
        == a[T.ACTUALLY_PAID]
    )
    assert "context term" in report.dedup["note"]


def test_no_duplicates_means_no_saving_and_an_identical_request(loader):
    session(loader, retrieved=CLEAN, model_id=MODEL).ask(Q)
    base = sent_parts()
    chat = session(loader, retrieved=CLEAN, model_id=MODEL, dedup=True)
    _, report = chat.ask(Q)
    assert sent_parts() == base
    assert report.dedup["items_removed"] == "0"
    assert report.dedup["tokens_removed"].startswith("0 ")


def test_dedup_runs_before_compression_when_both_are_on(loader):
    chat = session(
        loader,
        retrieved=DUPED,
        model_id=MODEL,
        dedup=True,
        compression=CompressionMode.FAKE,
    )
    _, report = chat.ask(Q)
    (deduped,) = payloads(chat, ContextDeduped)
    (compressed,) = payloads(chat, ContextCompressed)
    found = next(c for c in compressed.components if c.component.value == "retrieved")
    # compression saw the 3 items that were left, not the 6 that came in
    assert found.items_compressed + found.items_skipped == 3
    assert deduped.items_removed == 3
    order = [e.payload.event_type for e in chat._sink.events]
    assert order.index("context_deduped") < order.index("context_compressed")
    assert report.dedup["items_removed"] == "3"
    assert report.compression


def test_compression_alone_is_unchanged_by_the_dedup_code(loader):
    chat = session(
        loader, retrieved=DUPED, model_id=MODEL, compression=CompressionMode.FAKE
    )
    _, report = chat.ask(Q)
    (compressed,) = payloads(chat, ContextCompressed)
    found = next(c for c in compressed.components if c.component.value == "retrieved")
    assert found.items_compressed + found.items_skipped == 6
    assert not payloads(chat, ContextDeduped)
    assert report.dedup == {}


@pytest.mark.parametrize("layout", [None, "dataset_positions"])
@pytest.mark.parametrize("repeated", [False, True])
def test_compression_collisions_do_not_run_a_second_dedup(loader, layout, repeated):
    """Distinct source chunks can compress to the same text. Keep both outputs
    so the invocation still matches the measured sent request and trace."""
    from metis_auto.adapters.compressors import FakeCompressor
    from metis_auto.ports import CompressedText

    class CollidingCompressor(FakeCompressor):
        def compress(self, text, rate):
            return CompressedText("[SYNTHETIC] مشترک", len(text.split()), 2)

    first, second = D1 * 2, D2 * 2  # both exceed compression's min_chars
    documents = [first, second, first] if repeated else [first, second]
    chat = session(
        loader,
        retrieved=documents,
        model_id=MODEL,
        dedup=True,
        compression=CompressionMode.LLMLINGUA2,
        compressor_factory=lambda _l, _n: CollidingCompressor(),
        context_layout=layout,
    )
    chat.ask(Q)
    sent = chat.last_trace.sent_request
    measured_texts = [item.text for item in sent.retrieved.value.items]
    assert measured_texts == ["[SYNTHETIC] مشترک"] * 2
    assert retrieved_texts(sent_parts()) == measured_texts
    (deduped,) = payloads(chat, ContextDeduped)
    assert deduped.items_removed == int(repeated)
    (built,) = payloads(chat, ContextBuilt)
    row = next(c for c in built.record.components if c.component.value == "retrieved")
    assert row.items_total == len(documents)
    assert row.items_kept == 2


# --- bot-level exact cache with dedup ----------------------------------------


def test_the_cache_key_uses_the_context_as_received_before_dedup(loader):
    chat = session(loader, retrieved=DUPED, model_id=MODEL, dedup=True, bot_cache=True)
    first, _ = chat.ask(Q)
    assert first.metadata.served_by == ServedBy.MODEL
    calls = CountingFake.calls
    chat.new_user()
    chat.set_retrieved(DUPED)
    hit, report = chat.ask(Q)
    assert hit.metadata.served_by == ServedBy.CACHE  # the same original request
    assert CountingFake.calls == calls
    assert report.dedup == {}  # a hit builds no context, so no dedup ran
    assert chat.last_trace.dedup is None
    chat.new_user()
    chat.set_retrieved(CLEAN)  # differs from DUPED only by its duplicate chunks
    other, _ = chat.ask(Q)
    assert other.metadata.served_by == ServedBy.MODEL  # a miss, never a wrong hit
    assert CountingFake.calls == calls + 1


def test_a_cache_hit_never_anchors_a_session(loader):
    chat = session(
        loader,
        retrieved=DUPED,
        routing=RoutingMode.STICKY_V1,
        dedup=True,
        bot_cache=True,
    )
    chat.ask(Q)
    chat.new_user()
    chat.set_retrieved(DUPED)
    hit, report = chat.ask(Q)
    assert hit.metadata.served_by == ServedBy.CACHE
    assert "does not anchor" in report.routing["decision"]


def test_the_demo_has_no_retrieval_step():
    """The retrieved context is pasted into the retrieval-context box and
    carried on the request; nothing fetches it, so there is no retrieval fee
    or retrieval-result cache to wire."""
    import metis_auto.wiring.chat as chat_module
    import metis_auto.wiring.demo as demo_module

    for module in (chat_module, demo_module):
        text = Path(module.__file__).read_text("utf-8").lower()
        assert "retrieval_fee" not in text and "retrieval_cache" not in text
