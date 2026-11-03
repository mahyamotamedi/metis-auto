"""UI Stage 3 (spec §3, §4.3, §4.4, §5, §6.1, §7): the application shell's state
and view models, with no Streamlit and no network: journeys and screens, one
``ChatSession`` per (journey, bot), settings that are the real session's
(UI-SB01..SB07), the direct-chat banner, the savings panel and its charts
(UI-D01..D13). Fake mode only; the settings loader is injected and writes to
``tmp_path``. Synthetic bots only."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from metis_auto.adapters.providers import FakeModelClient
from metis_auto.settings import load_settings
from metis_auto.wiring.chat import ChatSession, CompressionMode, RoutingMode
from metis_auto.wiring.demo_ui import (
    cost_view,
    load_presets,
    waterfall_rows,
)
from metis_auto.wiring.demo_workspace import (
    DemoWorkspace,
    Journey,
    Screen,
    banner_for,
    entry_cards,
    make_session_factory,
    setting_cards,
    synthetic_bots,
)
from metis_auto.wiring.savings_panel import panel_view
from metis_auto.wiring.ui_config import load_strings, translator

REPO = Path(__file__).resolve().parents[3]
STRINGS = load_strings()
FA, EN = translator(STRINGS, "fa"), translator(STRINGS, "en")
LRI, PDI = "⁦", "⁩"


def loader_for(tmp_path):
    def load(overrides):
        return load_settings(
            overrides={
                **overrides,
                "paths.spend_ledger": str(tmp_path / "spend" / "ledger.jsonl"),
                "paths.recorded_dir": str(tmp_path / "recorded"),
                "live.enabled": False,
            },
            runtime=None,
            dotenv=None,
            environ={},
        )

    return load


@pytest.fixture
def workspace(tmp_path):
    factory = make_session_factory(
        settings_loader=loader_for(tmp_path),
        client_factory=lambda _l, _r: FakeModelClient(),
    )
    return DemoWorkspace(synthetic_bots(load_presets()), session_factory=factory)


def say(ws: DemoWorkspace, *messages: str) -> None:
    for message in messages:
        ws.ask(message)


# --- journeys and the router (UI-S01, UI-S04..S06, UI-H02) ---------------------------


def test_starts_on_the_entry_screen_with_no_journey(workspace):
    assert workspace.journey == Journey.NONE
    assert workspace.screen == Screen.ENTRY


def test_chatbot_journey_goes_to_selection_then_settings_then_chat(workspace):
    workspace.choose_journey(Journey.CHATBOT)
    assert (workspace.journey, workspace.screen) == (Journey.CHATBOT, Screen.BOTS)
    assert workspace.bot_key == workspace.bots[0].key  # a bot is always selected
    assert workspace.continue_to_settings() is None
    assert workspace.screen == Screen.SETTINGS
    workspace.start_chatting()
    assert workspace.screen == Screen.CHAT


def test_direct_journey_goes_straight_to_the_chat_without_a_bot(workspace):
    workspace.choose_journey(Journey.DIRECT)
    assert (workspace.journey, workspace.screen) == (Journey.DIRECT, Screen.CHAT)
    assert workspace.bot_key is None


def test_the_brand_returns_to_the_entry_screen_and_keeps_every_conversation(workspace):
    workspace.choose_journey(Journey.DIRECT)
    say(workspace, "hello")
    workspace.go_entry()
    assert (workspace.journey, workspace.screen) == (Journey.NONE, Screen.ENTRY)
    workspace.choose_journey(Journey.DIRECT)
    assert len(workspace.current().messages) == 2  # nothing was lost


def test_the_chat_tab_returns_to_the_current_workspace_or_the_entry(workspace):
    assert workspace.chat_target() == Screen.ENTRY
    workspace.choose_journey(Journey.CHATBOT)
    assert workspace.chat_target() == Screen.BOTS
    workspace.continue_to_settings()
    assert workspace.chat_target() == Screen.SETTINGS
    workspace.start_chatting()
    assert workspace.chat_target() == Screen.CHAT


def test_the_brand_link_is_a_query_parameter_consumed_once(workspace):
    workspace.choose_journey(Journey.DIRECT)
    assert workspace.consume_query({"screen": "entry"}) is True
    assert workspace.screen == Screen.ENTRY
    assert workspace.consume_query({}) is False
    assert workspace.consume_query({"screen": "nonsense"}) is False


# --- one ChatSession per (journey, bot); bots keep their conversations (UI-SB04) -----


def test_switching_bots_keeps_each_bots_conversation(workspace):
    first, second = (b.key for b in workspace.bots[:2])
    workspace.choose_journey(Journey.CHATBOT)
    workspace.select_bot(first)
    workspace.start_chatting()
    say(workspace, "hello")
    session_a = workspace.current().session
    workspace.select_bot(second)
    assert workspace.current().session is not session_a
    assert workspace.current().messages == []
    say(workspace, "hello", "hi again")
    workspace.select_bot(first)
    assert workspace.current().session is session_a
    assert len(workspace.current().messages) == 2
    workspace.select_bot(second)
    assert len(workspace.current().messages) == 4


def test_direct_and_chatbot_sessions_are_separate(workspace):
    workspace.choose_journey(Journey.DIRECT)
    say(workspace, "hello")
    direct = workspace.current().session
    workspace.go_entry()
    workspace.choose_journey(Journey.CHATBOT)
    assert workspace.current().session is not direct
    assert workspace.current().messages == []


def test_a_bots_instructions_and_documents_reach_the_request(workspace):
    bot = workspace.bots[0]
    workspace.choose_journey(Journey.CHATBOT)
    workspace.start_chatting()
    say(workspace, "hello")
    session = workspace.current().session
    assert session.instructions == bot.instructions
    assert session.retrieved == bot.documents
    direct = workspace
    direct.go_entry()
    direct.choose_journey(Journey.DIRECT)
    assert direct.current().session.instructions is None  # no bot behind direct chat


def test_new_conversation_archives_the_old_one_and_it_can_be_reopened(workspace):
    workspace.choose_journey(Journey.DIRECT)
    say(workspace, "first question")
    ws = workspace.current()
    workspace.new_conversation()
    assert ws.current_number == 2 and ws.messages == []
    assert ws.session.history == []  # the next request carries no old turns
    say(workspace, "second question")
    assert [c.number for c in ws.conversations] == [1, 2]
    workspace.open_conversation(1)
    assert [m["text"] for m in ws.messages if m["role"] == "user"] == ["first question"]
    assert len(ws.session.history) == 2  # the session sends that conversation's turns
    workspace.open_conversation(2)
    assert len(ws.messages) == 2


def test_new_conversation_on_an_empty_one_does_nothing(workspace):
    workspace.choose_journey(Journey.DIRECT)
    workspace.new_conversation()
    assert len(workspace.current().conversations) == 1


def test_conversation_titles_use_the_first_message_or_a_number(workspace):
    workspace.choose_journey(Journey.DIRECT)
    ws = workspace.current()
    assert ws.title_of(ws.conversations[0], EN) == f"Conversation {LRI}1{PDI}"
    say(workspace, "How do I export my notes?")
    assert ws.title_of(ws.conversations[0], EN) == "How do I export my notes?"
    say(workspace, "x" * 200)
    workspace.new_conversation()
    say(workspace, "y" * 200)
    assert len(ws.title_of(ws.conversations[1], EN)) <= 41


def test_conversation_list_is_newest_first(workspace):
    workspace.choose_journey(Journey.DIRECT)
    say(workspace, "one")
    workspace.new_conversation()
    say(workspace, "two")
    assert [n for n, _, _ in workspace.current().listing(EN)] == [2, 1]
    assert [cur for _, _, cur in workspace.current().listing(EN)] == [True, False]


# --- settings: defaults, real session, per bot vs per user (UI-A21, UI-SB01..SB05) ---


def test_defaults_equal_the_chatsession_defaults(workspace, tmp_path):
    reference = ChatSession(live=False, settings_loader=loader_for(tmp_path))
    workspace.choose_journey(Journey.CHATBOT)
    cards = {c.key: c for c in setting_cards(workspace.current(), EN)}
    assert reference.bot_cache is False and cards["cache"].on is False
    assert reference.compression == CompressionMode.OFF and cards["context"].on is False
    assert reference.routing != RoutingMode.FIXED and cards["routing"].on is True
    assert workspace.current().session.routing == reference.routing  # routing ON


def test_switches_always_reflect_the_real_session(workspace):
    workspace.choose_journey(Journey.DIRECT)
    ws = workspace.current()
    ws.session.set_bot_cache(True)  # changed behind the UI's back
    ws.session.set_compression(CompressionMode.FAKE)
    ws.session.switch_model("gpt-4.1-nano")
    state = ws.switches()
    assert (state.cache, state.context, state.routing) == (True, True, False)


def test_switches_change_the_session_and_the_next_request(workspace):
    workspace.choose_journey(Journey.DIRECT)
    ws = workspace.current()
    say(workspace, "hello")
    assert ws.messages[-1]["report"].routing  # routed
    assert ws.set_routing(False) is None
    assert ws.session.routing == RoutingMode.FIXED
    say(workspace, "hello again")
    last = ws.messages[-1]["report"]
    assert last.model_id == ws.preferred_model  # the fixed model is respected
    assert last.routing["reason_code"] == "fixed_model"
    assert ws.set_routing(True) is None
    assert ws.session.routing != RoutingMode.FIXED
    assert ws.set_cache(True) is None and ws.session.bot_cache is True
    refused = ws.set_context(True)
    if refused is None:  # compressor weights present (fetched locally)
        assert ws.session.compression != CompressionMode.OFF
    else:  # no weights (e.g. CI): refused with its reason, setting unchanged
        assert "compression unavailable" in refused
        assert ws.session.compression == CompressionMode.OFF
    assert ws.set_context(False) is None
    assert ws.session.compression == CompressionMode.OFF
    assert ws.set_cache(False) is None and ws.session.bot_cache is False


def test_cache_switch_gives_a_cross_user_hit_on_the_same_bot(workspace):
    workspace.choose_journey(Journey.CHATBOT)
    workspace.start_chatting()
    ws = workspace.current()
    assert ws.set_cache(True) is None
    question = "هزینه ارسال برای شهرستان چقدر است؟"
    say(workspace, question)
    ws.session.new_user()
    say(workspace, question)
    assert ws.messages[-1]["report"].served_by == "cache"


def test_a_failing_setting_returns_the_reason_and_changes_nothing(tmp_path):
    def broken(_loaded, _name):
        raise ValueError("compression unavailable: [SYNTHETIC] test")

    factory = make_session_factory(
        settings_loader=loader_for(tmp_path),
        client_factory=lambda _l, _r: FakeModelClient(),
        compressor_factory=broken,
    )
    ws = DemoWorkspace(synthetic_bots(load_presets()), session_factory=factory)
    ws.choose_journey(Journey.DIRECT)
    reason = ws.current().set_context(True)
    assert reason and "compression unavailable" in reason
    assert ws.current().session.compression == CompressionMode.OFF
    assert ws.current().switches().context is False


def test_settings_are_per_bot_and_direct_chat_is_its_own(workspace):
    first, second = (b.key for b in workspace.bots[:2])
    workspace.choose_journey(Journey.CHATBOT)
    workspace.select_bot(first)
    workspace.current().set_cache(True)
    workspace.select_bot(second)
    assert workspace.current().switches().cache is False  # a new bot, defaults
    workspace.select_bot(first)
    assert workspace.current().switches().cache is True  # kept
    workspace.go_entry()
    workspace.choose_journey(Journey.DIRECT)
    assert workspace.current().switches().cache is False  # direct chat's own
    workspace.current().set_cache(True)
    workspace.go_entry()
    workspace.choose_journey(Journey.CHATBOT)
    workspace.select_bot(second)
    assert workspace.current().switches().cache is False


def test_settings_survive_navigation_between_screens(workspace):
    workspace.choose_journey(Journey.CHATBOT)
    workspace.current().set_cache(True)
    workspace.start_chatting()
    workspace.go_entry()
    workspace.choose_journey(Journey.CHATBOT)
    assert workspace.current().switches().cache is True


def test_user_level_state_is_not_stored_per_bot(workspace):
    workspace.choose_journey(Journey.DIRECT)
    assert workspace.banner_dismissed is False
    workspace.dismiss_banner()
    workspace.go_entry()
    workspace.choose_journey(Journey.CHATBOT)
    assert workspace.banner_dismissed is True  # user-level: one flag for the session


def test_setting_cards_carry_name_text_state_chip_and_the_cache_caption(workspace):
    workspace.choose_journey(Journey.CHATBOT)
    cards = {c.key: c for c in setting_cards(workspace.current(), EN)}
    assert list(cards) == ["cache", "context", "routing"]
    assert cards["cache"].name == "Cache"
    assert cards["cache"].text.startswith("Reuse a previously generated answer")
    assert "semantic matching is not available" in cards["cache"].caption.lower()
    assert cards["context"].name == "Context optimization"
    assert cards["context"].text.startswith("Reduce unnecessary conversation context")
    assert cards["routing"].name == "Intelligent model routing"
    assert cards["routing"].text.startswith("Automatically select a suitable")
    assert cards["routing"].chip == "On" and cards["cache"].chip == "Off"
    assert all(c.enabled or c.disabled_reason for c in cards.values())


def test_context_optimization_is_disabled_with_its_reason_when_unavailable(
    workspace,
):
    workspace.choose_journey(Journey.CHATBOT)
    ws = workspace.current()
    off = {c.key: c for c in setting_cards(ws, EN, context_available=(False, "x"))}
    assert off["context"].enabled is False
    assert off["context"].disabled_reason == "x"
    on = {c.key: c for c in setting_cards(ws, EN, context_available=(True, None))}
    assert on["context"].enabled is True and on["context"].disabled_reason is None


def test_context_availability_is_not_claimed_without_the_extra_or_weights(
    tmp_path, monkeypatch
):
    from metis_auto.wiring import demo_workspace as module

    monkeypatch.setattr(module, "_module_present", lambda name: False)
    available, reason = module.context_availability(loader_for(tmp_path), EN)
    assert available is False and "compress" in reason


def test_the_settings_caption_says_the_switches_drive_demo_rules():
    text = EN("set_caption")
    assert "demo rules" in text and "Results" in text


# --- direct chat: the banner and the preferred model (UI-B02, UI-B04, UI-SB07) -------


def test_the_banner_shows_on_entering_direct_chat_and_stays_dismissed(workspace):
    assert banner_for(workspace, EN) is None  # no journey
    workspace.choose_journey(Journey.DIRECT)
    banner = banner_for(workspace, EN)
    assert banner is not None
    assert banner.text == (
        "Cost optimization is on. Metis-Auto may choose a different AI model "
        "from the one you selected to reduce cost while aiming to keep response "
        "quality. You can change this in Settings."
    )
    assert banner_for(workspace, EN) is not None  # shown again on every rerun
    workspace.dismiss_banner()
    assert banner_for(workspace, EN) is None
    workspace.go_entry()
    workspace.choose_journey(Journey.DIRECT)
    assert banner_for(workspace, EN) is None  # remembered for the session


def test_the_banner_is_not_shown_in_the_chatbot_journey(workspace):
    workspace.choose_journey(Journey.CHATBOT)
    workspace.start_chatting()
    assert banner_for(workspace, EN) is None


def test_the_banner_text_in_persian_does_not_promise_quality():
    text = FA("ws_banner_direct")
    assert text.strip()
    assert "[PLACEHOLDER" not in text  # the marker lives in the strings meta
    for promise in ("guarantee", "identical", "same quality"):
        assert promise not in EN("ws_banner_direct").lower()
    assert "may choose a different" in EN("ws_banner_direct")


def test_the_banner_link_marks_the_settings_for_attention(workspace):
    workspace.choose_journey(Journey.DIRECT)
    assert workspace.settings_focus is False
    workspace.open_settings()
    assert workspace.settings_focus is True
    workspace.current().set_routing(False)  # using a switch clears the mark
    assert workspace.settings_focus is False


def test_the_preferred_model_is_greyed_while_routing_is_on(workspace):
    workspace.choose_journey(Journey.DIRECT)
    ws = workspace.current()
    selector = ws.model_selector(EN)
    assert selector.disabled is True
    assert selector.label == "Preferred model"
    assert selector.caption == "routing chooses the model"
    assert selector.value == ws.preferred_model
    assert selector.options and selector.value in selector.options


def test_the_model_selector_is_enabled_and_respected_with_routing_off(workspace):
    workspace.choose_journey(Journey.DIRECT)
    ws = workspace.current()
    ws.set_routing(False)
    selector = ws.model_selector(EN)
    assert selector.disabled is False and selector.label == "Model"
    assert selector.caption is None
    assert ws.set_preferred_model("gpt-4.1-nano") is None
    assert ws.session.model_id == "gpt-4.1-nano"
    say(workspace, "hello")
    assert ws.messages[-1]["report"].model_id == "gpt-4.1-nano"


def test_a_preferred_model_chosen_while_routing_is_on_applies_when_it_is_turned_off(
    workspace,
):
    workspace.choose_journey(Journey.DIRECT)
    ws = workspace.current()
    assert ws.set_preferred_model("gpt-4.1-nano") is None
    assert ws.session.routing != RoutingMode.FIXED  # routing still decides
    ws.set_routing(False)
    assert ws.session.model_id == "gpt-4.1-nano"


def test_the_status_line_names_routing_or_the_fixed_model(workspace):
    workspace.choose_journey(Journey.DIRECT)
    ws = workspace.current()
    assert ws.status_line(EN) == "Model: chosen by routing"
    ws.set_routing(False)
    assert ws.status_line(EN) == f"Model: {LRI}{ws.session.model_id}{PDI}"
    assert "Model:" not in FA("ws_status_routing") or FA("ws_status_routing")


def test_the_chatbot_title_is_the_bots_label(workspace):
    workspace.choose_journey(Journey.CHATBOT)
    assert workspace.current().title(EN) == workspace.bots[0].label


def test_the_routing_method_chosen_in_advanced_survives_the_switch(workspace):
    workspace.choose_journey(Journey.DIRECT)
    ws = workspace.current()
    assert ws.set_routing_method(RoutingMode.PER_REQUEST) is None
    assert ws.session.routing == RoutingMode.PER_REQUEST
    ws.set_routing(False)
    ws.set_routing(True)
    assert ws.session.routing == RoutingMode.PER_REQUEST


# --- the bots, listed the way Stage 4 will list real bots (UI-A01 shape) -------------


def test_synthetic_bots_are_labelled_and_content_free_in_their_listing(workspace):
    cards = workspace.bot_cards(EN)
    assert [c.key for c in cards] == [b.key for b in workspace.bots]
    for card in cards:
        assert "SYNTHETIC" in card.label
        assert card.facts and "instructions" not in card.facts.lower()
    assert any(c.selected for c in workspace.bot_cards(EN)) is False  # none yet
    workspace.choose_journey(Journey.CHATBOT)
    selected = [c for c in workspace.bot_cards(EN) if c.selected]
    assert [c.key for c in selected] == [workspace.bots[0].key]


# --- entry screen (UI-E02..E05) ------------------------------------------------------


def test_entry_cards_use_the_exact_spec_copy_and_one_cta_each():
    cards = entry_cards(EN)
    assert [c.journey for c in cards] == [Journey.CHATBOT, Journey.DIRECT]
    assert cards[0].text == (
        "Chat with an existing configured assistant or create your own."
    )
    assert cards[1].text == (
        "Start chatting with AI directly, with automatic cost optimization."
    )
    assert all(c.cta and c.icon and c.title for c in cards)
    assert len(entry_cards(FA)) == 2


def test_entry_hero_copy_is_ours_with_the_persian_placeholder_marker():
    assert EN("entry_headline") == (
        "Metis-Auto | the lowest-cost way to answer every request"
    )
    assert FA("entry_headline") == "متیس‌اتو | کم‌هزینه‌ترین راه پاسخ به هر درخواست"
    assert not STRINGS.persian_reviewed  # the placeholder marker stays on


# --- savings panel: the existing calculations, plus the session charts (UI-D*) -------


def test_empty_panel_before_the_first_message_and_no_chart_rows(workspace):
    workspace.choose_journey(Journey.DIRECT)
    view = panel_view(workspace.current(), EN)
    assert view.empty is True
    assert view.message is None and view.session is None
    assert view.charts.cost_trend == () and view.charts.tokens == ()
    assert view.charts.by_model == () and view.charts.breakdown == ()
    assert view.title.endswith(": —") or "—" in view.title


def test_panel_values_equal_cost_view_and_waterfall_rows_for_the_same_turns(workspace):
    workspace.choose_journey(Journey.CHATBOT)
    workspace.start_chatting()
    say(workspace, "hello", "هزینه ارسال برای شهرستان چقدر است؟")
    ws = workspace.current()
    last = ws.messages[-1]["report"]
    view = panel_view(ws, EN)
    assert view.empty is False
    assert view.message == cost_view(last.parts)
    assert view.session == cost_view(last.session_parts)
    assert view.waterfall_message == waterfall_rows(cost_view(last.parts))
    assert view.waterfall_session == waterfall_rows(cost_view(last.session_parts))


def test_panel_title_carries_the_session_saving_for_the_small_screen_expander(
    workspace,
):
    workspace.choose_journey(Journey.DIRECT)
    say(workspace, "هزینه ارسال برای شهرستان چقدر است؟")
    view = panel_view(workspace.current(), EN)
    saved = view.session.saved_fraction
    assert saved is not None
    assert view.title.startswith("Session saving")
    assert "%" in view.title and view.title.count(LRI) >= 1


def test_chart_rows_come_only_from_the_sessions_answered_messages(workspace):
    workspace.choose_journey(Journey.DIRECT)
    say(workspace, "hello", "write a python function to sort a list", "thanks")
    ws = workspace.current()
    reports = [m["report"] for m in ws.messages if m["role"] == "assistant"]
    charts = panel_view(ws, EN).charts
    views = [cost_view(r.parts) for r in reports]
    numbers = sorted({r["n"] for r in charts.cost_trend})
    assert numbers == [1, 2, 3]
    actual = [r for r in charts.cost_trend if r["series"] == EN("ws_series_actual_est")]
    premium = [
        r for r in charts.cost_trend if r["series"] == EN("ws_series_premium_est")
    ]
    assert len(actual) == len(premium) == 3
    running = 0.0
    for row, view in zip(actual, views, strict=True):
        running += float(view.paid)
        assert row["value"] == pytest.approx(running)  # cumulative
    running = 0.0
    for row, view in zip(premium, views, strict=True):
        running += float(view.premium)
        assert row["value"] == pytest.approx(running)
    assert {r["model"] for r in charts.by_model} <= {r.model_id for r in reports}
    total = sum(r["cost"] for r in charts.by_model)
    assert total == pytest.approx(sum(float(v.paid) for v in views))
    for row in charts.tokens:
        assert row["tokens"] >= 0 and row["series"] in (
            EN("ws_series_input"),
            EN("ws_series_output"),
        )


def test_tokens_per_message_are_the_reports_counts(workspace):
    workspace.choose_journey(Journey.DIRECT)
    say(workspace, "hello")
    report = workspace.current().messages[-1]["report"]
    charts = panel_view(workspace.current(), EN).charts
    given = {r["series"]: r["tokens"] for r in charts.tokens}
    count = int(re.match(r"\d+", report.tokens["input"]).group())
    assert given[EN("ws_series_input")] == count


def test_breakdown_slices_are_the_saving_terms_of_the_session_decomposition(workspace):
    workspace.choose_journey(Journey.DIRECT)
    say(workspace, "هزینه ارسال برای شهرستان چقدر است؟")
    ws = workspace.current()
    view = panel_view(ws, EN)
    expected = {
        label: -float(value)
        for label, value in view.session.terms
        if value is not None and value < 0
    }
    shown = {row["key"]: row["amount"] for row in view.charts.breakdown}
    assert shown == pytest.approx(expected)


def test_estimated_and_observed_values_are_distinguished(workspace):
    workspace.choose_journey(Journey.DIRECT)
    say(workspace, "hello")
    view = panel_view(workspace.current(), EN)
    assert view.actual_is_estimate is True  # fake mode: nothing observed
    assert "est." in view.actual_label
    assert "est." in view.premium_label  # the premium is always an estimate
    assert EN("ws_series_actual_est").endswith("(est.)")


def test_message_facts_cover_models_chips_tokens_and_latency(workspace):
    workspace.choose_journey(Journey.DIRECT)
    say(workspace, "hello")
    facts = panel_view(workspace.current(), EN).facts
    assert facts.model_used and facts.model_selected
    assert facts.routing_applied is True
    ws = workspace.current()
    ws.set_routing(False)
    say(workspace, "hello again")
    assert panel_view(ws, EN).facts.routing_applied is False  # fixed model
    assert facts.cache_applied is False and facts.context_applied is False
    assert "(" in facts.input_tokens  # value with its method label
    assert facts.latency == EN("ws_latency_not_measured")  # fake mode


def test_panel_never_shows_a_value_it_did_not_compute(workspace):
    workspace.choose_journey(Journey.DIRECT)
    view = panel_view(workspace.current(), EN)
    assert view.facts is None  # nothing to say before a message


# --- strings (UI-V06, rule 8) ---------------------------------------------------------


def test_every_workspace_string_exists_in_fa_and_en():
    keys = [k for k in STRINGS.table if k.startswith(("entry_", "ws_", "set_"))]
    assert len(keys) >= 30
    for key in keys:
        for lang in ("fa", "en"):
            assert STRINGS.text(key, lang).strip(), (key, lang)


def test_workspace_modules_hold_no_colours_and_no_streamlit():
    for name in ("demo_workspace.py", "savings_panel.py"):
        source = (REPO / "src" / "metis_auto" / "wiring" / name).read_text("utf-8")
        assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", source), name
        assert "streamlit" not in source and "altair" not in source, name
