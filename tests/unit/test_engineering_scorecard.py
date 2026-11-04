"""``scripts/engineering_scorecard.py``: counts only (sprint plan E-5). The
repository here is a [SYNTHETIC] folder layout, so every count is known."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def sc():
    name = "engineering_scorecard_under_test"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts/engineering_scorecard.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(name, None)


def fake_repo(tmp_path: Path) -> Path:
    (tmp_path / "tests/unit").mkdir(parents=True)
    (tmp_path / "tests/architecture").mkdir(parents=True)
    (tmp_path / "tests/unit/test_a.py").write_text(
        "def test_one():\n    pass\n\n"
        "def test_two():\n    pass\n\n"
        "def helper():\n    pass\n"
    )
    (tmp_path / "tests/architecture/test_b.py").write_text(
        "def test_x():\n    pass\n\nclass TestK:\n    def test_y(self):\n        pass\n"
    )
    (tmp_path / "docs/adr").mkdir(parents=True)
    for n in ("0001-a.md", "0002-b.md", "draft-c.md", "README.md"):
        (tmp_path / "docs/adr" / n).write_text("# x\n")
    (tmp_path / "docs/architecture").mkdir(parents=True)
    (tmp_path / "docs/architecture/module_reference.md").write_text(
        "| Module | x |\n|---|---|\n| `a/b.py` | 1 |\n| `a/c.py` | 2 |\n| not a row |\n"
    )
    (tmp_path / "requirements-dev.lock").write_text(
        "pkg==1.0 \\\n    --hash=sha256:aa \\\n    --hash=sha256:bb\n"
        "other==2.0 \\\n    --hash=sha256:cc\n"
    )
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / ".github/workflows/ci.yml").write_text(
        "jobs:\n  test:\n    runs-on: x\n  test-macos:\n    runs-on: y\n"
    )
    (tmp_path / "reports/levers").mkdir(parents=True)
    (tmp_path / "reports/levers/ok.json").write_text(
        json.dumps({"lever_id": "x", "manifest": {"seed": 1}})
    )
    (tmp_path / "reports/levers/no_manifest.json").write_text(
        json.dumps({"lever_id": "y"})
    )
    (tmp_path / "reports/levers/other.json").write_text(json.dumps({"a": 1}))
    return tmp_path


def test_counts_come_from_the_repo(sc, tmp_path):
    out = sc.scorecard(fake_repo(tmp_path), contract_counts=(7, 7))
    assert out["tests"]["test_functions"] == 4  # two + x + the method y
    assert out["tests"]["architecture_test_functions"] == 2
    assert out["adrs"] == {"numbered": 2, "drafts": 1}
    assert out["contract_models"] == {"total": 7, "all_fields_classified": 7}
    assert out["module_reference_rows"] == 2
    assert out["locked_dependencies"] == {"pinned": 2, "hashes": 3}
    assert out["ci"] == {
        "workflow_present": True,
        "jobs": ["test", "test-macos"],
        "last_run": "not queried (offline)",
    }
    assert out["levers"] == {"results": 2, "with_manifest": 1}


def test_counts_change_when_the_repo_changes(sc, tmp_path):
    repo = fake_repo(tmp_path)
    (repo / "docs/adr/0003-c.md").write_text("# y\n")
    (repo / "tests/unit/test_c.py").write_text("def test_z():\n    pass\n")
    out = sc.scorecard(repo, contract_counts=(1, 1))
    assert out["adrs"]["numbered"] == 3 and out["tests"]["test_functions"] == 5


def test_output_numbers_and_names_only(sc, tmp_path):
    out = sc.scorecard(fake_repo(tmp_path), contract_counts=(3, 3))

    def leaves(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert k.replace("_", "").isalnum(), k
                yield from leaves(v)
        elif isinstance(o, list):
            for v in o:
                yield from leaves(v)
        else:
            yield o

    for leaf in leaves(out):
        assert isinstance(leaf, (int, bool)) or (
            isinstance(leaf, str) and len(leaf) <= 40
        ), leaf
        assert not (
            isinstance(leaf, str) and ("/" in leaf and "offline" not in leaf)
        ), leaf
    text = json.dumps(out)
    assert str(tmp_path) not in text and "kimia" not in text.lower()


def test_real_repository_counts_are_positive(sc):
    out = sc.scorecard(ROOT)
    assert out["tests"]["test_functions"] > 1000
    assert out["adrs"]["numbered"] >= 56
    assert out["contract_models"]["total"] > 0
    assert (
        out["contract_models"]["all_fields_classified"]
        == out["contract_models"]["total"]
    )
    assert out["levers"]["with_manifest"] == out["levers"]["results"]
