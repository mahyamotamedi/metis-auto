"""The live SDK (extra ``live``) is imported only by the OpenAI-compatible
adapter (ADR-0021), so offline code never needs it. Static check (``ast``)."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "metis_auto"
LIVE_LIBRARIES = {"openai", "httpx2", "httpcore2"}
ALLOWED = {SRC / "adapters" / "providers" / "openai_compat.py"}


def _roots(tree: ast.AST) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_live_libraries_only_in_the_adapter():
    offenders = [
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if path not in ALLOWED
        and _roots(ast.parse(path.read_text(encoding="utf-8"))) & LIVE_LIBRARIES
    ]
    assert offenders == []


def test_the_providers_package_does_not_import_the_adapter_eagerly():
    init = (SRC / "adapters" / "providers" / "__init__.py").read_text(encoding="utf-8")
    assert "openai_compat" not in init
