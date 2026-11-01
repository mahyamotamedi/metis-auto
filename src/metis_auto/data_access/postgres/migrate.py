"""Run Alembic migrations from code; the URL stays out of the config file."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import URL


def alembic_config(ini: Path, url: URL) -> Config:
    cfg = Config(str(ini))
    cfg.attributes["url"] = url
    return cfg


def upgrade_head(ini: Path, url: URL) -> None:
    command.upgrade(alembic_config(ini, url), "head")


def downgrade_base(ini: Path, url: URL) -> None:
    command.downgrade(alembic_config(ini, url), "base")


def check_no_drift(ini: Path, url: URL) -> None:
    """Raises if the table definitions and the migrations disagree."""
    command.check(alembic_config(ini, url))
