"""Engine factory. The password arrives as an argument and never reaches a log."""

from __future__ import annotations

from sqlalchemy import URL, Engine, create_engine


def database_url(
    *, host: str, port: int, name: str, user: str, password: str | None
) -> URL:
    """A SQLAlchemy URL; its ``repr`` and ``str`` hide the password."""
    if not password:
        raise ValueError("METIS_DB_PASSWORD is not set")
    return URL.create(
        "postgresql+psycopg",
        username=user,
        password=password,
        host=host,
        port=port,
        database=name,
    )


def make_engine(url: URL) -> Engine:
    return create_engine(url, pool_pre_ping=True, hide_parameters=True)
