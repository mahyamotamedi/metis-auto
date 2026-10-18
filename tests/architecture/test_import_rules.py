"""Enforce the import rules in docs/architecture/repository_structure.md §3 (ADR-0009).

Checks, by static parsing (stdlib ``ast``; nothing is imported or executed):
  1. Each top-level package under src/metis_auto imports only the internal
     packages that ALLOWED lists. Unknown packages fail, so adding a layer forces
     a rule decision.
  2. src/metis_auto never imports experiments, tests, scripts, or the sample-EDA
     helpers.
  3. Nothing outside experiments/sample_eda imports the sample-EDA helpers, except
     tests/test_sample_eda_helpers.py, which tests them (ADR-0008, FR-DATA-08).
     Notebook code cells are checked too.

ALLOWED mirrors §3.1 of the structure doc. Change both together.
"""

import ast
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PACKAGE = "metis_auto"
SRC = REPO / "src" / PACKAGE

ALLOWED: dict[str, set[str]] = {
    "contracts": set(),
    "ports": {"contracts"},
    "domain": {"contracts"},  # S3-2 (Q-19): domain never calls a port (P-1)
    "settings": {"contracts"},
    "application": {"domain", "ports", "contracts"},
    "adapters": {"ports", "contracts"},
    "data_access": {"ports", "contracts"},
    "analysis": {"domain", "ports", "contracts"},
    "evaluation": {"application", "domain", "settings", "ports", "contracts"},
    "wiring": {
        "application",
        "adapters",
        "data_access",
        "evaluation",
        "analysis",
        "settings",
        "domain",
        "ports",
        "contracts",
    },
}
# Root modules forbidden inside src/metis_auto (§3.2).
FORBIDDEN_IN_SRC = {"experiments", "tests", "scripts", "eda_helpers"}
SAMPLE_EDA_MODULES = {"eda_helpers"}
SAMPLE_EDA_DIR = Path("experiments") / "sample_eda"
SAMPLE_EDA_TEST = Path("tests") / "test_sample_eda_helpers.py"


def _module_name(path: Path, src_root: Path) -> list[str]:
    parts = list(path.relative_to(src_root).with_suffix("").parts)
    return parts[:-1] if parts[-1] == "__init__" else parts


def imported_modules(
    tree: ast.AST, module: list[str] | None = None, is_pkg: bool = False
) -> list[str]:
    """Absolute dotted names imported by ``tree``.

    Relative imports resolve against ``module`` and are skipped when it is None.
    """
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if module is None:
                    continue
                package = module if is_pkg else module[:-1]
                base = package[: len(package) - (node.level - 1)]
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            names.append(target)
            # `from metis_auto import domain` imports the domain layer.
            names.extend(f"{target}.{alias.name}" for alias in node.names)
    return names


def parse_file(path: Path) -> ast.AST:
    """Parse a .py file, or a notebook's code cells without IPython magics."""
    text = path.read_text(encoding="utf-8")
    if path.suffix != ".ipynb":
        return ast.parse(text)
    lines = []
    for cell in json.loads(text).get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", "")
        source = "".join(source) if isinstance(source, list) else source
        lines += [
            ln for ln in source.splitlines() if not ln.lstrip().startswith(("%", "!"))
        ]
    return ast.parse("\n".join(lines))


def layer_violations(src: Path) -> list[str]:
    """Violations of rules 1 and 2 for a package tree rooted at ``src``."""
    violations = []
    src_root = src.parent
    for path in sorted(src.rglob("*.py")):
        module = _module_name(path, src_root)
        rel = path.relative_to(src_root)
        layer = module[1] if len(module) > 1 else None
        if layer is not None and layer not in ALLOWED:
            violations.append(f"{rel}: package '{layer}' has no rule in ALLOWED")
            continue
        allowed = ALLOWED.get(layer, set()) if layer else set()
        is_pkg = path.name == "__init__.py"
        for name in imported_modules(parse_file(path), module, is_pkg):
            parts = name.split(".")
            if parts[0] in FORBIDDEN_IN_SRC:
                violations.append(f"{rel}: imports '{parts[0]}' (forbidden in src)")
            elif parts[0] == PACKAGE and len(parts) > 1:
                target = parts[1]
                if target in ALLOWED and target != layer and target not in allowed:
                    importer = layer or PACKAGE
                    violations.append(f"{rel}: '{importer}' may not import '{target}'")
    # `from X import y` yields both X and X.y; report each violation once.
    return list(dict.fromkeys(violations))


def sample_eda_violations(repo: Path) -> list[str]:
    """Violations of rule 3 across src, tests, experiments, and scripts."""
    violations = []
    for top in ("src", "tests", "experiments", "scripts"):
        root = repo / top
        if not root.exists():
            continue
        for path in sorted([*root.rglob("*.py"), *root.rglob("*.ipynb")]):
            rel = path.relative_to(repo)
            exempt = rel == SAMPLE_EDA_TEST or SAMPLE_EDA_DIR in rel.parents
            if exempt or ".ipynb_checkpoints" in rel.parts:
                continue
            for name in imported_modules(parse_file(path)):
                parts = name.split(".")
                is_helper = parts[0] in SAMPLE_EDA_MODULES
                if is_helper or parts[:2] == ["experiments", "sample_eda"]:
                    reason = "sample-EDA code is reference-only"
                    violations.append(f"{rel}: imports '{parts[0]}' ({reason})")
    return list(dict.fromkeys(violations))


def test_every_package_has_a_rule():
    packages = {p.name for p in SRC.iterdir() if (p / "__init__.py").exists()}
    assert packages == set(ALLOWED), (
        "src packages and ALLOWED differ; update the rules and the structure doc"
    )


def test_layer_imports_follow_the_rules():
    assert layer_violations(SRC) == []


def test_nothing_imports_sample_eda_helpers():
    assert sample_eda_violations(REPO) == []


# --- Self-tests: the checker must catch what it claims to. Synthetic trees only. ---


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _notebook(*lines: str) -> str:
    return json.dumps({"cells": [{"cell_type": "code", "source": list(lines)}]})


def test_checker_flags_forbidden_layer_imports(tmp_path):
    pkg = tmp_path / PACKAGE
    _write(pkg, "__init__.py", "")
    _write(pkg, "domain/__init__.py", "")
    _write(
        pkg,
        "domain/policy.py",
        "from metis_auto.adapters import x\nfrom ..contracts import y\n",
    )
    _write(pkg, "adapters/fake.py", "from metis_auto import application\n")
    _write(pkg, "ports/p.py", "from . import q\nimport experiments.routing\n")
    _write(pkg, "mystery/__init__.py", "")
    found = layer_violations(pkg)
    assert any("domain/policy.py" in v and "'adapters'" in v for v in found)
    assert any("adapters/fake.py" in v and "'application'" in v for v in found)
    assert any("ports/p.py" in v and "'experiments'" in v for v in found)
    assert any("'mystery' has no rule" in v for v in found)
    assert not any("contracts" in v for v in found)  # domain -> contracts is allowed
    assert len(found) == 4


def test_checker_flags_domain_importing_ports(tmp_path):
    # S3-2 (Q-19, 2026-10-17): domain may import only contracts.
    pkg = tmp_path / PACKAGE
    _write(pkg, "__init__.py", "")
    _write(pkg, "domain/routing.py", "from metis_auto.ports import ModelClient\n")
    found = layer_violations(pkg)
    assert len(found) == 1
    assert "domain/routing.py" in found[0] and "'ports'" in found[0]


def test_checker_flags_sample_eda_imports_in_scripts_and_notebooks(tmp_path):
    helper_import = "from eda_helpers import load\n"
    _write(tmp_path, "experiments/routing/run.py", helper_import)
    _write(
        tmp_path,
        "experiments/full_eda/eda.ipynb",
        _notebook("%matplotlib inline\n", "import experiments.sample_eda.eda_helpers"),
    )
    # Exempt: the sample EDA itself and its own test.
    _write(tmp_path, "experiments/sample_eda/eda_helpers.py", "")
    _write(tmp_path, "experiments/sample_eda/eda.ipynb", _notebook(helper_import))
    _write(tmp_path, "tests/test_sample_eda_helpers.py", helper_import)
    found = sample_eda_violations(tmp_path)
    assert len(found) == 2
    assert any("routing/run.py" in v for v in found)
    assert any("full_eda/eda.ipynb" in v for v in found)
