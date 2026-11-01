"""PostgreSQL integration tests (opt-in: ``--run-postgres``; ADR-0027).

Each test module run creates a throwaway database, applies the migrations, and ingests
tiny [SYNTHETIC] Parquet files generated here with the real column names. The server
comes from settings and ``METIS_DB_PASSWORD``. No real data is read.
"""

import json
import tomllib
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.postgres
pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")
sa = pytest.importorskip("sqlalchemy")

ROOT = Path(__file__).resolve().parents[2]
SOURCE = tomllib.loads((ROOT / "config/evaluation/source_v1.toml").read_text("utf-8"))


def _arrow(type_name):
    return {
        "large_string": pa.large_string(),
        "timestamp[us]": pa.timestamp("us"),
        "bool": pa.bool_(),
        "int64": pa.int64(),
        "double": pa.float64(),
        "null": pa.null(),
    }[type_name]


def _write(root, table, rows):
    spec = SOURCE["tables"][table]
    name = spec["pattern"].replace("*", "-00000-of-00001")
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema([(c, _arrow(t)) for c, t in spec["columns"]])
    arrays = {c: [r.get(c) for r in rows] for c, _ in spec["columns"]}
    pq.write_table(pa.table(arrays, schema=schema), path)


RAG = json.dumps(
    [
        {
            "query": "[SYNTHETIC] q",
            "relevantChunks": [
                {
                    "id": "c1",
                    "content": "[SYNTHETIC] chunk",
                    "corpusId": "k",
                    "reference": None,
                    "relevancy": 0.5,
                }
            ],
        }
    ]
)


def fixture_files(root):
    _write(root, "users", [{"user_id": "u1", "activated": True}])
    _write(
        root,
        "chat_bot",
        [
            {
                "bot_id": "b1",
                "user_id": "u1",
                "instructions": "[SYNTHETIC] instructions",
                "corpus_ids": '["k"]',
                "provider_name": "p",
                "provider_model": "[SYNTHETIC]-model",
            }
        ],
    )
    _write(
        root,
        "chat_session",
        [{"session_id": "s1", "user_id": "u1", "bot_id": "b1", "dialogue_length": 4}],
    )
    from datetime import datetime

    t = [datetime(2026, 3, 1, 0, 0, i) for i in range(4)]
    _write(
        root,
        "chat_message",
        [
            {
                "message_id": "m1",
                "session_id": "s1",
                "type": "USER",
                "timestamp": t[0],
                "content": "[SYNTHETIC] one",
            },
            {
                "message_id": "m2",
                "session_id": "s1",
                "type": "AI",
                "timestamp": t[1],
                "content": "[SYNTHETIC] two",
                "finish_reason": "STOP",
                "rag": RAG,
                "billing": '[{"inputTokens": 1}]',
                "input": '{"items": []}',
            },
            {
                "message_id": "m3",
                "session_id": "s1",
                "type": "USER",
                "timestamp": t[2],
                "content": "[SYNTHETIC] three",
            },
            {
                "message_id": "m4",
                "session_id": "s1",
                "type": "AI",
                "timestamp": t[3],
                "content": "[SYNTHETIC] four",
                "finish_reason": "STOP",
                "rag": "bad{",
            },
        ],
    )
    _write(root, "rag_query", [{"message_id": "m2", "query": "[SYNTHETIC] q"}])
    _write(
        root,
        "rag_chunk",
        [
            {
                "message_id": "m2",
                "chunk_id": "c1",
                "content": "[SYNTHETIC] chunk",
                "corpusId": "k",
                "relevancy": 0.5,
            }
        ],
    )
    _write(root, "billing_item", [{"message_id": "m2", "inputTokens": 1}])
    _write(root, "input_item", [{"message_id": "m2", "items": "[]"}])
    _write(
        root,
        "tool_call",
        [{"message_id": "m2", "call.id": "x", "result.outputs": "[SYNTHETIC]"}],
    )
    _write(root, "action", [{"message_id": "m2", "type": "t"}])


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    from metis_auto.data_access.postgres.engine import make_engine
    from metis_auto.data_access.postgres.loader import discover, load_file
    from metis_auto.data_access.postgres.migrate import upgrade_head
    from metis_auto.wiring.database import database_url_from_settings

    admin_url = database_url_from_settings()
    name = f"metis_test_{uuid.uuid4().hex[:10]}"
    admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f"CREATE DATABASE {name}"))
    url = admin_url.set(database=name)
    ini = ROOT / "infra/db/alembic.ini"
    upgrade_head(ini, url)
    engine = make_engine(url)
    raw = tmp_path_factory.mktemp("raw")
    fixture_files(raw)
    tables = {
        k: {"pattern": v["pattern"].replace("*", "*"), "columns": v["columns"]}
        for k, v in SOURCE["tables"].items()
    }
    with engine.begin() as conn:
        run_id = conn.scalar(
            sa.text(
                "INSERT INTO meta.ingest_run (started_at, dataset_repo, "
                "dataset_revision, tool_versions, options, status) VALUES (now(), "
                "'[SYNTHETIC]', 'x', '{}', '{}', 'running') RETURNING run_id"
            )
        )
    sources = discover(raw, tables)
    first = [
        load_file(engine, s, run_id, batch_rows=2, log=lambda _: None) for s in sources
    ]
    yield {
        "engine": engine,
        "url": url,
        "ini": ini,
        "sources": sources,
        "run_id": run_id,
        "first": first,
    }
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(sa.text(f"DROP DATABASE {name} WITH (FORCE)"))
    admin.dispose()


def scalar(db, sql, **kw):
    with db["engine"].connect() as conn:
        return conn.scalar(sa.text(sql), kw)


def test_ingest_loaded_every_row(db):
    assert sum(f["inserted"] for f in db["first"]) == 13
    assert scalar(db, "SELECT count(*) FROM src.chat_message") == 4
    assert scalar(db, "SELECT min(source_ordinal) FROM src.chat_message") == 0


def test_reingest_is_a_noop(db):
    from metis_auto.data_access.postgres.loader import load_file

    again = [
        load_file(db["engine"], s, db["run_id"], batch_rows=2, log=lambda _: None)
        for s in db["sources"]
    ]
    assert sum(f["inserted"] for f in again) == 0
    assert all(f["skipped_file"] for f in again)


def test_malformed_json_is_kept_as_a_state_not_dropped(db):
    assert scalar(
        db, "SELECT rag_state FROM src.chat_message WHERE message_id='m4'"
    ) == ("malformed")


def test_chunk_text_is_stored_once_with_a_hash_in_the_message_json(db):
    rag = scalar(db, "SELECT rag::text FROM src.chat_message WHERE message_id='m2'")
    assert "[SYNTHETIC] chunk" not in rag and "content_sha256" in rag
    assert scalar(db, "SELECT content FROM src.rag_chunk") == "[SYNTHETIC] chunk"


def test_reconciliation_flags_a_problem(db):
    from metis_auto.data_access.postgres.reconcile import run_checks

    expected = {k: 1 for k in SOURCE["tables"]}
    checks = {c.name: c for c in run_checks(db["engine"], expected, 0)}
    assert not checks["rows:chat_message"].ok
    assert checks["rag_chunks_match_message_json"].ok
    assert not checks["malformed_json_values"].ok
    assert checks["bot_owner_missing_from_users"].ok


def test_constraints_reject_bad_rows(db):
    with pytest.raises(sa.exc.IntegrityError), db["engine"].begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO src.chat_message (message_id, session_id, type, "
                "source_ordinal, attachments_state, citations_state, tool_calls_state,"
                " rag_state, billing_state, input_state, actions_state, "
                "_source_file_id, _source_row) VALUES ('z','no_session','USER',9,"
                "'null','null','null','null','null','null','null',1,99)"
            )
        )
    with pytest.raises(sa.exc.IntegrityError), db["engine"].begin() as conn:
        conn.execute(sa.text("UPDATE src.chat_message SET type='BAD'"))


def _dataset(conn, record="r1"):
    conn.execute(
        sa.text(
            """INSERT INTO eval.request (request_id, session_id, bot_id, owner_cohort,
               turn_index, answer_message_id, pair_flag, eligible, language_label,
               language_group, language_method, target_chars, target_words,
               n_prior_messages, history_chars, instruction_chars, rag_chunk_chars,
               bot_class, instruction_evidence, rag_config, config_unknown,
               attachment_count, attachment_types, after_widget,
               rag_observed_on_answer, rule_intent, rule_tags, complexity_proxy,
               timestamp_is_null, feature_version)
               VALUES ('m3','s1','b1','User A',2,'m4','clean',true,'en','english','t',
               1,1,2,1,1,0,'instruction_rag','custom','configured',false,0,'[]',false,
               false,'factual_qa','{}','simple',false,'t')"""
        )
    )
    conn.execute(
        sa.text(
            """INSERT INTO eval.dataset VALUES
               ('d1','n','1','draft','c',now())"""
        )
    )
    conn.execute(
        sa.text(
            f"""INSERT INTO eval.dataset_record (record_id, dataset_id, request_id,
                session_id, stratum, population_weight, weight_basis, selection_rank,
                selection_rationale) VALUES ('{record}','d1','m3','s1','{{}}',1,'b',0,
                'x')"""
        )
    )
    conn.execute(
        sa.text(
            f"""INSERT INTO eval.record_reference (record_id, answer_message_id,
                reference_model_source, billing_summary) VALUES ('{record}','m4','s',
                '{{}}')"""
        )
    )
    for pos, kind, src_, msg, pre in (
        (0, "earlier_message", "message", "m1", True),
        (1, "earlier_message", "message", "m2", True),
        (2, "target_user_message", "message", "m3", True),
        # A deliberately wrong component: the view must still refuse the answer.
        (3, "smuggled_answer", "message", "m4", True),
    ):
        conn.execute(
            sa.text(
                """INSERT INTO eval.record_input_component (record_id, position, kind,
                   source_kind, source_message_id, availability_stage,
                   included_pre_retrieval, included_post_retrieval,
                   transmitted_to_provider) VALUES (:r,:p,:k,:s,:m,'request_arrival',
                   :pre,:pre,'unknown')"""
            ),
            {"r": record, "p": pos, "k": kind, "s": src_, "m": msg, "pre": pre},
        )


def test_views_exclude_the_answer_and_freezing_blocks_changes(db):
    with db["engine"].begin() as conn:
        _dataset(conn)
    with db["engine"].connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT kind, content FROM eval.routing_input_pre_retrieval_v1 "
                "WHERE record_id='r1' ORDER BY position"
            )
        ).all()
    assert [r.kind for r in rows] == [
        "earlier_message",
        "earlier_message",
        "target_user_message",
    ]
    assert "[SYNTHETIC] four" not in [r.content for r in rows]
    with db["engine"].begin() as conn:
        conn.execute(sa.text("UPDATE eval.dataset SET status='frozen'"))
    for sql in (
        "UPDATE eval.dataset_record SET selection_rank=5",
        "DELETE FROM eval.record_input_component WHERE position=3",
        "UPDATE eval.dataset SET status='draft'",
        "DELETE FROM eval.dataset",
    ):
        with pytest.raises(sa.exc.DBAPIError), db["engine"].begin() as conn:
            conn.execute(sa.text(sql))


def test_exp_tables_exist_and_are_empty(db):
    for table in ("model", "experiment", "run", "attempt", "result", "judgement"):
        assert scalar(db, f"SELECT count(*) FROM exp.{table}") == 0


def test_exp_attempt_accepts_a_synthetic_row_and_requires_latency_state(db):
    with db["engine"].begin() as conn:
        conn.execute(
            sa.text(
                """INSERT INTO exp.model VALUES ('[SYNTHETIC]','p','s','2026-11-01',
                   NULL);
                   INSERT INTO exp.experiment VALUES ('e','routing',NULL);
                   INSERT INTO exp.run VALUES ('r','e',NULL,'h',NULL,'fake')"""
            )
        )
    with pytest.raises(sa.exc.IntegrityError), db["engine"].begin() as conn:
        conn.execute(
            sa.text(
                """INSERT INTO exp.attempt (run_id, record_id, attempt_index,
                   attempt_kind, model_id, token_count_fidelity, latency_state)
                   VALUES ('r','r1',0,'first','[SYNTHETIC]','approx','bad')"""
            )
        )
    with db["engine"].begin() as conn:
        for table in ("run", "experiment", "model"):
            conn.execute(sa.text(f"DELETE FROM exp.{table}"))


def test_migrations_have_no_drift_and_downgrade_cleanly():
    from metis_auto.data_access.postgres.migrate import (
        check_no_drift,
        downgrade_base,
        upgrade_head,
    )
    from metis_auto.wiring.database import database_url_from_settings

    admin_url = database_url_from_settings()
    name = f"metis_test_{uuid.uuid4().hex[:10]}"
    admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f"CREATE DATABASE {name}"))
    try:
        url = admin_url.set(database=name)
        ini = ROOT / "infra/db/alembic.ini"
        upgrade_head(ini, url)
        check_no_drift(ini, url)
        downgrade_base(ini, url)
        upgrade_head(ini, url)
    finally:
        with admin.connect() as conn:
            conn.execute(sa.text(f"DROP DATABASE {name} WITH (FORCE)"))
        admin.dispose()
