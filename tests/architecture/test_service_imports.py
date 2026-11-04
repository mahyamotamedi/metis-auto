"""Service libraries (extra ``services``) are imported only in their adapter
module (sprint T-0, ADR-0059; the pattern of
``test_db_imports.py`` and ``test_live_sdk_imports.py``), so the default test run
and every other module never need Redis, MLflow or a database driver.

- ``redis``: only ``adapters/stores/redis_store.py`` (lazily, inside its factory).
- ``mlflow``: only ``adapters/tracking/mlflow_tracker.py``.
- ``psycopg``: only ``data_access/postgres`` (already enforced by
  ``test_db_imports.py``, not repeated); the Postgres event sink
  ``adapters/sinks/postgres.py`` imports no database library at all (the connection
  is injected, ADR-0033).

Static (``ast``) over ``src``, ``scripts`` and ``experiments``. Each rule is shown on
a planted forbidden import first.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "metis_auto"
SEARCH = (ROOT / "src", ROOT / "scripts", ROOT / "experiments")
REDIS_ALLOWED = {SRC / "adapters" / "stores" / "redis_store.py"}
MLFLOW_ALLOWED = {SRC / "adapters" / "tracking" / "mlflow_tracker.py"}
SINK = SRC / "adapters" / "sinks" / "postgres.py"
DB_DRIVERS = {"psycopg", "psycopg2", "sqlalchemy", "asyncpg"}


def roots(tree: ast.AST) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def offenders(folders, library: str, allowed: set[Path]) -> list[str]:
    bad = []
    for folder in folders:
        for path in Path(folder).rglob("*.py"):
            if path in allowed:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if library in roots(tree):
                bad.append(path.as_posix())
    return sorted(bad)


# --- the check catches a planted forbidden import ----------------------------------


def test_a_planted_redis_import_is_caught(tmp_path):
    (tmp_path / "ok.py").write_text("import json\n")
    (tmp_path / "bad.py").write_text("def f():\n    import redis\n")
    (tmp_path / "bad2.py").write_text("from redis.client import Redis\n")
    found = offenders([tmp_path], "redis", set())
    assert [Path(p).name for p in found] == ["bad.py", "bad2.py"]
    assert (
        offenders([tmp_path], "redis", {tmp_path / "bad.py", tmp_path / "bad2.py"})
        == []
    )


def test_a_planted_mlflow_import_is_caught(tmp_path):
    (tmp_path / "bad.py").write_text("import mlflow.tracking\n")
    assert [Path(p).name for p in offenders([tmp_path], "mlflow", set())] == ["bad.py"]


def test_a_planted_driver_import_in_the_sink_is_caught(tmp_path):
    sink = tmp_path / "postgres.py"
    sink.write_text("import psycopg\n")
    assert roots(ast.parse(sink.read_text())) & DB_DRIVERS


# --- the repository ----------------------------------------------------------------


def test_redis_imported_only_in_redis_store():
    assert offenders(SEARCH, "redis", REDIS_ALLOWED) == []


def test_mlflow_imported_only_in_mlflow_tracker():
    assert offenders(SEARCH, "mlflow", MLFLOW_ALLOWED) == []


def test_postgres_sink_imports_no_database_library():
    """``psycopg`` itself is confined to ``data_access/postgres`` by
    ``test_db_imports.py``; the event sink must not import a driver at all."""
    assert not roots(ast.parse(SINK.read_text(encoding="utf-8"))) & DB_DRIVERS


def test_services_extra_and_marker_are_declared():
    import tomllib

    doc = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extra = doc["project"]["optional-dependencies"]["services"]
    names = sorted(e.split(">")[0].split("=")[0].split("[")[0] for e in extra)
    assert names == ["mlflow-skinny", "redis"]  # psycopg stays in the `db` extra
    markers = doc["tool"]["pytest"]["ini_options"]["markers"]
    assert any(m.startswith("services:") for m in markers)
