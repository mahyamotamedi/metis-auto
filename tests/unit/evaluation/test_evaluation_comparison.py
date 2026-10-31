"""Baselines and comparison metrics (Stage E1). SYNTHETIC numbers; expected
values are worked out by hand in the comments."""

import pytest

from metis_auto.evaluation.comparison import (
    PRIMARY_LANGUAGE,
    BaselineSpec,
    Estimate,
    EvalRequest,
    Outcome,
    OutcomeTable,
    apgr,
    as_logged_assignment,
    by_language,
    cluster_bootstrap,
    cost_at_quality,
    cpt,
    fixed_assignment,
    holm,
    non_inferiority,
    oracle_assignment,
    oracle_headroom,
    paired_effect,
    pareto_front,
    pgr,
    quality_at_cost,
    random_mix_expected,
    rank_estimates,
    sufficient,
    system_point,
)

FA = PRIMARY_LANGUAGE


def req(rid, session, language, cheap, mid, prem):
    outcomes = {"cheap": Outcome(*cheap), "mid": Outcome(*mid), "prem": Outcome(*prem)}
    return EvalRequest(rid, session, language, outcomes)


# fa slice, per model (cost, quality):
#   cheap: cost 1,  quality (0.6 + 0.9 + 0.2 + 0.5) / 4 = 0.55
#   mid:   cost 2,  quality (0.8 + 0.9 + 0.7 + 0.5) / 4 = 0.725
#   prem:  cost 10, quality (0.9 + 0.9 + 1.0 + 0.5) / 4 = 0.825
REQUESTS = (
    req("r1", "s1", FA, (1, 0.6), (2, 0.8), (10, 0.9)),
    req("r2", "s1", FA, (1, 0.9), (2, 0.9), (10, 0.9)),
    req("r3", "s2", FA, (1, 0.2), (2, 0.7), (10, 1.0)),
    req("r4", "s3", FA, (1, 0.5), (2, 0.5), (10, 0.5)),
    req("r5", "s4", "en", (1, 0.5), (2, 0.5), (10, 1.0)),
)


def table(requests=REQUESTS, validated=True):
    return OutcomeTable(requests, "estimated", "measured", validated)


FA_TABLE = table().language(FA)


# --- types ------------------------------------------------------------------


def test_estimate_invariants():
    with pytest.raises(ValueError):
        Estimate("measured", 1, "measured")  # measured needs a value
    with pytest.raises(ValueError):
        Estimate("insufficient", 1, "measured", value=1.0, reason="x")
    with pytest.raises(ValueError):
        Estimate("insufficient", 1, "measured")  # needs a reason
    assert not Estimate("measured", 1, "measured", value=1.0).claims_allowed
    assert Estimate(
        "measured", 1, "measured", value=1.0, interval=(0.0, 2.0)
    ).claims_allowed


def test_table_validates_provenance_and_unique_ids():
    with pytest.raises(ValueError):
        OutcomeTable((), "guessed", "measured", True)
    with pytest.raises(ValueError):
        OutcomeTable((REQUESTS[0], REQUESTS[0]), "measured", "measured", True)
    assert table().provenance == "cost=estimated,quality=measured"


def test_sufficiency_never_passes_an_unset_minimum():
    assert sufficient(5, None) == (False, "min_n_unset")
    assert sufficient(5, 6) == (False, "n_below_minimum")
    assert sufficient(6, 6) == (True, None)


def test_baseline_spec_validates():
    BaselineSpec("premium", "fixed_model", "prem")
    with pytest.raises(ValueError):
        BaselineSpec("x", "fixed_model")
    with pytest.raises(ValueError):
        BaselineSpec("x", "teleport")


# --- system points and baselines --------------------------------------------


def test_fixed_systems_by_hand():
    prem = system_point(FA_TABLE, fixed_assignment(FA_TABLE, "prem"), "premium")
    cheap = system_point(FA_TABLE, fixed_assignment(FA_TABLE, "cheap"), "cheap")
    assert (prem.n, prem.mean_cost, prem.mean_quality) == (4, 10, 0.825)
    assert (cheap.mean_cost, cheap.mean_quality) == (1, 0.55)
    assert prem.provenance == "cost=estimated,quality=measured"


def test_as_logged_leaves_unmapped_requests_out_and_reports_coverage():
    logged = {"r1": "mid", "r2": None, "r3": "mid"}  # r4 absent, r2 unmapped
    assignment = as_logged_assignment(FA_TABLE, logged)
    assert assignment == {"r1": "mid", "r3": "mid"}
    point = system_point(FA_TABLE, assignment, "as_logged")
    assert (point.n, point.total, point.coverage) == (2, 4, 0.5)
    assert point.mean_quality == (0.8 + 0.7) / 2


def test_random_mix_expected_by_hand():
    point = random_mix_expected(FA_TABLE, {"cheap": 0.5, "prem": 0.5})
    # cost 0.5*1 + 0.5*10 = 5.5; quality mean of .75, .9, .6, .5
    assert point.mean_cost == 5.5
    assert point.mean_quality == pytest.approx((0.75 + 0.9 + 0.6 + 0.5) / 4)
    with pytest.raises(ValueError):
        random_mix_expected(FA_TABLE, {"cheap": 0.5, "prem": 0.4})


def test_oracle_best_quality_takes_ties_to_the_cheapest():
    result = oracle_assignment(FA_TABLE, mode="best_quality", noise_margin=0.0)
    assert result.state == "measured"
    assert result.assignment == {
        "r1": "prem",
        "r2": "cheap",
        "r3": "prem",
        "r4": "cheap",
    }
    point = system_point(FA_TABLE, result.assignment, "oracle")
    assert (point.mean_cost, point.mean_quality) == (5.5, 0.825)


def test_oracle_noise_margin_widens_the_ties():
    result = oracle_assignment(FA_TABLE, mode="best_quality", noise_margin=0.1)
    assert result.assignment["r1"] == "mid"  # 0.8 is within 0.1 of 0.9
    point = system_point(FA_TABLE, result.assignment, "oracle")
    assert (point.mean_cost, point.mean_quality) == (3.5, 0.8)


def test_oracle_cheapest_within_delta_of_a_reference():
    result = oracle_assignment(
        FA_TABLE, mode="cheapest_within_delta", reference_model="prem", delta=0.1
    )
    assert result.assignment == {
        "r1": "mid",
        "r2": "cheap",
        "r3": "prem",
        "r4": "cheap",
    }


@pytest.mark.parametrize(
    "kwargs, validated, reason",
    [
        ({"mode": "best_quality", "noise_margin": 0.0}, False, "unvalidated_quality"),
        ({"mode": "best_quality"}, True, "noise_margin_unset"),
        (
            {"mode": "cheapest_within_delta", "reference_model": "prem"},
            True,
            "delta_unset",
        ),
    ],
)
def test_oracle_is_not_evaluated_without_validation_or_its_parameters(
    kwargs, validated, reason
):
    result = oracle_assignment(table(validated=validated).language(FA), **kwargs)
    assert (result.state, result.reason, result.assignment) == (
        "not_evaluated",
        reason,
        {},
    )


def test_oracle_counts_requests_it_cannot_decide():
    missing = req("r9", "s9", FA, (None, None), (None, 0.5), (3, None))
    result = oracle_assignment(
        table(REQUESTS + (missing,)).language(FA), mode="best_quality", noise_margin=0.0
    )
    assert result.skipped == 1 and "r9" not in result.assignment


# --- fronts, curves, recovery, headroom -------------------------------------


def test_pareto_front_drops_dominated_points():
    points = [("a", 1, 0.5), ("b", 2, 0.7), ("c", 3, 0.6), ("d", 10, 0.9)]
    assert [p[0] for p in pareto_front(points)] == ["a", "b", "d"]


CURVE = [(1, 0.5), (2, 0.7), (10, 0.9)]


def test_quality_at_matched_cost_interpolates_and_refuses_extrapolation():
    est = quality_at_cost(CURVE, 6, n=4, provenance="p")
    assert est.value == pytest.approx(0.8)  # 0.7 + 0.2 * 4/8
    assert quality_at_cost(CURVE, 0.5, n=4, provenance="p").reason == (
        "target_outside_curve"
    )


def test_cost_at_matched_quality():
    assert cost_at_quality(CURVE, 0.8, n=4, provenance="p").value == pytest.approx(6.0)
    assert cost_at_quality(CURVE, 0.4, n=4, provenance="p").value == 1
    assert (
        cost_at_quality(CURVE, 0.95, n=4, provenance="p").reason == "target_not_reached"
    )


def test_cpt_is_the_least_strong_call_share_reaching_the_target():
    curve = [(0.0, 0.5), (0.5, 0.7), (1.0, 0.9)]
    assert cpt(curve, 0.8, n=4, provenance="p").value == pytest.approx(0.75)
    assert cpt(curve, 0.99, n=4, provenance="p").state == "undefined"


def test_pgr_by_hand_and_the_gap_guard():
    est = pgr(0.725, 0.55, 0.825, min_gap=0.01, n=4, provenance="p")
    assert est.value == pytest.approx(0.175 / 0.275)
    assert est.extra["gap"] == pytest.approx(0.275)
    near_zero = pgr(0.5, 0.5, 0.505, min_gap=0.1, n=4, provenance="p")
    assert (near_zero.state, near_zero.reason) == ("undefined", "gap_below_minimum")
    assert near_zero.extra["gap"] == pytest.approx(0.005)  # the gap is shown
    unset = pgr(0.5, 0.5, 0.9, min_gap=None, n=4, provenance="p")
    assert (unset.state, unset.reason) == ("not_evaluated", "min_gap_unset")


def test_apgr_over_a_linear_curve_is_one_half():
    curve = [(0.0, 0.5), (1.0, 0.9)]
    est = apgr(curve, 0.5, 0.9, n_points=3, min_gap=0.01, n=4, provenance="p")
    assert est.value == pytest.approx(0.5)  # PGR 0, 0.5, 1 at shares 0, 0.5, 1
    short = apgr(
        [(0.0, 0.5), (0.6, 0.8)],
        0.5,
        0.9,
        n_points=3,
        min_gap=0.01,
        n=4,
        provenance="p",
    )
    assert short.reason == "curve_does_not_span_0_to_1"
    with pytest.raises(ValueError):
        apgr(curve, 0.5, 0.9, n_points=1, min_gap=0.01, n=4, provenance="p")


def test_oracle_headroom_by_hand_and_guard():
    est = oracle_headroom(10, 7, 5, min_gap=0.1, n=4, provenance="p")
    assert est.value == pytest.approx(0.6)  # (10 - 7) / (10 - 5)
    assert oracle_headroom(10, 7, 9.95, min_gap=0.1, n=4, provenance="p").state == (
        "undefined"
    )


# --- bootstrap and Holm -----------------------------------------------------


def test_bootstrap_resamples_clusters_not_items():
    items = [(0.0, "a")] * 50 + [(1.0, "b")] * 50

    def mean(xs):
        return sum(v for v, _ in xs) / len(xs)

    result = cluster_bootstrap(
        items, lambda it: it[1], mean, n_boot=400, seed="x", level=0.95
    )
    assert result.point == 0.5 and result.n_clusters == 2
    # with two clusters a replicate mean is 0, 0.5 or 1: item-level resampling
    # would give a far narrower interval
    assert (result.low, result.high) == (0.0, 1.0)


def test_bootstrap_is_seeded_and_validates_its_arguments():
    items = [(float(i), f"s{i % 7}") for i in range(40)]

    def mean(xs):
        return sum(v for v, _ in xs) / len(xs)

    def run(seed):
        return cluster_bootstrap(
            items, lambda it: it[1], mean, n_boot=100, seed=seed, level=0.9
        )

    assert run("a").replicates == run("a").replicates
    assert run("a").replicates != run("b").replicates
    with pytest.raises(ValueError):
        cluster_bootstrap(items, lambda it: it[1], mean, n_boot=0, seed=1, level=0.9)
    with pytest.raises(ValueError):
        cluster_bootstrap(items, lambda it: it[1], mean, n_boot=5, seed=1, level=1.0)


def test_holm_step_down():
    rejected = holm({"a": 0.01, "b": 0.04, "c": 0.03}, 0.05)
    assert rejected == {"a": True, "b": False, "c": False}


# --- paired effects and non-inferiority -------------------------------------

BOOT = {"n_boot": 200, "seed": "seed", "level": 0.95}


def paired_table(candidate_drop, validated=True, n_sessions=30):
    requests = []
    for s in range(n_sessions):
        for k in range(2):
            q = 0.5 + 0.01 * ((s + k) % 5)
            requests.append(
                req(f"r{s}_{k}", f"s{s}", FA, (1, q - candidate_drop), (2, q), (10, q))
            )
    return table(tuple(requests), validated)


def test_paired_cost_ratio_by_hand():
    est = paired_effect(
        FA_TABLE,
        fixed_assignment(FA_TABLE, "mid"),
        fixed_assignment(FA_TABLE, "prem"),
        quantity="cost_ratio",
        min_n=1,
        **BOOT,
    )
    assert est.value == pytest.approx(0.2)  # 8 / 40
    assert est.state == "measured" and est.interval is not None and est.n == 4


def test_non_inferiority_uses_the_interval_not_the_point():
    t = paired_table(0.01)  # candidate is always 0.01 below the reference
    cand, ref = fixed_assignment(t, "cheap"), fixed_assignment(t, "prem")
    passes = non_inferiority(t, cand, ref, delta=0.05, min_n=10, **BOOT)
    assert passes.non_inferior is True and passes.p_value == 0.0
    assert passes.estimate.value == pytest.approx(-0.01)
    fails = non_inferiority(t, cand, ref, delta=0.005, min_n=10, **BOOT)
    assert fails.non_inferior is False and fails.p_value == 1.0


@pytest.mark.parametrize(
    "delta, validated, min_n, state, reason",
    [
        (None, True, 10, "not_evaluated", "delta_unset"),
        (0.05, False, 10, "not_evaluated", "unvalidated_quality"),
        (0.05, True, None, "insufficient", "min_n_unset"),
        (0.05, True, 1000, "insufficient", "n_below_minimum"),
    ],
)
def test_non_inferiority_says_why_it_is_not_evaluated(
    delta, validated, min_n, state, reason
):
    t = paired_table(0.01, validated=validated)
    result = non_inferiority(
        t,
        fixed_assignment(t, "cheap"),
        fixed_assignment(t, "prem"),
        delta=delta,
        min_n=min_n,
        **BOOT,
    )
    assert (result.estimate.state, result.estimate.reason) == (state, reason)
    assert result.non_inferior is None and result.p_value is None
    assert result.estimate.value is None


# --- language slicing -------------------------------------------------------


def mean_prem_quality(sub):
    values = [r.outcomes["prem"].quality for r in sub.requests]
    return Estimate(
        "measured",
        len(values),
        sub.provenance,
        value=sum(values) / len(values),
        interval=(0.0, 1.0),
    )


def test_persian_is_primary_overall_is_labelled_and_small_slices_are_insufficient():
    slices = by_language(table(), mean_prem_quality, min_n=3)
    assert slices.primary.measured and slices.primary.n == 4
    assert slices.overall.measured and slices.overall_label == "dominated_by_persian"
    assert slices.others["en"].state == "insufficient"
    assert slices.others["en"].value is None and slices.others["en"].n == 1
    assert slices.others["en"].reason == "n_below_minimum"


def test_an_unset_minimum_makes_every_slice_insufficient():
    slices = by_language(table(), mean_prem_quality, min_n=None)
    states = [slices.primary.state, slices.overall.state, slices.others["en"].state]
    assert states == ["insufficient"] * 3
    assert slices.primary.reason == "min_n_unset"


def test_no_persian_requests_means_an_insufficient_primary_slice():
    only_en = table((REQUESTS[4],))
    slices = by_language(only_en, mean_prem_quality, min_n=1)
    assert slices.primary.state == "insufficient" and slices.primary.n == 0


def test_only_slices_that_allow_claims_are_ranked():
    estimates = {
        "a": Estimate("measured", 9, "p", value=0.2, interval=(0.1, 0.3)),
        "b": Estimate("measured", 9, "p", value=0.9),  # no interval
        "c": Estimate("insufficient", 1, "p", reason="n_below_minimum"),
        "d": Estimate("measured", 9, "p", value=0.5, interval=(0.4, 0.6)),
    }
    assert rank_estimates(estimates, higher_is_better=True) == ["d", "a"]
    assert rank_estimates(estimates, higher_is_better=False) == ["a", "d"]
