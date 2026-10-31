"""E4 sampler: allocation, selection, weights, unmet quotas. SYNTHETIC units;
expected allocations are worked out by hand in the comments."""

import pytest

from metis_auto.evaluation.sampling import (
    AllocationConfig,
    SamplingUnit,
    parse_allocation_config,
    plan_sample,
    slice_counts,
)


def make_units(fa=80, en=15, mixed=5, with_length=False):
    units = []
    for language, n in (("fa", fa), ("en", en), ("mixed", mixed)):
        for i in range(n):
            strata = {"language": language}
            if with_length:
                strata["length_bucket"] = str(i % 3)
            units.append(
                SamplingUnit(f"{language}-{i}", f"s-{language}-{i // 2}", strata)
            )
    return units


def config(**kw):
    base = {"dimensions": ("language",), "total": 20, "seed": "seed-a"}
    return AllocationConfig(**{**base, **kw})


def achieved(plan):
    return {c.label.split("=", 1)[1]: c.achieved for c in plan.cells}


def test_nothing_is_set_by_default_and_unset_values_say_why():
    units = make_units()
    assert plan_sample(units, AllocationConfig()).reason == "dimensions_unset"
    assert (
        plan_sample(units, AllocationConfig(dimensions=("language",))).reason
        == "total_unset"
    )
    assert (
        plan_sample(units, AllocationConfig(dimensions=("language",), total=5)).reason
        == "seed_unset"
    )
    needs = AllocationConfig(
        dimensions=("length_bucket",), total=5, seed="s", quotas={"en": 3}
    )
    assert plan_sample(units, needs).reason == "quota_needs_language_dimension"
    assert plan_sample(units, AllocationConfig()).state == "not_evaluated"


def test_proportional_allocation_by_hand():
    plan = plan_sample(make_units(), config())  # 80/15/5 of 20 = 16 / 3 / 1
    assert achieved(plan) == {"fa": 16, "en": 3, "mixed": 1}
    assert (plan.achieved_total, plan.over_budget_by, plan.state) == (20, 0, "planned")


def test_a_minority_quota_is_met_first_and_the_rest_is_proportional():
    plan = plan_sample(make_units(), config(quotas={"en": 8}))
    # en: 8 by quota; 12 remain, split 9.6 / 1.8 / 0.6 -> fa 10, en +2, mixed 0
    assert achieved(plan) == {"fa": 10, "en": 10, "mixed": 0}
    assert [q.status for q in plan.quotas] == ["met"]
    reasons = {c.label: c.reasons for c in plan.cells}
    assert "quota" in reasons["language=en"]


def test_an_unmet_quota_reports_the_achieved_n_and_is_not_topped_up():
    plan = plan_sample(make_units(), config(quotas={"mixed": 10}))
    (quota,) = plan.quotas
    assert (quota.requested, quota.achieved, quota.status) == (10, 5, "unmet")
    assert quota.reason == "population_smaller_than_quota"
    assert achieved(plan)["mixed"] == 5  # everything there is, never more


def test_floors_and_quotas_are_not_trimmed_when_they_exceed_the_total():
    plan = plan_sample(make_units(), config(total=3, floor_per_cell=2))
    assert achieved(plan) == {"fa": 2, "en": 2, "mixed": 2}
    assert (plan.achieved_total, plan.over_budget_by) == (6, 3)


def test_rare_cells_are_pooled_within_the_first_dimension():
    units = make_units(with_length=True)
    plan = plan_sample(
        units,
        config(dimensions=("language", "length_bucket"), pool_below_n=6, total=20),
    )
    pooled = [c for c in plan.cells if c.pooled]
    assert pooled and all("*pooled*" in c.label for c in pooled)
    # mixed has 5 units in all: every mixed cell is below 6, so one pooled cell
    mixed = [c for c in plan.cells if "language=mixed" in c.label]
    assert len(mixed) == 1 and mixed[0].population == 5


def test_selection_is_deterministic_and_independent_of_input_order():
    units = make_units()
    a = plan_sample(units, config())
    again = plan_sample(list(reversed(units)), config())
    other = plan_sample(units, config(seed="seed-b"))
    assert set(a.selected_ids()) == set(again.selected_ids())
    assert set(a.selected_ids()) != set(other.selected_ids())
    assert len(set(a.selected_ids())) == a.achieved_total  # without replacement


def test_weights_are_stored_apart_from_allocation_and_recover_the_population():
    units = make_units()
    plan = plan_sample(units, config(quotas={"en": 8}))  # fa 10, en 10, mixed 0
    by_cell = {s.cell: s for s in plan.selected}
    assert by_cell["language=fa"].selection_probability == pytest.approx(10 / 80)
    assert by_cell["language=fa"].weight == pytest.approx(8.0)
    assert by_cell["language=en"].weight == pytest.approx(1.5)
    rows = {r.value: r for r in slice_counts(plan, units, "language", min_n=None)}
    # allocation oversamples en (10 of 20 drawn), the population share is 15%
    assert rows["en"].sample_share == pytest.approx(0.5)
    assert rows["en"].population_share == pytest.approx(0.15)
    # the weighted shares recover the population over the cells that were drawn
    assert rows["en"].weighted_share / rows["fa"].weighted_share == pytest.approx(
        15 / 80
    )


def test_slice_counts_label_insufficient_slices_and_list_persian_first():
    units = make_units()
    plan = plan_sample(units, config(quotas={"en": 8}))
    rows = slice_counts(plan, units, "language", min_n=10)
    assert [r.value for r in rows][0] == "fa"
    states = {r.value: (r.sufficiency, r.sufficiency_reason) for r in rows}
    assert states["mixed"] == ("insufficient", "n_below_minimum")
    assert states["fa"] == ("sufficient", None)
    unset = slice_counts(plan, units, "language", min_n=None)
    assert {r.sufficiency_reason for r in unset} == {"min_n_unset"}


def test_config_validation():
    with pytest.raises(ValueError):
        parse_allocation_config({"total": -1})
    with pytest.raises(ValueError):
        parse_allocation_config({"dimensions": []})
    with pytest.raises(ValueError):
        parse_allocation_config({"surprise": 1})
    assert parse_allocation_config({}).total is None
