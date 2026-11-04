"""UI Stage 4 (real bots, UI-A01..A06, UI-A33): the content-free bot cards, the
list's ranking, search and filters, the request a real bot's chat sends
(instructions, history, target message, then the chunks, A-84), the live gate and
the unavailable-database state.

Everything here is a SYNTHETIC stand-in source with known marker strings: no
database, no key, no network, and no file that is git-ignored (CI has none).
"""

import dataclasses
import tempfile
from pathlib import Path

import pytest

from metis_auto.adapters.providers import FakeModelClient
from metis_auto.contracts import PartRole
from metis_auto.evaluation.golden_answers.request import build_request
from metis_auto.settings import SettingsError, load_settings
from metis_auto.wiring.demo_bots import (
    PAGE_SIZE,
    BotCard,
    BotDirectory,
    filter_cards,
    load_directory,
    real_data_reasons,
)
from metis_auto.wiring.demo_workspace import (
    DemoWorkspace,
    Screen,
    make_session_factory,
)
from metis_auto.wiring.ui_config import load_strings, translator

EN = translator(load_strings(), "en")
FA = translator(load_strings(), "fa")

# SYNTHETIC markers: content that must never be displayed or logged.
INSTRUCTION = "[SYNTHETIC] INSTR-MARKER-7f3a you are a helpful stand-in bot"
CHUNK_1 = "[SYNTHETIC] CHUNK-MARKER-1 first passage"
CHUNK_2 = "[SYNTHETIC] CHUNK-MARKER-2 second passage"
RAW_ID = "RAW-BOT-ID-5d1e"
FA_TEXT = "شما یک دستیار فارسی هستید که به پرسش‌های مشتریان پاسخ می‌دهد"


def row(
    n: int,
    *,
    sessions: int = 1,
    requests: int = 1,
    instructions: str | None = INSTRUCTION,
    provider: str = "openai_chat_completion",
    corpus: str = "null",
    top_k: int | None = None,
    memory: bool = False,
    summariser: str = "IGNORE",
    model: str = "gpt-4o-mini",
) -> dict:
    return {
        "bot_id": f"{RAW_ID}-{n}",
        "instructions": instructions,
        "provider_name": provider,
        "provider_model": model,
        "memory_enabled": memory,
        "summarizer_mode": summariser,
        "corpus_ids_state": corpus,
        "rag_top_k": top_k,
        "sessions": sessions,
        "requests": requests,
    }


class Source:
    """A SYNTHETIC stand-in for the database; records what is asked of it."""

    def __init__(self, rows, chunks=None):
        self._rows = rows
        self._chunks = chunks or {}
        self.asked: list[tuple[str, str]] = []

    def directory_rows(self):
        self.asked.append(("rows", ""))
        return [dict(r) for r in self._rows]

    def instructions(self, bot_id):
        self.asked.append(("instructions", bot_id))
        return next(r["instructions"] for r in self._rows if r["bot_id"] == bot_id)

    def rag_texts(self, bot_id):
        self.asked.append(("rag", bot_id))
        return list(self._chunks.get(bot_id, ()))


ROWS = [
    row(1, sessions=10, requests=100, corpus="ok", top_k=5, memory=True),
    row(2, sessions=30, requests=900, instructions=FA_TEXT, summariser="AI_SUMMARIZE"),
    row(3, sessions=5, requests=900, instructions="Reply in plain English please"),
    row(4, sessions=0, requests=0),  # unused: no session
    row(5, sessions=9, requests=9, provider="workflow"),  # not an LLM bot
    row(6, sessions=9, requests=9, instructions=None, corpus="empty"),  # neither
    row(7, sessions=2, requests=2, instructions=None, corpus="ok", top_k=3),
]


def directory(rows=ROWS, chunks=None) -> tuple[BotDirectory, Source]:
    source = Source(rows, chunks or {f"{RAW_ID}-1": [CHUNK_1, CHUNK_2]})
    return load_directory(lambda: source), source


# --- the cards (UI-A01, UI-A03) ------------------------------------------------------


def test_card_has_no_content_or_raw_id_field():
    names = {f.name for f in dataclasses.fields(BotCard)}
    for forbidden in ("bot_id", "id", "instructions", "text", "content", "chunks"):
        assert forbidden not in names
    assert {"label", "language", "rag", "memory", "summariser", "model"} <= names
    assert "instruction_chars" in names and "sessions" in names


def test_no_card_value_holds_a_marker_or_the_raw_id():
    cards = directory()[0].cards
    dumped = " ".join(repr(c) for c in cards)
    for secret in (RAW_ID, "INSTR-MARKER", "CHUNK-MARKER", FA_TEXT):
        assert secret not in dumped
    assert RAW_ID not in repr(directory()[0])
    assert "INSTR-MARKER" not in repr(directory()[0])


def test_only_used_llm_bots_with_instructions_or_rag_are_listed():
    d, _ = directory()
    assert len(d.cards) == 4  # 1, 2, 3 and 7
    assert d.excluded_workflow == 1
    assert d.available


def test_cards_are_ranked_by_traffic_with_stable_labels():
    d, _ = directory()
    assert [c.label for c in d.cards] == ["bot-001", "bot-002", "bot-003", "bot-004"]
    # bots 2 and 3 tie on requests (900): sessions decide, then the raw id (private)
    assert [c.sessions for c in d.cards[:2]] == [30, 5]
    assert d.cards[2].requests == 100
    shuffled, _ = directory(list(reversed(ROWS)))
    assert [(c.label, c.sessions) for c in shuffled.cards] == [
        (c.label, c.sessions) for c in d.cards
    ]


def test_tied_traffic_ranks_by_the_raw_id_not_by_input_order():
    tied = [row(9, sessions=3, requests=3), row(8, sessions=3, requests=3)]
    a, _ = directory(tied)
    b, _ = directory(list(reversed(tied)))
    assert [c.label for c in a.cards] == [c.label for c in b.cards]
    assert a.profile("bot-001").label == "bot-001"


def test_facts_of_a_card():
    cards = {c.label: c for c in directory()[0].cards}
    persian, english, with_rag, rag_only = (cards[f"bot-00{n}"] for n in (1, 2, 3, 4))
    assert (persian.language, english.language, rag_only.language) == (
        "fa",
        "en",
        "none",
    )
    assert persian.summariser and not with_rag.summariser
    assert with_rag.rag and with_rag.rag_top_k == 5 and not persian.rag
    assert with_rag.memory and not persian.memory
    assert persian.instruction_chars == len(FA_TEXT)
    assert rag_only.instruction_chars == 0 and rag_only.rag and rag_only.rag_top_k == 3
    assert with_rag.model == "gpt-4o-mini" and with_rag.sessions == 10


# --- search and filters (UI-A02) ------------------------------------------------------


def test_search_runs_over_the_label_only():
    cards = directory()[0].cards
    assert [c.label for c in filter_cards(cards, query="002")] == ["bot-002"]
    assert [c.label for c in filter_cards(cards, query="BOT-00")] == [
        c.label for c in cards
    ]
    assert filter_cards(cards, query="INSTR-MARKER") == ()  # never content
    assert filter_cards(cards, query="zzz") == ()


def test_filters_for_language_rag_memory_and_instructions():
    cards = directory()[0].cards
    names = lambda found: [c.label for c in found]  # noqa: E731
    assert names(filter_cards(cards, language="fa")) == ["bot-001"]
    assert names(filter_cards(cards, rag=True)) == [c.label for c in cards if c.rag]
    assert all(c.rag for c in filter_cards(cards, rag=True))
    assert not any(c.rag for c in filter_cards(cards, rag=False))
    assert all(c.memory for c in filter_cards(cards, memory=True))
    assert [c.label for c in filter_cards(cards, has_instructions=False)] == [
        c.label for c in cards if c.instruction_chars == 0
    ]
    both = filter_cards(cards, rag=True, memory=True)
    assert all(c.rag and c.memory for c in both)


def test_the_list_pages_by_fifty_with_more():
    many = [row(n, sessions=1, requests=n) for n in range(1, 131)]
    d, _ = directory(many)
    ws = workspace(d)
    view = ws.bot_list(EN)
    assert len(view.real) == PAGE_SIZE == 50
    assert view.total == 130 and view.has_more
    ws.show_more_bots()
    assert len(ws.bot_list(EN).real) == 100
    ws.show_more_bots()
    ws.show_more_bots()
    last = ws.bot_list(EN)
    assert len(last.real) == 130 and not last.has_more
    ws.set_bot_filter(query="bot-12")
    assert len(ws.bot_list(EN).real) <= PAGE_SIZE  # a new filter starts at one page
    assert ws.bot_list(EN).total == 10  # bot-120..bot-129


# --- the workspace: list, details, screens (UI-A01..A06) ----


def workspace(d, *, settings=None):
    from metis_auto.wiring.demo_ui import load_presets
    from metis_auto.wiring.demo_workspace import synthetic_bots

    settings = settings or loader(Path(tempfile.mkdtemp()))
    factory = make_session_factory(
        settings_loader=settings, client_factory=lambda _l, _r: FakeModelClient()
    )
    return DemoWorkspace(
        synthetic_bots(load_presets()),
        session_factory=factory,
        directory=d,
        real_data_check=lambda t: real_data_reasons(settings, t),
    )


def loader(tmp_path, *, approved=False, live=False, key=None):
    def load(overrides):
        return load_settings(
            overrides={
                **overrides,
                "paths.spend_ledger": str(tmp_path / "spend" / "ledger.jsonl"),
                "paths.recorded_dir": str(tmp_path / "recorded"),
                "live.enabled": live,
                "golden_answers.real_data_approved": approved,
            },
            runtime=None,
            dotenv=None,
            environ={"METIS_API_KEY": key} if key else {},
        )

    return load


def test_synthetic_samples_stay_at_the_top_of_the_list():
    ws = workspace(directory()[0])
    view = ws.bot_list(EN)
    assert view.synthetic and all(
        c.label.startswith("[SYNTHETIC]") for c in view.synthetic
    )
    assert [c.label for c in view.real][:1] == ["bot-001"]
    assert view.synthetic_title == EN("ws_synthetic_samples")


def test_a_card_line_reads_label_language_rag_and_chats():
    ws = workspace(directory()[0])
    line = {c.label: c.facts for c in ws.bot_list(EN).real}["bot-003"]
    assert "RAG" in line and "English" in line
    assert "10" in line  # sessions, LTR-isolated
    fa_line = {c.label: c.facts for c in ws.bot_list(FA).real}["bot-001"]
    assert FA("ws_lang_fa") in fa_line


def test_choosing_the_chatbot_journey_opens_the_selection_screen():
    ws = workspace(directory()[0])
    from metis_auto.wiring.demo_workspace import Journey

    ws.choose_journey(Journey.CHATBOT)
    assert ws.screen == Screen.BOTS
    assert ws.select_bot("bot-003") is None
    ws.continue_to_settings()
    assert ws.screen == Screen.SETTINGS and ws.bot_key == "bot-003"
    ws.go_back()
    assert ws.screen == Screen.BOTS
    ws.go_back()
    assert ws.screen == Screen.ENTRY


def test_details_card_holds_derived_facts_only():
    ws = workspace(directory()[0])
    ws.select_bot("bot-003")
    details = ws.bot_details(EN)
    assert details.title == "bot-003"
    text = " | ".join(f"{k}: {v}" for k, v in details.rows)
    for needed in ("gpt-4o-mini", "5", "10"):
        assert needed in text
    assert str(len(INSTRUCTION)) in text  # instruction length in characters
    assert "#3" in text  # traffic rank
    for secret in (RAW_ID, "INSTR-MARKER", "CHUNK-MARKER"):
        assert secret not in text
    assert details.create_enabled is False
    assert details.create_reason == EN("bots_create_unavailable")


def test_a_synthetic_bot_also_has_details():
    ws = workspace(directory()[0])
    key = ws.bots[0].key
    ws.select_bot(key)
    details = ws.bot_details(EN)
    assert details.title.startswith("[SYNTHETIC]")


def test_unknown_bot_is_refused():
    ws = workspace(directory()[0])
    with pytest.raises(ValueError):
        ws.select_bot("bot-999")


# --- the request a real bot sends (UI-A05, UI-A33, A-84) ----


class Recorder:
    """Wraps the fake client and keeps every invocation's parts (SYNTHETIC)."""

    def __init__(self):
        self.inner = FakeModelClient()
        self.parts: list[list] = []

    @property
    def source(self):
        return self.inner.source

    def invoke(self, invocation):
        self.parts.append(list(invocation.parts))
        return self.inner.invoke(invocation)


def chat_with(label, d, tmp_path):
    rec = Recorder()
    factory = make_session_factory(
        settings_loader=loader(tmp_path), client_factory=lambda _l, _r: rec
    )
    from metis_auto.wiring.demo_ui import load_presets
    from metis_auto.wiring.demo_workspace import Journey, synthetic_bots

    ws = DemoWorkspace(
        synthetic_bots(load_presets()), session_factory=factory, directory=d
    )
    ws.choose_journey(Journey.CHATBOT)
    ws.select_bot(label)
    ws.continue_to_settings()
    ws.start_chatting()
    return ws, rec


def test_request_matches_the_golden_answers_builder_in_a84_order(tmp_path):
    d, _ = directory()
    first = next(c for c in d.cards if c.rag and c.instruction_chars > 0)
    ws, rec = chat_with(first.label, d, tmp_path)
    ws.ask("first question")
    answer = ws.current().messages[-1]["text"]
    ws.ask("second question")
    sent = [(p.role, p.text) for p in rec.parts[-1]]

    rows = [
        {
            "position": 0,
            "kind": "bot_instruction",
            "role": "SYSTEM",
            "content": INSTRUCTION,
            "metadata": {},
        },
        {
            "position": 1,
            "kind": "earlier_message",
            "role": "USER",
            "content": "first question",
            "metadata": {},
        },
        {
            "position": 2,
            "kind": "earlier_message",
            "role": "AI",
            "content": answer,
            "metadata": {},
        },
        {
            "position": 3,
            "kind": "target_user_message",
            "role": "USER",
            "content": "second question",
            "metadata": {},
        },
        {
            "position": 4,
            "kind": "target_rag_chunk",
            "role": "SYSTEM",
            "content": CHUNK_1,
            "metadata": {},
        },
        {
            "position": 5,
            "kind": "target_rag_chunk",
            "role": "SYSTEM",
            "content": CHUNK_2,
            "metadata": {},
        },
    ]
    built = build_request(rows, {r["kind"] for r in rows}, "dataset_positions")
    assert sent == [(p.role, p.text) for p in built.parts]
    assert [r for r, _ in sent][-3:] == [
        PartRole.USER,
        PartRole.RETRIEVED,
        PartRole.RETRIEVED,
    ]


def test_bots_without_rag_get_instructions_only_and_no_chunk_is_read(tmp_path):
    d, source = directory()
    plain = next(c for c in d.cards if not c.rag and c.language == "en")
    ws, rec = chat_with(plain.label, d, tmp_path)
    ws.ask("hello")
    roles = [p.role for p in rec.parts[-1]]
    assert PartRole.RETRIEVED not in roles
    assert roles[0] == PartRole.INSTRUCTIONS and roles[-1] == PartRole.USER
    assert not any(kind == "rag" for kind, _ in source.asked)
    note = ws.current().knowledge_note(EN)
    assert note == EN("ws_knowledge_none")


def test_a_rag_bot_labels_its_knowledge_as_one_logged_turn(tmp_path):
    d, _ = directory()
    rag = next(c for c in d.cards if c.rag and c.instruction_chars > 0)
    ws, _ = chat_with(rag.label, d, tmp_path)
    assert ws.current().knowledge_note(EN) == EN("ws_knowledge_logged")
    assert ws.current().knowledge_note(FA) == FA("ws_knowledge_logged")
    assert "logged turn" in EN("ws_knowledge_logged")


def test_the_chunk_set_is_loaded_once_per_bot(tmp_path):
    d, source = directory()
    rag = next(c for c in d.cards if c.rag and c.instruction_chars > 0)
    ws, _ = chat_with(rag.label, d, tmp_path)
    ws.ask("one")
    ws.ask("two")
    ws.new_conversation()
    ws.ask("three")
    assert sum(1 for kind, _ in source.asked if kind == "rag") == 1


def test_content_is_loaded_lazily_and_never_at_list_time():
    d, source = directory()
    assert {kind for kind, _ in source.asked} == {"rows"}
    d.profile("bot-001")
    assert {kind for kind, _ in source.asked} == {"rows"}  # still nothing read


def test_a_profile_never_shows_content_in_its_repr():
    d, _ = directory()
    profile = d.profile("bot-001")
    profile.content()
    for secret in (INSTRUCTION, "INSTR-MARKER", "CHUNK-MARKER", RAW_ID):
        assert secret not in repr(profile) and secret not in str(profile)


def test_no_content_in_the_conversation_or_reports(tmp_path):
    d, _ = directory()
    rag = next(c for c in d.cards if c.rag and c.instruction_chars > 0)
    ws, _ = chat_with(rag.label, d, tmp_path)
    ws.ask("an own message")
    seen = repr(ws.current().messages) + repr(ws.current().reports)
    seen += repr(ws.bot_details(EN)) + repr(ws.bot_list(EN))
    for secret in ("INSTR-MARKER", "CHUNK-MARKER", RAW_ID):
        assert secret not in seen


# --- live with a real bot (UI-R05, UI-R06) ----


def test_live_is_refused_for_a_real_bot_without_the_approval(tmp_path):
    d, _ = directory()
    first = d.cards[0]
    settings = loader(tmp_path, approved=False, live=True, key="sk-SYNTHETIC-not-a-key")
    factory = make_session_factory(
        settings_loader=settings, client_factory=lambda _l, _r: FakeModelClient()
    )
    with pytest.raises(SettingsError) as refused:
        factory(d.profile(first.label), live=True)
    assert "real_data_approved" in str(refused.value)


def test_live_is_allowed_for_a_real_bot_with_all_three(tmp_path):
    d, _ = directory()
    settings = loader(tmp_path, approved=True, live=True, key="sk-SYNTHETIC-not-a-key")
    factory = make_session_factory(
        settings_loader=settings, client_factory=lambda _l, _r: FakeModelClient()
    )
    session = factory(d.profile(d.cards[0].label), live=True)
    assert session.live


def test_a_synthetic_bot_does_not_need_the_approval(tmp_path):
    settings = loader(tmp_path, approved=False, live=True, key="sk-SYNTHETIC-not-a-key")
    d, _ = directory()
    ws = workspace(d, settings=settings)
    synthetic = ws.bots[0]
    factory = make_session_factory(
        settings_loader=settings, client_factory=lambda _l, _r: FakeModelClient()
    )
    assert factory(synthetic, live=True).live


def test_reasons_name_every_missing_piece(tmp_path):
    none = real_data_reasons(loader(tmp_path), EN)
    text = " ".join(none)
    assert "real_data_approved" in text
    assert any("live" in r.lower() for r in none)
    ok = real_data_reasons(
        loader(tmp_path, approved=True, live=True, key="sk-SYNTHETIC-not-a-key"), EN
    )
    assert ok == ()
    only_approval = real_data_reasons(
        loader(tmp_path, approved=False, live=True, key="sk-SYNTHETIC-not-a-key"), EN
    )
    assert len(only_approval) == 1 and "real_data_approved" in only_approval[0]


def test_selecting_a_real_bot_while_live_without_approval_is_refused(tmp_path):
    d, _ = directory()
    settings = loader(tmp_path, approved=False, live=True, key="sk-SYNTHETIC-not-a-key")
    ws = workspace(d, settings=settings)
    from metis_auto.wiring.demo_workspace import Journey

    ws.choose_journey(Journey.CHATBOT)
    assert ws.set_live(True) is None  # the synthetic bot is fine
    refused = ws.select_bot("bot-001")
    assert refused is not None and "real_data_approved" in refused
    assert ws.bot_key != "bot-001"


# --- the database is not running (UI-A03) ----


def test_database_down_gives_the_empty_state_and_presets_remain():
    def broken():
        raise ConnectionError("could not connect to server")

    d = load_directory(broken)
    assert not d.available and d.cards == ()
    ws = workspace(d)
    view = ws.bot_list(EN)
    assert view.real == () and view.synthetic
    assert view.unavailable == EN("bots_db_down")
    assert "team_setup.md" in EN("bots_db_down")
    ws.select_bot(ws.bots[0].key)  # presets still work


def test_database_error_text_is_not_shown():
    def broken():
        raise ConnectionError("password authentication failed for user secret-user")

    d = load_directory(broken)
    assert "secret-user" not in repr(d) and "secret-user" not in (d.error or "")


def test_an_empty_database_is_its_own_state():
    d = load_directory(lambda: Source([]))
    assert d.available and d.cards == ()
    assert workspace(d).bot_list(EN).unavailable is None
    assert workspace(d).bot_list(EN).empty == EN("bots_none")


def test_strings_exist_in_both_languages():
    for key in (
        "bots_title",
        "bots_db_down",
        "bots_none",
        "bots_create",
        "bots_create_unavailable",
        "bots_continue",
        "bots_search",
        "bots_more",
        "bots_filter_language",
        "ws_synthetic_samples",
        "ws_knowledge_logged",
        "ws_knowledge_none",
        "live_real_needs_approval",
    ):
        assert EN(key) and FA(key)
