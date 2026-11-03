"""UI Stage 5 (owner requirement, UI-A10..A12, UI-A31): the address-bar mapping of
the router, the step indicator, the create-chatbot screen and the saved files.
No Streamlit, no network, synthetic text only; every file goes to ``tmp_path``."""

from __future__ import annotations

import json

import pytest
from test_demo_workspace import loader_for

from metis_auto.adapters.providers import FakeModelClient
from metis_auto.wiring.demo_nav import chat_controls, journey_steps
from metis_auto.wiring.demo_store import (
    BotFormError,
    DemoStore,
    validate_bot,
)
from metis_auto.wiring.demo_ui import load_presets
from metis_auto.wiring.demo_workspace import (
    DemoWorkspace,
    Journey,
    Screen,
    make_session_factory,
    synthetic_bots,
)
from metis_auto.wiring.ui_config import load_strings, translator

EN = translator(load_strings(), "en")
FA = translator(load_strings(), "fa")


def build(tmp_path, *, store=True) -> DemoWorkspace:
    factory = make_session_factory(
        settings_loader=loader_for(tmp_path),
        client_factory=lambda _l, _r: FakeModelClient(),
    )
    return DemoWorkspace(
        synthetic_bots(load_presets()),
        session_factory=factory,
        store=DemoStore(tmp_path / "demo") if store else None,
    )


@pytest.fixture
def ws(tmp_path):
    return build(tmp_path)


def walk_to_chat(ws: DemoWorkspace) -> str:
    ws.choose_journey(Journey.CHATBOT)
    key = ws.bot_key
    ws.continue_to_settings()
    ws.current()
    ws.start_chatting()
    return key


# --- state -> URL ---


def test_url_params_carry_only_identifiers_for_every_screen(ws):
    assert ws.url_params() == {"screen": "entry"}
    ws.choose_journey(Journey.CHATBOT)
    assert ws.url_params() == {"screen": "bots", "journey": "chatbot"}
    ws.open_create()
    assert ws.url_params() == {"screen": "create", "journey": "chatbot"}
    ws.go_back()
    key = ws.bot_key
    ws.continue_to_settings()
    assert ws.url_params() == {"screen": "settings", "journey": "chatbot", "bot": key}
    ws.start_chatting()
    assert ws.url_params()["screen"] == "chat"
    ws.go_entry()
    ws.choose_journey(Journey.DIRECT)
    assert ws.url_params() == {"screen": "chat", "journey": "direct"}


def test_no_message_text_ever_reaches_the_url(ws):
    ws.choose_journey(Journey.DIRECT)
    ws.ask("SYNTHETIC-SECRET-TEXT")
    assert "SYNTHETIC-SECRET-TEXT" not in json.dumps(ws.url_params())


# --- URL -> state: Back, Forward, refresh, stale and invalid URLs ---


def test_clicks_write_the_url_and_back_forward_follow_it(ws):
    written = [ws.sync_url({})]
    ws.choose_journey(Journey.CHATBOT)
    written.append(ws.sync_url(written[-1]))
    key = ws.bot_key
    ws.continue_to_settings()
    ws.current()  # the settings page builds the chat
    written.append(ws.sync_url(written[-1]))
    ws.start_chatting()
    written.append(ws.sync_url(written[-1]))
    assert [w["screen"] for w in written] == ["entry", "bots", "settings", "chat"]
    for back in (2, 1, 0):  # Back x3: the bar shows an earlier URL
        ws.sync_url(written[back])
        assert ws.url_params() == written[back]
    ws.sync_url(written[1])
    assert ws.screen == Screen.BOTS and ws.bot_key == key
    ws.sync_url(written[3])  # Forward to the chat: it exists in this session
    assert ws.screen == Screen.CHAT


def test_back_loses_nothing(ws):
    key = walk_to_chat(ws)
    ws.sync_url(ws.url_params())
    ws.ask("SYNTHETIC one")
    ws.current().set_cache(True)
    chat_url = ws.sync_url({})
    ws.sync_url({"screen": "entry"})  # Back to the start
    ws.choose_journey(Journey.CHATBOT)
    ws.select_bot(key)
    ws.sync_url(chat_url)
    chat = ws.current()
    assert ws.screen == Screen.CHAT
    assert [m["text"] for m in chat.messages][0] == "SYNTHETIC one"
    assert chat.switches().cache is True


def test_a_refresh_on_the_chat_falls_back_to_settings(tmp_path):
    first = build(tmp_path)
    key = walk_to_chat(first)
    url = first.sync_url({})
    fresh = build(tmp_path)  # a new session: no chat is loaded
    fresh.sync_url(url)
    assert (fresh.journey, fresh.screen, fresh.bot_key) == (
        Journey.CHATBOT,
        Screen.SETTINGS,
        key,
    )


def test_a_refresh_on_direct_chat_opens_it(tmp_path):
    fresh = build(tmp_path)
    fresh.sync_url({"screen": "chat", "journey": "direct"})
    assert (fresh.journey, fresh.screen) == (Journey.DIRECT, Screen.CHAT)


@pytest.mark.parametrize(
    "params, expected",
    [
        ({"screen": "chat", "journey": "chatbot", "bot": "no-such-bot"}, Screen.BOTS),
        ({"screen": "settings", "journey": "chatbot", "bot": "bot-999"}, Screen.BOTS),
        ({"screen": "settings", "journey": "chatbot"}, Screen.BOTS),
        ({"screen": "create", "journey": "chatbot"}, Screen.CREATE),
        ({"screen": "bots", "journey": "chatbot"}, Screen.BOTS),
        ({"screen": "bots", "journey": "direct"}, Screen.ENTRY),
        ({"screen": "settings", "journey": "direct"}, Screen.ENTRY),
        ({"screen": "chat"}, Screen.ENTRY),
        ({"screen": "nonsense", "journey": "chatbot"}, Screen.ENTRY),
        ({"screen": "chat", "journey": "nonsense"}, Screen.ENTRY),
        ({"screen": ["chat", "x"], "journey": ["direct"]}, Screen.CHAT),
        ({"screen": "x" * 5000}, Screen.ENTRY),
    ],
)
def test_invalid_and_stale_urls_fall_back_without_an_error(ws, params, expected):
    ws.sync_url(params)
    assert ws.screen == expected
    assert ws.url_params()["screen"] == expected.value  # the bar is corrected


def test_no_router_parameters_leave_the_state_alone(ws):
    walk_to_chat(ws)
    ws.sync_url({})
    ws.sync_url({"theme": "dark", "lang": "fa"})  # the Results page's links
    assert ws.screen == Screen.CHAT


def test_the_brand_link_goes_home_from_anywhere_and_keeps_the_chats(ws):
    key = walk_to_chat(ws)
    ws.ask("SYNTHETIC hello")
    ws.sync_url({})
    assert ws.sync_url({"screen": "entry"}) == {"screen": "entry"}
    assert ws.journey == Journey.NONE
    ws.choose_journey(Journey.CHATBOT)
    ws.select_bot(key)
    assert ws.current().messages[0]["text"] == "SYNTHETIC hello"


def test_a_url_for_a_real_bot_the_session_cannot_read_is_refused(tmp_path):
    ws = build(tmp_path)
    ws.sync_url({"screen": "settings", "journey": "chatbot", "bot": "bot-007"})
    assert ws.screen == Screen.BOTS  # not in the (absent) directory


# --- visible back-tracking ---


def test_step_indicator_marks_done_active_and_todo(ws):
    assert journey_steps(ws, EN) == ()
    ws.choose_journey(Journey.CHATBOT)
    steps = journey_steps(ws, EN)
    assert [s.label for s in steps] == ["Start", "Chatbot", "Settings", "Chat"]
    assert [s.state for s in steps] == ["done", "active", "todo", "todo"]
    assert [s.clickable for s in steps] == [True, False, False, False]
    ws.continue_to_settings()
    assert [s.state for s in journey_steps(ws, EN)] == [
        "done",
        "done",
        "active",
        "todo",
    ]
    ws.start_chatting()
    assert [s.state for s in journey_steps(ws, EN)][-1] == "active"


def test_create_screen_belongs_to_the_chatbot_step(ws):
    ws.choose_journey(Journey.CHATBOT)
    ws.open_create()
    assert [s.state for s in journey_steps(ws, EN)] == [
        "done",
        "active",
        "todo",
        "todo",
    ]


def test_step_controls_go_back_and_keep_the_conversation(ws):
    walk_to_chat(ws)
    ws.ask("SYNTHETIC kept")
    ws.go_step(Screen.SETTINGS)
    assert ws.screen == Screen.SETTINGS
    ws.go_step(Screen.BOTS)
    assert ws.screen == Screen.BOTS
    ws.go_step(Screen.SETTINGS)
    ws.start_chatting()
    assert ws.current().messages[0]["text"] == "SYNTHETIC kept"
    ws.go_step(Screen.ENTRY)
    assert ws.journey == Journey.NONE


def test_chat_controls_per_journey(ws):
    walk_to_chat(ws)
    assert [c.screen for c in chat_controls(ws, EN)] == [Screen.BOTS, Screen.SETTINGS]
    ws.go_entry()
    ws.choose_journey(Journey.DIRECT)
    assert [c.screen for c in chat_controls(ws, EN)] == [Screen.ENTRY]
    ws.go_step(Screen.ENTRY)
    assert ws.journey == Journey.NONE


def test_navigation_strings_exist_in_both_languages():
    for key in (
        "nav_steps_label nav_step_entry nav_step_bots nav_step_settings "
        "nav_step_chat ws_change_bot ws_change_settings ws_back_start "
        "ws_back_help create_title create_save create_cancel store_skipped "
        "bots_mine_title bots_yours ws_conversations_saved create_err_name "
        "create_err_empty create_err_write create_upload create_share"
    ).split():
        assert EN(key, n=1, **{}) and FA(key, n=1)


# --- create chatbot (UI-A10..A12) ---


def test_create_saves_a_file_lists_it_as_yours_and_goes_to_settings(tmp_path, ws):
    ws.choose_journey(Journey.CHATBOT)
    ws.open_create()
    ws.set_draft("name", "SYNTHETIC helper")
    ws.set_draft("instructions", "SYNTHETIC instructions")
    ws.set_draft_passage(0, "SYNTHETIC passage")
    ws.add_draft_passage()
    ws.set_draft_passage(1, "  ")
    assert ws.save_draft() is None
    assert ws.screen == Screen.SETTINGS and ws.bot_key.startswith("mine-")
    files = list((tmp_path / "demo" / "bots").glob("*.json"))
    assert len(files) == 1
    view = ws.bot_list(EN)
    assert [c.label for c in view.mine] == ["SYNTHETIC helper"]
    assert "yours" in view.mine[0].facts
    assert ws.draft.name == ""  # cleared after saving


def test_a_made_bot_reaches_the_request_and_survives_a_restart(tmp_path, ws):
    ws.choose_journey(Journey.CHATBOT)
    assert ws.create_bot("SYNTHETIC b", "SYNTHETIC rules", ["SYNTHETIC doc"]) is None
    chat = ws.current()
    chat.ask("hello")
    assert chat.session.instructions == "SYNTHETIC rules"
    assert chat.session.retrieved == ("SYNTHETIC doc",)
    again = build(tmp_path)
    assert [b.label for b in again.mine] == ["SYNTHETIC b"]
    again.sync_url({"screen": "settings", "journey": "chatbot", "bot": ws.bot_key})
    assert again.screen == Screen.SETTINGS  # a saved bot can be addressed


def test_the_draft_survives_leaving_the_create_screen(ws):
    ws.choose_journey(Journey.CHATBOT)
    ws.open_create()
    ws.set_draft("name", "SYNTHETIC half")
    ws.go_back()
    ws.open_create()
    assert ws.draft.name == "SYNTHETIC half"


@pytest.mark.parametrize(
    "name, instructions, passages, code",
    [
        ("", "x", [], "name"),
        ("n" * 61, "x", [], "name_long"),
        ("n", "", ["  "], "empty"),
        ("n", "x" * 8001, [], "long"),
        ("n", "x", ["p"] * 11, "many"),
    ],
)
def test_the_form_rules(ws, tmp_path, name, instructions, passages, code):
    with pytest.raises(BotFormError) as info:
        validate_bot(name, instructions, passages)
    assert info.value.code == code
    ws.choose_journey(Journey.CHATBOT)
    assert ws.create_bot(name, instructions, passages) == code
    assert not (tmp_path / "demo" / "bots").exists()
    assert EN(f"create_err_{code}") and FA(f"create_err_{code}")


def test_create_without_a_store_says_so(tmp_path):
    ws = build(tmp_path, store=False)
    ws.choose_journey(Journey.CHATBOT)
    assert ws.create_bot("n", "x", []) == "unavailable"
    assert ws.bot_details(EN).create_enabled is False


def test_an_unwritable_folder_is_reported_not_raised(tmp_path):
    blocker = tmp_path / "demo"
    blocker.write_text("a file where the folder should be", encoding="utf-8")
    ws = build(tmp_path)
    ws.choose_journey(Journey.CHATBOT)
    assert ws.create_bot("n", "x", []) == "write"


# --- conversation files (UI-A31, UI-R11) ---


def test_history_survives_a_restart_one_file_per_conversation(tmp_path):
    first = build(tmp_path)
    first.choose_journey(Journey.DIRECT)
    first.ask("SYNTHETIC q1")
    first.new_conversation()
    first.ask("SYNTHETIC q2")
    files = sorted((tmp_path / "demo" / "conversations").glob("*.json"))
    assert len(files) == 2
    second = build(tmp_path)  # the demo restarted
    second.choose_journey(Journey.DIRECT)
    chat = second.current()
    assert [c.number for c in chat.conversations] == [1, 2]
    assert chat.current_number == 2
    assert chat.messages[0]["text"] == "SYNTHETIC q2"
    chat.open_conversation(1)
    assert chat.messages[0]["text"] == "SYNTHETIC q1"
    assert [t.text for t in chat.session.history][0] == "SYNTHETIC q1"
    chat.ask("SYNTHETIC q3")  # the model still gets the restored history
    assert len(chat.session.history) == 4


def test_conversations_are_kept_per_bot_and_journey(tmp_path):
    first = build(tmp_path)
    keys = [b.key for b in first.bots[:2]]
    first.choose_journey(Journey.CHATBOT)
    for key in keys:
        first.select_bot(key)
        first.ask(f"SYNTHETIC for {key}")
    first.choose_journey(Journey.DIRECT)
    first.ask("SYNTHETIC direct")
    second = build(tmp_path)
    second.choose_journey(Journey.CHATBOT)
    for key in keys:
        second.select_bot(key)
        assert second.current().messages[0]["text"] == f"SYNTHETIC for {key}"
    second.choose_journey(Journey.DIRECT)
    assert second.current().messages[0]["text"] == "SYNTHETIC direct"


def test_corrupt_and_missing_files_are_skipped_with_a_note(tmp_path):
    first = build(tmp_path)
    first.choose_journey(Journey.DIRECT)
    first.ask("SYNTHETIC ok")
    folder = tmp_path / "demo" / "conversations"
    good = next(folder.glob("*.json"))
    (folder / good.name.replace("__1.json", "__2.json")).write_text("{not json")
    (folder / good.name.replace("__1.json", "__3.json")).write_text(
        json.dumps({"version": 1, "journey": "direct", "bot": None, "number": 3})
    )
    (folder / good.name.replace("__1.json", "__4.json")).write_text(
        json.dumps({"version": 99})
    )
    bots = tmp_path / "demo" / "bots"
    bots.mkdir()
    (bots / "mine-deadbeef.json").write_text("[]")
    second = build(tmp_path)
    assert second.skipped_files == 1  # the bad bot file
    second.choose_journey(Journey.DIRECT)
    chat = second.current()
    assert chat.messages[0]["text"] == "SYNTHETIC ok"
    note = second.take_store_note(EN)
    assert note and "4" in note
    assert second.take_store_note(EN) is None
    assert "SYNTHETIC" not in note


def test_a_reset_conversation_removes_its_file(tmp_path):
    ws = build(tmp_path)
    ws.choose_journey(Journey.DIRECT)
    ws.ask("SYNTHETIC gone")
    ws.current().reset_conversation()
    assert list((tmp_path / "demo" / "conversations").glob("*.json")) == []


def test_no_store_means_nothing_is_written(tmp_path):
    ws = build(tmp_path, store=False)
    ws.choose_journey(Journey.DIRECT)
    ws.ask("SYNTHETIC memory only")
    assert not (tmp_path / "demo").exists()
    assert ws.conversations_note(EN) == EN("ws_conversations_note")


# --- accessibility: text contrast in both themes (UI-K02) ---


def _luminance(colour: str) -> float:
    rgb = [int(colour.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_text_colours_reach_4_5_to_1_on_every_surface(mode):
    from metis_auto.wiring.ui_config import load_theme

    c = load_theme(mode).colours
    for text in ("text", "text_muted", "accent_text", "nav_text"):
        for surface in ("bg", "surface", "header", "elevated"):
            assert _contrast(c[text], c[surface]) >= 4.5, (mode, text, surface)
    assert _contrast(c["on_accent"], c["accent"]) >= 4.5, mode


def test_every_step_control_has_a_text_label_and_the_current_step_is_marked():
    from metis_auto.wiring.ui_style import step_html

    assert 'aria-current="step"' in step_html("Settings", "active")
    assert "aria-current" not in step_html("Chat", "todo")
    assert "<script" not in step_html("<script>", "todo")
