"""UI Stage 5 under Streamlit's offline test runner: the address bar follows the
steps, the step indicator and the change controls go back without losing a
conversation, the create screen saves a local bot, and a restarted demo shows
the saved history. Fake mode, synthetic text, files in ``tmp_path``."""

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402
from test_demo_ui_app import (  # noqa: E402
    PAGE,
    NoBots,
    _css,
    make_loader,
    page,
    send,
)

from metis_auto.adapters.providers import FakeModelClient  # noqa: E402
from metis_auto.wiring.ui_config import load_strings  # noqa: E402

EN = load_strings()


def _page(tmp_path, lang="en") -> AppTest:
    """The entry screen with the demo's files in ``tmp_path/demo``."""
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["_test_bot_source"] = NoBots
    at.query_params["lang"] = lang
    at.session_state["_test_settings_loader"] = make_loader(tmp_path)
    at.session_state["_test_client_factory"] = lambda _l, _r: FakeModelClient()
    at.session_state["_test_demo_dir"] = str(tmp_path / "demo")
    return at.run()


def _screen(at: AppTest) -> str:
    return at.query_params["screen"]


def _to_settings(at: AppTest) -> AppTest:
    at = at.button(key="mx-cta-entry-chatbot").click().run()
    return at.button(key="mx-cta-continue").click().run()


def test_the_url_follows_every_step_and_back_follows_the_url(tmp_path):
    at = page(tmp_path)
    assert _screen(at) == "entry"
    at = at.button(key="mx-cta-entry-chatbot").click().run()
    assert _screen(at) == "bots" and at.query_params["journey"] == "chatbot"
    at = at.button(key="mx-cta-continue").click().run()
    assert _screen(at) == "settings" and "bot" in at.query_params
    at = at.button(key="mx-cta-start").click().run()
    assert _screen(at) == "chat"
    at = send(at, "SYNTHETIC hello")
    for back, title in (("settings", "Optimisation settings"), ("bots", None)):
        at.query_params["screen"] = back  # what Back does: the bar shows an old URL
        at = at.run()
        assert not at.exception
        assert _screen(at) == back
        assert (
            (at.title[0].value == title)
            if title
            else at.session_state["workspace"].screen.value == "bots"
        )
    at.query_params["screen"] = "entry"
    at = at.run()
    assert at.session_state["workspace"].journey.value == "none"
    # Forward to the chat: the conversation is still there
    at.query_params["screen"] = "chat"
    at.query_params["journey"] = "chatbot"
    at.query_params["bot"] = at.session_state["workspace"].bots[0].key
    at = at.run()
    assert [m.markdown[0].value for m in at.chat_message][0] == "SYNTHETIC hello"


def test_the_url_holds_identifiers_only(tmp_path):
    at = page(tmp_path)
    at = at.button(key="mx-cta-entry-direct").click().run()
    at = send(at, "SYNTHETIC-TEXT-NOT-IN-URL")
    assert "SYNTHETIC-TEXT-NOT-IN-URL" not in str(dict(at.query_params))
    assert set(at.query_params) <= {"theme", "lang", "screen", "journey", "bot"}


def test_a_stale_url_falls_back_with_no_traceback(tmp_path):
    for params in (
        {"screen": "chat", "journey": "chatbot", "bot": "nope"},
        {"screen": "settings", "journey": "chatbot", "bot": "../../etc"},
        {"screen": "<b>", "journey": "direct"},
    ):
        at = AppTest.from_file(PAGE, default_timeout=60)
        for k, v in params.items():
            at.query_params[k] = v
        at.query_params["lang"] = "en"
        at.session_state["_test_demo_dir"] = str(tmp_path / "d")
        at.run()
        assert not at.exception


@pytest.mark.parametrize("lang", ["fa", "en"])
def test_step_indicator_and_change_controls(tmp_path, lang):
    at = page(tmp_path, lang=lang)
    assert not [b for b in at.button if (b.key or "").startswith("mx-step-")]
    at = at.button(key="mx-cta-entry-chatbot").click().run()
    assert [b.key for b in at.button if (b.key or "").startswith("mx-step-")] == [
        "mx-step-entry"
    ]
    at = at.button(key="mx-cta-continue").click().run()
    at = at.button(key="mx-cta-start").click().run()
    keys = [b.key for b in at.button if (b.key or "").startswith("mx-step-")]
    assert keys == ["mx-step-entry", "mx-step-bots", "mx-step-settings"]
    at = send(at, "SYNTHETIC kept")
    at = at.button(key="mx-change-settings").click().run()
    assert _screen(at) == "settings"
    at = at.button(key="mx-step-bots").click().run()
    assert _screen(at) == "bots"
    at = at.button(key="mx-cta-continue").click().run()
    at = at.button(key="mx-cta-start").click().run()
    assert len(at.chat_message) == 2  # the conversation was not ended


def test_direct_chat_has_a_way_back_to_the_start(tmp_path):
    at = page(tmp_path)
    at = at.button(key="mx-cta-entry-direct").click().run()
    at = send(at, "SYNTHETIC kept")
    at = at.button(key="mx-change-start").click().run()
    assert _screen(at) == "entry"
    at = at.button(key="mx-cta-entry-direct").click().run()
    assert len(at.chat_message) == 2


def test_brand_style_hover_state_is_in_the_style_sheet(tmp_path):
    at = page(tmp_path)
    css = _css(at)
    assert "mx-brand-wrap" in css and "cursor: pointer" in css


def test_create_a_chatbot_end_to_end(tmp_path):
    at = _to_create(tmp_path)
    assert at.title[0].value == EN.text("create_title", "en")
    assert [b.key for b in at.button if (b.key or "").startswith("mx-unsupported")] == [
        "mx-unsupported-upload",
        "mx-unsupported-corpus",
        "mx-unsupported-share",
    ]
    assert all(
        b.disabled for b in at.button if (b.key or "").startswith("mx-unsupported")
    )
    at = at.button(key="mx-cta-save-bot").click().run()  # empty: an error, no file
    assert EN.text("create_err_name", "en") in [e.value for e in at.error]
    at.text_input(key="mx-draft-name").set_value("SYNTHETIC mine").run()
    at.text_area(key="mx-draft-instructions").set_value("SYNTHETIC rules").run()
    at.text_area(key="mx-draft-passage-0").set_value("SYNTHETIC passage").run()
    at = at.button(key="mx-cta-save-bot").click().run()
    assert not at.exception and _screen(at) == "settings"
    ws = at.session_state["workspace"]
    assert ws.bot_key.startswith("mine-")
    assert any(b.key == f"mx-bot-{ws.bot_key}" for b in at.button)  # listed
    assert list((tmp_path / "demo" / "bots").glob("*.json"))


def _to_create(tmp_path, **kwargs) -> AppTest:
    at = _page(tmp_path, **kwargs)
    at = at.button(key="mx-cta-entry-chatbot").click().run()
    return at.button(key="mx-create-bot").click().run()


def test_create_is_part_of_the_back_trail_and_keeps_the_draft(tmp_path):
    at = _to_create(tmp_path)
    assert _screen(at) == "create"
    at.text_input(key="mx-draft-name").set_value("SYNTHETIC draft").run()
    at.query_params["screen"] = "bots"  # Back
    at = at.run()
    assert at.title[0].value == EN.text("bots_title", "en")
    at.query_params["screen"] = "create"  # Forward
    at = at.run()
    assert at.text_input(key="mx-draft-name").value == "SYNTHETIC draft"


def test_history_and_made_bots_survive_a_restart(tmp_path):
    def start() -> AppTest:
        return _page(tmp_path)

    at = start()
    at = at.button(key="mx-cta-entry-direct").click().run()
    at = send(at, "SYNTHETIC remembered")
    again = start()  # a new session: the demo was restarted
    again = again.button(key="mx-cta-entry-direct").click().run()
    texts = " ".join(m.markdown[0].value for m in again.chat_message)
    assert "SYNTHETIC remembered" in texts


def test_unreadable_history_files_give_a_note_not_a_crash(tmp_path):
    folder = tmp_path / "demo" / "conversations"
    folder.mkdir(parents=True)
    (folder / "direct__direct__1.json").write_text("{broken", encoding="utf-8")
    at = _page(tmp_path)
    at = at.button(key="mx-cta-entry-direct").click().run()
    assert not at.exception
    assert any("1" in i.value and "skipped" in i.value for i in at.info)
