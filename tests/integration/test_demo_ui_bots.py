"""UI Stage 4 under Streamlit's offline test runner: the chatbot selection screen
(UI-S02), the bot list with search, filters and paging, the details card, a
fake-mode conversation with a SYNTHETIC stand-in for a real bot, and the rule
that no raw bot id, instruction or chunk text appears anywhere in the page
output (UI-R05). No database, no browser, no network, no key."""

import html
import logging

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402
from test_demo_ui_app import PAGE, make_loader  # noqa: E402

from metis_auto.adapters.providers import FakeModelClient  # noqa: E402
from metis_auto.settings import load_settings  # noqa: E402
from metis_auto.wiring.ui_config import load_strings  # noqa: E402

EN = load_strings()
INSTRUCTION = "[SYNTHETIC] INSTR-MARKER-7f3a stand-in instructions"
CHUNK = "[SYNTHETIC] CHUNK-MARKER-1 stand-in passage"
RAW_ID = "RAW-BOT-ID-5d1e"
SECRETS = ("INSTR-MARKER", "CHUNK-MARKER", RAW_ID)


def _row(n, *, sessions=1, requests=1, instructions=INSTRUCTION, **extra):
    return {
        "bot_id": f"{RAW_ID}-{n}",
        "instructions": instructions,
        "provider_name": "openai_chat_completion",
        "provider_model": "gpt-4o-mini",
        "memory_enabled": False,
        "summarizer_mode": "IGNORE",
        "corpus_ids_state": "null",
        "rag_top_k": None,
        "sessions": sessions,
        "requests": requests,
        **extra,
    }


class Source:
    """SYNTHETIC stand-in for the database."""

    def __init__(self, rows):
        self._rows = rows

    def directory_rows(self):
        return [dict(r) for r in self._rows]

    def instructions(self, bot_id):
        return next(r["instructions"] for r in self._rows if r["bot_id"] == bot_id)

    def rag_texts(self, bot_id):
        return [CHUNK] if bot_id.endswith("-1") else []


ROWS = [
    _row(1, sessions=40, requests=400, corpus_ids_state="ok", rag_top_k=4),
    _row(2, sessions=20, requests=200, memory_enabled=True),
    _row(3, sessions=10, requests=100, instructions="Reply in plain English please"),
]


def broken():
    raise ConnectionError("could not connect to server")


def app(tmp_path, *, source=None, theme="dark", lang="en", loader=None) -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.query_params["theme"] = theme
    at.query_params["lang"] = lang
    at.session_state["_test_settings_loader"] = loader or make_loader(tmp_path)
    at.session_state["_test_client_factory"] = lambda _l, _r: FakeModelClient()
    at.session_state["_test_bot_source"] = source or (lambda: Source(ROWS))
    return at.run()


def selection(tmp_path, **kwargs) -> AppTest:
    at = app(tmp_path, **kwargs)
    return at.button(key="mx-cta-entry-chatbot").click().run()


def dump(at: AppTest) -> str:
    """Every rendered element of the page, labels, values, help, keys: one string."""
    parts: list[str] = []

    def walk(block):
        for child in block.children.values():
            parts.append(str(getattr(child, "proto", "")))
            parts.append(str(getattr(child, "key", "")))
            if hasattr(child, "children"):
                walk(child)

    walk(at.main)
    walk(at.sidebar)
    return html.unescape("\n".join(parts))


def labels(at: AppTest) -> list[str]:
    return [
        b.key[len("mx-bot-") :]
        for b in at.button
        if (b.key or "").startswith("mx-bot-")
    ]


# --- the selection screen (UI-S02) ----


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("lang", ["fa", "en"])
def test_selection_and_the_chat_render_in_every_theme_and_language(
    tmp_path, theme, lang
):
    at = selection(tmp_path, theme=theme, lang=lang)
    assert not at.exception
    assert at.title[0].value == EN.text("bots_title", lang)
    assert "bot-001" in labels(at)
    at = at.button(key="mx-bot-bot-001").click().run()
    assert not at.exception
    at = at.button(key="mx-cta-continue").click().run()  # S04
    assert not at.exception
    at = at.button(key="mx-cta-start").click().run()  # S05
    at = at.chat_input[0].set_value("a message of my own").run()
    assert not at.exception
    assert len(at.chat_message) == 2


def test_the_list_is_ranked_and_the_synthetic_samples_stay_at_the_top(tmp_path):
    at = selection(tmp_path)
    names = labels(at)
    synthetic = [n for n in names if not n.startswith("bot-")]
    real = [n for n in names if n.startswith("bot-")]
    assert names[: len(synthetic)] == synthetic and synthetic
    assert real == ["bot-001", "bot-002", "bot-003"]
    html = " ".join(h.value for h in at.sidebar.markdown) + dump(at)
    assert EN.text("ws_synthetic_samples", "en") in html


def test_selected_state_and_details_card(tmp_path):
    at = selection(tmp_path)
    at = at.button(key="mx-bot-bot-001").click().run()
    assert at.button(key="mx-bot-bot-001").proto.type == "primary"
    assert at.button(key="mx-bot-bot-002").proto.type == "secondary"
    text = dump(at)
    for needed in ("gpt-4o-mini", "bot-001", str(len(INSTRUCTION))):
        assert needed in text
    create = at.button(key="mx-create-bot")
    assert create.disabled
    assert EN.text("bots_create_next_stage", "en") in dump(at)
    assert not at.button(key="mx-cta-continue").disabled


def test_search_and_filters(tmp_path):
    at = selection(tmp_path)
    at.text_input(key="mx-bots-search").set_value("002").run()
    at = at.run()
    assert [n for n in labels(at) if n.startswith("bot-")] == ["bot-002"]
    at.text_input(key="mx-bots-search").set_value("").run()
    at = at.run()
    at.selectbox(key="mx-bots-rag").select("yes").run()
    at = at.run()
    assert [n for n in labels(at) if n.startswith("bot-")] == ["bot-001"]


def test_the_list_pages_fifty_at_a_time(tmp_path):
    many = [_row(n, sessions=1, requests=n) for n in range(1, 131)]
    at = selection(tmp_path, source=lambda: Source(many))
    assert len([n for n in labels(at) if n.startswith("bot-")]) == 50
    at = at.button(key="mx-bots-more").click().run()
    assert len([n for n in labels(at) if n.startswith("bot-")]) == 100


# --- no raw id, no content, anywhere (UI-R05) ----


def test_no_raw_id_or_content_on_the_selection_screen(tmp_path):
    at = selection(tmp_path)
    at = at.button(key="mx-bot-bot-001").click().run()
    for secret in SECRETS:
        assert secret not in dump(at)


def test_no_raw_id_or_content_in_a_conversation_with_a_real_bot(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    at = selection(tmp_path)
    at = at.button(key="mx-bot-bot-001").click().run()
    at = at.button(key="mx-cta-continue").click().run()
    for secret in SECRETS:
        assert secret not in dump(at)
    at = at.button(key="mx-cta-start").click().run()
    at = at.chat_input[0].set_value("first question").run()
    at = at.chat_input[0].set_value("second question").run()
    assert not at.exception
    assert len(at.chat_message) == 4
    for expander in at.expander:  # the per-message details sections too
        expander.run()
    page = dump(at)
    for secret in SECRETS:
        assert secret not in page
        assert secret not in caplog.text
    assert EN.text("ws_knowledge_logged", "en") in page


def test_a_bot_without_rag_says_instructions_only(tmp_path):
    at = selection(tmp_path)
    at = at.button(key="mx-bot-bot-003").click().run()
    at = at.button(key="mx-cta-continue").click().run()
    at = at.button(key="mx-cta-start").click().run()
    assert EN.text("ws_knowledge_none", "en") in dump(at)


# --- live with a real bot (UI-R06) ----


def _to_chat(at):
    at = at.button(key="mx-bot-bot-001").click().run()
    at = at.button(key="mx-cta-continue").click().run()
    return at.button(key="mx-cta-start").click().run()


def test_live_option_is_disabled_for_a_real_bot_with_the_reason(tmp_path):
    at = _to_chat(selection(tmp_path))
    assert at.radio(key="mode").disabled
    assert "real_data_approved" in dump(at)


def test_live_option_stays_enabled_when_all_three_are_present(tmp_path):
    def loader(overrides):
        return load_settings(
            overrides={
                **overrides,
                "paths.spend_ledger": str(tmp_path / "spend" / "ledger.jsonl"),
                "paths.recorded_dir": str(tmp_path / "recorded"),
                "live.enabled": True,
                "golden_answers.real_data_approved": True,
            },
            runtime=None,
            dotenv=None,
            environ={"METIS_API_KEY": "sk-SYNTHETIC-not-a-key"},
        )

    at = _to_chat(selection(tmp_path, loader=loader))
    assert not at.radio(key="mode").disabled


def test_a_synthetic_sample_keeps_the_live_option_as_before(tmp_path):
    at = selection(tmp_path)
    sample = next(n for n in labels(at) if not n.startswith("bot-"))
    at = at.button(key=f"mx-bot-{sample}").click().run()
    at = at.button(key="mx-cta-continue").click().run()
    at = at.button(key="mx-cta-start").click().run()
    assert not at.radio(key="mode").disabled


# --- the database is not running (UI-A03) ----


def test_database_down_shows_the_empty_state_and_the_samples_remain(tmp_path):
    at = selection(tmp_path, source=lambda: broken())
    assert not at.exception
    assert EN.text("bots_db_down", "en") in dump(at)
    assert [n for n in labels(at) if n.startswith("bot-")] == []
    sample = next(n for n in labels(at) if not n.startswith("bot-"))
    at = at.button(key=f"mx-bot-{sample}").click().run()
    at = at.button(key="mx-cta-continue").click().run()
    at = at.button(key="mx-cta-start").click().run()
    at = at.chat_input[0].set_value("hello").run()
    assert not at.exception and len(at.chat_message) == 2


def test_back_links(tmp_path):
    at = selection(tmp_path)
    at = at.button(key="mx-bot-bot-002").click().run()
    at = at.button(key="mx-cta-continue").click().run()
    assert at.button(key="set_back")
    at = at.button(key="set_back").click().run()
    assert at.button(key="mx-cta-continue")  # back on the selection screen
    at = at.button(key="bots_back").click().run()
    assert at.button(key="mx-cta-entry-chatbot")  # back on the entry screen
