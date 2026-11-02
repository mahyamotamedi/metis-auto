"""The demo's lever view model (D-1): LeverResult JSON in, view objects out.

Every result file here is SYNTHETIC and written to a temporary folder; the
``bot:`` slice name below is a made-up ID-like string, not a real ID.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from metis_auto.analysis.lever_result import LeverResult, Manifest
from metis_auto.wiring import lever_view
from metis_auto.wiring.lever_view import load_view, rank_label, slice_rows, waterfall

SYNTHETIC_ID = "synthetic0123abcd"


def _manifest() -> Manifest:
    return Manifest(
        data_revision="0" * 40,
        code_commit="unknown",
        config_hash="a" * 64,
        seed=7,
        price_version="prices-synthetic-1",
        python_version="3.13.5",
        created_at=datetime(2026, 11, 2, 9, 0, tzinfo=UTC),
    )


def _result(
    lever_id: str = "cache.synthetic-a",
    *,
    baseline: str = "as_logged",
    baseline_cost: dict[str, str] | None = None,
    saving: dict[str, str] | None = None,
    extra_slices: dict[str, dict[str, str]] | None = None,
) -> LeverResult:
    slices = {
        "all": {"n_requests": Decimal(10)},
        "llm_only": {"n_requests": Decimal(7)},
    } | {
        k: {n: Decimal(v) for n, v in d.items()}
        for k, d in (extra_slices or {}).items()
    }
    cost = baseline_cost or {"fees": "2", "token_cost": "6", "total": "8"}
    save = saving or {"fees": "0.5", "token_cost": "1.5", "total": "2"}
    return LeverResult(
        lever_id=lever_id,
        step="cache",
        version="v1",
        n_requests=10,
        n_eligible=7,
        baseline=baseline,
        baseline_cost={k: Decimal(v) for k, v in cost.items()},
        saving={k: Decimal(v) for k, v in save.items()},
        slices=slices,
        evidence_class="simulation",
        correctness_state="unmeasured",
        assumptions=("synthetic fixture",),
        manifest=_manifest(),
    )


def _write(folder: Path, result: LeverResult) -> Path:
    path = folder / f"{result.lever_id}.json"
    path.write_text(result.to_json(), encoding="utf-8")
    return path


def test_view_reads_only_lever_result_json(tmp_path, monkeypatch):
    _write(tmp_path, _result("cache.synthetic-a"))
    _write(tmp_path, _result("context.synthetic-b"))
    (tmp_path / "requests.parquet").write_bytes(b"PAR1 synthetic, not parquet")
    (tmp_path / "notes.txt").write_text("synthetic", encoding="utf-8")
    (tmp_path / "final.json").write_text('{"synthetic": true}', encoding="utf-8")
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

    calls: list[int] = []
    real = LeverResult.from_json.__func__

    def spy(cls, text):
        calls.append(1)
        return real(cls, text)

    monkeypatch.setattr(LeverResult, "from_json", classmethod(spy))
    view = load_view(tmp_path)

    assert [r.lever_id for r in view.results] == [
        "cache.synthetic-a",
        "context.synthetic-b",
    ]
    assert view.skipped == 2  # final.json (other shape) and broken.json
    assert len(calls) == 4  # every *.json goes through the shared loader, nothing else

    tree = ast.parse(Path(lever_view.__file__).read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module)
    forbidden = ("pandas", "pyarrow", "polars", "duckdb", "sqlalchemy", "psycopg")
    assert not [m for m in roots for f in forbidden if m.split(".")[0] == f]
    assert not [m for m in roots if "data_access" in m or "settings" in m]


def test_rank_labels_not_ids(tmp_path):
    _write(
        tmp_path,
        _result(
            extra_slices={
                "bot_rank:7": {"saving:total": "0.3"},
                "tenant_rank:1": {"share": "0.30"},
                f"bot:{SYNTHETIC_ID}": {"saving:total": "0.1"},
                f"lang:{SYNTHETIC_ID}0000000000": {"n_requests": "1"},
                "lang:fa": {"n_requests": "4"},
            }
        ),
    )
    view = load_view(tmp_path)
    rows = slice_rows(view.results[0])
    labels = [label for label, _ in rows]

    assert rank_label("bot", 7) == "bot-07"
    assert rank_label("bot", 123) == "bot-123"
    assert "bot-07" in labels and "tenant-01" in labels and "lang:fa" in labels
    assert SYNTHETIC_ID not in repr(rows)
    assert not [label for label in labels if label.startswith(("bot:", "bot_rank"))]


def test_waterfall_rows_sum_to_total(tmp_path):
    _write(tmp_path, _result("cache.synthetic-a"))
    _write(tmp_path, _result("route.synthetic-c", baseline="best_single_cheap"))
    _write(
        tmp_path,
        _result(
            "context.synthetic-b",
            baseline_cost={"fees": "2"},
            saving={"fees": "0.5"},
        ),
    )
    view = load_view(tmp_path)

    recorded = view.for_baseline("as_logged")
    assert {r.lever_id for r in recorded} == {
        "cache.synthetic-a",
        "context.synthetic-b",
    }
    assert "route.synthetic-c" not in {r.lever_id for r in recorded}

    wf = waterfall(next(r for r in recorded if r.lever_id == "cache.synthetic-a"))
    assert wf.unit == "recorded"
    assert [row.block for row in wf.rows] == ["fees", "token_cost"]
    assert sum(row.baseline for row in wf.rows) == wf.baseline_total == Decimal(8)
    assert sum(row.saving for row in wf.rows) == wf.saving_total == Decimal(2)
    assert wf.after_total == Decimal(6)

    repriced = waterfall(view.for_baseline("best_single_cheap")[0])
    assert repriced.unit == "repriced"

    partial = waterfall(
        next(r for r in recorded if r.lever_id == "context.synthetic-b")
    )
    token = next(row for row in partial.rows if row.block == "token_cost")
    assert token.baseline is None and token.saving is None  # unknown, never zero
    assert partial.baseline_total is None and partial.saving_total is None

    bad = _result(
        "cache.synthetic-d",
        saving={"fees": "0.5", "token_cost": "1.5", "total": "9"},
    )
    with pytest.raises(ValueError, match="total"):
        waterfall(bad)


def test_empty_state_when_no_results(tmp_path):
    for folder in (tmp_path / "missing", tmp_path):
        view = load_view(folder)
        assert view.empty
        assert view.results == ()
        assert view.baselines == ()
        assert view.message and "no lever results" in view.message.lower()
    _write(tmp_path, _result())
    view = load_view(tmp_path)
    assert not view.empty and view.message is None
