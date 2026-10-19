"""docs/architecture/module_reference.md matches the code (Stage 5 exit criterion).

Checks, by static parsing (nothing is imported):
  1. every module under src/metis_auto, except contracts/ and __init__.py
     re-export files, has exactly one row, and no row names a missing module;
  2. each row's "Imports (checked)" cell equals the metis_auto sub-packages the
     module imports outside its own sub-package (`contracts`, `ports`, and
     `settings` as whole packages: they have no sub-packages).
"""

import ast
import re
from pathlib import Path

from test_import_rules import SRC, _module_name, imported_modules

DOC = SRC.parents[1] / "docs" / "architecture" / "module_reference.md"
WHOLE = {"contracts", "ports", "settings"}


def _key(dotted: str) -> str | None:
    parts = dotted.split(".")
    if parts[0] != "metis_auto" or len(parts) < 2:
        return None
    if parts[1] in WHOLE or len(parts) == 2:
        return parts[1]
    return f"{parts[1]}.{parts[2]}"


def actual_imports(path: Path) -> set[str]:
    module = _module_name(path, SRC.parent)
    own = ".".join(module[1:-1][:2])  # the module's (sub-)package
    names = imported_modules(ast.parse(path.read_text(encoding="utf-8")), module)
    found = {
        k for n in names if (k := _key(n)) and k != own and not k.startswith(own + ".")
    }
    # `from metis_auto.domain import routing` also yields `domain`; keep the leaf.
    return {k for k in found if not any(o.startswith(k + ".") for o in found)}


def documented() -> dict[str, set[str]]:
    rows: dict[str, set[str]] = {}
    for line in DOC.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        match = re.fullmatch(r"`([\w/]+\.py)`", cells[0]) if len(cells) > 4 else None
        if not match:
            continue
        assert match.group(1) not in rows, f"duplicate row: {match.group(1)}"
        rows[match.group(1)] = set(re.findall(r"`([\w.]+)`", cells[4]))
    return rows


def modules() -> dict[str, Path]:
    return {
        str(p.relative_to(SRC)): p
        for p in SRC.rglob("*.py")
        if p.name != "__init__.py" and p.relative_to(SRC).parts[0] != "contracts"
    }


def test_every_module_has_exactly_one_row():
    assert set(documented()) == set(modules())


def test_documented_imports_match_the_code():
    rows, code = documented(), modules()
    mismatches = {
        rel: {"doc": sorted(rows[rel]), "code": sorted(actual_imports(path))}
        for rel, path in code.items()
        if rel in rows and rows[rel] != actual_imports(path)
    }
    assert mismatches == {}


def test_checker_reads_rows_and_imports():
    # Sanity: the parser and the import walk see real data, not empty sets.
    rows = documented()
    assert len(rows) >= 40
    pipeline = "application/pipeline/pipeline.py"
    assert {"domain.routing", "application.events", "ports"} <= rows[pipeline]
    assert "domain.routing" in actual_imports(SRC / pipeline)
