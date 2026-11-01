"""Database settings → engine (ADR-0027). The password comes only from
``METIS_DB_PASSWORD`` (process environment or the owner's ``.env``)."""

from __future__ import annotations

from metis_auto.data_access.postgres.engine import database_url, make_engine
from metis_auto.settings import load_settings


def database_url_from_settings():
    loaded = load_settings()
    db = loaded.settings.database
    secret = loaded.secrets.database_password
    return database_url(
        host=db.host,
        port=db.port,
        name=db.name,
        user=db.user,
        password=secret.get_secret_value() if secret else None,
    )


def engine_from_settings():
    return make_engine(database_url_from_settings())
