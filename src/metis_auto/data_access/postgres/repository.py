"""SQL reads and writes for the evaluation dataset. No decisions here (P-1).

Every text ordering uses ``COLLATE "C"`` so results do not depend on the locale.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, Engine, insert, text

from metis_auto.data_access.postgres import models as m

_SESSION_SQL = """
SELECT session_id, message_id, type, "timestamp", source_ordinal, content,
       finish_reason, input_state,
       CASE WHEN attachments_state = 'ok' AND jsonb_typeof(attachments) = 'array' THEN
         (SELECT coalesce(jsonb_agg(a->>'contentType'), '[]'::jsonb)
          FROM jsonb_array_elements(attachments) a)
       ELSE '[]'::jsonb END AS attachment_types
FROM src.chat_message
ORDER BY session_id COLLATE "C", "timestamp" NULLS LAST, source_ordinal
"""


def iter_session_messages(engine: Engine) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Whole sessions, in a fixed order, through a server-side cursor."""
    raw = engine.raw_connection()
    try:
        cur = raw.driver_connection.cursor(name="sessions")
        cur.itersize = 5000
        cur.execute(_SESSION_SQL)
        names = [d[0] for d in cur.description]
        current, rows = None, []
        for values in cur:
            row = dict(zip(names, values, strict=True))
            row["timestamp_is_null"] = row["timestamp"] is None
            if row["session_id"] != current:
                if rows:
                    yield current, rows
                current, rows = row["session_id"], []
            rows.append(row)
        if rows:
            yield current, rows
        cur.close()
    finally:
        raw.rollback()
        raw.close()


def rag_stats(conn: Connection) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(dict)
    for r in conn.execute(
        text(
            "SELECT message_id, count(*) n, coalesce(sum(length(content)),0) c "
            "FROM src.rag_chunk GROUP BY 1"
        )
    ):
        out[r.message_id].update(rag_n_chunks=r.n, rag_chunk_chars=int(r.c))
    for r in conn.execute(
        text("SELECT message_id, count(*) n FROM src.rag_query GROUP BY 1")
    ):
        out[r.message_id]["rag_n_queries"] = r.n
    return dict(out)


def bots_for_features(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT bot_id, instructions, user_id, provider_name, corpus_ids, "
            'corpus_ids_state FROM src.chat_bot ORDER BY bot_id COLLATE "C"'
        )
    )
    return [dict(r._mapping) for r in rows]


def session_owner_map(conn: Connection) -> dict[str, tuple[str, str]]:
    return {
        r.session_id: (r.bot_id, r.user_id)
        for r in conn.execute(
            text("SELECT session_id, bot_id, user_id FROM src.chat_session")
        )
    }


def owners_by_user_turns(conn: Connection) -> list[str]:
    """Owner ids, most USER turns first, ties in "C" order. Never printed."""
    return list(
        conn.scalars(
            text(
                """SELECT s.user_id FROM src.chat_message m
                   JOIN src.chat_session s USING (session_id)
                   WHERE m.type = 'USER' GROUP BY 1
                   ORDER BY count(*) DESC, s.user_id COLLATE "C" """
            )
        )
    )


def user_char_percentile(conn: Connection, q: float) -> int:
    return int(
        conn.scalar(
            text(
                "SELECT percentile_disc(:q) WITHIN GROUP (ORDER BY length(content)) "
                "FROM src.chat_message WHERE type='USER' AND content IS NOT NULL"
            ),
            {"q": q},
        )
    )


def request_count(conn: Connection, feature_version: str) -> int:
    return conn.scalar(
        text("SELECT count(*) FROM eval.request WHERE feature_version = :v"),
        {"v": feature_version},
    )


def replace_requests(engine: Engine, rows: Iterable[Mapping[str, Any]]) -> int:
    """Rebuild ``eval.request`` in one transaction, then fill family sizes."""
    cols = [c.name for c in m.request.columns]
    quoted = ", ".join(f'"{c}"' for c in cols)
    raw = engine.raw_connection()
    n = 0
    try:
        with raw.driver_connection.cursor() as cur:
            cur.execute("DELETE FROM eval.request")
            with cur.copy(f"COPY eval.request ({quoted}) FROM STDIN") as copy:
                for row in rows:
                    values = dict(row)
                    values["rule_tags"] = json.dumps(values["rule_tags"])
                    values["attachment_types"] = json.dumps(values["attachment_types"])
                    copy.write_row([values.get(c) for c in cols])
                    n += 1
            cur.execute(
                """UPDATE eval.request r SET family_size = f.n
                   FROM (SELECT exact_family_id, count(*) n FROM eval.request
                         WHERE exact_family_id IS NOT NULL GROUP BY 1) f
                   WHERE r.exact_family_id = f.exact_family_id"""
            )
        raw.commit()
    except BaseException:
        raw.rollback()
        raise
    finally:
        raw.close()
    return n


def eligible_requests(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """SELECT request_id, session_id, bot_id, owner_cohort, turn_index,
                      rule_intent, rule_tags, complexity_proxy, language_group,
                      target_chars, bot_class, exact_family_id, near_family_id,
                      rag_observed_on_answer
               FROM eval.request WHERE eligible AND exact_family_id IS NOT NULL
               ORDER BY request_id COLLATE "C" """
        )
    )
    return [dict(r._mapping) for r in rows]


def exclusion_counts(conn: Connection) -> dict[str, int]:
    return {
        r.k: r.n
        for r in conn.execute(
            text(
                "SELECT coalesce(exclusion_reason,'eligible') k, count(*) n "
                "FROM eval.request GROUP BY 1"
            )
        )
    }


def request_totals(conn: Connection) -> dict[str, int]:
    row = conn.execute(
        text(
            """SELECT (SELECT count(*) FROM src.chat_message WHERE type='USER') users,
                      (SELECT count(*) FROM src.chat_message WHERE type='AI') ais,
                      (SELECT count(*) FROM eval.request) requests,
                      (SELECT count(*) FROM eval.request
                       WHERE answer_message_id IS NOT NULL) answered"""
        )
    ).one()
    return dict(row._mapping)


def texts_for(conn: Connection, ids: Sequence[str]) -> dict[str, str]:
    """Message text, for in-memory near-duplicate checks only."""
    return {
        r.message_id: r.content or ""
        for r in conn.execute(
            text(
                "SELECT message_id, content FROM src.chat_message "
                "WHERE message_id = ANY(:ids)"
            ),
            {"ids": list(ids)},
        )
    }


def request_rows(conn: Connection, ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    return {
        r.request_id: dict(r._mapping)
        for r in conn.execute(
            text("SELECT * FROM eval.request WHERE request_id = ANY(:ids)"),
            {"ids": list(ids)},
        )
    }


def session_messages(conn: Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """SELECT message_id, type, "timestamp", source_ordinal, input_state,
                      encode(sha256(convert_to(coalesce(content,''),'UTF8')),'hex')
                        AS content_sha256,
                      session_id
               FROM src.chat_message WHERE session_id = :s
               ORDER BY "timestamp" NULLS LAST, source_ordinal"""
        ),
        {"s": session_id},
    )
    return [dict(r._mapping) for r in rows]


def chunks_for(conn: Connection, message_ids: Sequence[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in conn.execute(
        text(
            """SELECT message_id, _source_file_id AS file_id, _source_row AS row,
                      content_sha256
               FROM src.rag_chunk WHERE message_id = ANY(:ids)
               ORDER BY _source_file_id, _source_row"""
        ),
        {"ids": list(message_ids)},
    ):
        out[r.message_id].append(dict(r._mapping))
    return dict(out)


def bot_snapshot(conn: Connection, bot_id: str) -> dict[str, Any]:
    r = conn.execute(
        text(
            """SELECT bot_id, instructions_sha256, corpus_ids, rag_top_k, rag_reranking,
                      memory_enabled, summarizer_mode, provider_name, provider_model
               FROM src.chat_bot WHERE bot_id = :b"""
        ),
        {"b": bot_id},
    ).one()
    return dict(r._mapping)


def billing_items(conn: Connection, message_id: str) -> list[dict[str, Any]]:
    return [
        dict(r._mapping)
        for r in conn.execute(
            text(
                """SELECT input_tokens, cached_input_tokens, output_tokens, total_cost
                   FROM src.billing_item WHERE message_id = :m"""
            ),
            {"m": message_id},
        )
    ]


def dataset_state(conn: Connection, dataset_id: str) -> dict[str, Any] | None:
    r = conn.execute(
        text(
            """SELECT d.status, d.config_sha256,
                      (SELECT count(*) FROM eval.annotation a
                       JOIN eval.dataset_record x USING (record_id)
                       WHERE x.dataset_id = d.dataset_id AND a.method = 'human')
                        AS human_labels
               FROM eval.dataset d WHERE dataset_id = :d"""
        ),
        {"d": dataset_id},
    ).one_or_none()
    return dict(r._mapping) if r else None


def write_dataset(
    conn: Connection,
    *,
    dataset: Mapping[str, Any],
    sampling: Mapping[str, Any],
    margins: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
    reserves: Sequence[Mapping[str, Any]],
    components: Sequence[Mapping[str, Any]],
    references: Sequence[Mapping[str, Any]],
    rubric: Mapping[str, Any],
    rubric_values: Sequence[Mapping[str, Any]],
    annotations: Sequence[Mapping[str, Any]],
) -> int:
    """Replace one dataset in one transaction; the caller checked it may be replaced."""
    now = datetime.now(UTC)
    conn.execute(
        text("DELETE FROM eval.dataset WHERE dataset_id = :d"),
        {"d": dataset["dataset_id"]},
    )
    conn.execute(
        text(
            "INSERT INTO eval.rubric VALUES (:rubric_version, :document, "
            ":config_sha256) ON CONFLICT (rubric_version) DO UPDATE SET "
            "config_sha256 = excluded.config_sha256"
        ),
        dict(rubric),
    )
    conn.execute(
        text("DELETE FROM eval.rubric_value WHERE rubric_version = :v"),
        {"v": rubric["rubric_version"]},
    )
    conn.execute(insert(m.rubric_value), list(rubric_values))
    conn.execute(insert(m.dataset), [{**dataset, "created_at": now}])
    run_id = conn.scalar(
        insert(m.sampling_run)
        .values(**sampling, created_at=now)
        .returning(m.sampling_run.c.sampling_run_id)
    )
    conn.execute(
        insert(m.stratum_population),
        [{**row, "sampling_run_id": run_id} for row in margins],
    )
    conn.execute(insert(m.dataset_record), list(records))
    if reserves:
        conn.execute(insert(m.dataset_reserve), list(reserves))
    conn.execute(insert(m.record_input_component), list(components))
    conn.execute(insert(m.record_reference), list(references))
    if annotations:
        conn.execute(insert(m.annotation), list(annotations))
    return run_id


def delete_dataset(conn: Connection, dataset_id: str) -> None:
    conn.execute(
        text("DELETE FROM eval.dataset WHERE dataset_id = :d"), {"d": dataset_id}
    )


def set_status(conn: Connection, dataset_id: str, status: str) -> None:
    conn.execute(
        text("UPDATE eval.dataset SET status = :s WHERE dataset_id = :d"),
        {"s": status, "d": dataset_id},
    )


def dataset_records(conn: Connection, dataset_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """SELECT x.record_id, x.request_id, x.session_id, x.stratum,
                      x.population_weight, x.weight_basis, x.selection_rank,
                      x.selection_rationale, q.answer_message_id, q.pair_flag,
                      q.bot_id, q.owner_cohort, q.turn_index, q.language_label,
                      q.bot_class, q.rule_tags, q.config_unknown, q.timestamp_is_null,
                      q.exact_family_id, q.near_family_id, q.target_chars,
                      q.history_chars, q.rag_observed_on_answer, q.attachment_count,
                      q.after_widget,
                      t.type AS target_type, a.type AS answer_type,
                      coalesce(btrim(t.content),'') <> '' AS target_nonblank,
                      coalesce(btrim(a.content),'') <> '' AS answer_nonblank,
                      t."timestamp" AS target_timestamp,
                      a."timestamp" AS answer_timestamp,
                      r.answer_message_id = q.answer_message_id AS answer_id_matches
               FROM eval.dataset_record x
               JOIN eval.request q USING (request_id)
               JOIN eval.record_reference r USING (record_id)
               JOIN src.chat_message t ON t.message_id = x.request_id
               JOIN src.chat_message a ON a.message_id = r.answer_message_id
               WHERE x.dataset_id = :d ORDER BY x.selection_rank"""
        ),
        {"d": dataset_id},
    )
    return [dict(r._mapping) for r in rows]


def reserve_rows(conn: Connection, dataset_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """SELECT request_id, cell, reserve_rank, stratum FROM eval.dataset_reserve
               WHERE dataset_id = :d ORDER BY reserve_rank"""
        ),
        {"d": dataset_id},
    )
    return [dict(r._mapping) for r in rows]


def components_of(conn: Connection, dataset_id: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in conn.execute(
        text(
            """SELECT c.* FROM eval.record_input_component c
               JOIN eval.dataset_record x USING (record_id)
               WHERE x.dataset_id = :d ORDER BY c.record_id, c.position"""
        ),
        {"d": dataset_id},
    ):
        out[r.record_id].append(dict(r._mapping))
    return dict(out)


def labels_of(conn: Connection, dataset_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """SELECT a.record_id, a.dimension, a.value, a.method,
                      a.annotator_pseudonym, a.rubric_version, a.confidence,
                      a.review_status, a.rationale_code
               FROM eval.annotation a JOIN eval.dataset_record x USING (record_id)
               WHERE x.dataset_id = :d
               ORDER BY a.record_id COLLATE "C", a.dimension COLLATE "C",
                        a.annotator_pseudonym COLLATE "C", a.annotation_id"""
        ),
        {"d": dataset_id},
    )
    return [dict(r._mapping) for r in rows]


def add_annotations(conn: Connection, rows: Sequence[Mapping[str, Any]]) -> int:
    """Append, skipping a row already there (same record, dimension, value, person)."""
    n = 0
    for row in rows:
        exists = conn.scalar(
            text(
                """SELECT 1 FROM eval.annotation WHERE record_id=:record_id AND
                   dimension=:dimension AND value=:value AND
                   annotator_pseudonym=:annotator_pseudonym LIMIT 1"""
            ),
            dict(row),
        )
        if not exists:
            conn.execute(insert(m.annotation), [dict(row)])
            n += 1
    return n


def margin_rows(conn: Connection, dataset_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """SELECT s.margin, s.key, s.population_n, s.quota, s.achieved, s.shortfall,
                      s.basis, s.redistribution_note
               FROM eval.stratum_population s
               JOIN eval.sampling_run r USING (sampling_run_id)
               WHERE r.dataset_id = :d
               ORDER BY s.margin COLLATE "C", s.key COLLATE "C" """
        ),
        {"d": dataset_id},
    )
    return [dict(r._mapping) for r in rows]


def view_leak_counts(conn: Connection, dataset_id: str) -> dict[str, int]:
    """Rows in both views, and rows that break the availability rules."""
    total, leaks = 0, 0
    for view, chunks_allowed in (
        ("routing_input_pre_retrieval_v1", False),
        ("routing_input_post_retrieval_v1", True),
    ):
        total += conn.scalar(
            text(
                f"""SELECT count(*) FROM eval.{view} v
                    JOIN eval.dataset_record x USING (record_id)
                    WHERE x.dataset_id = :d"""
            ),
            {"d": dataset_id},
        )
        chunk_rule = "" if chunks_allowed else "OR c.source_kind = 'rag_chunk'"
        leaks += conn.scalar(
            text(
                f"""SELECT count(*) FROM eval.{view} v
                    JOIN eval.record_input_component c USING (record_id, position)
                    JOIN eval.dataset_record x USING (record_id)
                    JOIN eval.record_reference r USING (record_id)
                    JOIN src.chat_message t ON t.message_id = x.request_id
                    LEFT JOIN src.chat_message cm
                      ON cm.message_id = c.source_message_id
                    WHERE x.dataset_id = :d AND (
                      c.source_message_id = r.answer_message_id
                      OR c.availability_stage = 'post_generation'
                      OR c.kind = 'earlier_rag_chunk'
                      OR (cm.message_id IS NOT NULL AND cm.message_id <> t.message_id
                          AND (cm."timestamp" IS NULL OR
                               (cm."timestamp", cm.source_ordinal)
                                 >= (t."timestamp", t.source_ordinal)))
                      {chunk_rule})"""
            ),
            {"d": dataset_id},
        )
    return {"rows": total, "leaks": leaks}


def ownership_errors(conn: Connection, dataset_id: str) -> int:
    return conn.scalar(
        text(
            """SELECT
              (SELECT count(*) FROM eval.record_input_component c
                 JOIN eval.dataset_record x USING (record_id)
                 JOIN src.chat_session s ON s.session_id = x.session_id
                 WHERE x.dataset_id = :d AND c.source_bot_id IS NOT NULL
                   AND c.source_bot_id <> s.bot_id)
            + (SELECT count(*) FROM eval.record_input_component c
                 JOIN eval.dataset_record x USING (record_id)
                 JOIN src.rag_chunk rc ON rc._source_file_id = c.source_chunk_file_id
                                      AND rc._source_row = c.source_chunk_row
                 JOIN src.chat_message m ON m.message_id = rc.message_id
                 WHERE x.dataset_id = :d AND m.session_id <> x.session_id)
            + (SELECT count(*) FROM eval.dataset_record x
                 JOIN src.chat_session s ON s.session_id = x.session_id
                 JOIN src.chat_bot b ON b.bot_id = s.bot_id
                 WHERE x.dataset_id = :d AND s.user_id <> b.user_id)"""
        ),
        {"d": dataset_id},
    )


def latest_reconciliation(conn: Connection) -> dict[str, Any]:
    runs = conn.execute(
        text("SELECT run_id, status FROM meta.ingest_run ORDER BY run_id DESC")
    ).all()
    ok_runs = [r.run_id for r in runs if r.status == "ok"]
    if not ok_runs:
        return {"runs": len(runs), "checks": [], "noop_run": False}
    checks = conn.execute(
        text(
            "SELECT check_name, expected, actual, ok FROM meta.reconciliation "
            'WHERE run_id = :r ORDER BY check_name COLLATE "C"'
        ),
        {"r": ok_runs[0]},
    ).all()
    noop = conn.scalar(
        text(
            "SELECT count(*) FROM meta.reconciliation WHERE "
            "check_name='rows_inserted_this_run' AND actual='0' AND ok"
        )
    )
    return {
        "runs": len(runs),
        "checks": [dict(c._mapping) for c in checks],
        "noop_run": noop > 0,
    }


def routing_input(conn: Connection, record_id: str, profile: str) -> list[dict]:
    view = {
        "pre_retrieval_v1": "routing_input_pre_retrieval_v1",
        "post_retrieval_v1": "routing_input_post_retrieval_v1",
    }[profile]
    return [
        dict(r._mapping)
        for r in conn.execute(
            text(
                f"""SELECT position, kind, role, availability_stage,
                           transmitted_to_provider, content, metadata
                    FROM eval.{view} WHERE record_id = :r ORDER BY position"""
            ),
            {"r": record_id},
        )
    ]


def reference_of(conn: Connection, record_id: str) -> dict[str, Any]:
    r = conn.execute(
        text(
            """SELECT r.answer_message_id, m.content AS answer_text,
                      r.reference_provider_label, r.reference_model_label,
                      r.reference_model_source, r.finish_reason, r.billing_summary,
                      r.availability_stage, m.input AS answer_input
               FROM eval.record_reference r
               JOIN src.chat_message m ON m.message_id = r.answer_message_id
               WHERE r.record_id = :r"""
        ),
        {"r": record_id},
    ).one()
    return dict(r._mapping)


def recent_history_text(
    conn: Connection, record_id: str, limit: int
) -> tuple[str, list[dict[str, str]], int, bool]:
    """(target, last ``limit`` earlier messages, instruction chars, RAG present)."""
    rows = routing_input(conn, record_id, "post_retrieval_v1")
    history = [r for r in rows if r["kind"] == "earlier_message"]
    target = next(r for r in rows if r["kind"] == "target_user_message")
    instruction = next((r for r in rows if r["kind"] == "bot_instruction"), None)
    return (
        target["content"] or "",
        [{"role": r["role"], "content": r["content"] or ""} for r in history[-limit:]],
        len(instruction["content"] or "") if instruction else 0,
        any(r["kind"] == "target_rag_chunk" for r in rows),
    )


def latest_sampling_run(conn: Connection, dataset_id: str) -> dict[str, Any]:
    r = conn.execute(
        text(
            "SELECT config, population_snapshot FROM eval.sampling_run "
            "WHERE dataset_id=:d ORDER BY sampling_run_id DESC LIMIT 1"
        ),
        {"d": dataset_id},
    ).one()
    return dict(r._mapping)
