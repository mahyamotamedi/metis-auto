"""Demo B view model (``wiring.demo_ui``) over the real configuration and the
fake model client: presets, text direction, live banner, cost and budget
views, details, friendly failures. Needs no Streamlit, no network, no key;
config/local.toml and .env are not read (runtime=None, dotenv=None)."""

from decimal import Decimal

import pytest

from metis_auto.adapters.providers import FakeModelClient
from metis_auto.settings import load_settings
from metis_auto.wiring.chat import ChatSession, TurnReport
from metis_auto.wiring.demo_ui import (
    PREMIUM_CAVEATS,
    budget_view,
    cost_view,
    detail_sections,
    friendly_failure,
    live_banner,
    live_check,
    load_presets,
    routing_kind,
    text_direction,
    waterfall_rows,
)

MARKER = "SYNTHETIC-CONTENT-MARKER-7f3a"


@pytest.fixture
def loader(tmp_path):
    def load(overrides, *, live_enabled=False, key=None):
        return load_settings(
            overrides={
                **overrides,
                "paths.spend_ledger": str(tmp_path / "spend" / "ledger.jsonl"),
                "paths.recorded_dir": str(tmp_path / "recorded"),
                "live.enabled": live_enabled,
            },
            runtime=None,
            dotenv=None,
            environ={"METIS_API_KEY": key} if key else {},
        )

    return load


def chat(loader, **kw) -> ChatSession:
    preset = load_presets()[0]
    return ChatSession(
        live=False,
        instructions=preset.instructions,
        retrieved=preset.documents,
        settings_loader=loader,
        client_factory=lambda _l, _r: FakeModelClient(),
        **kw,
    )


def test_presets_are_synthetic_long_and_complete():
    presets = load_presets()
    assert [p.key for p in presets] == ["fa_shop", "en_faq"]
    for p in presets:
        assert "[SYNTHETIC]" in p.instructions
        assert 2 <= len(p.documents) <= 3
        assert all("[SYNTHETIC]" in d and len(d) >= 200 for d in p.documents)
        assert len(p.instructions) + sum(map(len, p.documents)) > 4000
        assert p.suggested
    assert text_direction(presets[0].instructions) == "rtl"
    assert text_direction(presets[1].instructions) == "ltr"


def test_an_unmarked_preset_is_refused(tmp_path):
    bad = tmp_path / "p.toml"
    bad.write_text(
        '[presets.x]\ntitle = "t"\ndescription = "d"\ninstructions = "plain"\n'
        'documents = ["[SYNTHETIC] doc"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="SYNTHETIC"):
        load_presets(bad)


@pytest.mark.parametrize(
    ("text", "direction"),
    [
        ("سلام، سفارشم کی می‌رسه؟", "rtl"),
        ("Where is my order?", "ltr"),
        ("سلام، API من خطای 401 می‌دهد", "rtl"),  # mostly Persian, one English word
        ("My order سفارش is late, please help", "ltr"),  # mostly English
        ("کد زیر کار نمی‌کند:\n```python\ndef add(a, b):\n    return a + b\n```", "rtl"),
        ("12345 !?", "ltr"),
        ("", "ltr"),
    ],
)
def test_text_direction(text, direction):
    assert text_direction(text) == direction


def test_cost_view_follows_the_fixed_order_and_sums_exactly(loader):
    session = chat(loader)
    session.ask("سلام")
    _, report = session.ask("سفارشم کی می‌رسه؟")
    view = cost_view(report.parts)
    assert [label for label, _ in view.terms] == [
        "Premium estimate",
        "Routing",
        "Compression",
        "Cache",
        "Provider cache",
        "Extra cost",
        "Actually paid",
    ]
    values = dict(view.terms)
    middle = sum(v for label, v in view.terms[1:-1])
    assert values["Premium estimate"] + middle == values["Actually paid"]
    assert values["Routing"] < 0  # savings are shown negative
    assert 0 < view.saved_fraction < 1
    assert view.premium > view.paid

    session_view = cost_view(report.session_parts)
    assert session_view.messages == 2
    rows = waterfall_rows(session_view)
    assert rows[0]["kind"] == rows[-1]["kind"] == "total"
    assert rows[-1]["end"] == pytest.approx(float(session_view.paid))
    # each step starts where the previous one ended
    assert rows[1]["end"] == pytest.approx(rows[0]["end"])


def test_badges_name_each_routing_decision(loader):
    session = chat(loader)
    kinds = [
        routing_kind(session.ask(text)[1])
        for text in (
            "سلام",
            "سفارشم کی می‌رسه؟",
            "هزینه ارسال برای شهرستان چقدر است؟",
            "مرسی",
            "write a python function to check an 8-digit order number",
        )
    ]
    assert kinds == ["greeting", "anchored", "stayed", "greeting", "re-routed"]


def test_cache_hit_shows_a_cache_saving_and_badge(loader):
    session = chat(loader, bot_cache=True)
    session.ask("هزینه ارسال چقدر است؟")
    session.new_user()
    _, hit = session.ask("هزینه ارسال چقدر است؟")
    assert hit.served_by == "cache"
    assert routing_kind(hit) == "cache"
    assert dict(cost_view(hit.parts).terms)["Cache"] < 0
    assert cost_view(hit.session_parts).cache_hits == 1


def test_details_are_content_free_and_complete(loader):
    session = chat(loader)
    _, report = session.ask(f"{MARKER} where is my order")
    sections = dict(detail_sections(report))
    assert list(sections) == [
        "Served",
        "Routing",
        "Features",
        "Cache lookups",
        "Tokens",
        "Cost",
        "Compression",
        "Overhead",
    ]
    assert dict(sections["Tokens"]).keys() >= {"input", "cached input (provider)"}
    assert dict(sections["Features"])["coding intent"] == "no"
    flat = repr(sections) + repr(report)
    assert MARKER not in flat
    assert "[SYNTHETIC]" not in flat  # neither the bot nor the answer text


def test_budget_view_reads_the_caps_and_warnings(loader, tmp_path):
    session = chat(loader)
    view = budget_view(session)
    assert view.lifetime_cap == Decimal("10") and view.run_cap == Decimal("1")
    assert view.warn_at == (0.5, 0.8) and view.crossed is None
    ledger = tmp_path / "spend" / "ledger.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        '{"amount": "8.5", "currency": "USD", "run_id": "earlier", '
        '"time": "2026-10-19T00:00:00+00:00", "v": 1}\n',
        encoding="utf-8",
    )
    view = budget_view(session)
    assert view.crossed == 0.8 and view.lifetime_fraction == pytest.approx(0.85)
    assert view.run_spent == 0


def test_live_check_lists_why_live_is_blocked(loader):
    allowed, reasons = live_check(lambda o: loader(o))
    assert not allowed
    assert any("live.enabled is false" in r for r in reasons)
    assert any("METIS_API_KEY is not set" in r for r in reasons)
    allowed, reasons = live_check(
        lambda o: loader(o, live_enabled=True, key="sk-SYNTHETIC-not-a-key")
    )
    assert allowed and reasons == ()


def test_live_banner_states():
    assert live_banner(live=True, allowed=True, reasons=()).state == "on"
    off = live_banner(live=False, allowed=False, reasons=("live.enabled is false",))
    assert off.state == "off" and "live.enabled is false" in off.detail
    stopped = live_banner(live=True, allowed=True, reasons=(), stopped="cost unknown")
    assert stopped.state == "stopped"
    assert "estimate" in PREMIUM_CAVEATS and "lower bound" in PREMIUM_CAVEATS


def _report(**kw) -> TurnReport:
    base = dict(
        status="error",
        served_by="none",
        model_id=None,
        provider_model=None,
        tokens={},
        cost="0.000000 USD",
        cost_caveats=(),
        premium_estimate="n/a",
        premium_caveats=(),
        decomposition=(),
        session_decomposition=(),
        overhead_ms=None,
        overhead_cost="0.000000 USD",
    )
    return TurnReport(**{**base, **kw})


def test_friendly_failures():
    budget = {
        "run_spent": "0.99",
        "run_cap": "1",
        "lifetime_spent": "2",
        "lifetime_cap": "10",
        "currency": "USD",
    }
    text = friendly_failure(_report(failure="budget_exhausted", budget=budget))
    assert "Nothing was charged" in text and "0.99 of 1 USD" in text
    assert "stopped" in friendly_failure(_report(live_stopped="cost not computed"))
    assert friendly_failure(_report(status="ok", served_by="model")) is None
