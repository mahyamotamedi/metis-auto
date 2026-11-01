"""Post-load reconciliation: counts and relationships only, no content (ADR-0027)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import Engine, text

from metis_auto.data_access.postgres.loader import TABLES


@dataclass(frozen=True)
class Check:
    name: str
    expected: str
    actual: str
    ok: bool


_ZERO_CHECKS = {
    "message_without_session": """
        SELECT count(*) FROM src.chat_message m
        LEFT JOIN src.chat_session s USING (session_id)
        WHERE s.session_id IS NULL""",
    "session_without_bot": """
        SELECT count(*) FROM src.chat_session s
        LEFT JOIN src.chat_bot b USING (bot_id) WHERE b.bot_id IS NULL""",
    "session_without_user": """
        SELECT count(*) FROM src.chat_session s
        LEFT JOIN src.users u USING (user_id) WHERE u.user_id IS NULL""",
    "session_owner_differs_from_bot_owner": """
        SELECT count(*) FROM src.chat_session s JOIN src.chat_bot b USING (bot_id)
        WHERE s.user_id IS DISTINCT FROM b.user_id""",
    "dialogue_length_differs_from_messages": """
        SELECT count(*) FROM src.chat_session s
        LEFT JOIN (SELECT session_id, count(*) n FROM src.chat_message
                   GROUP BY session_id) c USING (session_id)
        WHERE s.dialogue_length IS DISTINCT FROM coalesce(c.n, 0)""",
    "malformed_json_values": """
        SELECT (SELECT count(*) FROM src.chat_message WHERE 'malformed' IN (
                  attachments_state, citations_state, tool_calls_state, rag_state,
                  billing_state, input_state, actions_state))
             + (SELECT count(*) FROM src.chat_bot WHERE 'malformed' IN (
                  provider_args_state, corpus_ids_state,
                  summarizer_provider_args_state, functions_state))""",
    "rag_chunks_match_message_json": """
        WITH a AS (
          SELECT m.message_id, c->>'id' AS chunk_id, c->>'content_sha256' AS sha,
                 count(*) AS n
          FROM src.chat_message m,
               jsonb_array_elements(m.rag) q,
               jsonb_array_elements(q->'relevantChunks') c
          WHERE m.rag_state = 'ok'
          GROUP BY 1, 2, 3),
        b AS (
          SELECT message_id, chunk_id, content_sha256 AS sha, count(*) AS n
          FROM src.rag_chunk GROUP BY 1, 2, 3)
        SELECT count(*) FROM a FULL JOIN b
          ON a.message_id = b.message_id AND a.chunk_id IS NOT DISTINCT FROM b.chunk_id
         AND a.sha IS NOT DISTINCT FROM b.sha AND a.n = b.n
        WHERE a.message_id IS NULL OR b.message_id IS NULL""",
    "rag_queries_match_message_json": """
        SELECT count(*) FROM (
          SELECT coalesce(a.message_id, b.message_id) FROM
            (SELECT m.message_id, count(*) n FROM src.chat_message m,
                    jsonb_array_elements(m.rag) q WHERE m.rag_state='ok' GROUP BY 1) a
          FULL JOIN (SELECT message_id, count(*) n FROM src.rag_query GROUP BY 1) b
            ON a.message_id = b.message_id AND a.n = b.n
          WHERE a.message_id IS NULL OR b.message_id IS NULL) d""",
    "input_items_match_message_json": """
        SELECT abs((SELECT count(*) FROM src.chat_message WHERE input_state='ok')
                 - (SELECT count(*) FROM src.input_item))""",
    "billing_messages_match_message_json": """
        SELECT abs((SELECT count(*) FROM src.chat_message WHERE billing_state='ok')
                 - (SELECT count(DISTINCT message_id) FROM src.billing_item))""",
}


def run_checks(
    engine: Engine,
    expected_rows: Mapping[str, int],
    known_owner_gaps: int,
    partial: bool = False,
) -> list[Check]:
    """Every check; ``partial`` (a --limit-rows smoke run) skips footer totals."""
    out: list[Check] = []
    with engine.connect() as conn:
        for name, table in TABLES.items():
            actual = conn.scalar(
                text(f'SELECT count(*) FROM {table.schema}."{table.name}"')
            )
            if partial:
                continue
            want = expected_rows[name]
            out.append(
                Check(f"rows:{name}", str(want), str(actual), int(actual) == want)
            )
        if not partial:
            for row in conn.execute(
                text(
                    "SELECT logical_table, relative_path, parquet_rows, loaded_rows "
                    "FROM meta.source_file WHERE status <> 'loaded' "
                    "OR parquet_rows <> loaded_rows"
                )
            ):
                out.append(
                    Check(
                        f"file:{row.relative_path}",
                        str(row.parquet_rows),
                        str(row.loaded_rows),
                        False,
                    )
                )
            for row in conn.execute(
                text("SELECT type, count(*) n FROM src.chat_message GROUP BY 1")
            ):
                out.append(Check(f"message_type:{row.type}", "info", str(row.n), True))
            for name, sql in _ZERO_CHECKS.items():
                actual = conn.scalar(text(sql))
                out.append(Check(name, "0", str(actual), int(actual) == 0))
            gaps = conn.scalar(
                text(
                    "SELECT count(*) FROM src.chat_bot b LEFT JOIN src.users u "
                    "ON b.user_id = u.user_id WHERE u.user_id IS NULL"
                )
            )
            out.append(
                Check(
                    "bot_owner_missing_from_users",
                    str(known_owner_gaps),
                    str(gaps),
                    int(gaps) == known_owner_gaps,
                )
            )
    return out
