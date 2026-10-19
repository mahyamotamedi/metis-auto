"""Demo A backend end to end over fakes (Demo milestone, ADR-0023): the chat
session on the real configuration and pipeline with the fake model client,
the fake compressor, and a SYNTHETIC sample-shaped file for the demo seed.
No network, no key, no spend; the developer's config/local.toml and .env are
not read (runtime=None, dotenv=None)."""

from decimal import Decimal

import pytest
from fixtures.synthetic import sample_shaped

from metis_auto.adapters.providers import FakeModelClient
from metis_auto.contracts import (
    CACHE_PRODUCER,
    Component,
    ComponentState,
    ContextAction,
    Role,
    ServedBy,
    Turn,
)
from metis_auto.contracts.events import ContextBuilt, ContextCompressed
from metis_auto.settings import load_settings
from metis_auto.wiring.chat import ChatSession, CompressionMode, RoutingMode
from metis_auto.wiring.from_settings import build_accounting_service

BOT = "[SYNTHETIC] You are a demo shop assistant. پاسخ کوتاه بده."
LONG_DOC = (
    "[SYNTHETIC] " + "ارسال رایگان برای سفارش‌های بالای یک میلیون تومان است. " * 20
)


class CountingFake(FakeModelClient):
    calls = 0

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
    return ChatSession(
        live=False,
        instructions=BOT,
        settings_loader=loader,
        client_factory=lambda _l, _r: CountingFake(),
        **kw,
    )


def test_sticky_v1_anchors_through_turn_producers(loader):
    chat = session(loader)
    assert chat.routing == RoutingMode.STICKY_V1
    _, greet = chat.ask("سلام")
    assert greet.routing["reason_code"] == "sticky.greeting"
    _, first = chat.ask("سفارشم کی می‌رسه؟")
    assert first.routing["reason_code"].startswith("sticky.first_substantive")
    _, stay = chat.ask("هزینه ارسال چقدر است؟")
    assert stay.routing["reason_code"] == "sticky.stay"
    assert stay.model_id == first.model_id
    _, code = chat.ask("def f(x):\n    return x * 2\nچرا کار نمی‌کند؟")
    assert code.routing["reason_code"].startswith("sticky.reroute.code_appeared.")
    _, thanks = chat.ask("مرسی")  # anchored: a greeting stays (Q-41)
    assert thanks.routing["reason_code"] == "sticky.greeting.stay"
    assert thanks.model_id == code.model_id

    producers = [t.producer for t in chat.history]
    assert all(p.state == ComponentState.ABSENT for p in producers[::2])  # users
    assert [p.value for p in producers[1::2]] == [
        greet.model_id,
        first.model_id,
        stay.model_id,
        code.model_id,
        thanks.model_id,
    ]


def test_a_coding_request_without_code_reroutes_to_the_stronger_tier(loader):
    # The gap found by the owner (2026-10-19): code=no, but it asks for code.
    chat = session(loader)
    _, first = chat.ask("where is my order")
    assert first.features["coding_intent"] == "no"
    _, ask = chat.ask("write a python function to add two numbers")
    assert ask.features["code"] == "no" and ask.features["coding_intent"] == "yes"
    assert ask.routing["reason_code"] == (
        "sticky.reroute.coding_intent_appeared.rule.coding_intent"
    )
    tiers = {e.model_id: e.tier for e in chat.loaded.reference.catalogue.entries}
    assert tiers[first.model_id] == 0 and tiers[ask.model_id] == 1
    _, follow = chat.ask("and make it handle negative numbers")
    assert follow.routing["reason_code"] == "sticky.stay"
    assert follow.model_id == ask.model_id


def test_escalation_raises_the_anchor(loader):
    chat = session(loader)
    _, first = chat.ask("سفارشم کی می‌رسه؟")
    chat.degrade_next()
    _, bad = chat.ask("و هزینه ارسال چقدر است؟")
    assert "ESCALATED" in bad.routing["decision"]
    assert bad.model_id != first.model_id
    _, after = chat.ask("آدرس فروشگاه کجاست؟")
    assert after.routing["reason_code"] == "sticky.stay.escalated"
    assert after.model_id == bad.model_id


def test_per_request_mode_and_fixed_mode(loader):
    chat = session(loader, routing=RoutingMode.PER_REQUEST)
    _, report = chat.ask("سلام")
    assert report.routing["reason_code"].startswith("per_request.rule.")
    chat.switch_model("gpt-4o-mini")
    _, fixed = chat.ask("سلام")
    assert fixed.routing["reason_code"] == "fixed_model"
    assert fixed.model_id == "gpt-4o-mini"


def test_bot_level_cache_is_shared_by_a_new_user_of_the_same_bot(loader):
    chat = session(loader)
    chat.ask("سفارشم کی می‌رسه؟")
    chat.new_user()
    _, session_scoped = chat.ask("سفارشم کی می‌رسه؟")
    assert session_scoped.served_by == "model"  # default scope: session

    chat.set_bot_cache(True)
    chat.new_user()
    chat.ask("ساعت کاری؟")
    chat.new_user()
    calls = CountingFake.calls
    _, shared = chat.ask("ساعت کاری؟")
    assert shared.served_by == ServedBy.CACHE.value
    assert CountingFake.calls == calls  # no model call
    assert any("full/global: hit" in row for row in shared.cache)
    assert Decimal(dict(shared.decomposition)["cache_saving"].split()[0]) > 0
    assert chat.history[-1].producer.value == CACHE_PRODUCER
    _, next_turn = chat.ask("آدرس فروشگاه کجاست؟")  # a cache hit never anchors
    assert next_turn.routing["reason_code"].startswith("sticky.first_substantive")


def test_demo_seed_serves_logged_answers_locally_without_a_model_call(loader, tmp_path):
    data = sample_shaped.write(tmp_path / "sample.json")
    chat = session(loader, seed=True, seed_path=data)
    assert chat.seeded  # SYNTHETIC questions from the sample-shaped file
    question = chat.seeded[0]
    calls = CountingFake.calls
    response, report = chat.ask(question)
    assert CountingFake.calls == calls
    assert report.served_by == "cache" and report.model_id == "demo-seed"
    assert any("DEMO seed hit" in row for row in report.cache)
    assert response.answer.startswith(sample_shaped.S)  # the logged answer

    chat.set_seed(False)
    chat.new_user()
    _, off = chat.ask(question)
    assert off.served_by == "model"  # the seed is looked up only when enabled


def test_seed_is_never_offered_to_later_turns(loader, tmp_path):
    data = sample_shaped.write(tmp_path / "sample.json")
    chat = session(loader, seed=True, seed_path=data)
    chat.ask("[SYNTHETIC] first question")
    _, later = chat.ask(chat.seeded[0])
    assert later.served_by == "model"
    assert any("not_first_turn" in row for row in later.cache)


def test_compression_counts_as_overhead_and_feeds_the_decomposition(loader):
    chat = session(loader, retrieved=[LONG_DOC], compression=CompressionMode.FAKE)
    response, report = chat.ask("ارسال رایگان است؟")
    assert report.compression["compressor"].startswith("fake_word_drop")
    assert float(report.compression["time_ms"]) >= 0
    saving = Decimal(dict(report.decomposition)["compression_saving"].split()[0])
    assert saving > 0
    sent = {p.component.value: p.text for p in CountingFake.last.parts}
    assert sent["instructions"] == BOT  # never compressed by default
    assert len(sent["retrieved"]) < len(LONG_DOC)

    events = [e.payload for e in chat._sink.events if e.request_id]
    compressed = [p for p in events if isinstance(p, ContextCompressed)]
    assert len(compressed) == 1 and compressed[0].components
    built = next(p for p in events if isinstance(p, ContextBuilt))
    actions = {r.component.value: r.action for r in built.record.components}
    assert actions["retrieved"] == ContextAction.COMPRESSED
    assert actions["instructions"] == ContextAction.KEPT


def test_thinking_toggle_switches_the_deepseek_template_and_request_option(loader):
    chat = session(loader)
    accounting = build_accounting_service(chat.loaded)
    deepseek = accounting.entry("deepseek-v4-flash")
    roles = ["instructions", "user"]
    on = chat.accounting._measurement.overhead_for(deepseek, roles)
    chat.set_deepseek_thinking(False)
    assert (
        chat.loaded.settings.model_options["deepseek-v4-flash"].thinking == "disabled"
    )
    off = chat.accounting._measurement.overhead_for(deepseek, roles)
    assert (on.tokens, off.tokens) == (30, 5)  # live check §1 and probe §4.3
    chat.set_deepseek_thinking(True)
    assert "deepseek-v4-flash" not in chat.loaded.settings.model_options


def test_a_failed_toggle_keeps_the_previous_settings(loader):
    chat = session(loader)

    def broken(_loaded, _name):
        raise ValueError("compressor unavailable (test)")

    chat._compressor_factory = broken
    with pytest.raises(ValueError):
        chat.set_compression(CompressionMode.LLMLINGUA2)
    assert chat.compression == CompressionMode.OFF
    _, report = chat.ask("سلام")
    assert report.status == "ok"


def test_turn_producer_contract_rules():
    with pytest.raises(ValueError):
        Turn(role=Role.USER, text="[SYNTHETIC] a", producer=Component.present("x"))
    assert Turn(role=Role.ASSISTANT, text="[SYNTHETIC] a").producer.state == (
        ComponentState.UNKNOWN
    )


def test_history_fingerprint_ignores_producers(loader):
    from metis_auto.adapters.system import SystemClock
    from metis_auto.adapters.tokenizers import ApproxCharsTokenizer
    from metis_auto.application.measurement import Fingerprinter, MeasurementService
    from metis_auto.contracts import Request

    service = MeasurementService(
        Fingerprinter(b"k" * 32), SystemClock(), ApproxCharsTokenizer()
    )

    def history_fp(producer):
        turns = (
            Turn(role=Role.USER, text="[SYNTHETIC] q", producer=Component.absent()),
            Turn(role=Role.ASSISTANT, text="[SYNTHETIC] a", producer=producer),
        )
        request = Request(message="[SYNTHETIC] m", history=Component.present(turns))
        return next(
            c.fingerprint
            for c in service.measure(request).components
            if c.component.value == "history"
        )

    assert history_fp(Component.present("gpt-4o-mini")) == history_fp(
        Component.unknown()
    )


def test_seed_without_the_sample_file_is_a_settings_error(loader, tmp_path):
    from metis_auto.settings import SettingsError

    chat = session(loader, seed_path=tmp_path / "missing.json")
    with pytest.raises(SettingsError, match="demo seed needs the sample file"):
        chat.set_seed(True)
    assert chat.seed is False
