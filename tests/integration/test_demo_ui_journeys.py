"""UI Stage 3 under Streamlit's offline test runner: the entry screen, the
optimisation settings and both chat workspaces render in every theme and
language without errors (fake mode, synthetic bots), the journeys work from the
entry screen to the chat (spec §10), the settings are the real session's, the
direct-chat banner is shown once and stays dismissed, the preferred model is
greyed while routing is on, the savings panel shows the empty state and then the
real figures, and every number on the Results cards is LTR-isolated on every
tab (owner review of Stage 2b, point 7a). No browser, no network, no key."""

import re
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402
from test_demo_ui_app import (  # noqa: E402
    LRI,
    PAGE,
    PDI,
    REAL_LEVERS,
    RESULTS_PAGE,
    _app,
    _html,
    _messages,
    chatbot,
    direct,
    page,
    send,
)

from metis_auto.wiring.chat import RoutingMode  # noqa: E402
from metis_auto.wiring.ui_config import load_strings  # noqa: E402

EN = load_strings()
PERSIAN = re.compile(r"[؀-ۿ]")


def _entry(tmp_path, *, theme="dark", lang="en") -> AppTest:
    return _app(tmp_path, theme=theme, lang=lang)


# --- every screen, every theme and language (spec §10)


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("lang", ["fa", "en"])
def test_every_stage3_screen_renders_without_exceptions(tmp_path, theme, lang):
    at = _entry(tmp_path, theme=theme, lang=lang)  # S01
    assert not at.exception
    assert [b.key for b in at.button][:2] == [
        "mx-cta-entry-chatbot",
        "mx-cta-entry-direct",
    ]
    at = at.button(key="mx-cta-entry-chatbot").click().run()  # S02
    at = at.button(key="mx-cta-continue").click().run()  # S04
    assert not at.exception
    assert [t.key for t in at.toggle if t.key.startswith("sw_")] == [
        "sw_cache",
        "sw_context",
        "sw_routing",
    ]
    at = at.button(key="mx-cta-start").click().run()  # S05
    assert not at.exception
    at = send(at, "سلام")
    at = send(at, "هزینه ارسال برای شهرستان چقدر است؟")
    assert not at.exception
    assert len(at.chat_message) == 4
    at = _entry(tmp_path, theme=theme, lang=lang)
    at = at.button(key="mx-cta-entry-direct").click().run()  # S06
    at = send(at, "hello")
    assert not at.exception
    at = at.switch_page(RESULTS_PAGE).run()  # S07
    assert not at.exception


def test_entry_screen_has_two_cards_one_cta_each_and_no_extras(tmp_path):
    at = _entry(tmp_path, lang="en")
    html = " ".join(_html(at))
    assert EN.text("entry_headline", "en") in html
    assert EN.text("entry_chatbot_text", "en") in html
    assert EN.text("entry_direct_text", "en") in html
    assert len([b for b in at.button if (b.key or "").startswith("mx-cta")]) == 2
    low = html.lower()
    for absent in ("login", "sign up", "<img", "openai", "anthropic", "ticker"):
        assert absent not in low, absent


# --- journey A


def test_journey_a_goes_entry_settings_chat_with_the_bot_as_title(tmp_path):
    at = page(tmp_path)
    at = at.button(key="mx-cta-entry-chatbot").click().run()  # S02
    at = at.button(key="mx-cta-continue").click().run()  # S04
    ws = at.session_state["workspace"]
    assert ws.screen.value == "settings" and ws.journey.value == "chatbot"
    assert at.title[0].value == "Optimisation settings"
    assert any(EN.text("set_caption", "en") in c.value for c in at.caption)
    at = at.button(key="mx-cta-start").click().run()
    assert ws.screen.value == "chat"
    assert any(ws.bots[0].label in h for h in _html(at))  # the bot's label is the title
    assert any(b.key == f"mx-bot-{ws.bots[1].key}" for b in at.button)  # bot list


def test_settings_defaults_are_the_chatsessions_and_cards_explain_them(tmp_path):
    at = page(tmp_path)
    at = at.button(key="mx-cta-entry-chatbot").click().run()  # S02
    at = at.button(key="mx-cta-continue").click().run()  # S04
    assert at.toggle(key="sw_cache").value is False
    assert at.toggle(key="sw_context").value is False
    assert at.toggle(key="sw_routing").value is True  # routing on by default
    text = " ".join(_html(at))
    assert "Intelligent model routing" in text and ">On<" in text.replace(" ", "")
    assert "semantic matching is not available" in text


def test_switching_a_setting_on_the_settings_screen_changes_the_next_request(tmp_path):
    at = page(tmp_path)
    at = at.button(key="mx-cta-entry-chatbot").click().run()  # S02
    at = at.button(key="mx-cta-continue").click().run()  # S04
    at.toggle(key="sw_routing").set_value(False).run()
    chat = at.session_state["workspace"].current().session
    assert chat.routing == RoutingMode.FIXED
    at = at.button(key="mx-cta-start").click().run()
    assert at.toggle(key="sw_routing").value is False  # survives the screen change
    at = send(at, "hello")
    report = _messages(at)[-1]["report"]
    assert report.routing["reason_code"] == "fixed_model"


def test_switching_bots_keeps_each_bots_conversation(tmp_path):
    at = chatbot(tmp_path)
    ws = at.session_state["workspace"]
    first, second = ws.bots[0].key, ws.bots[1].key
    at = send(at, "سلام")
    at = at.button(key=f"mx-bot-{second}").click().run()
    assert _messages(at) == []
    at = send(at, "hello")
    at = at.button(key=f"mx-bot-{first}").click().run()
    assert [m["text"] for m in _messages(at) if m["role"] == "user"] == ["سلام"]
    assert len(at.chat_message) == 2  # only the open bot's messages are drawn


def test_new_conversation_and_the_list_keep_the_old_one(tmp_path):
    at = chatbot(tmp_path)
    at = send(at, "سلام")
    at = at.button(key="new_conversation").click().run()
    assert _messages(at) == []
    at = send(at, "hello there")
    keys = [b.key for b in at.button if (b.key or "").startswith("mx-conv")]
    assert keys == ["mx-conv-current-2", "mx-conv-1"]
    at = at.button(key="mx-conv-1").click().run()
    assert [m["text"] for m in _messages(at) if m["role"] == "user"] == ["سلام"]


# --- journey B


def test_direct_chat_has_no_bot_steps_and_shows_the_routing_status(tmp_path):
    at = direct(tmp_path)
    ws = at.session_state["workspace"]
    assert ws.journey.value == "direct" and ws.bot_key is None
    assert not [b for b in at.button if (b.key or "").startswith("mx-bot-")]
    html = " ".join(_html(at))
    assert "Model: chosen by routing" in html
    at = send(at, "hello")
    last = _messages(at)[-1]["report"]
    assert last.model_id and f"{LRI}{last.model_id}{PDI}" in " ".join(
        m.value for m in at.markdown
    )  # the model actually used, on the message


def test_banner_is_shown_dismissible_and_remembered(tmp_path):
    at = direct(tmp_path)
    assert any(
        "may choose a different AI model" in h for h in _html(at)
    )  # the banner text
    at = at.button(key="banner_settings").click().run()  # the link to the settings
    assert at.session_state["workspace"].settings_focus is True
    at = at.button(key="banner_dismiss").click().run()
    assert not any("may choose a different AI model" in h for h in _html(at))
    at = send(at, "hello")
    assert not any("may choose a different AI model" in h for h in _html(at))
    ws = at.session_state["workspace"]
    ws.go_entry()  # what the brand link does
    at = at.run()
    at = at.button(key="mx-cta-entry-direct").click().run()
    assert not any("may choose a different AI model" in h for h in _html(at))


def test_preferred_model_is_greyed_while_routing_is_on_and_respected_when_off(tmp_path):
    at = direct(tmp_path)
    select = at.selectbox(key="preferred_model")
    assert select.disabled is True
    assert any("routing chooses the model" in c.value for c in at.caption)
    at.toggle(key="sw_routing").set_value(False).run()
    select = at.selectbox(key="preferred_model")
    assert select.disabled is False
    select.set_value("gpt-4.1-nano").run()
    at = send(at, "hello")
    assert _messages(at)[-1]["report"].model_id == "gpt-4.1-nano"
    assert "Model: " + LRI + "gpt-4.1-nano" + PDI in " ".join(_html(at))


# --- the savings panel (UI-D*, UI-G*)


def test_panel_is_empty_before_the_first_message_and_real_after(tmp_path):
    at = direct(tmp_path)
    html = " ".join(_html(at))
    assert "Savings appear after the first answer." in html
    assert not at.metric  # no invented figures
    assert not at.get("vega_lite_chart")  # no sample chart (UI-G08)
    at = send(at, "How do I export my notes to PDF?")
    assert at.metric and at.metric[0].label == "Actually paid (est.)"
    labels = {m.label for m in at.metric}
    assert {"Premium estimate (est.)", "Saved"} <= labels
    assert len(at.get("vega_lite_chart")) >= 3  # waterfall, trend, tokens, ...
    html = " ".join(_html(at))
    assert "Cost trend (cumulative)" in html and "Tokens per message" in html
    assert "Cost by model used" in html and "Savings breakdown" in html
    assert "est. = estimated" in " ".join(c.value for c in at.caption)


def test_panel_sits_beside_the_chat_with_the_chat_at_least_60_percent(tmp_path):
    from metis_auto.wiring import ui_style  # the layout is a 3:2 column pair

    at = direct(tmp_path)
    columns = [c for c in at.columns if len(at.columns) >= 2]
    assert columns  # chat | panel
    source = (Path(PAGE).parent / "demo_pages" / "workspace.py").read_text("utf-8")
    assert "st.columns([3, 2]" in source  # 60 % : 40 %
    assert "min-width: 641px" in ui_style._WORKSPACE  # stacks below on small screens


# --- LTR isolation on every Results card, every tab (owner review 7a)


def _tab_names() -> list[str]:
    return [EN.text(k, "en") for k in ("step_cache", "step_context", "step_routing")]


@pytest.mark.parametrize("lang", ["en", "fa"])
def test_every_results_card_isolates_its_numbers_on_all_tabs(tmp_path, lang):
    at = _app(tmp_path, theme="dark", lang=lang, levers=REAL_LEVERS)
    at = at.switch_page(RESULTS_PAGE).run()
    assert not at.exception
    seen = 0
    for baseline in ("as_logged", "todays_models", "premium_gpt_5_5"):
        at.selectbox(key="res_baseline").set_value(baseline).run()
        for slice_option in at.selectbox(key=f"res_slice_{baseline}").options:
            at.selectbox(key=f"res_slice_{baseline}").set_value(slice_option).run()
            assert not at.exception, (baseline, slice_option)
            for metric in at.metric:
                value = metric.value
                assert value.startswith(LRI) and value.endswith(PDI), (
                    metric.label,
                    value,
                )
                inner = value[1:-1]
                if re.search(r"[0-9]", inner):  # a figure never carries words
                    assert not PERSIAN.search(inner), (metric.label, value)
                seen += 1
    assert seen > 50


def test_the_interval_card_keeps_its_note_outside_the_isolate(tmp_path):
    from decimal import Decimal

    from metis_auto.wiring.lever_view import dashboard, load_view

    view = load_view(REAL_LEVERS)
    board = dashboard(
        view,
        strings=EN,
        tenant_cap=Decimal("0.35"),
        lang="fa",
        slice_name="llm_only",
    )
    cards = [
        c for s in board.overview for c in s.cards if c.key == "interval" and c.note
    ]
    assert cards  # a slice other than the result's own totals shows the note
    for card in cards:
        assert card.note not in card.text and "—" not in card.text


def test_unranked_bars_use_the_muted_gray_token_in_both_themes():
    source = (Path(PAGE).parent / "demo_pages" / "results.py").read_text("utf-8")
    assert 'colours["text_muted"]' in source
    assert "alt.value(muted)" in source
    assert "opacity=alt.condition" not in source and "faded(" not in source
