"""The bot directory's SQL against the throwaway SYNTHETIC database of
``test_postgres.py`` (opt-in: ``--run-postgres``; ADR-0027). The fixture's bot has
one session, two USER turns, instructions, a corpus and one AI turn with a chunk;
a later AI turn has malformed RAG JSON and no chunks."""

import pytest
from test_postgres import db  # noqa: F401  (the module-scoped fixture)

pytestmark = pytest.mark.postgres


def test_directory_rows_count_traffic_and_hold_the_facts(db):  # noqa: F811
    from metis_auto.data_access.postgres import repository as repo

    with db["engine"].connect() as conn:
        rows = repo.bot_directory_rows(conn)
    assert len(rows) == 1
    bot = rows[0]
    assert bot["bot_id"] == "b1"
    assert (bot["sessions"], bot["requests"]) == (1, 2)
    assert bot["instructions"] == "[SYNTHETIC] instructions"
    assert bot["corpus_ids_state"] == "ok"
    assert bot["has_rag"] is True
    assert {
        "provider_name",
        "provider_model",
        "memory_enabled",
        "summarizer_mode",
    } <= set(bot)


def test_latest_rag_texts_come_from_the_latest_turn_that_has_chunks(db):  # noqa: F811
    from metis_auto.data_access.postgres import repository as repo

    with db["engine"].connect() as conn:
        assert repo.latest_rag_texts(conn, "b1") == ["[SYNTHETIC] chunk"]
        assert repo.latest_rag_texts(conn, "no-such-bot") == []
        assert repo.bot_instructions(conn, "b1") == "[SYNTHETIC] instructions"


def test_the_postgres_source_matches_the_protocol(db):  # noqa: F811
    from metis_auto.wiring.demo_bots import PostgresBotSource, load_directory

    directory = load_directory(lambda: PostgresBotSource(lambda: db["engine"]))
    assert directory.available
    assert [c.label for c in directory.cards] == ["bot-001"]
    content = directory.profile("bot-001").content()
    assert content[0] == "[SYNTHETIC] instructions"
    assert content[1] == ("[SYNTHETIC] chunk",)


def test_logged_chunks_are_available_without_a_corpus_snapshot(db):  # noqa: F811
    from sqlalchemy import text

    from metis_auto.data_access.postgres import repository as repo

    with db["engine"].connect() as conn:
        conn.execute(
            text(
                "UPDATE src.chat_bot SET corpus_ids_state = 'null' WHERE bot_id = 'b1'"
            )
        )
        assert repo.bot_directory_rows(conn)[0]["has_rag"] is True
        assert repo.latest_rag_texts(conn, "b1") == ["[SYNTHETIC] chunk"]
        # The connection rolls this fixture-only change back on exit.


@pytest.mark.parametrize("blank", ["   ", "\t\r\n"])
def test_a_corpus_with_only_blank_chunks_has_no_usable_rag(db, blank):  # noqa: F811
    from sqlalchemy import text

    from metis_auto.data_access.postgres import repository as repo

    with db["engine"].connect() as conn:
        conn.execute(
            text("UPDATE src.rag_chunk SET content = :blank"), {"blank": blank}
        )
        row = repo.bot_directory_rows(conn)[0]
        assert row["corpus_ids_state"] == "ok"
        assert row["has_rag"] is False
        assert repo.latest_rag_texts(conn, "b1") == []


def test_a_later_whitespace_only_turn_does_not_mask_usable_rag(db):  # noqa: F811
    from metis_auto.data_access.postgres import models as m
    from metis_auto.data_access.postgres import repository as repo

    with db["engine"].connect() as conn:
        # Copy fixture metadata but attach the blank chunk to the newer AI turn.
        original = conn.execute(m.rag_chunk.select()).mappings().first()
        newer = {
            **original,
            "_source_row": original["_source_row"] + 1,
            "message_id": "m4",
            "content": "\t\n",
        }
        conn.execute(m.rag_chunk.insert().values(**newer))
        assert repo.latest_rag_texts(conn, "b1") == ["[SYNTHETIC] chunk"]
