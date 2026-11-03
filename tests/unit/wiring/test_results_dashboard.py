"""The D-2 results dashboard view (spec UI-S07, UI-R20 to UI-R30): LeverResult
files in, one Streamlit-free ``Dashboard`` out.

Every result here is SYNTHETIC and written to a temporary folder; the ``bot:``
and ``user:`` slice names are made-up ID-like strings, not real IDs. One test
also reads the committed aggregates in ``reports/levers/`` (content-free) to
check that the view matches the files exactly.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from metis_auto.analysis.lever_result import LeverResult, Manifest
from metis_auto.wiring.demo_ui import text_direction
from metis_auto.wiring.lever_view import (
    LEVERS_DIR,
    RESULT_SLICE,
    cache_monitor,
    dashboard,
    load_view,
    tenant_cap,
    version_key,
)
from metis_auto.wiring.ui_config import LANGUAGES, load_strings

SYNTHETIC_ID = "synthetic0123abcd"
SYNTHETIC_USER = "synthuser9876fedc"
REPO = Path(__file__).resolve().parents[3]
CAP = Decimal("0.35")


def _manifest(price_version: str = "prices-synthetic-1") -> Manifest:
    return Manifest(
        data_revision="0" * 40,
        code_commit="unknown",
        config_hash="a" * 64,
        seed=7,
        price_version=price_version,
        python_version="3.13.5",
        created_at=datetime(2026, 11, 3, 9, 0, tzinfo=UTC),
    )


def _d(values: dict[str, str]) -> dict[str, Decimal]:
    return {k: Decimal(v) for k, v in values.items()}


def _result(
    name: str = "cache.synth_a",
    *,
    step: str = "cache",
    version: str | None = None,
    baseline: str = "as_logged",
    cost: dict[str, str] | None = None,
    saving: dict[str, str] | None = None,
    slices: dict[str, dict[str, str]] | None = None,
    ci: tuple[float, float] | None = (0.01, 0.03),
    price_version: str = "prices-synthetic-1",
    n_requests: int = 100,
    evidence: str = "simulation",
    correctness: str = "unmeasured",
    assumptions: tuple[str, ...] = ("synthetic fixture",),
) -> LeverResult:
    recorded = baseline == "as_logged"
    default_cost = (
        {"fees": "2", "token_cost": "6", "total": "8"}
        if recorded
        else {"token_cost": "6", "total": "6"}
    )
    default_saving = (
        {"fees": "0.5", "token_cost": "1.5", "total": "2"}
        if recorded
        else {"token_cost": "1.5", "total": "1.5"}
    )
    base_slice = {"n_requests": "100", "baseline:total": "8", "saving:total": "2"}
    all_slices = {"all": base_slice, "llm_only": base_slice} | (slices or {})
    return LeverResult(
        lever_id=f"{name}.{baseline}",
        step=step,
        version=version or name.rsplit(".", 1)[-1],
        n_requests=n_requests,
        n_eligible=60,
        baseline=baseline,
        baseline_cost=_d(cost or default_cost),
        saving=_d(saving if saving is not None else default_saving),
        ci_low=ci[0] if ci else None,
        ci_high=ci[1] if ci else None,
        slices={k: _d(v) for k, v in all_slices.items()},
        evidence_class=evidence,
        correctness_state=correctness,
        assumptions=assumptions,
        manifest=_manifest(price_version),
    )


def _write(folder: Path, *results: LeverResult) -> None:
    for r in results:
        (folder / f"{r.lever_id}.json").write_text(r.to_json(), encoding="utf-8")


def _board(folder: Path, **kwargs):
    kwargs.setdefault("lang", "en")
    kwargs.setdefault("tenant_cap", CAP)
    return dashboard(load_view(folder), strings=load_strings(), **kwargs)


def _texts(value: object) -> list[str]:
    """Every string reachable from a view object (what the page can render)."""
    if isinstance(value, str):
        return [value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return [
            t for f in dataclasses.fields(value) for t in _texts(getattr(value, f.name))
        ]
    if isinstance(value, dict):
        return [t for k, v in value.items() for t in _texts(k) + _texts(v)]
    if isinstance(value, list | tuple):
        return [t for v in value for t in _texts(v)]
    return []


# --- plan tests (D-2) -------------------------------------------------------


def test_cache_monitor_counts_match_lever_result(tmp_path):
    retrieval = _result(
        "cache.synth_retrieval",
        slices={
            "retrieval": {
                "n_lookups_llm": "50",
                "n_hits": "12",
                "n_guard_blocks": "3",
                "n_ineligible": "5",
                "n_shadow_sampled": "4",
                "n_shadow_agree": "3",
                "n_shadow_unknown": "1",
            }
        },
    )
    memo = _result(
        "cache.synth_memo",
        slices={
            "session_memo": {
                "n_retrieval_turns": "40",
                "n_performed": "30",
                "n_reused": "2",
                "n_skipped_phatic": "8",
                "n_guard_block": "1",
            }
        },
    )
    plain = _result(
        "cache.synth_plain",
        slices={"all": {"n_requests": "100", "n_cache_hits": "9"}},
    )
    context = _result("context.synth_ctx", step="context")
    _write(tmp_path, retrieval, memo, plain, context)

    rows = {row.version: row for row in cache_monitor(load_view(tmp_path).results)}

    assert set(rows) == {
        "cache.synth_retrieval",
        "cache.synth_memo",
        "cache.synth_plain",
    }
    r = rows["cache.synth_retrieval"]
    assert (r.lookups, r.hits, r.guard_blocks) == (50, 12, 3)
    assert r.misses == 50 - 12 - 3 - 5  # statuses: hit, guard_block, ineligible, miss
    assert (r.shadow_sampled, r.shadow_agree, r.shadow_unknown) == (4, 3, 1)
    m = rows["cache.synth_memo"]
    assert (m.lookups, m.hits, m.misses, m.guard_blocks) == (40, 2, 30, 1)
    assert m.gate_skips == 8
    assert m.shadow_sampled is None  # not in the result: never 0
    p = rows["cache.synth_plain"]
    assert p.hits == 9 and p.misses == 60 - 9  # eligible requests not served
    assert p.guard_blocks is None and p.shadow_sampled is None
    for row in rows.values():
        assert row.guard_reasons is None  # no result carries reasons yet


def test_rtl_for_persian_labels(tmp_path):
    strings = load_strings()
    assert LANGUAGES == ("fa", "en")
    for key in strings.keys():
        fa, en = strings.text(key, "fa"), strings.text(key, "en")
        assert text_direction(fa) == "rtl", key
        assert text_direction(en) == "ltr", key

    _write(tmp_path, _result())
    fa_board = _board(tmp_path, lang="fa")
    en_board = _board(tmp_path, lang="en")
    assert fa_board.direction == "rtl" and en_board.direction == "ltr"
    assert fa_board.labels["title"] == strings.text("title", "fa")
    assert all(text_direction(v) == "rtl" for v in fa_board.labels.values())
    assert all(text_direction(o.label) == "rtl" for o in fa_board.baselines)
    assert all(text_direction(o.label) == "rtl" for o in fa_board.slices)


# --- every number equals the files ------------------------------------------


def test_dashboard_numbers_equal_the_lever_results(tmp_path):
    result = _result(
        slices={
            "over_8k": {
                "baseline:fees": "1",
                "baseline:token_cost": "3",
                "baseline:total": "4",
                "saving:fees": "0.25",
                "saving:token_cost": "0.75",
                "saving:total": "1",
                "saving_share": "0.25",
            }
        }
    )
    _write(tmp_path, result)

    top = _board(tmp_path, baseline="as_logged").overview[0]
    assert top.chosen == version_key(result)
    cards = {c.key: c.value for c in top.cards}
    assert cards["baseline_cost"] == result.baseline_cost["total"]
    assert cards["saving"] == result.saving["total"]
    assert (
        cards["saving_share"] == result.saving["total"] / result.baseline_cost["total"]
    )
    assert top.interval == (result.ci_low, result.ci_high)
    rows = {r.block: r for r in top.waterfall.rows}
    assert rows["fees"].baseline == result.baseline_cost["fees"]
    assert rows["token_cost"].saving == result.saving["token_cost"]

    sliced = _board(tmp_path, baseline="as_logged", slice_name="over_8k").overview[0]
    s = result.slices["over_8k"]
    cards = {c.key: c.value for c in sliced.cards}
    assert cards["baseline_cost"] == s["baseline:total"]
    assert cards["saving"] == s["saving:total"]
    assert cards["saving_share"] == s["saving_share"]
    assert sliced.interval is None  # the interval belongs to the result totals
    assert {r.block: r.baseline for r in sliced.waterfall.rows} == {
        "fees": s["baseline:fees"],
        "token_cost": s["baseline:token_cost"],
    }


@pytest.mark.skipif(
    not (REPO / LEVERS_DIR).is_dir(), reason="no committed lever results"
)
def test_real_results_shown_exactly_as_stored():
    """Committed aggregates (content-free): every card equals its file."""
    view = load_view(REPO / LEVERS_DIR)
    strings = load_strings()
    # A lever_id is unique per baseline only (some writers reuse it).
    by_id = {(r.lever_id, r.baseline): r for r in view.results}
    checked = 0
    for baseline in view.baselines:
        for slice_name in (RESULT_SLICE, "all", "llm_only"):
            board = dashboard(
                view,
                baseline=baseline,
                slice_name=slice_name,
                lang="en",
                strings=strings,
                tenant_cap=CAP,
            )
            for step in board.overview:
                if step.result_id is None or not step.cards:
                    continue
                r = by_id[(step.result_id, baseline)]
                cards = {c.key: c.value for c in step.cards}
                if slice_name == RESULT_SLICE:
                    want = r.baseline_cost.get("total")
                    if want is not None:
                        assert cards["baseline_cost"] == want
                else:
                    want = r.slices[slice_name].get("baseline:total")
                    if want is not None and cards["baseline_cost"] is not None:
                        assert cards["baseline_cost"] == want
                checked += 1
    assert checked > 0


# --- ranking ------------------------------------------------------------------


def test_different_baselines_or_price_versions_never_ranked_together(tmp_path):
    _write(
        tmp_path,
        _result("cache.synth_a", saving={"fees": "1", "token_cost": "1", "total": "2"}),
        _result(
            "cache.synth_b",
            saving={"fees": "1", "token_cost": "2", "total": "3"},
            price_version="prices-synthetic-2",
        ),
        _result("cache.synth_c", baseline="best_single_cheap"),
        _result("cache.synth_d", ci=None),  # no interval: insufficient
    )
    board = _board(tmp_path, baseline="as_logged")
    rows = board.comparison["cache"]

    assert {r.version for r in rows} >= {
        "cache.synth_a",
        "cache.synth_b",
        "cache.synth_d",
    }
    assert all(r.baseline == "as_logged" for r in rows)
    assert "cache.synth_c" not in {r.version for r in rows if r.status == "ranked"}
    a = next(r for r in rows if r.version == "cache.synth_a")
    b = next(r for r in rows if r.version == "cache.synth_b")
    assert a.group != b.group  # another price version: another group
    assert a.rank == 1 and b.rank == 1  # each first in its own group, never 1 vs 2
    d = next(r for r in rows if r.version == "cache.synth_d")
    assert d.rank is None and d.status == "insufficient evidence"
    assert all("0" * 40 not in r.group for r in rows)  # no data hash on screen


# --- units ----------------------------------------------------------------------


def test_repriced_total_says_fees_not_priced(tmp_path):
    _write(tmp_path, _result(baseline="todays_models"))
    board = _board(tmp_path, baseline="todays_models")
    step = board.overview[0]
    wf = step.waterfall
    fees = next(r for r in wf.rows if r.block == "fees")
    assert not fees.priced and fees.baseline is None and fees.saving is None
    assert wf.baseline_total == Decimal(6) and wf.saving_total == Decimal("1.5")
    assert wf.note == load_strings().text("not_priced", "en")
    assert "unknown" not in step.unit_note.lower()
    assert step.unit_note == load_strings().text("not_priced", "en")


def test_repriced_slice_in_recorded_units_is_not_shown(tmp_path):
    recorded_slice = {
        "baseline:fees": "100",
        "baseline:token_cost": "200",
        "baseline:total": "300",
        "saving:total": "3",
    }
    _write(
        tmp_path,
        _result(
            baseline="premium_gpt_5_5",
            slices={"all": recorded_slice, "llm_only": recorded_slice},
        ),
    )
    step = _board(tmp_path, baseline="premium_gpt_5_5", slice_name="all").overview[0]
    assert step.waterfall is None and all(c.value is None for c in step.cards)
    assert step.message == load_strings().text("slice_other_units", "en")


def test_other_block_is_part_of_token_cost(tmp_path):
    _write(
        tmp_path,
        _result(
            cost={"fees": "2", "token_cost": "6", "other": "1", "total": "8"},
            saving={"fees": "0.5", "token_cost": "1.5", "total": "2"},
        ),
    )
    wf = _board(tmp_path, baseline="as_logged").overview[0].waterfall
    other = next(r for r in wf.rows if r.block == "other")
    assert other.part_of == "token_cost" and other.baseline == Decimal(1)
    assert wf.baseline_total == Decimal(8)  # not added a second time


# --- empty state, IDs -------------------------------------------------------------


def test_empty_state_without_files(tmp_path):
    for folder in (tmp_path / "missing", tmp_path):
        board = _board(folder)
        assert board.empty
        assert board.empty_message
        assert board.overview == () and board.cache == () and board.routing is None
        assert board.comparison == {}


def test_no_rendered_label_holds_an_id(tmp_path):
    routing = _result(
        "route.synth_rules",
        step="routing",
        slices={
            "bot_rank:1": {
                "n_requests": "40",
                "n_moved": "10",
                "saving:total": "0.4",
                "saving_share": "0.1",
                "share_of_saving": "0.6",
                "insufficient": "0",
            },
            "bot_rank:12": {"n_requests": "3", "n_moved": "0", "insufficient": "1"},
            f"bot:{SYNTHETIC_ID}": {"n_requests": "40"},
            f"user:{SYNTHETIC_USER}": {"n_requests": "40"},
            "tenant_rank:1": {"n_requests": "70", "share": "0.7", "over_cap": "1"},
            "tenant_rank:2": {"n_requests": "30", "share": "0.3", "over_cap": "0"},
            "traffic_weighted": {"n_requests": "100", "saving_share": "0.05"},
        },
    )
    _write(tmp_path, routing, _result())
    for lang in LANGUAGES:
        board = _board(tmp_path, lang=lang, baseline="as_logged")
        texts = " ".join(_texts(board))
        assert SYNTHETIC_ID not in texts and SYNTHETIC_USER not in texts
        assert not re.search(r"\b(bot|tenant|user)_rank:", texts)
        assert not re.search(r"\b[0-9a-f]{16,}\b", texts)

    table = _board(tmp_path, baseline="as_logged").routing
    assert [b.label for b in table.bots] == ["bot-01", "bot-12"]
    first, small = table.bots
    assert first.moved_share == Decimal(10) / Decimal(40)
    assert first.share_of_saving == Decimal("0.6") and not first.insufficient
    assert small.insufficient
    assert [(t.label, t.flagged) for t in table.tenants] == [
        ("tenant-01", True),
        ("tenant-02", False),
    ]
    assert table.traffic_weighted_share == Decimal("0.05")
    assert table.caveats == ("synthetic fixture",)


# --- greeting gate, version switch, evidence --------------------------------------


def test_greeting_gate_token_part_from_its_slice(tmp_path):
    memo = {"n_retrieval_turns": "40", "n_skipped_phatic": "8", "n_reused": "2"}
    _write(
        tmp_path,
        _result(
            "cache.synth_gate",
            saving={"fees": "0.5", "token_cost": "0.2", "total": "0.7"},
            slices={"session_memo": memo},
        ),
        _result(
            "cache.synth_gate",
            baseline="best_single_cheap",
            saving={},
            ci=None,
            slices={"session_memo": memo | {"token_saving_lower_bound": "0.05"}},
        ),
    )
    recorded = _board(tmp_path, baseline="as_logged").gate
    assert recorded.token_saving == Decimal("0.2") and not recorded.lower_bound
    assert recorded.skipped == 8
    repriced = _board(tmp_path, baseline="best_single_cheap").gate
    assert repriced.token_saving == Decimal("0.05") and repriced.lower_bound


def test_version_switch_changes_the_overview_never_sums_steps(tmp_path):
    _write(
        tmp_path,
        _result("cache.synth_a", saving={"fees": "1", "token_cost": "1", "total": "2"}),
        _result("cache.synth_b", saving={"fees": "1", "token_cost": "2", "total": "3"}),
        _result("context.synth_c", step="context"),
    )
    default = _board(tmp_path, baseline="as_logged")
    cache = next(s for s in default.overview if s.step == "cache")
    assert cache.options == ("cache.synth_a", "cache.synth_b")
    assert cache.chosen == "cache.synth_b"  # rank 1 by default

    switched = _board(
        tmp_path, baseline="as_logged", choices={"cache": "cache.synth_a"}
    )
    cache = next(s for s in switched.overview if s.step == "cache")
    assert cache.chosen == "cache.synth_a"
    assert {c.key: c.value for c in cache.cards}["saving"] == Decimal(2)
    assert [s.step for s in switched.overview] == ["cache", "context", "routing"]
    assert switched.combined_note == load_strings().text("combined_absent", "en")

    stale = _board(tmp_path, baseline="as_logged", choices={"cache": "gone"})
    assert (
        next(s for s in stale.overview if s.step == "cache").chosen == "cache.synth_b"
    )


def test_every_number_carries_its_evidence_label(tmp_path):
    _write(tmp_path, _result(), _result("context.synth_c", step="context"))
    strings = load_strings()
    board = _board(tmp_path, baseline="as_logged")
    for step in board.overview:
        if step.result_id is None:
            assert step.message == strings.text("step_none", "en")
            continue
        assert "simulation" in step.evidence
        assert step.quality == strings.text("quality_line", "en")
    for rows in board.comparison.values():
        assert all(r.evidence_class and r.correctness for r in rows)


def test_tenant_cap_from_sprint_config():
    assert tenant_cap(REPO / "config" / "evaluation" / "sprint.toml") == CAP
