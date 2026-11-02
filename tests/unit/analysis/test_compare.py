"""Lever comparison (S-2). Every result here is a SYNTHETIC, test-local fake that
satisfies the shape protocol in ``analysis.compare``; it is not the shared
``LeverResult`` (interim, see docs/experiments/pipeline_b_interim_contracts.md)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal

import pandas as pd
import pytest

from metis_auto.analysis.compare import BASELINES, compare, to_markdown

D = Decimal
CAP = D("0.35")  # the sprint.toml [sample] tenant_cap, passed in


@dataclass(frozen=True)
class FakeManifest:
    price_version: str = "prices-synthetic-1"
    data_revision: str = "rev-synthetic"


def _slices(tenant_share: str = "0.30") -> dict[str, dict[str, Decimal]]:
    return {
        "llm_only": {"saving_share": D("0.14")},
        "traffic_weighted": {"saving_share": D("0.09")},
        "tenant_rank:1": {"share": D(tenant_share)},
        "tenant_rank:2": {"share": D("0.20")},
    }


@dataclass(frozen=True)
class FakeResult:
    lever_id: str = "cache.synthetic-a"
    step: str = "cache"
    version: str = "v1"
    n_requests: int = 1000
    n_eligible: int = 400
    baseline: str = "as_logged"
    baseline_cost: Mapping[str, Decimal] = field(
        default_factory=lambda: {"total": D("100")}
    )
    saving: Mapping[str, Decimal] = field(default_factory=lambda: {"total": D("10")})
    ci_low: float | None = 0.08
    ci_high: float | None = 0.12
    slices: Mapping[str, Mapping[str, Decimal]] = field(default_factory=_slices)
    evidence_class: str = "simulation"
    correctness_state: str = "unmeasured"
    assumptions: tuple[str, ...] = ("synthetic fixture",)
    overhead_ms_p50: float | None = None
    overhead_ms_p95: float | None = None
    manifest: FakeManifest = field(default_factory=FakeManifest)


def _saving(amount: str) -> dict[str, Decimal]:
    return {"total": D(amount)}


def _row(frame: pd.DataFrame, lever_id: str, version: str = "v1") -> pd.Series:
    match = frame[(frame["lever_id"] == lever_id) & (frame["version"] == version)]
    assert len(match) == 1, f"expected one row for {lever_id} {version}"
    return match.iloc[0]


def test_orders_versions_by_saving_within_a_step():
    results = [
        FakeResult(lever_id="cache.synthetic-a", saving=_saving("5")),
        FakeResult(lever_id="cache.synthetic-b", saving=_saving("20")),
        FakeResult(lever_id="cache.synthetic-c", saving=_saving("10")),
        # A bigger saving in another step is never ranked against cache versions.
        FakeResult(
            lever_id="context.synthetic-a", step="context", saving=_saving("50")
        ),
    ]
    frame = compare(results, baseline="as_logged", max_tenant_share=CAP)

    cache = frame[frame["step"] == "cache"].sort_values("rank")
    assert list(cache["lever_id"]) == [
        "cache.synthetic-b",
        "cache.synthetic-c",
        "cache.synthetic-a",
    ]
    assert list(cache["rank"]) == [1, 2, 3]
    assert _row(frame, "context.synthetic-a")["rank"] == 1
    assert cache["group"].nunique() == 1
    assert _row(frame, "context.synthetic-a")["group"] != cache["group"].iloc[0]
    # Money stays Decimal and the share is exact (no rounding before display).
    top = _row(frame, "cache.synthetic-b")
    assert top["saving"] == D("20")
    assert top["saving_share"] == D("0.2")
    assert top["eligible"] == "400 of 1000"


def test_shows_unmeasured_correctness():
    results = [
        FakeResult(lever_id="cache.synthetic-a", correctness_state="unmeasured"),
        FakeResult(lever_id="cache.synthetic-b", correctness_state="sampled:30"),
        FakeResult(lever_id="cache.synthetic-c", correctness_state="measured"),
        FakeResult(lever_id="cache.synthetic-d", correctness_state="0 errors"),
    ]
    frame = compare(results, baseline="as_logged", max_tenant_share=CAP)

    unmeasured = _row(frame, "cache.synthetic-a")["correctness"]
    assert "unmeasured" in unmeasured
    assert "0" not in unmeasured and "error" not in unmeasured
    assert _row(frame, "cache.synthetic-b")["correctness"] == "sampled (n=30)"
    assert _row(frame, "cache.synthetic-c")["correctness"] == "measured"
    # A state outside the three agreed forms is never read as a pass.
    assert _row(frame, "cache.synthetic-d")["correctness"].startswith("unknown")

    text = to_markdown(results, max_tenant_share=CAP)
    assert "unmeasured" in text


def test_four_baselines_present_or_marked_missing():
    assert len(BASELINES) == 4
    names = [b.key for b in BASELINES]
    present = names[:3]
    results = [FakeResult(baseline=name) for name in present]

    for name in present:
        row = _row(
            compare(results, baseline=name, max_tenant_share=CAP), "cache.synthetic-a"
        )
        assert row["status"] == "ranked"

    missing = compare(results, baseline=names[3], max_tenant_share=CAP)
    assert len(missing) == 1
    row = missing.iloc[0]
    assert row["status"] == "baseline missing"
    assert row["saving"] is None and pd.isna(row["rank"])

    text = to_markdown(results, max_tenant_share=CAP)
    for baseline in BASELINES:
        assert baseline.label in text
    missing_label = BASELINES[3].label
    section = text.split(missing_label, 1)[1]
    assert "Missing" in section.split("\n## ", 1)[0]

    with pytest.raises(ValueError, match="not one of the four baselines"):
        compare(results, baseline="invented-baseline", max_tenant_share=CAP)


def test_results_with_different_baselines_are_not_compared():
    logged = FakeResult(lever_id="cache.synthetic-a", saving=_saving("5"))
    premium = FakeResult(
        lever_id="cache.synthetic-b", baseline=BASELINES[0].key, saving=_saving("90")
    )
    frame = compare([logged, premium], baseline="as_logged", max_tenant_share=CAP)

    assert _row(frame, "cache.synthetic-a")["rank"] == 1
    other = _row(frame, "cache.synthetic-b")
    assert other["status"] == "baseline missing"
    assert pd.isna(other["rank"]) and other["saving"] is None

    # Different price versions, data scopes and evidence classes are grouped
    # apart under one baseline: each is rank 1 of its own group.
    variants = [
        FakeResult(lever_id="cache.synthetic-a", saving=_saving("5")),
        FakeResult(
            lever_id="cache.synthetic-b",
            saving=_saving("50"),
            manifest=FakeManifest(price_version="prices-synthetic-2"),
        ),
        FakeResult(
            lever_id="cache.synthetic-c",
            saving=_saving("40"),
            manifest=FakeManifest(data_revision="rev-synthetic-other"),
        ),
        FakeResult(
            lever_id="cache.synthetic-d",
            saving=_saving("30"),
            evidence_class="measured potential",
        ),
    ]
    grouped = compare(variants, baseline="as_logged", max_tenant_share=CAP)
    assert grouped["group"].nunique() == 4
    assert set(grouped["rank"]) == {1}


def test_tenant_share_above_35_percent_is_flagged():
    over = FakeResult(lever_id="cache.synthetic-a", slices=_slices("0.36"))
    at_limit = FakeResult(lever_id="cache.synthetic-b", slices=_slices("0.35"))
    no_tenant = FakeResult(
        lever_id="cache.synthetic-c",
        slices={k: v for k, v in _slices().items() if not k.startswith("tenant")},
    )
    frame = compare(
        [over, at_limit, no_tenant], baseline="as_logged", max_tenant_share=CAP
    )

    assert _row(frame, "cache.synthetic-a")["tenant_flag"] == "over 35%"
    assert _row(frame, "cache.synthetic-a")["max_tenant_share"] == D("0.36")
    assert _row(frame, "cache.synthetic-b")["tenant_flag"] == "ok"
    # No tenant slice is unknown, not "ok".
    assert _row(frame, "cache.synthetic-c")["tenant_flag"] == "unknown"

    assert "over 35%" in to_markdown([over], max_tenant_share=CAP)


def test_tenant_cap_is_an_argument():
    result = FakeResult(slices=_slices("0.30"))

    strict = compare([result], baseline="as_logged", max_tenant_share=D("0.25"))
    loose = compare([result], baseline="as_logged", max_tenant_share=D("0.35"))

    assert _row(strict, "cache.synthetic-a")["tenant_flag"] == "over 25%"
    assert _row(loose, "cache.synthetic-a")["tenant_flag"] == "ok"
    assert "over 25%" in to_markdown([result], max_tenant_share=D("0.25"))


@pytest.mark.parametrize("cap", [0.35, D("0"), D("1.5"), D("NaN")])
def test_tenant_cap_must_be_a_decimal_share(cap):
    with pytest.raises((TypeError, ValueError)):
        compare([FakeResult()], baseline="as_logged", max_tenant_share=cap)


# --- Further behaviour from the S-2 spec ---


def test_insufficient_evidence_is_never_ranked():
    results = [
        FakeResult(lever_id="cache.synthetic-a", saving=_saving("5")),
        FakeResult(lever_id="cache.synthetic-b", saving=_saving("99"), ci_low=None),
        FakeResult(
            lever_id="cache.synthetic-c", saving=_saving("98"), ci_high=float("nan")
        ),
        FakeResult(lever_id="cache.synthetic-d", saving=_saving("97"), n_eligible=0),
    ]
    frame = compare(results, baseline="as_logged", max_tenant_share=CAP)

    assert _row(frame, "cache.synthetic-a")["rank"] == 1
    for lever in ("cache.synthetic-b", "cache.synthetic-c", "cache.synthetic-d"):
        row = _row(frame, lever)
        assert row["status"] == "insufficient evidence"
        assert pd.isna(row["rank"])
        assert row["notes"]


def test_n_eligible_below_the_results_own_minimum_is_insufficient():
    @dataclass(frozen=True)
    class WithMinimum(FakeResult):
        min_n: int | None = 500

    frame = compare(
        [WithMinimum(n_eligible=400)], baseline="as_logged", max_tenant_share=CAP
    )
    row = frame.iloc[0]
    assert row["status"] == "insufficient evidence"
    assert "min_n" in row["notes"]


def test_unknown_saving_stays_unknown_not_zero():
    unknown = FakeResult(lever_id="cache.synthetic-a", saving={})
    nan_cost = FakeResult(
        lever_id="cache.synthetic-b", baseline_cost={"total": D("NaN")}
    )
    frame = compare([unknown, nan_cost], baseline="as_logged", max_tenant_share=CAP)

    row = _row(frame, "cache.synthetic-a")
    assert row["saving"] is None and row["status"] == "insufficient evidence"
    assert _row(frame, "cache.synthetic-b")["saving_share"] is None
    text = to_markdown([unknown], max_tenant_share=CAP)
    assert "unknown" in text


def test_saving_without_total_is_the_exact_sum_of_its_blocks():
    blocks = FakeResult(
        saving={"fees": D("0.002"), "input": D("1.1"), "output": D("0.0001")},
        baseline_cost={"fees": D("1"), "input": D("2"), "output": D("1")},
    )
    row = compare([blocks], baseline="as_logged", max_tenant_share=CAP).iloc[0]
    assert row["saving"] == D("1.1021")
    assert row["saving_share"] == D("1.1021") / D("4")


def test_row_shows_slices_overhead_assumptions_and_cost_unit():
    result = FakeResult(
        overhead_ms_p50=1.5,
        overhead_ms_p95=4.0,
        assumptions=("synthetic fixture", "timestamps naive"),
    )
    row = compare([result], baseline="as_logged", max_tenant_share=CAP).iloc[0]
    assert row["llm_only_share"] == D("0.14")
    assert row["traffic_weighted_share"] == D("0.09")
    assert row["overhead"] == "p50 1.5 ms, p95 4.0 ms"
    assert row["assumptions"] == "synthetic fixture; timestamps naive"
    assert row["cost_unit"] == "recorded cost units"
    half = replace(result, overhead_ms_p50=None)
    none = replace(result, overhead_ms_p50=None, overhead_ms_p95=None)
    assert compare([half], baseline="as_logged", max_tenant_share=CAP).iloc[0][
        "overhead"
    ] == ("p50 unknown, p95 4.0 ms")
    assert (
        compare([none], baseline="as_logged", max_tenant_share=CAP).iloc[0]["overhead"]
        == "not measured"
    )
    premium = replace(result, baseline=BASELINES[0].key)
    unit = compare([premium], baseline=BASELINES[0].key, max_tenant_share=CAP).iloc[0][
        "cost_unit"
    ]
    assert "repriced" in unit and "prices-synthetic-1" in unit
