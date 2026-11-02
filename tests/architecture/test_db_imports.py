"""Database libraries (extra ``db``) are imported only in ``data_access/postgres``
(ADR-0027), so offline code never needs them. ``scripts/full_eda_*`` predate the rule
and are outside ``src``. Static check (``ast``)."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "metis_auto"
DB_LIBRARIES = {"sqlalchemy", "psycopg", "alembic", "pyarrow"}
ALLOWED_DIR = SRC / "data_access" / "postgres"
# Composition passes engines around; it may name the engine type, nothing else.
COMPOSITION = {
    SRC / "wiring" / "golden.py",
    SRC / "wiring" / "db_ingest.py",
    SRC / "wiring" / "golden_answers.py",
}
COMPOSITION_ALLOWED = {"sqlalchemy"}


def _roots(tree: ast.AST) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_database_libraries_only_in_postgres_package():
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.is_relative_to(ALLOWED_DIR):
            continue
        used = _roots(ast.parse(path.read_text(encoding="utf-8"))) & DB_LIBRARIES
        if path in COMPOSITION:
            used -= COMPOSITION_ALLOWED
        if used:
            offenders.append(path.relative_to(SRC).as_posix())
    assert offenders == []


def test_data_access_init_does_not_import_postgres_eagerly():
    init = (SRC / "data_access" / "__init__.py").read_text(encoding="utf-8")
    assert "postgres" not in init
