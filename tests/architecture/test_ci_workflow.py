"""The CI workflow (ADR-XXXX (ci-github-actions), QA-TEST, QA-REPL) runs the
documented setup and the default, offline test run on Linux and macOS: no
secrets, no opt-in tests, actions pinned by commit. Static check (PyYAML, which
the dev lock pins). No network."""

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
COMMANDS = [
    "python -m venv .venv",
    ".venv/bin/pip install --require-hashes -r requirements-db.lock",
    ".venv/bin/pip install -e . --no-deps",
    ".venv/bin/python scripts/fetch_tokenizer_assets.py",
    ".venv/bin/ruff check .",
    ".venv/bin/ruff format --check .",
    ".venv/bin/python -m pytest -q",
]


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _job() -> dict:
    jobs = _workflow()["jobs"]
    assert len(jobs) == 1
    return next(iter(jobs.values()))


def test_runs_on_push_and_pull_request():
    data = _workflow()
    triggers = data.get("on", data.get(True))  # YAML 1.1 reads a bare `on` as True
    assert {"push", "pull_request"} <= set(triggers)


def test_matrix_is_linux_and_macos_on_python_313():
    matrix = _job()["strategy"]["matrix"]
    assert matrix["os"] == ["ubuntu-latest", "macos-latest"]
    assert matrix["python-version"] == ["3.13"]


def test_steps_run_the_documented_commands_in_order():
    runs = [s["run"].strip() for s in _job()["steps"] if "run" in s]
    assert runs == COMMANDS


def test_default_run_is_offline_and_needs_no_secrets():
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in ("secrets.", "--run-network", "--run-postgres", "METIS_API_KEY"):
        assert forbidden not in text, forbidden
    assert _workflow()["permissions"] == {"contents": "read"}


def test_actions_are_pinned_to_a_commit():
    uses = [s["uses"] for s in _job()["steps"] if "uses" in s]
    assert uses and all(re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", u) for u in uses)
