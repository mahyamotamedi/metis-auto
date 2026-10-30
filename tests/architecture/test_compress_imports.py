"""The compression libraries (extra ``compress``: torch, transformers,
llmlingua) are imported only by the LLMLingua-2 adapter (ADR-0023), so
offline code and the runtime lock never need them; wiring imports the
adapter lazily. Static check (``ast``)."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "metis_auto"
COMPRESS_LIBRARIES = {"torch", "transformers", "llmlingua", "accelerate", "nltk"}
ALLOWED = {SRC / "adapters" / "compressors" / "llmlingua2.py"}


def _roots(tree: ast.AST) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_compression_libraries_only_in_the_adapter():
    offenders = [
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if path not in ALLOWED
        and _roots(ast.parse(path.read_text(encoding="utf-8"))) & COMPRESS_LIBRARIES
    ]
    assert offenders == []


def test_the_adapter_is_not_imported_eagerly():
    init = (SRC / "adapters" / "compressors" / "__init__.py").read_text(encoding="utf-8")
    assert "llmlingua2" not in init.split('"""', 2)[-1]
    tree = ast.parse((SRC / "wiring" / "compression.py").read_text(encoding="utf-8"))
    top_level = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "metis_auto.adapters.compressors.llmlingua2" not in top_level
