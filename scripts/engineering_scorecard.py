"""Engineering scorecard: counts only (sprint plan E-5).

    .venv/bin/python scripts/engineering_scorecard.py

Writes ``reports/engineering_scorecard.json``: how many test functions and
architecture tests, ADRs (numbered and drafts), contract models and how many have
a privacy class on every field, ``module_reference`` rows, locked dependencies
and their hashes, the CI workflow's jobs, and lever results with a reproducibility
manifest. Everything is counted from the repository's files (static, by
reading); nothing is run, no name or path is written, no network. The CI run
status is "not queried (offline)". Numbers and short names only.
"""

from __future__ import annotations

import ast
import json
import pkgutil
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/engineering_scorecard.json"


def count_test_functions(folder: Path) -> int:
    """``test_*`` functions and methods under ``folder`` (parametrised cases count
    once)."""
    n = 0
    for path in folder.rglob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        n += sum(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
            for node in ast.walk(tree)
        )
    return n


def contract_counts() -> tuple[int, int]:
    """(contract models, those whose every field declares a privacy class)."""
    import importlib

    import metis_auto.contracts as contracts
    from metis_auto.contracts._base import ContractModel, privacy_of

    total = classified = 0
    seen: set[type] = set()
    for info in pkgutil.iter_modules(contracts.__path__):
        module = importlib.import_module(f"{contracts.__name__}.{info.name}")
        for obj in vars(module).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, ContractModel)
                and obj is not ContractModel
                and obj.__module__ == module.__name__
                and obj not in seen
            ):
                seen.add(obj)
                total += 1
                if all(privacy_of(obj, f) is not None for f in obj.model_fields):
                    classified += 1
    return total, classified


def scorecard(
    root: Path, *, contract_counts: tuple[int, int] | None = None
) -> dict[str, Any]:
    """The scorecard of the repository at ``root`` (module docstring)."""
    adr = sorted((root / "docs/adr").glob("*.md"))
    numbered = [p for p in adr if re.match(r"\d{4}-", p.name)]
    drafts = [p for p in adr if p.name.startswith("draft-")]
    ref = (root / "docs/architecture/module_reference.md").read_text(encoding="utf-8")
    lock = (root / "requirements-dev.lock").read_text(encoding="utf-8")
    ci = root / ".github/workflows/ci.yml"
    jobs = (
        re.findall(
            r"^  ([a-z][a-z0-9-]*):\s*$",
            ci.read_text(encoding="utf-8").split("jobs:", 1)[1],
            re.M,
        )
        if ci.is_file()
        else []
    )
    results = with_manifest = 0
    for path in (root / "reports/levers").glob("*.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(doc, dict) and "lever_id" in doc:
            results += 1
            with_manifest += isinstance(doc.get("manifest"), dict)
    total, classified = (
        contract_counts if contract_counts else globals()["contract_counts"]()
    )
    return {
        "tests": {
            "test_functions": count_test_functions(root / "tests"),
            "architecture_test_functions": count_test_functions(
                root / "tests/architecture"
            ),
        },
        "adrs": {"numbered": len(numbered), "drafts": len(drafts)},
        "contract_models": {"total": total, "all_fields_classified": classified},
        "module_reference_rows": len(re.findall(r"^\| `[^`]+` \|", ref, re.M)),
        "locked_dependencies": {
            "pinned": len(re.findall(r"^[A-Za-z0-9._-]+==", lock, re.M)),
            "hashes": len(re.findall(r"--hash=sha256:", lock)),
        },
        "ci": {
            "workflow_present": ci.is_file(),
            "jobs": jobs,
            "last_run": "not queried (offline)",
        },
        "levers": {"results": results, "with_manifest": with_manifest},
    }


def main() -> int:
    sys.path.insert(0, str(ROOT / "src"))
    out = scorecard(ROOT)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
