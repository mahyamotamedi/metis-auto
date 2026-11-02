"""F-2 cost trace (exp-cost-002). SYNTHETIC billing JSON only."""

import json
from decimal import Decimal

import pytest

CHECK = "cost/exp-cost-002-cost-trace/check.py"


@pytest.fixture(scope="module")
def f2(load_experiment):
    return load_experiment(CHECK)


def item(total, breakdown=None, **kw):
    out = {"totalCost": total, "callCount": 1}
    if breakdown is not None:
        out["costBreakdown"] = breakdown
    out.update(kw)
    return out


def blocks_sum(trace):
    return sum(trace["blocks"].values(), Decimal(0))


def test_blocks_sum_to_total_cost(f2):
    raw = json.dumps(
        [
            item(0.01, {"input_tokens": 0.006, "output_tokens": 0.003}),  # gap 0.001
            item(0.002, {"per_call": 0.002}),
            item(0.005, None, usageCost=0.004, fixedCost=0.001, inputTokens=9),
            item(0.003, {}),  # empty breakdown
            item(0.001, {"cache_write_tokens": 0.0004, "new_kind": 0.0006}),
            item(-0.002, {"per_call": -0.002}),  # signed adjustment kept
            "not a dict",
            item("n/a", {"per_call": 0.002}),  # non-numeric total
            item(0.004, {"input_tokens": "x", "output_tokens": 0.004}),
        ]
    )
    t = f2.trace_message(raw)
    assert t["state"] == "items"
    assert blocks_sum(t) == t["total"]
    b = t["blocks"]
    assert b["fees"] == Decimal("0")  # 0.002 + (-0.002); the n/a item is unknown
    assert b["input"] == Decimal("0.006")
    assert b["output"] == Decimal("0.007")
    assert b["breakdown_gap"] == Decimal("0.001")  # the bad value stays in total
    assert b["unbroken_usage"] == Decimal("0.004")
    assert b["unbroken_fixed"] == Decimal("0.001")
    assert b["unresolved"] == Decimal("0.003")  # the empty breakdown
    assert b["cache_write"] == Decimal("0.0004")
    assert b["breakdown_other"] == Decimal("0.0006")
    assert t["other_keys"] == {"new_kind": 1}
    assert t["counts"]["items_not_dict"] == 1
    assert t["counts"]["items_total_unknown"] == 1
    assert t["counts"]["breakdown_values_malformed"] == 1
    assert t["counts"]["negative_entries"] == 2  # the item total and its fee
    assert t["total"] == Decimal("0.023")


def test_missing_and_malformed_billing_is_unknown_not_zero(f2):
    for raw, state in (
        (None, "null"),
        ("[", "malformed"),
        ('{"a": 1}', "malformed"),
        ("[]", "empty_list"),
    ):
        t = f2.trace_message(raw)
        assert t["state"] == state
        assert t["total"] is None
        assert all(v == 0 for v in t["blocks"].values())


def test_income_breakdown_is_never_counted_as_cost(f2):
    raw = json.dumps(
        [
            item(
                0.01,
                {"input_tokens": 0.01},
                incomeBreakdown={"input_tokens": 0.02},
                totalIncome=0.02,
            )
        ]
    )
    t = f2.trace_message(raw)
    assert t["blocks"]["input"] == Decimal("0.01")
    assert blocks_sum(t) == t["total"] == Decimal("0.01")


def test_unbroken_item_without_usage_split_is_unresolved(f2):
    raw = json.dumps([item(0.003, None, webSearchCalls=2, audioInputTokens=5)])
    t = f2.trace_message(raw)
    assert t["blocks"]["unresolved"] == Decimal("0.003")
    assert t["counts"]["unbroken_with_web_search"] == 1
    assert t["counts"]["unbroken_with_audio"] == 1


def test_reconcile_aggregates_with_coverage_and_labelled_remainder(f2):
    raws = [
        json.dumps([item(0.01, {"input_tokens": 0.01})]),
        json.dumps([item(0.002, {"per_call": 0.002})]),
        json.dumps([item(0.004, None, usageCost=0.004, fixedCost=0, inputTokens=3)]),
        None,
        "[]",
    ]
    r = f2.reconcile([f2.trace_message(x) for x in raws])
    assert r["coverage"]["messages"] == 5
    assert r["coverage"]["by_state"] == {"items": 3, "null": 1, "empty_list": 1}
    assert r["total"] == Decimal("0.016")
    assert r["blocks"]["unbroken_usage"] == Decimal("0.004")
    assert r["check"]["blocks_minus_total"] == Decimal(0)
    assert r["shares"]["fees"] == pytest.approx(0.125)
    rows = {row["block"]: row for row in r["waterfall"]}
    assert rows["unbroken_usage"]["group"] == "other"
    assert rows["unbroken_usage"]["label"]  # every remainder piece is named
    assert rows["fees"]["group"] == "fees"
    assert sum(row["amount"] for row in r["waterfall"]) == r["total"]
    assert r["lever_blocks"] == {
        "fees": Decimal("0.002"),
        "token_cost": Decimal("0.014"),
    }


def test_nan_billing_from_a_frame_is_null_not_an_error(f2):
    t = f2.trace_message(float("nan"))
    assert t["state"] == "null"
    assert t["total"] is None
