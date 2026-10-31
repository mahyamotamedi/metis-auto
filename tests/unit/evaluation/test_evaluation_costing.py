"""E2: price age, usage quantiles, output-token estimators, scenario config and
engine. SYNTHETIC numbers; the price table is the repo's (g55) file, and every
expected cost is worked out by hand from its prices."""

from datetime import date
from decimal import Decimal

import pytest

from metis_auto.contracts import Fidelity
from metis_auto.evaluation.costing import (
    CostLine,
    ObservedUsage,
    RequestFeatures,
    ScenarioConfig,
    StratifiedQuantile,
    UsageRecord,
    VerbosityRatio,
    breakeven_equal_output_tokens,
    compare_estimators,
    cost_line,
    cost_quantiles,
    empirical_quantile,
    evaluate_scenarios,
    min_n_for_quantile,
    parse_scenario_config,
    price_table_age,
)
from metis_auto.settings import repo_root
from metis_auto.settings.reference import read_catalogue, read_prices

CONFIG = repo_root() / "config" / "reference"
PRICES = read_prices(CONFIG / "prices-metis-2026-10-18-g55.toml")
CATALOGUE = {
    e.model_id: e for e in read_catalogue(CONFIG / "catalogue-metis-test.toml").entries
}
AS_OF = date(2026, 10, 30)
MILLION = 1_000_000


# --- price age --------------------------------------------------------------


def test_price_age_reports_the_dates_and_what_an_unset_maximum_means():
    age = price_table_age(PRICES, as_of=AS_OF, max_age_days=None)
    assert age.version == "prices-metis-2026-10-18-s75-g55"
    assert (age.checked_on, age.age_days) == (date(2026, 10, 18), 12)
    assert age.effective_from is None  # the page states none
    assert (age.state, age.reason) == ("not_evaluated", "max_age_unset")
    assert "unset" in age.consequence and "not judged" in age.consequence


@pytest.mark.parametrize(
    "max_age, state", [(11, "stale"), (12, "fresh"), (30, "fresh"), (0, "stale")]
)
def test_price_age_against_a_configured_maximum(max_age, state):
    age = price_table_age(PRICES, as_of=AS_OF, max_age_days=max_age)
    assert age.state == state and age.reason is None and age.age_days == 12


def test_price_age_refuses_a_negative_maximum_and_a_date_before_the_check():
    with pytest.raises(ValueError):
        price_table_age(PRICES, as_of=AS_OF, max_age_days=-1)
    early = price_table_age(PRICES, as_of=date(2026, 10, 1), max_age_days=5)
    assert (early.state, early.reason) == ("undefined", "as_of_before_check_date")


# --- usage and quantiles ----------------------------------------------------


def test_the_identifiability_floor_is_arithmetic_not_chosen():
    assert [min_n_for_quantile(q) for q in (0.5, 0.9, 0.99, 0.01)] == [2, 10, 100, 100]
    with pytest.raises(ValueError):
        min_n_for_quantile(1.0)


def test_empirical_quantile_interpolates():
    assert empirical_quantile([10, 20, 30, 40], 0.5) == 25
    assert empirical_quantile([5], 0.9) == 5 and empirical_quantile([], 0.5) is None


def rec(i, out, *, model="m", session=None, strata=None, reasoning=None, **kw):
    return UsageRecord(
        f"r{i}",
        session or f"s{i}",
        model,
        None,
        input_tokens=kw.pop("input_tokens", 1000),
        output_tokens=out,
        reasoning_tokens=reasoning,
        strata=strata or {},
        **kw,
    )


# --- estimators -------------------------------------------------------------

NONE = RequestFeatures()


def test_observed_usage_quantile_and_refusals():
    est = ObservedUsage([rec(i, 10 * (i + 1)) for i in range(10)])  # 10..100
    assert est.estimate("m", None, NONE, 0.5).value == 55
    p99 = est.estimate("m", None, NONE, 0.99)
    assert (p99.state, p99.reason) == ("insufficient", "quantile_not_identifiable")
    assert p99.extra["min_n_for_quantile"] == 100
    missing = est.estimate("other", None, NONE, 0.5)
    assert (missing.state, missing.reason) == ("not_evaluated", "no_recorded_usage")
    assert est.estimate("m", None, NONE, 0.5).provenance == "estimated"


def strata_records():
    fa = [rec(i, 10 + i, strata={"language": "fa"}) for i in range(6)]  # 10..15
    en = [rec(10 + i, 500 + i, strata={"language": "en"}) for i in range(4)]
    return fa + en


def test_stratified_quantile_falls_back_with_a_stated_reason():
    fa, en = RequestFeatures({"language": "fa"}), RequestFeatures({"language": "en"})
    unset = StratifiedQuantile(
        strata_records(), strata_keys=["language"], min_stratum_n=None
    )
    pooled = unset.estimate("m", None, fa, 0.5)
    assert pooled.extra["fallback"] == "min_stratum_n_unset"
    assert pooled.extra["level"] == "pooled"
    est = StratifiedQuantile(
        strata_records(), strata_keys=["language"], min_stratum_n=5
    )
    assert est.estimate("m", None, fa, 0.5).value == 12.5  # median of 10..15
    assert est.estimate("m", None, fa, 0.5).extra["level"] == "stratum"
    small = est.estimate("m", None, en, 0.5)  # 4 records < 5
    assert small.extra["fallback"] == "stratum_below_min_n"
    assert (
        est.estimate("m", None, NONE, 0.5).extra["fallback"] == "request_strata_missing"
    )


def test_verbosity_ratio_by_hand_and_it_never_predicts_reasoning():
    records = [
        rec(i, 100, reasoning=0, visible_output_chars=200, logged_answer_chars=100)
        for i in range(4)
    ]  # ratio 2 chars/char; 100 tokens / 200 chars = 0.5 tokens per char
    est = VerbosityRatio(records)
    out = est.estimate(
        "m", None, RequestFeatures(numeric={"logged_answer_chars": 50}), 0.5
    )
    assert out.value == pytest.approx(2 * 50 * 0.5)
    assert out.extra["reasoning_tokens"] == "not_predicted"
    no_logged = est.estimate("m", None, NONE, 0.5)
    assert no_logged.reason == "logged_answer_chars_missing"
    assert est.estimate("x", None, NONE, 0.5).reason == "no_recorded_usage"
    # records without a reasoning count cannot give tokens per char
    only_chars = VerbosityRatio(
        [rec(1, 100, visible_output_chars=200, logged_answer_chars=100)]
    )
    assert (
        only_chars.estimate(
            "m", None, RequestFeatures(numeric={"logged_answer_chars": 5}), 0.5
        ).state
        == "not_evaluated"
    )


def test_compare_estimators_uses_a_paired_interval_and_a_configured_minimum():
    fit = strata_records() * 1
    test = [
        rec(100 + i, 10 + i % 6, session=f"t{i}", strata={"language": "fa"})
        for i in range(6)
    ]
    test += [
        rec(200 + i, 500 + i % 4, session=f"u{i}", strata={"language": "en"})
        for i in range(4)
    ]
    features = {r.request_id: RequestFeatures(dict(r.strata)) for r in test}
    estimators = {
        "pooled": ObservedUsage(fit),
        "stratified": StratifiedQuantile(
            fit, strata_keys=["language"], min_stratum_n=4
        ),
    }
    kw = {
        "reference": "pooled",
        "q": 0.5,
        "target": "output",
        "features": features,
        "n_boot": 200,
        "seed": "s",
        "level": 0.9,
    }
    result = compare_estimators(test, estimators, min_n=5, **kw)
    assert result.n == 10
    assert result.better_than_reference["stratified"] is True
    assert result.versus_reference["stratified"].interval[1] < 0
    assert result.better_than_reference["pooled"] is None
    unset = compare_estimators(test, estimators, min_n=None, **kw)
    assert unset.loss["stratified"].reason == "min_n_unset"
    assert unset.better_than_reference["stratified"] is None


# --- scenario config --------------------------------------------------------


def test_nothing_is_set_by_default():
    config = ScenarioConfig()
    assert (config.max_age_days, config.output, config.cache) == (None, (), ())
    assert parse_scenario_config({}) == config


@pytest.mark.parametrize(
    "raw",
    [
        {"output": [{"name": "a", "source": "recorded_quantile"}]},
        {
            "output": [
                {
                    "name": "a",
                    "source": "recorded_quantile",
                    "quantile": 1.0,
                    "estimator": "e",
                }
            ]
        },
        {
            "output": [
                {
                    "name": "a",
                    "source": "documented_assumption",
                    "output_tokens_per_request": {"m": 1},
                }
            ]
        },
        {
            "output": [
                {"name": "a", "source": "documented_assumption", "assumption_note": "x"}
            ]
        },
        {
            "output": [
                {
                    "name": "a",
                    "source": "documented_assumption",
                    "output_tokens_per_request": {"m": 1},
                    "assumption_note": "x",
                    "quantile": 0.5,
                }
            ]
        },
        {
            "cache": [
                {"name": "c", "source": "sensitivity_range", "cached_input_share": 0.5}
            ]
        },
        {
            "cache": [
                {"name": "c", "source": "sensitivity_range", "label": "hypothetical"}
            ]
        },
        {
            "cache": [
                {
                    "name": "c",
                    "source": "sensitivity_range",
                    "cached_input_share": 1.5,
                    "label": "h",
                }
            ]
        },
        {"cache": [{"name": "c", "source": "measured", "cached_input_share": 0.5}]},
        {
            "cache": [
                {"name": "c", "source": "measured"},
                {"name": "c", "source": "measured"},
            ]
        },
        {"surprise": 1},
    ],
)
def test_invalid_scenario_config_is_refused(raw):
    with pytest.raises(ValueError):
        parse_scenario_config(raw)


# --- scenario engine --------------------------------------------------------

M55, NANO = "gpt-5.5", "gpt-5-nano"
INPUTS = {M55: [100_000], NANO: [100_000]}  # inside the standard tier (<= 270,000)


def run(config, **kw):
    return evaluate_scenarios(
        config,
        catalogue=CATALOGUE,
        prices=PRICES,
        inputs=INPUTS,
        input_fidelity=Fidelity.EXACT_LOCAL,
        **kw,
    )


def by_key(rows):
    return {(r.model_id, r.output_scenario, r.cache_scenario): r for r in rows}


def test_with_nothing_configured_only_input_cost_is_computed_and_the_rest_says_why():
    rows = run(ScenarioConfig())
    index = by_key(rows)
    assert index[(M55, "input_only", "uncached")].total_usd == Decimal("0.55")
    assert index[(NANO, "input_only", "uncached")].total_usd == Decimal("0.0055")
    assert "output_not_included" in index[(M55, "input_only", "uncached")].caveats
    assert index[(M55, "input_only", "uncached")].provenance == "estimated"
    reasons = {r.reason for r in rows if r.state == "not_evaluated"}
    assert reasons == {
        "no_output_scenarios_configured",
        "no_cache_scenarios_configured",
    }
    assert all(r.total_usd is None for r in rows if r.state == "not_evaluated")


def test_documented_assumption_and_hypothetical_cache_are_labelled_simulated():
    config = parse_scenario_config(
        {
            "output": [
                {
                    "name": "assumed",
                    "source": "documented_assumption",
                    "output_tokens_per_request": {M55: 1000},
                    "assumption_note": "SYNTHETIC test value",
                }
            ],
            "cache": [
                {
                    "name": "half",
                    "source": "sensitivity_range",
                    "cached_input_share": 0.5,
                    "label": "hypothetical",
                }
            ],
        }
    )
    index = by_key(run(config))
    uncached = index[(M55, "assumed", "uncached")]
    assert uncached.total_usd == Decimal("0.55") + Decimal("0.033")  # 1,000 x 33/1M
    half = index[(M55, "assumed", "half")]
    # 50k at 5.5 + 50k cached at 0.55 + 1,000 output at 33, per million
    assert half.total_usd == Decimal("0.275") + Decimal("0.0275") + Decimal("0.033")
    assert half.provenance == "simulated" and uncached.provenance == "simulated"
    # a model not named in the assumption is not given a number
    assert index[(NANO, "assumed", "uncached")].reason == "model_not_in_scenario"


def test_recorded_quantile_without_recorded_data_is_not_evaluated():
    config = parse_scenario_config(
        {
            "output": [
                {
                    "name": "p50",
                    "source": "recorded_quantile",
                    "quantile": 0.5,
                    "estimator": "obs",
                }
            ]
        }
    )
    no_estimator = by_key(run(config))
    assert no_estimator[(M55, "p50", "uncached")].reason == "estimator_not_provided"
    empty = by_key(run(config, estimators={"obs": ObservedUsage([])}))
    assert empty[(M55, "p50", "uncached")].reason == "no_recorded_usage"
    data = [rec(i, 1000 + i, model=M55) for i in range(4)]
    ok = by_key(run(config, estimators={"obs": ObservedUsage(data)}, usage=data))
    row = ok[(M55, "p50", "uncached")]
    assert row.state == "computed" and row.provenance == "estimated"
    assert row.details["output_tokens_per_request"] == 1001.5  # median of 1000..1003
    assert ok[(NANO, "p50", "uncached")].reason == "no_recorded_usage"


def test_measured_cache_share_comes_from_usage_or_says_why_not():
    config = parse_scenario_config(
        {
            "output": [
                {
                    "name": "a",
                    "source": "documented_assumption",
                    "output_tokens_per_request": {M55: 0, NANO: 0},
                    "assumption_note": "SYNTHETIC",
                }
            ],
            "cache": [{"name": "seen", "source": "measured"}],
        }
    )
    usage = [
        rec(1, 10, model=M55, input_tokens=1000, cached_input_tokens=300),
        rec(2, 10, model=M55, input_tokens=1000, cached_input_tokens=100),
    ]
    index = by_key(run(config, usage=usage))
    assert index[(M55, "a", "seen")].details["cached_input_share"] == pytest.approx(0.2)
    assert index[(NANO, "a", "seen")].reason == "no_recorded_usage"
    unreported = [rec(1, 10, model=M55)]
    again = by_key(run(config, usage=unreported))
    assert again[(M55, "a", "seen")].reason == "cached_tokens_not_reported"


def test_an_unknown_model_is_reported_not_priced():
    rows = evaluate_scenarios(
        ScenarioConfig(),
        catalogue=CATALOGUE,
        prices=PRICES,
        inputs={"no-such-model": [10]},
        input_fidelity=Fidelity.EXACT_LOCAL,
    )
    assert rows[0].reason == "model_not_in_catalogue"


def test_the_cost_line_and_break_even_need_no_scenario_values():
    line = cost_line(CATALOGUE[M55], PRICES, 100_000, Fidelity.EXACT_LOCAL)
    assert isinstance(line, CostLine)
    assert line.fixed_usd == Decimal("0.55")
    assert line.per_output_token_usd == Decimal("33") / MILLION
    # above 270,000 input tokens the long tier prices the whole call
    long = cost_line(CATALOGUE[M55], PRICES, MILLION, Fidelity.EXACT_LOCAL)
    assert long.fixed_usd == Decimal("11.0")
    assert long.per_output_token_usd == Decimal("49.5") / MILLION
    a = CostLine("a", Decimal(1), Decimal("0.001"))
    b = CostLine("b", Decimal(3), Decimal("0.0005"))
    assert breakeven_equal_output_tokens(a, b).value == pytest.approx(4000)
    assert breakeven_equal_output_tokens(b, a).value == pytest.approx(4000)  # symmetric
    dearer = CostLine("d", Decimal(3), Decimal("0.002"))  # worse on both counts
    assert (
        breakeven_equal_output_tokens(a, dearer).reason == "no_non_negative_breakeven"
    )
    same = CostLine("c", Decimal(2), Decimal("0.001"))
    assert breakeven_equal_output_tokens(a, same).reason == "equal_output_prices"


def test_cost_quantiles_refuse_what_the_sample_cannot_identify():
    out = cost_quantiles(
        [Decimal(i) for i in range(1, 11)], [0.5, 0.9, 0.99], "estimated"
    )
    assert out[0.5].value == 5.5 and out[0.9].measured
    assert (out[0.99].state, out[0.99].reason) == (
        "insufficient",
        "quantile_not_identifiable",
    )
