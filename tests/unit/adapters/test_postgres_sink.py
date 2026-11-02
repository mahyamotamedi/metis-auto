"""Postgres event sink (T-3), with a fake connection: no server, no database
library. Events are the SYNTHETIC contract examples; the password is a synthetic
placeholder set only in a test environment mapping."""

from __future__ import annotations

import ast
import inspect
import sys
import types
from pathlib import Path

import pytest
from fixtures.synthetic import contract_examples as ex

from metis_auto.adapters.sinks import (
    FanOutEventSink,
    InMemoryEventSink,
    JsonLinesEventSink,
    PostgresEventSink,
)
from metis_auto.adapters.sinks.postgres import (
    EVENT_COLUMNS,
    EventSinkError,
    event_from_row,
)
from metis_auto.contracts import Event, Privacy
from metis_auto.contracts._base import privacy_of
from metis_auto.data_access.postgres import event_store
from metis_auto.settings import SettingsError, load_settings
from metis_auto.settings.model import DatabaseSettings
from metis_auto.wiring.from_settings import event_sink

REPO = Path(__file__).resolve().parents[3]
VERSIONS = REPO / "infra" / "db" / "versions"
SECRET = "synthetic-secret-pw"
DSN = f"postgresql://metis:{SECRET}@localhost:5432/metis"


class FakeConnection:
    """Records parameterised statements; optionally fails like a driver would,
    with the DSN in its message."""

    def __init__(self, fail_on_execute: int | None = None, fail_commit=False):
        self.statements: list[tuple[str, dict[str, object]]] = []
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0
        self._fail_on_execute = fail_on_execute
        self._fail_commit = fail_commit

    def execute(self, sql: str, params: dict[str, object]) -> None:
        if self._fail_on_execute == len(self.statements):
            raise RuntimeError(f"connection to {DSN} lost")
        self.statements.append((sql, dict(params)))

    def commit(self) -> None:
        if self._fail_commit:
            raise RuntimeError(f"commit failed on {DSN}")
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closes += 1


def _sink(conn: FakeConnection) -> PostgresEventSink:
    return PostgresEventSink(lambda: conn)


def _revision() -> Path:
    found = sorted(VERSIONS.glob("*_events.py"))
    assert len(found) == 1, "one Alembic revision creates exp.events"
    return found[0]


def _tables(path: Path) -> dict[str, dict[str, str | None]]:
    """table name → {column: privacy comment} from the revision's create_table."""
    tables: dict[str, dict[str, str | None]] = {}
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not (
            isinstance(node, ast.Call)
            and getattr(node.func, "attr", "") == "create_table"
        ):
            continue
        name = node.args[0].value
        columns: dict[str, str | None] = {}
        for arg in node.args[1:]:
            if isinstance(arg, ast.Call) and getattr(arg.func, "attr", "") == "Column":
                comment = next(
                    (k.value.value for k in arg.keywords if k.arg == "comment"), None
                )
                columns[arg.args[0].value] = comment
        tables[name] = columns
    return tables


def test_emit_writes_one_row_per_event_in_order():
    conn = FakeConnection()
    sink = _sink(conn)
    events = ex.events()
    for event in events:
        sink.emit(event)

    assert len(conn.statements) == len(events)
    assert [p["event_id"] for _, p in conn.statements] == [e.event_id for e in events]
    # One parameterised statement: no value is ever formatted into the SQL.
    sqls = {sql for sql, _ in conn.statements}
    assert len(sqls) == 1
    (sql,) = sqls
    assert sql.startswith("INSERT INTO exp.events")
    for event in events:
        assert event.event_id not in sql
    # Each event is its own committed transaction.
    assert conn.commits == len(events)
    # The row holds the same content as the JSON Lines record.
    rows = [p for _, p in conn.statements]
    assert [event_from_row(r) for r in rows] == list(events)
    assert set(rows[0]) == set(EVENT_COLUMNS)


def test_close_is_idempotent():
    conn = FakeConnection()
    connects = []

    def connect():
        connects.append(1)
        return conn

    sink = PostgresEventSink(connect)
    sink.emit(ex.events()[0])
    sink.close()
    sink.close()

    assert conn.closes == 1
    assert len(connects) == 1
    with pytest.raises(EventSinkError, match="closed"):
        sink.emit(ex.events()[1])


def test_sink_failure_raises():
    events = ex.events()
    conn = FakeConnection(fail_on_execute=2)
    sink = _sink(conn)
    sink.emit(events[0])
    sink.emit(events[1])
    with pytest.raises(EventSinkError) as caught:
        sink.emit(events[2])

    _assert_clean(caught.value)
    assert conn.commits == 2  # earlier events stay committed
    assert conn.rollbacks == 1  # the failed one is rolled back

    with pytest.raises(EventSinkError) as caught:
        _sink(FakeConnection(fail_commit=True)).emit(events[0])
    _assert_clean(caught.value)

    def refuse():
        raise RuntimeError(f"could not connect to {DSN}")

    with pytest.raises(EventSinkError) as caught:
        PostgresEventSink(refuse)
    _assert_clean(caught.value)


def _assert_clean(error: BaseException) -> None:
    """No DSN or password in the message, and no chained driver exception
    (a traceback would print its message)."""
    assert SECRET not in str(error) and "postgresql://" not in str(error)
    assert error.__cause__ is None and error.__suppress_context__


def test_schema_has_no_content_columns():
    tables = _tables(_revision())
    assert set(tables) == {"events", "lever_results"}
    allowed = {p.value for p in Privacy} - {Privacy.CONTENT.value}
    content_like = {"content", "text", "message", "instructions", "answer", "prompt"}
    for table, columns in tables.items():
        for column, comment in columns.items():
            assert comment is not None and comment.startswith("privacy="), (
                f"{table}.{column} has no privacy comment"
            )
            assert comment.removeprefix("privacy=") in allowed, f"{table}.{column}"
            assert not set(column.split("_")) & content_like, f"{table}.{column}"

    # exp.events mirrors the Event envelope and its privacy classes, plus a row
    # ordinal; nothing the contract does not have.
    events = tables["events"]
    assert set(events) == set(Event.model_fields) | {"seq"}
    for name in Event.model_fields:
        assert events[name] == f"privacy={privacy_of(Event, name).value}", name
    assert events["seq"] == "privacy=operational"


def test_models_match_the_revision():
    pytest.importorskip("sqlalchemy")
    from metis_auto.data_access.postgres import models

    tables = _tables(_revision())
    for name in ("events", "lever_results"):
        table = models.metadata.tables[f"exp.{name}"]
        assert {c.name: c.comment for c in table.columns} == tables[name]

    tree = ast.parse(_revision().read_text(encoding="utf-8"))
    assigned = {
        n.targets[0].id: n.value.value
        for n in tree.body
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
    }
    previous = sorted(p.name for p in VERSIONS.glob("0*.py") if p != _revision())
    assert assigned["down_revision"] == previous[-1].split("_", 1)[0]


def test_password_comes_only_from_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("METIS_DB_PASSWORD", raising=False)
    # A .env in the working directory holding the variable is never read.
    (tmp_path / ".env").write_text(f"METIS_DB_PASSWORD={SECRET}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    where = {"host": "localhost", "port": 5432, "name": "metis", "user": "metis"}
    with pytest.raises(ValueError, match="METIS_DB_PASSWORD") as caught:
        event_store.event_connection_factory(**where)
    assert SECRET not in str(caught.value)

    # Never from configuration: no parameter, no settings field, refused in files.
    params = inspect.signature(event_store.event_connection_factory).parameters
    assert not any("password" in p for p in params)
    assert not any("password" in f for f in DatabaseSettings.model_fields)
    with pytest.raises(SettingsError, match="secret"):
        load_settings(
            environ={},
            dotenv=None,
            runtime=None,
            overrides={"database.password": SECRET},
        )

    # From the process environment: handed to the driver, never shown.
    seen: dict[str, object] = {}
    fake_driver = types.SimpleNamespace(connect=lambda **kw: seen.update(kw) or "conn")
    monkeypatch.setitem(sys.modules, "psycopg", fake_driver)
    monkeypatch.setenv("METIS_DB_PASSWORD", SECRET)
    connect = event_store.event_connection_factory(**where)
    assert SECRET not in repr(connect)
    assert connect() == "conn"
    assert seen["password"] == SECRET and seen["dbname"] == "metis"
    assert seen["autocommit"] is False


# --- Wiring and the fan-out sink ---


def test_default_event_sink_is_the_unchanged_json_lines_sink(tmp_path):
    loaded = load_settings(environ={}, dotenv=None, runtime=None)
    assert loaded.settings.events.sink == "jsonl"
    sink = event_sink(loaded, tmp_path / "events.jsonl")
    assert isinstance(sink, JsonLinesEventSink)
    for event in ex.events():
        sink.emit(event)
    sink.close()
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert [Event.model_validate_json(x) for x in lines] == list(ex.events())


def test_postgres_switch_keeps_the_json_lines_record_and_adds_postgres(
    tmp_path, monkeypatch
):
    conn = FakeConnection()
    monkeypatch.setattr(
        event_store, "event_connection_factory", lambda **kw: lambda: conn
    )
    loaded = load_settings(
        environ={}, dotenv=None, runtime=None, overrides={"events.sink": "postgres"}
    )
    sink = event_sink(loaded, tmp_path / "events.jsonl")
    assert isinstance(sink, FanOutEventSink)
    for event in ex.events():
        sink.emit(event)
    sink.close()
    sink.close()

    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert [Event.model_validate_json(x) for x in lines] == list(ex.events())
    assert [event_from_row(p) for _, p in conn.statements] == list(ex.events())
    assert conn.closes == 1


def test_sink_choice_does_not_change_the_config_hash():
    plain = load_settings(environ={}, dotenv=None, runtime=None)
    switched = load_settings(
        environ={}, dotenv=None, runtime=None, overrides={"events.sink": "postgres"}
    )
    assert plain.config_hash == switched.config_hash
    with pytest.raises(SettingsError):
        load_settings(
            environ={}, dotenv=None, runtime=None, overrides={"events.sink": "kafka"}
        )


def test_fan_out_fails_on_any_sink_and_still_closes_all():
    memory = InMemoryEventSink()
    broken = _sink(FakeConnection(fail_on_execute=0))
    conn_ok = FakeConnection()
    sink = FanOutEventSink((memory, broken, _sink(conn_ok)))

    with pytest.raises(EventSinkError):
        sink.emit(ex.events()[0])
    assert memory.events == [ex.events()[0]]  # sinks are written in order

    closed = FakeConnection()

    class FailingClose:
        def emit(self, event):
            pass

        def close(self):
            raise EventSinkError("synthetic close failure")

    later = _sink(closed)
    fan = FanOutEventSink((FailingClose(), later))
    with pytest.raises(EventSinkError, match="synthetic close failure"):
        fan.close()
    assert closed.closes == 1  # the later sink was closed anyway
