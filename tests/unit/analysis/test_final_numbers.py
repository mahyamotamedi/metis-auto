"""``analysis/final_numbers.py``: the content of ``reports/levers/final.json``
(sprint plan I-2). Every input here is [SYNTHETIC]: invented numbers, no dataset
content. Rules under test: the waterfall adds up, the unexplained "other" block
is shown and never hidden in a share, recorded and price-file units are never
mixed, a step without a figure in a baseline's units is "not computed", the
winners are labelled provisional, and the document holds no identifier."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from metis_auto.analysis.final_numbers import FORMAT, build_final
from metis_auto.analysis.lever_result import LeverResult, build_manifest
from metis_auto.analysis.levers import ReplayContext

BASELINES = ("as_logged", "premium_gpt_5_5", "todays_models", "best_single_cheap")
STATUS = "provisional: cost only, pending quality"


def result(step, version, baseline, share, *, ci=(None, None), slices=()):
    ctx = ReplayContext(
        period_bounds={}, price_table={"version": "p-syn"}, catalogue={}, seed=1
    )
    manifest = build_manifest(
        {"v": version},
        ctx,
        code_commit="abc1234",
        python_version="3.13.0",
        created_at=datetime(2026, 11, 3, tzinfo=UTC),
    )
    names = (
        ("token_cost", "total")
        if baseline != "as_logged"
        else ("fees", "token_cost", "total")
    )
    all_slices = {
        "all": {"n_requests": Decimal(10)},
        "llm_only": {"saving_share": Decimal(str(share))},
    }
    for s in slices:
        all_slices[s] = {"n_requests": Decimal(1)}
    return LeverResult(
        lever_id=f"{version}.{baseline}",
        step=step,
        version=version,
        n_requests=10,
        n_eligible=5,
        baseline=baseline,
        baseline_cost={b: Decimal(100) for b in names},
        saving={b: Decimal(share * 100) for b in names},
        ci_low=ci[0],
        ci_high=ci[1],
        slices=all_slices,
        evidence_class="simulation",
        correctness_state="unmeasured",
        assumptions=("synthetic",),
        overhead_ms_p95=12.5,
        manifest=manifest,
    )


def summary():
    def cell(alone, combined, **extra):
        return {"alone": alone, "combined": combined, **extra}

    return {
        "status": STATUS,
        "population": {"split": "report", "scored_requests": 10, "llm_requests": 8},
        "pipelines": {
            "winners": {
                "versions": {
                    "cache": "cache-w",
                    "context": "ctx-w",
                    "routing": "route-w",
                },
                "baselines": {
                    "as_logged": {
                        "steps": {
                            "cache": cell("2", "2"),
                            "context": cell("6", "6"),
                            "routing": cell("10", "8"),
                        },
                        "combined_total": "16",
                        "standalone_sum": "18",
                        "sum_rule": {"holds": True, "equal": False},
                    },
                    "todays_models": {
                        "steps": {
                            "cache": cell(None, None, not_computed="no fee block"),
                            "context": cell("7", "7"),
                            "routing": cell("9", "8"),
                        },
                        "combined_total": "15",
                        "standalone_sum": "16",
                        "sum_rule": {"holds": True, "equal": False},
                    },
                },
            }
        },
        "skipped": {},
        "not_run": {"x": "reason"},
    }


F2 = {
    "scopes": {
        "all_ai_messages": {
            "total": "200",
            "other_total": "10",
            "blocks": {
                "fees": "80",
                "input": "70",
                "output": "30",
                "cached": "10",
                "cache_write": "2",
                "unbroken_usage": "7",
                "unbroken_fixed": "1",
            },
            "waterfall": [],
        },
        "tune": {
            "total": "150",
            "other_total": "9",
            "blocks": {
                "fees": "60",
                "input": "52",
                "output": "24",
                "cached": "5",
                "cache_write": "1",
                "unbroken_usage": "7",
                "unbroken_fixed": "1",
            },
            "waterfall": [],
        },
    }
}
TOTALS = {
    "as_logged": {"total": "100", "fees": "40", "token_cost": "60"},
    "todays_models": {"total": "60"},
    "premium_gpt_5_5": {"total": "300"},
    "best_single_cheap": {"total": "50"},
}
CONFIG = {
    "status": STATUS,
    "note": "cost only",
    "winners": {"cache": "cache-w", "context": "ctx-w", "routing": "route-w"},
    "runners_up": {"cache": "cache-r", "context": "ctx-r", "routing": "route-r"},
}


def results():
    out = []
    for b in BASELINES:
        out.append(
            result("cache", "cache-w", b, 0.02, ci=(0.01, 0.03), slices=("over_8k",))
        )
        out.append(result("context", "ctx-w", b, 0.06))
        out.append(
            result(
                "routing",
                "route-w",
                b,
                0.1,
                ci=(0.08, 0.12),
                slices=("lang:fa", "tenant_rank:1"),
            )
        )
    return out


@pytest.fixture()
def final():
    return build_final(summary(), results(), F2, TOTALS, CONFIG)


def test_format_status_and_units_caveat(final):
    assert final["format"] == FORMAT
    assert final["status"] == STATUS
    caveat = final["units_caveat"].lower()
    assert "never added" in caveat and "recorded" in caveat and "price" in caveat
    assert final["population"]["scored_requests"] == 10


def test_units_per_baseline(final):
    assert final["baselines"]["as_logged"]["unit"] == "recorded"
    present = [b for b in final["baselines"] if b != "as_logged"]
    assert present == ["todays_models"]
    for b in present:
        assert final["baselines"][b]["unit"] == "price-file"
        assert "fees" not in final["baselines"][b]  # fees are not priced


def test_waterfall_adds_up(final):
    wf = final["baselines"]["as_logged"]["pipelines"]["winners"]["waterfall"]
    start = next(r for r in wf if r["kind"] == "baseline")
    end = next(r for r in wf if r["kind"] == "after")
    steps = [r for r in wf if r["kind"] == "step"]
    assert Decimal(start["amount"]) == Decimal("100")
    assert Decimal(start["amount"]) - sum(
        Decimal(r["amount"]) for r in steps
    ) == Decimal(end["amount"])
    assert [r["step"] for r in steps] == ["cache", "context", "routing"]
    assert steps[0]["blocks"] == "fees"  # a retrieval cache saves fees only
    assert Decimal(end["amount"]) == Decimal("84")


def test_not_computed_step_has_a_reason_and_no_row(final):
    wf = final["baselines"]["todays_models"]["pipelines"]["winners"]["waterfall"]
    steps = {r["step"] for r in wf if r["kind"] == "step"}
    assert steps == {"context", "routing"}
    cell = final["baselines"]["todays_models"]["pipelines"]["winners"]["steps"]["cache"]
    assert cell["combined"] is None and cell["not_computed"] == "no fee block"


def test_other_block_is_shown_for_recorded_units_only(final):
    other = final["baselines"]["as_logged"]["other_block"]
    # report-derived: all minus tune = (10 - 9) of (200 - 150)
    assert Decimal(other["amount"]) == Decimal("1")
    assert other["share"] == pytest.approx(1 / 50)
    assert "part of token cost" in other["note"].lower()
    assert final["baselines"]["todays_models"]["other_block"]["share"] is None
    assert "price-file" in final["baselines"]["todays_models"]["other_block"]["note"]
    # the tune scope's larger share is stated, so no total hides it
    assert final["cost_blocks"]["scopes"]["tune"]["other_share"] == pytest.approx(
        9 / 150
    )
    assert final["cost_blocks"]["scopes"]["report_derived"][
        "other_share"
    ] == pytest.approx(1 / 50)


def test_shares_are_of_the_baseline_total(final):
    p = final["baselines"]["as_logged"]["pipelines"]["winners"]
    assert p["share_of_total"] == pytest.approx(0.16)
    assert p["sum_rule"]["holds"] is True
    assert p["interval"] is None  # the combined interval is not computed


def test_versions_table_has_intervals_slices_and_overhead(final):
    rows = [
        r
        for r in final["versions"]
        if r["version"] == "route-w" and r["baseline"] == "as_logged"
    ]
    assert len(rows) == 1
    row = rows[0]
    assert row["ci"] == [0.08, 0.12] and row["overhead_ms_p95"] == 12.5
    assert "lang:fa" in row["slices"] and "tenant_rank:1" in row["slices"]
    assert row["correctness_state"] == "unmeasured"
    assert set(row["slices_missing"]) >= {"traffic_weighted"}
    assert row["role"] == "winner"
    other = [r for r in final["versions"] if r["version"] == "cache-w"][0]
    assert other["role"] == "winner"


def test_winners_and_runners_up_are_labelled(final):
    assert final["winners"]["status"] == STATUS
    assert final["winners"]["versions"]["routing"] == "route-w"
    assert final["winners"]["runners_up"]["routing"] == "route-r"


def test_document_holds_no_identifier(final):
    text = json.dumps(final)
    for key in ("session_id", "user_id", "bot_id", "message_id"):
        assert key not in text


def test_a_total_must_exist_for_every_baseline_with_figures():
    bad = {k: v for k, v in TOTALS.items() if k != "as_logged"}
    with pytest.raises(ValueError, match="baseline total"):
        build_final(summary(), results(), F2, bad, CONFIG)
