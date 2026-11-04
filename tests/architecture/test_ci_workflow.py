"""The CI workflow (ADR-0035 and its Amendment 1, QA-TEST, QA-REPL) runs the
documented setup and the default, offline test run: on pinned Linux for every push
and pull request, with the ADR-numbering and progress-index checks before the tests,
and on macOS only for pushes to main. No secrets, no opt-in tests, actions pinned by
commit. Static check (PyYAML, which the dev lock pins). No network."""

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
SETUP = [
    "python -m venv .venv",
    ".venv/bin/pip install --require-hashes -r requirements-db.lock",
    ".venv/bin/pip install -e . --no-deps",
]
CHECKS = [
    ".venv/bin/python scripts/fetch_tokenizer_assets.py",
    ".venv/bin/ruff check .",
    ".venv/bin/ruff format --check .",
    ".venv/bin/python -m pytest -q",
]
COMMANDS = SETUP + CHECKS
# T-4 (draft ADR services-extra-and-adapters): the Linux job validates compose.yaml
# without pulling images or starting anything. macOS runners have no Docker.
COMPOSE_CHECK = "docker compose --profile db --profile services config -q"
LINUX_CHECKS = CHECKS[:-1] + [COMPOSE_CHECK] + CHECKS[-1:]
ADR_CHECK = (
    ".venv/bin/python scripts/adr_finalize.py --check\n"
    ".venv/bin/python scripts/progress_index.py --check"
)
LINUX_COMMANDS = SETUP + [ADR_CHECK] + LINUX_CHECKS
MAIN_PUSH_ONLY = "github.event_name == 'push' && github.ref == 'refs/heads/main'"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _jobs() -> dict:
    jobs = _workflow()["jobs"]
    assert set(jobs) == {"test", "test-macos"}
    return jobs


def _runs(job: dict) -> list[str]:
    return [s["run"].strip() for s in job["steps"] if "run" in s]


def test_runs_on_push_and_pull_request():
    data = _workflow()
    triggers = data.get("on", data.get(True))  # YAML 1.1 reads a bare `on` as True
    assert {"push", "pull_request"} <= set(triggers)


def test_linux_job_is_pinned_and_runs_on_every_push_and_pull_request():
    job = _jobs()["test"]
    assert job["runs-on"] == "ubuntu-24.04"
    assert "if" not in job


def test_macos_job_runs_only_on_pushes_to_main():
    job = _jobs()["test-macos"]
    assert job["runs-on"] == "macos-latest"
    assert job["if"].strip() == MAIN_PUSH_ONLY
    assert "needs" not in job


def test_jobs_use_python_313_without_fail_fast_and_a_20_minute_timeout():
    for job in _jobs().values():
        assert job["strategy"]["fail-fast"] is False
        assert job["strategy"]["matrix"]["python-version"] == ["3.13"]
        assert job["timeout-minutes"] == 20


def test_linux_steps_run_the_documented_commands_with_the_adr_check_before_tests():
    job = _jobs()["test"]
    assert _runs(job) == LINUX_COMMANDS
    named = [s for s in job["steps"] if s.get("run", "").strip() == ADR_CHECK]
    assert named[0]["name"] == "ADRs numbered and progress index current"


def test_macos_steps_run_the_documented_commands_in_order():
    assert _runs(_jobs()["test-macos"]) == COMMANDS


def test_default_run_is_offline_and_needs_no_secrets():
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in ("secrets.", "--run-network", "--run-postgres", "METIS_API_KEY"):
        assert forbidden not in text, forbidden
    assert _workflow()["permissions"] == {"contents": "read"}


def test_actions_are_pinned_to_a_commit():
    for job in _jobs().values():
        uses = [s["uses"] for s in job["steps"] if "uses" in s]
        assert uses
        assert all(re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", u) for u in uses)


def test_the_compose_file_is_validated_without_pulling_or_starting_anything():
    job = _jobs()["test"]
    runs = _runs(job)
    assert COMPOSE_CHECK in runs
    assert runs.index(COMPOSE_CHECK) < runs.index(".venv/bin/python -m pytest -q")
    for forbidden in ("compose up", "compose pull", "compose build", "docker pull"):
        assert forbidden not in WORKFLOW.read_text(encoding="utf-8")
    assert COMPOSE_CHECK not in _runs(_jobs()["test-macos"])
