"""Demo discoverability and usable RAG, using SYNTHETIC data only.

No provider calls, credentials, real conversation text, or database required.
Traces: UI-A01, UI-A33, UI-R03, FR-FIN-02.
"""

import pytest

pytest.importorskip("streamlit")

from test_demo_ui_app import direct, make_loader  # noqa: E402

from metis_auto.adapters.providers import FakeModelClient  # noqa: E402
from metis_auto.wiring.demo_bots import load_directory  # noqa: E402
from metis_auto.wiring.demo_ui import load_presets  # noqa: E402
from metis_auto.wiring.demo_workspace import (  # noqa: E402
    DemoWorkspace,
    make_session_factory,
    synthetic_bots,
)
from metis_auto.wiring.ui_config import load_strings, translator  # noqa: E402


class Source:
    def directory_rows(self):
        return [
            {
                "bot_id": f"synthetic-bot-{n}",
                "instructions": "[SYNTHETIC] Test assistant.",
                "provider_name": "openai_chat_completion",
                "provider_model": "gpt-4o-mini",
                "memory_enabled": False,
                "summarizer_mode": "IGNORE",
                "corpus_ids_state": corpus,
                "rag_top_k": 3,
                "sessions": 1,
                "requests": 10 - n,
                "has_rag": usable,
            }
            for n, corpus, usable in (
                (1, "null", True),  # observed chunks, missing corpus snapshot
                (2, "ok", False),  # configured corpus, no usable logged chunks
                (3, "null", False),
            )
        ]

    def instructions(self, bot_id):
        return "[SYNTHETIC] Test assistant."

    def rag_texts(self, bot_id):
        return ["[SYNTHETIC] Stored knowledge passage."]


def test_one_synthetic_sample_per_language_with_dedup_documents():
    profiles = synthetic_bots(load_presets())
    assert [p.language for p in profiles] == ["fa", "en"]
    for profile in profiles:
        assert len(profile.documents) > len(set(profile.documents))


def test_observed_rag_is_loaded_even_without_configured_corpus():
    directory = load_directory(Source)
    assert directory.card("bot-001").rag is True
    assert directory.profile("bot-001").content()[1] == (
        "[SYNTHETIC] Stored knowledge passage.",
    )
    assert directory.card("bot-002").rag is False


def test_real_bot_list_hides_bots_without_usable_rag(tmp_path):
    directory = load_directory(Source)
    workspace = DemoWorkspace(
        synthetic_bots(load_presets()),
        directory=directory,
        session_factory=make_session_factory(
            settings_loader=make_loader(tmp_path),
            client_factory=lambda _loaded, _run: FakeModelClient(),
        ),
    )
    view = workspace.bot_list(translator(load_strings(), "en"))
    assert [card.key for card in view.real] == ["bot-001"]
    assert view.total == 1


def test_new_rag_only_profiles_do_not_rename_existing_bot_labels():
    class MoreRag(Source):
        def directory_rows(self):
            rows = super().directory_rows()
            rows.append(
                {
                    **rows[0],
                    "bot_id": "synthetic-new-rag-only",
                    "instructions": None,
                    "requests": 1000,
                }
            )
            return rows

    directory = load_directory(MoreRag)
    assert directory.card("bot-001").requests == 9
    assert directory.card("bot-004").requests == 1000


def test_advanced_settings_precede_conversations_and_bot_list(tmp_path):
    app = direct(tmp_path)
    assert not app.exception
    advanced = next(
        child for child in app.sidebar.children.values() if child.type == "expander"
    )
    assert advanced is next(iter(app.sidebar.children.values()))
    assert advanced.proto.expanded is True
    assert any(radio.key == "mode" for radio in advanced.radio)
