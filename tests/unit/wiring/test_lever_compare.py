"""The lever comparison command (S-2): JSON in, Markdown out. Every result file here
is SYNTHETIC and written to a temporary folder; the loader under test is the
interim stand-in for the shared ``LeverResult`` loader (S-1)."""

from __future__ import annotations

import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from metis_auto.wiring import _interim_lever_json as interim
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
            "data_revision": "rev-synthetic",
            "code_commit": "commit-synthetic",
            "config_hash": "cfg-synthetic",
            "seed": 7,
            "price_version": "prices-synthetic-1",
            "python_version": "3.13",
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


def test_money_is_read_as_decimal_and_float_money_is_refused():
    result = interim.result_from_json(_result_json())
    assert result.saving == {"total": Decimal("10.5")}
    assert result.slices["tenant_rank:1"]["share"] == Decimal("0.30")
    assert result.assumptions == ("synthetic fixture",)
    assert result.manifest.price_version == "prices-synthetic-1"

    with pytest.raises(ValueError, match="decimal string"):
        interim.result_from_json(_result_json(saving={"total": 10.5}))


def test_write_comparison_labels_the_interim_loader(tmp_path):
    result = _write(tmp_path / "cache.synthetic-a.json", _result_json())
    out = tmp_path / "comparison.md"

    summary = write_comparison([result], out=out)

    text = out.read_text(encoding="utf-8")
    assert "interim, not the shared implementation" in text
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
