"""The lever comparison command (S-2): JSON in, Markdown out. Every result file here
is SYNTHETIC and written to a temporary folder; results are read with the shared
``LeverResult`` (S-1, ``LeverResult.model_validate``)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from metis_auto.analysis.lever_result import LeverResult, Manifest
from metis_auto.wiring.lever_compare import collect, write_comparison

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "compare_levers.py"


def _result_json(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "lever_id": "cache.synthetic-a",
        "step": "cache",
        "version": "v1",
        "n_requests": 1000,
        "n_eligible": 400,
        "baseline": "as_logged",
        "baseline_cost": {"total": "100"},
        "saving": {"total": "10.5"},
        "ci_low": 0.08,
        "ci_high": 0.12,
        "slices": {
            "all": {"saving_share": "0.10"},
            "llm_only": {"saving_share": "0.14"},
            "traffic_weighted": {"saving_share": "0.09"},
            "tenant_rank:1": {"share": "0.30"},
        },
        "evidence_class": "simulation",
        "correctness_state": "unmeasured",
        "assumptions": ["synthetic fixture"],
        "overhead_ms_p50": None,
        "overhead_ms_p95": None,
        "manifest": {
            "data_revision": "0" * 40,
            "code_commit": "unknown",
            "config_hash": "0" * 64,
            "seed": 7,
            "price_version": "prices-synthetic-1",
            "python_version": "3.13.0",
            "created_at": "2026-11-02T00:00:00Z",
        },
    }
    return data | overrides


def _write(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_collect_reads_only_result_json_and_ignores_its_own_output(tmp_path):
    out = tmp_path / "comparison.md"
    out.write_text("# old comparison\n", encoding="utf-8")
    result = _write(tmp_path / "cache.synthetic-a.json", _result_json())
    summary = _write(tmp_path / "final.json", {"waterfall": [], "total": "1"})
    listed = _write(tmp_path / "list.json", [1, 2, 3])
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    results, skipped = collect([result, summary, listed, broken, out], out=out)

    assert [r.lever_id for r in results] == ["cache.synthetic-a"]
    assert {p.name for p in skipped} == {
        "final.json",
        "list.json",
        "broken.json",
        "comparison.md",
    }


def test_collect_returns_the_shared_lever_result(tmp_path):
    """A real ``LeverResult`` (SYNTHETIC values) round-trips through ``collect``."""
    real = LeverResult(
        lever_id="route.synthetic-real",
        step="routing",
        version="v1",
        n_requests=1000,
        n_eligible=400,
        baseline="todays_models",
        baseline_cost={"token_cost": Decimal("100.5")},
        saving={"token_cost": Decimal("10.25")},
        slices={
            "all": {"saving_share": Decimal("0.10")},
            "llm_only": {"saving_share": Decimal("0.14")},
        },
        evidence_class="simulation",
        correctness_state="unmeasured",
        assumptions=("synthetic fixture",),
        manifest=Manifest(
            data_revision="0" * 40,
            code_commit="unknown",
            config_hash="0" * 64,
            seed=7,
            price_version="prices-synthetic-1",
            python_version="3.13.0",
            created_at=datetime(2026, 11, 3, tzinfo=UTC),
        ),
    )
    path = tmp_path / "route.synthetic-real.json"
    path.write_text(real.to_json(), encoding="utf-8")
    bad = _write(tmp_path / "bad.json", _result_json(step="nope"))

    results, skipped = collect([path, bad], out=tmp_path / "comparison.md")

    assert results == [real]
    assert isinstance(results[0], LeverResult)
    assert results[0].saving == {"token_cost": Decimal("10.25")}
    assert skipped == [bad]


def test_write_comparison_has_no_interim_note(tmp_path):
    result = _write(tmp_path / "cache.synthetic-a.json", _result_json())
    out = tmp_path / "comparison.md"

    summary = write_comparison([result], out=out, max_tenant_share=Decimal("0.35"))

    text = out.read_text(encoding="utf-8")
    assert "interim" not in text.lower()
    assert "cache.synthetic-a" in text
    assert summary == {"results": 1, "skipped": 0, "out": str(out)}


def test_script_writes_the_comparison(tmp_path):
    levers = tmp_path / "levers"
    levers.mkdir()
    _write(levers / "cache.synthetic-a.json", _result_json())
    _write(
        levers / "cache.synthetic-b.json", _result_json(lever_id="cache.synthetic-b")
    )
    out = levers / "comparison.md"
    out.write_text("stale\n", encoding="utf-8")
    paths = sorted(str(p) for p in levers.iterdir())  # the glob matches the output

    run = subprocess.run(
        [sys.executable, str(SCRIPT), *paths, "--out", str(out)],
        capture_output=True,
        text=True,
        check=True,
    )

    report = json.loads(run.stdout)
    assert report["results"] == 2 and report["skipped"] == 1
    assert "cache.synthetic-b" in out.read_text(encoding="utf-8")


def test_script_reads_the_tenant_cap_from_the_sprint_config(tmp_path):
    result = _write(tmp_path / "cache.synthetic-a.json", _result_json())
    sprint = tmp_path / "sprint-synthetic.toml"
    sprint.write_text("[sample]\ntenant_cap = 0.25\n", encoding="utf-8")
    out = tmp_path / "comparison.md"

    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(result),
            "--out",
            str(out),
            "--sprint-config",
            str(sprint),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    # The synthetic result's top tenant holds 0.30: over a 0.25 cap.
    assert "over 25%" in out.read_text(encoding="utf-8")
