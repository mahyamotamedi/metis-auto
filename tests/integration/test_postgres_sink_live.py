"""Postgres event sink against a real server (opt-in: ``--run-postgres``; T-3,
ADR-0033). Skipped by default.

Creates a throwaway database, applies the migrations, writes the SYNTHETIC contract
events through ``PostgresEventSink`` and through the JSON Lines sink, and checks
that the rows read back equal the JSON Lines records. The server comes from
``[database]`` settings. The sink's password comes only from ``METIS_DB_PASSWORD``
in the process environment; without it the test is skipped.
"""

import os
import uuid
from pathlib import Path

import pytest
from fixtures.synthetic import contract_examples as ex

pytestmark = pytest.mark.postgres
sa = pytest.importorskip("sqlalchemy")
pytest.importorskip("psycopg")

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def database():
    from metis_auto.data_access.postgres.migrate import upgrade_head
    from metis_auto.wiring.database import database_url_from_settings

    if not os.environ.get("METIS_DB_PASSWORD"):
        pytest.skip("METIS_DB_PASSWORD is not in the process environment")
    admin_url = database_url_from_settings()
    name = f"metis_test_{uuid.uuid4().hex[:10]}"
    admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f"CREATE DATABASE {name}"))
    url = admin_url.set(database=name)
    upgrade_head(ROOT / "infra/db/alembic.ini", url)
    yield url
    with admin.connect() as conn:
        conn.execute(sa.text(f"DROP DATABASE {name} WITH (FORCE)"))
    admin.dispose()


def test_events_in_postgres_equal_the_json_lines_records(database, tmp_path):
    from metis_auto.adapters.sinks import JsonLinesEventSink, PostgresEventSink
    from metis_auto.adapters.sinks.postgres import EVENT_COLUMNS, event_from_row
    from metis_auto.contracts import Event
    from metis_auto.data_access.postgres.engine import make_engine
    from metis_auto.data_access.postgres.event_store import event_connection_factory

    connect = event_connection_factory(
        host=database.host,
        port=database.port,
        name=database.database,
        user=database.username,
    )
    sink = PostgresEventSink(connect)
    jsonl = JsonLinesEventSink(tmp_path / "events.jsonl")
    for event in ex.events():
        sink.emit(event)
        jsonl.emit(event)
    sink.close()
    jsonl.close()

    engine = make_engine(database)
    columns = ", ".join(f'"{c}"' for c in EVENT_COLUMNS)
    with engine.connect() as conn:
        rows = conn.execute(sa.text(f"SELECT {columns} FROM exp.events ORDER BY seq"))
        from_db = [event_from_row(r._mapping) for r in rows]
    engine.dispose()
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert from_db == [Event.model_validate_json(x) for x in lines]
