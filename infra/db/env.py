"""Alembic environment. The URL is built from settings; nothing is printed."""

from alembic import context
from sqlalchemy import create_engine, pool, text

from metis_auto.data_access.postgres.models import SCHEMAS, metadata
from metis_auto.wiring.database import database_url_from_settings

config = context.config


def _url():
    # Tests pass a throwaway database through the Alembic config object.
    return config.attributes.get("url") or database_url_from_settings()


def _include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in SCHEMAS
    return True


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        for schema in SCHEMAS:
            connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=metadata,
            include_schemas=True,
            include_name=_include_name,
            compare_type=True,
            compare_server_default=False,
            version_table_schema="meta",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("offline migrations are not supported; run against a server")
run_migrations_online()
