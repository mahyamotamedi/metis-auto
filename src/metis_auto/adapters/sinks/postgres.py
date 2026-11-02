"""Postgres event sink: one row per event in ``exp.events`` (T-3; FR-OBS-06,
FR-OBS-02, QA-PRIV, QA-REPL; ADR-0033).

Responsibility: durable, ordered event delivery to the local PostgreSQL
(ADR-0027). Implements ``ports.EventSink``. It imports no database library
(``tests/architecture/test_db_imports.py``): it is given ``connect``, a factory
for a DB-API-style connection with ``execute(sql, params)``, ``commit()``,
``rollback()`` and ``close()``. ``data_access.postgres.event_store`` builds one
from psycopg; tests pass a fake.

Columns: the ``Event`` envelope fields, with the contract's privacy classes, plus
``seq``, a row ordinal assigned by the database (not an event ID). ``versions``
and ``payload`` are JSON. Events carry no content (tested), so the table holds
none. ``event_from_row(event_row(e)) == e``: a row holds the same content as the
JSON Lines record.

Transactions: the connection is opened once, when the sink is built (a server that
cannot be reached fails the run before it starts). Each ``emit`` is one parameterised
INSERT and one COMMIT, so a row is durable once ``emit`` returns, and rows are in
emit order (one connection, ``seq`` ascending). On a failure the open transaction
is rolled back. Earlier events stay committed, the failed event is not written,
and ``EventSinkError`` is raised, which fails the run offline (observability §6).
Its message names only the exception class and never the DSN or password, and
the driver exception is not chained, so a traceback cannot print it. ``close``
is idempotent. ``emit`` after ``close`` raises.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol

from metis_auto.contracts import Event

TABLE = "exp.events"
EVENT_COLUMNS: tuple[str, ...] = tuple(Event.model_fields)
_JSON = ("versions", "payload")
_CASTS = {
    "timestamp": "timestamptz",
    "logged_timestamp": "timestamp",
    "versions": "jsonb",
    "payload": "jsonb",
}
INSERT_SQL = (
    f"INSERT INTO {TABLE} ("
    + ", ".join(f'"{c}"' for c in EVENT_COLUMNS)
    + ") VALUES ("
    + ", ".join(
        f"%({c})s::{_CASTS[c]}" if c in _CASTS else f"%({c})s" for c in EVENT_COLUMNS
    )
    + ")"
)
"""One statement, values only as parameters (psycopg ``pyformat`` style)."""


class EventConnection(Protocol):
    def execute(self, sql: str, params: Mapping[str, object]) -> object: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


class EventSinkError(RuntimeError):
    """A sink failure. The message never holds a DSN, password or driver text."""


def event_row(event: Event) -> dict[str, object]:
    """The column values for one event: JSON-mode values, JSON text for
    ``versions`` and ``payload``."""
    data = event.model_dump(mode="json")
    return {
        c: json.dumps(data[c], sort_keys=True) if c in _JSON else data[c]
        for c in EVENT_COLUMNS
    }


def event_from_row(row: Mapping[str, object]) -> Event:
    """Rebuild the ``Event`` from a row (from ``event_row`` or read back from the
    table: JSON as text or decoded, times as text or datetimes)."""
    data = {c: row[c] for c in EVENT_COLUMNS}
    for c in _JSON:
        if isinstance(data[c], str):
            data[c] = json.loads(data[c])
    if isinstance(data["timestamp"], datetime):
        data["timestamp"] = data["timestamp"].astimezone(UTC)
    return Event.model_validate(data)


class PostgresEventSink:
    def __init__(self, connect: Callable[[], EventConnection]) -> None:
        try:
            self._conn: EventConnection | None = connect()
        except Exception as exc:
            raise _failure("connect", exc) from None

    def emit(self, event: Event) -> None:
        conn = self._conn
        if conn is None:
            raise EventSinkError("postgres event sink is closed")
        try:
            conn.execute(INSERT_SQL, event_row(event))
            conn.commit()
        except Exception as exc:
            _rollback(conn)
            raise _failure("insert", exc) from None

    def close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            conn.close()
        except Exception as exc:
            raise _failure("close", exc) from None


def _rollback(conn: EventConnection) -> None:
    try:
        conn.rollback()
    except Exception:  # the insert failure is the one reported
        pass


def _failure(step: str, exc: BaseException) -> EventSinkError:
    error = EventSinkError(f"postgres event sink: {step} failed ({type(exc).__name__})")
    error.__suppress_context__ = True
    return error
