"""Connections for the Postgres event sink (T-3; FR-OBS-06, QA-PRIV; ADR-0033).

``event_connection_factory`` returns the ``connect`` callable that
``adapters.sinks.postgres.PostgresEventSink`` takes. Each call opens one psycopg
connection (``autocommit=False``: the sink commits each event itself). psycopg is
imported only when a connection is opened, so the offline tests and a machine
without the ``db`` extra can import this module.

The password comes **only** from the process environment variable
``METIS_DB_PASSWORD``. It is never a parameter, never read from configuration
(settings layers refuse secret-looking keys) and never read from ``.env``. It is
read once, when the factory is built, and is never shown in a ``repr`` or a
message. The other connection values come from ``[database]`` settings.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping

PASSWORD_ENV = "METIS_DB_PASSWORD"


class _Connect:
    """Opens one connection per call; its ``repr`` names no secret."""

    def __init__(self, params: dict[str, object]) -> None:
        self._params = params

    def __call__(self) -> object:
        import psycopg

        return psycopg.connect(**self._params, autocommit=False)

    def __repr__(self) -> str:
        p = self._params
        return f"<event store {p['user']}@{p['host']}:{p['port']}/{p['dbname']}>"


def event_connection_factory(
    *,
    host: str,
    port: int,
    name: str,
    user: str,
    environ: Mapping[str, str] | None = None,
) -> Callable[[], object]:
    """A ``connect`` callable for the event sink. ``environ`` defaults to
    ``os.environ`` (the process environment, never ``.env``)."""
    password = (os.environ if environ is None else environ).get(PASSWORD_ENV)
    if not password:
        raise ValueError(f"{PASSWORD_ENV} is not set in the process environment")
    return _Connect(
        {"host": host, "port": port, "dbname": name, "user": user, "password": password}
    )
