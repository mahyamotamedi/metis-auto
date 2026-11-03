"""The decision router's cost view (exp-route-013): the same logged tokens
priced on today's, the rules' and the router's model with an injected price
function; unpriced records counted, not guessed; extra reasoning output only in
its own variant. SYNTHETIC IDs and prices; no network."""

from __future__ import annotations

from decimal import Decimal

from metis_auto.evaluation.router_eval import ShadowRow
from metis_auto.evaluation.router_eval.costs import compare_costs

PER_TOKEN = {
    "syn-today": Decimal("0.010"),
    "syn-cheap": Decimal("0.001"),
    "syn-mid": Decimal("0.005"),
}
OUTPUT = {"s1": 100, "s2": 100, "s3": 100}


def price(model, record_id, extra):
    if model not in PER_TOKEN or record_id not in OUTPUT:
        return None
    return PER_TOKEN[model] * (OUTPUT[record_id] + extra)


def extra(model):
    return 50 if model == "syn-cheap" else 0


def _row(rid, rules, router, split="tune"):
    return ShadowRow(
        rid,
        split,
        "persian",
        None,
        None,
        None,
        "slow_hosted",
        "answered",
        None,
        False,
        None,
        rules_target=rules,
        router_target=router,
    )


def _rec(rid, today="syn-today"):
    return {"slice_record_id": rid, "provider_model": today}


def test_same_tokens_on_three_models_with_savings_and_moves():
    rows = [
        _row("s1", "syn-mid", "syn-cheap"),
        _row("s2", "syn-mid", "syn-mid", split="check"),
    ]
    out = compare_costs(
        rows,
        [_rec("s1"), _rec("s2")],
        price=price,
        extra_output=extra,
        price_basis="synthetic",
    )
    block = out["logged_tokens"]["all"]
    assert block["priced"] == 2 and block["router_moved_from_today"] == 2
    assert block["router_differs_from_rules"] == 1
    assert block["total_usd"] == {"today": "2", "rules": "1", "router": "0.6"}
    assert block["router_saving_vs_today_share"] == 0.7
    assert block["router_saving_vs_rules_share"] == 0.4
    assert out["logged_tokens"]["check"]["records"] == 1
    reasoning = out["with_expected_reasoning"]["all"]
    assert reasoning["total_usd"]["router"] == "0.65"  # cheap model + 50 tokens
    assert reasoning["total_usd"]["today"] == "2"
    assert out["evidence"].startswith("cost simulation")


def test_unpriced_or_missing_models_are_counted_not_priced():
    rows = [
        _row("s1", "syn-mid", None),
        _row("s2", "syn-mid", "syn-x"),
        _row("s3", "syn-mid", "syn-mid"),
        _row("s9", "syn-mid", "syn-mid"),
    ]
    recs = [_rec("s1"), _rec("s2"), _rec("s3", today="unknown-model")]
    out = compare_costs(
        rows, recs, price=price, extra_output=extra, price_basis="synthetic"
    )
    block = out["logged_tokens"]["all"]
    assert block["records"] == 3 and block["priced"] == 0
    assert block["unpriced"] == {
        "router_no_model": 1,
        "router_unpriced": 1,
        "today_unpriced": 1,
    }
    assert block["router_saving_vs_today_share"] is None


def _row(rid, rules, router, **kw):
    from metis_auto.evaluation.router_eval import ShadowRow

    return ShadowRow(
        record_id=rid,
        split=kw.pop("split", "tune"),
        language_group="persian",
        weight=None,
        rules_tier=kw.pop("rt", 1),
        router_tier=kw.pop("jt", 1),
        router_path="slow_hosted",
        decision_status=kw.pop("status", "answered"),
        confidence=None,
        below_gate=False,
        decide_ms=None,
        rules_target=rules,
        router_target=router,
        **kw,
    )


def test_differences_only_where_both_chose_and_differ():
    from metis_auto.evaluation.router_eval import DIFFERENCE_COLUMNS, differences

    rows = [
        _row("b", "m1", "m0", jt=0, gate_probability=0.7, gate_reported=0.6),
        _row("a", "m1", "m1"),
        _row("c", None, "m0", jt=0),
        _row("d", "m1", None, jt=None),
        _row("e", "m1", "m0", jt=0, split="check"),
    ]
    out = differences(rows)
    assert [d["record_id"] for d in out] == ["e", "b"]  # check < tune
    assert tuple(out[1]) == DIFFERENCE_COLUMNS
    assert out[1]["jev_probability"] == 0.7 and out[1]["jev_tier"] == 0


def test_skip_breakdown_counts_paths_and_no_model_reasons():
    from metis_auto.evaluation.router_eval import skip_breakdown

    rows = [
        _row("a", "m1", "m1", status="skipped", skip_reason="rules_decisive"),
        _row(
            "b",
            None,
            None,
            status="skipped",
            rules_reason="no_eligible_model",
            rules_exclusions=("modality_unsupported",),
        ),
        _row("c", "m1", "m1"),
    ]
    out = skip_breakdown(rows)
    assert out["skipped_by_path_and_reason"] == {
        "slow_hosted/none": 1,
        "slow_hosted/rules_decisive": 1,
    }
    assert out["rules_no_model_by_reason"] == {"no_eligible_model": 1}
    assert out["rules_no_model_exclusions"] == {"modality_unsupported": 1}


def test_net_of_decision_cost_adds_jev_calls():
    from decimal import Decimal

    from metis_auto.wiring.router_eval import net_of_decision_cost

    costs = {
        "logged_tokens": {
            "all": {"total_usd": {"today": "1", "rules": "0.5", "router": "0.4"}}
        }
    }
    out = net_of_decision_cost(costs, Decimal("0.1"))["logged_tokens"]
    assert out["router_incl_decision_usd"] == "0.5"
    assert out["saving_vs_rules_usd"] == "0"
    assert out["saving_vs_today_share"] == 0.5
