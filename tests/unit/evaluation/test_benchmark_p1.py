"""P-1: arm callability, the 35% tenant cap, pilot selection and the plan's
arithmetic (final plan "Paid branch"; ADR-0053).
SYNTHETIC catalogue, prices and IDs; no network."""

from __future__ import annotations

from collections import Counter

import pytest

from metis_auto.contracts import ModelCatalogue, PriceTable
from metis_auto.evaluation.benchmark.arms import callable_arms, check_arms
from metis_auto.evaluation.benchmark.config import (
    OwnerValueUnset,
    parse_config,
    require,
)
from metis_auto.evaluation.benchmark.pilot import Candidate, select_pilot
from metis_auto.evaluation.benchmark.plan import (
    build_plan,
    gates,
    generation_estimate,
    judge_estimate,
)
from metis_auto.evaluation.benchmark.tenant import check_tenant_cap


def _limit(v):
    return {"value": v, "evidence": {"source": "synthetic", "checked_on": "2026-11-03"}}


def _entry(model, *, provider="openai", tier=0, price_ref=None, enabled=True):
    return {
        "model_id": model,
        "provider": provider,
        "provider_model_name": model,
        "tier": tier,
        "equivalence_group": f"g{tier}",
        "context_window": _limit(100_000),
        "max_output_tokens": _limit(10_000),
        "tokenizer_ref": "syn",
        "price_ref": price_ref,
        "enabled": enabled,
    }


CATALOGUE = ModelCatalogue.model_validate(
    {
        "version": "cat-syn",
        "entries": [
            _entry("syn-a", price_ref="p-a"),
            _entry("syn-b", provider="deepseek", tier=1, price_ref="p-b"),
            _entry("syn-off", price_ref="p-a", enabled=False),
            _entry("syn-unpriced", price_ref=None),
            _entry("syn-gone", price_ref="p-a"),
            _entry("syn-gemini", provider="google", price_ref="p-a"),
        ],
    }
)


def _price(ref, kind, amount):
    return {
        "price_ref": ref,
        "token_type": kind,
        "amount": amount,
        "per_tokens": 1_000_000,
        "currency": "USD",
        "evidence": {"source": "synthetic", "checked_on": "2026-11-03"},
    }


PRICES = PriceTable.model_validate(
    {
        "version": "prices-syn",
        "entries": [
            _price("p-a", "input", "1"),
            _price("p-a", "output", "2"),
            _price("p-b", "input", "3"),
            _price("p-b", "output", "6"),
        ],
    }
)
ENTRIES = {e.model_id: e for e in CATALOGUE.entries}


def test_arms_refuse_with_a_reason_never_crash():
    statuses = check_arms(
        [
            "syn-a",
            "syn-gone",
            "syn-off",
            "syn-unpriced",
            "syn-gemini",
            "syn-b",
            "jev-latest",
            "syn-a",
        ],
        catalogue=CATALOGUE.entries,
        prices=PRICES,
        enabled_families={"openai", "deepseek"},
        not_callable={
            "syn-gone": "not callable on Metis: HTTP 404 (synthetic)",
            "jev-latest": "decision model, not a chat model",
        },
    )
    by = {s.model_id: s for s in statuses}
    assert [s.model_id for s in statuses].count("syn-a") == 1
    assert callable_arms(statuses) == ("syn-a", "syn-b")
    assert by["syn-gone"].reason.startswith("not callable on Metis")
    assert by["jev-latest"].reason == "decision model, not a chat model"
    assert by["syn-off"].reason == "disabled in the catalogue"
    assert by["syn-unpriced"].reason.startswith("not priced")
    assert "no enabled OpenAI-compatible endpoint" in by["syn-gemini"].reason
    assert by["syn-b"].tier == 1 and by["syn-b"].provider == "deepseek"


def test_the_live_check_reason_wins_over_an_enabled_catalogue_row():
    (status,) = check_arms(
        ["syn-a"],
        catalogue=CATALOGUE.entries,
        prices=PRICES,
        enabled_families={"openai"},
        not_callable={"syn-a": "gone"},
    )
    assert not status.callable and status.reason == "gone"


def test_tenant_cap_passes_fails_and_bounds_pooled_cohorts():
    ok = check_tenant_cap(
        ["t1"] * 35 + ["t2"] * 35 + ["t3"] * 30, cap=0.35, pooled=["t3"]
    )
    assert ok.passes and ok.largest_single_share == 0.35
    assert ok.pooled_upper_bound_share == 0.3
    bad = check_tenant_cap(["t1"] * 40 + ["t2"] * 60, cap=0.35)
    assert not bad.passes and bad.note == "a single tenant is above the cap"
    pooled_bad = check_tenant_cap(
        ["t1"] * 20 + ["pool"] * 80, cap=0.35, pooled=["pool"]
    )
    assert not pooled_bad.passes and "per-account counts" in pooled_bad.note
    unknown = check_tenant_cap([None, None, "t1"], cap=0.7)
    assert unknown.largest_single_share == pytest.approx(0.6667)
    with pytest.raises(ValueError):
        check_tenant_cap(["t1"], cap=0)
    with pytest.raises(ValueError):
        check_tenant_cap([], cap=0.35)


def test_tenant_shares_are_by_rank_never_by_label():
    out = check_tenant_cap(["User A"] * 3 + ["User B"], cap=1.0)
    assert out.shares_by_rank == (0.75, 0.25)
    assert "User" not in repr(out.__dict__)


def _candidates():
    langs = ["persian"] * 50 + ["english"] * 10 + ["mixed"] * 10
    return [
        Candidate(f"syn-r{i:03d}", f"t{i % 3}" if i < 60 else "big", lang)
        for i, lang in enumerate(langs)
    ]


def test_pilot_is_deterministic_spreads_languages_and_keeps_the_cap():
    a = select_pilot(_candidates(), size=20, seed="s1", cap=0.35)
    assert a == select_pilot(_candidates(), size=20, seed="s1", cap=0.35)
    assert a != select_pilot(_candidates(), size=20, seed="s2", cap=0.35)
    assert len(a) == 20 and len(set(a)) == 20
    by = {c.record_id: c for c in _candidates()}
    assert {by[r].language_group for r in a} == {"persian", "english", "mixed"}
    tenants = Counter(by[r].tenant for r in a)
    assert max(tenants.values()) <= 7  # floor(0.35 * 20)


def test_pilot_stops_short_rather_than_break_the_cap():
    one_tenant = [Candidate(f"syn-{i}", "t", "persian") for i in range(30)]
    assert len(select_pilot(one_tenant, size=20, seed="s", cap=0.35)) == 7
    with pytest.raises(ValueError):
        select_pilot(one_tenant, size=0, seed="s", cap=0.35)
    with pytest.raises(ValueError):
        select_pilot(one_tenant, size=5, seed="", cap=0.35)


def test_generation_estimate_needs_sizes_and_the_owner_limit():
    tokens = {("r1", "syn-a"): 1000, ("r2", "syn-a"): 2000}
    est = generation_estimate(
        ["r1", "r2"],
        ["syn-a"],
        input_tokens=tokens,
        catalogue=ENTRIES,
        prices=PRICES,
        max_output_tokens=None,
    )
    assert est["calls"] == 2 and est["lower_bound_usd"] == "0.003"
    assert est["ceiling_usd"] is None
    assert est["reasons"]["ceiling_usd"] == "max_output_tokens_unset"
    est = generation_estimate(
        ["r1", "r2"],
        ["syn-a"],
        input_tokens=tokens,
        catalogue=ENTRIES,
        prices=PRICES,
        max_output_tokens=500,
    )
    assert est["ceiling_usd"] == "0.005"  # 3000 x 1 + 1000 x 2 per million
    missing = generation_estimate(
        ["r1"],
        ["syn-b"],
        input_tokens=tokens,
        catalogue=ENTRIES,
        prices=PRICES,
        max_output_tokens=1,
    )
    assert missing["lower_bound_usd"] is None


def test_judge_estimate_counts_both_judges_both_orders():
    common = dict(catalogue=ENTRIES, prices=PRICES)
    unset = judge_estimate(
        ["r1"],
        ["syn-a", "syn-b"],
        judges=None,
        judge_input_tokens=None,
        candidate_max_tokens=None,
        judge_max_output=None,
        **common,
    )
    assert unset["calls"] == 1 * 2 * 2 * 2
    assert unset["reasons"] == {"all": "set by owner: judges.models"}
    sizes = {("r1", "syn-a"): 1000, ("r1", "syn-b"): 1000}
    est = judge_estimate(
        ["r1"],
        ["syn-a", "syn-b"],
        judges=("syn-a", "syn-b"),
        judge_input_tokens=sizes,
        candidate_max_tokens=100,
        judge_max_output=10,
        **common,
    )
    # lower: 1000 input per call x 4 calls per judge (2 arms x 2 orders)
    assert est["lower_bound_usd"] == "0.016"  # 4 x (0.001 + 0.003)
    assert est["ceiling_usd"] is not None
    no_limit = judge_estimate(
        ["r1"],
        ["syn-a"],
        judges=("syn-a", "syn-b"),
        judge_input_tokens=sizes,
        candidate_max_tokens=None,
        judge_max_output=10,
        **common,
    )
    assert no_limit["ceiling_usd"] is None
    assert no_limit["reasons"]["ceiling_usd"] == "set by owner: run.max_output_tokens"


RAW = {
    "version": "syn",
    "set": {
        "dataset_id": "golden-v2",
        "reference_run_id": "ga",
        "reference_model": "gpt-5.5",
        "shareable_ids": "x.parquet",
        "tenant_cap": 0.35,
    },
    "pilot": {"size": 20, "seed": "s"},
    "arms": {"requested": ["syn-a"]},
    "spend_share": {"summaries_dir": "reports/spend/ledgers"},
    "spot_check": {"size": 60, "seed": "s"},
}


def test_config_lists_every_unset_owner_value_and_refuses_bad_values():
    config = parse_config(RAW)
    unset = config.unset_owner_values()
    for key in (
        "run.hard_cap_usd",
        "run.max_output_tokens",
        "judges.models",
        "labels.acceptable_score",
        "labels.cheap_arms",
        "spend_share.max_age_hours",
    ):
        assert key in unset
    with pytest.raises(OwnerValueUnset, match="set by owner: judges.models"):
        require(config.judges.models, "judges.models")
    with pytest.raises(ValueError):
        parse_config({**RAW, "judges": {"models": ["syn-a"]}})
    with pytest.raises(ValueError):
        parse_config({**RAW, "gates": {"metis_allows_samples": True}})
    with pytest.raises(ValueError):
        parse_config({**RAW, "typo": 1})


def test_plan_lists_gates_owner_values_and_never_calls():
    config = parse_config(RAW)
    arms = check_arms(
        ["syn-a", "syn-gone"],
        catalogue=CATALOGUE.entries,
        prices=PRICES,
        enabled_families={"openai"},
        not_callable={"syn-gone": "gone"},
    )
    plan = build_plan(
        config,
        arms=arms,
        records=["r1", "r2"],
        generation={},
        judging={},
        budget={},
        gate_list=gates(amendment_committed=True, samples_allowed=False),
        tenant=None,
    )
    assert plan["makes_calls"] is False and plan["callable_arms"] == ["syn-a"]
    assert [g["state"] for g in plan["gates"]] == ["met", "missing", "per_run"]
    assert "judges.models" in plan["owner_values_unset"]
