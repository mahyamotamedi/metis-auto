"""E6: the comparison report end to end with FAKE clients and a FAKE judge.
SYNTHETIC; nothing here is a measurement, a validated judgement or real data."""

import json
from datetime import date
from decimal import Decimal

import pytest

from metis_auto.contracts import (
    AnswerSource,
    AttemptKind,
    ComponentName,
    Fidelity,
    FinishReason,
    InputPart,
    ModelInvocation,
    ModelResponse,
    PartRole,
    TokenCount,
    TokenUsage,
)
from metis_auto.evaluation.comparison import EvalRequest, Outcome, OutcomeTable
from metis_auto.evaluation.costing import (
    ScenarioConfig,
    evaluate_scenarios,
    price_table_age,
)
from metis_auto.evaluation.judging import (
    FakePairwiseJudge,
    GateConfig,
    JudgeRequestView,
    PairItem,
    evaluate_gate,
    judge_items,
    pairwise_quality,
)
from metis_auto.evaluation.judging.calibration import GateResult
from metis_auto.evaluation.reporting import (
    build_comparison_report,
    to_markdown,
    to_plain,
)
from metis_auto.evaluation.sampling import (
    AllocationConfig,
    BootstrapSettings,
    RunConfig,
    SamplingUnit,
    execute,
    outcome_table,
    plan_calls,
    plan_sample,
)
from metis_auto.settings import repo_root
from metis_auto.settings.reference import read_catalogue, read_prices

CONFIG = repo_root() / "config" / "reference"
PRICES = read_prices(CONFIG / "prices-metis-2026-10-18-g55.toml")
CATALOGUE = {
    e.model_id: e for e in read_catalogue(CONFIG / "catalogue-metis-test.toml").entries
}
M = "[SYNTHETIC] "
CAND, REF = "gpt-5-nano", "gpt-5.5"
AS_OF = date(2026, 10, 30)
BOOT = BootstrapSettings(100, "b", 0.9)


class Clock:
    def __init__(self):
        self._t = 0.0

    def now(self):
        raise NotImplementedError

    def monotonic_ms(self):
        self._t += 5.0
        return self._t


class Client:
    source = AnswerSource.FAKE

    def invoke(self, invocation):
        usage = TokenUsage(
            model_id=invocation.model_id,
            input=TokenCount(
                tokens=1000, fidelity=Fidelity.PROVIDER_REPORTED, method="f"
            ),
            output=TokenCount(
                tokens=100, fidelity=Fidelity.PROVIDER_REPORTED, method="f"
            ),
        )
        return ModelResponse(
            text=M + "answer",
            finish_reason=FinishReason.COMPLETE,
            usage=usage,
            provider_latency_ms=12.0,
            source=AnswerSource.FAKE,
        )


def invocation(case_id, model_id):
    return ModelInvocation(
        request_id=f"req-{case_id}",
        attempt_id="a1",
        attempt_kind=AttemptKind.PRIMARY,
        model_id=model_id,
        parts=(
            InputPart(
                role=PartRole.USER, text=M + case_id, component=ComponentName.MESSAGE
            ),
        ),
        case_id=case_id,
    )


def make_units(fa=20, en=6, mixed=4):
    units = {}
    for language, n in (("fa", fa), ("en", en), ("mixed", mixed)):
        for i in range(n):
            case = f"{language}{i}"
            units[case] = SamplingUnit(case, f"s-{language}{i}", {"language": language})
    return units


class Content:
    def __init__(self, units):
        self.units = units

    def request(self, case_id):
        return JudgeRequestView(message=M + case_id)

    def answer(self, case_id, variant):
        return M + ("x" * 20 if variant[0] == CAND else "y" * 10)


def build(
    *, table=None, gate=None, delta=None, min_n=None, bootstrap=BOOT, scenario=None
):
    units = make_units()
    plan = plan_sample(
        list(units.values()),
        AllocationConfig(
            dimensions=("language",), total=24, seed="s", quotas={"en": 6}
        ),
    )
    config = RunConfig(
        models=(CAND, REF),
        hard_cap_usd=Decimal("5"),
        max_output_tokens=500,
        order_seed="o",
    )
    calls = plan_calls(plan.selected_ids(), units, config)
    run = execute(
        calls,
        client_for=lambda m, e: Client(),
        build_invocation=invocation,
        config=config,
        catalogue=CATALOGUE,
        prices=PRICES,
        input_tokens={(c, m): 1000 for c in units for m in (CAND, REF)},
        clock=Clock(),
        uses_sample_conversations=False,  # SYNTHETIC units
    )
    items = [
        PairItem(
            c.case_id,
            c.session_ref,
            units[c.case_id].strata["language"],
            (CAND, None),
            (REF, None),
        )
        for c in calls
        if c.model_id == CAND
    ]
    judge_run = judge_items(
        FakePairwiseJudge("longer", judge_id="fake-pairwise@0"),
        items,
        Content(units),
        vision_candidates=None,
    )
    scores = pairwise_quality(judge_run, (REF, None))
    base = outcome_table(
        run, units, quality_by_call={(c, m, e): v for (c, m, e), v in scores.items()}
    )
    gate_results = gate or evaluate_gate({}, GateConfig())
    return build_comparison_report(
        report_id="synthetic-e6",
        generated_on=AS_OF,
        table=table if table is not None else base,
        gate_results=gate_results,
        reference=REF,
        candidates=[CAND],
        delta=delta,
        min_n=min_n,
        bootstrap=bootstrap,
        price_age=price_table_age(PRICES, as_of=AS_OF, max_age_days=None),
        price_table_version=PRICES.version,
        run=run,
        plan=plan,
        units=units,
        judge=judge_run,
        scenarios=scenario
        if scenario is not None
        else evaluate_scenarios(
            ScenarioConfig(),
            catalogue=CATALOGUE,
            prices=PRICES,
            inputs={CAND: [1000], REF: [1000]},
            input_fidelity=Fidelity.EXACT_LOCAL,
        ),
        image_exclusions={"vision_capability_unset": 0},
    )


def passing_gate(languages=("fa",)):
    results = {}
    for language in ("fa", "en", "mixed"):
        ok = language in languages
        results[language] = GateResult(
            language, ok, None if ok else "n_below_min_items", 0.9, 0.85, 30
        )
    return results


def hand_table(drop):
    """30 Persian and 30 English requests; the candidate's quality is ``drop``
    below the reference everywhere."""
    requests = []
    for language in ("fa", "en"):
        for i in range(30):
            q = 0.6 + 0.01 * (i % 4)
            requests.append(
                EvalRequest(
                    f"{language}{i}",
                    f"s-{language}{i}",
                    language,
                    {CAND: Outcome(0.01, q - drop), REF: Outcome(0.05, q)},
                )
            )
    return OutcomeTable(tuple(requests), "simulated", "estimated", False)


# --- structure ---------------------------------------------------------------


def test_persian_is_the_primary_slice_and_overall_is_labelled():
    report = build()
    slices = [(e.language, e.note) for e in report.effects]
    assert slices[0] == ("fa", "primary slice")
    assert slices[-1] == ("all", "dominated_by_persian")
    assert {s for s, _ in slices} == {"fa", "en", "mixed", "all"}
    assert [n for s, n in slices if s in ("en", "mixed")] == ["separate slice"] * 2


def test_a_slice_below_the_minimum_n_shows_no_value_only_why():
    report = build(min_n=12)  # fa has 14 judged pairs, en 6, mixed 4
    by = {e.language: e for e in report.effects}
    assert by["fa"].quality_diff.measured and by["fa"].label == "rankable"
    for small in ("en", "mixed"):
        row = by[small]
        assert row.quality_diff.value is None and row.cost_ratio.value is None
        assert (row.label, row.label_reason) == ("descriptive", "n_below_minimum")
    # with no minimum set nothing is claimed anywhere
    unset = build(min_n=None)
    assert all(e.quality_diff.value is None for e in unset.effects)
    assert {e.label_reason for e in unset.effects} == {"min_n_unset"}
    # the descriptive per-model table still shows its values, labelled
    assert any(r.cost_mean_usd.value is not None for r in unset.descriptive)
    assert {r.label for r in unset.descriptive} == {"descriptive"}


def test_every_number_carries_provenance_and_the_header_says_what_was_used():
    report = build(min_n=1)
    assert report.provenance == "cost=simulated,quality=estimated"
    for e in report.effects:
        assert e.quality_diff.provenance and e.cost_ratio.provenance and e.provenance
    for r in report.descriptive:
        assert r.provenance == "simulated"
        assert r.cost_mean_usd.provenance == "simulated"
        assert r.latency_total_ms.provenance == "simulated"
    assert report.price_table_version == "prices-metis-2026-10-18-s75-g55"
    assert (report.price_age.age_days, report.price_age.state) == (12, "not_evaluated")
    assert report.counterfactual_sources == ("fake",)
    assert (report.judge_id, report.judge_instruction_language) == (
        "fake-pairwise@0",
        "en",
    )


# --- claims, validation and the delta flag -------------------------------------


def test_the_non_inferiority_flag_follows_the_interval_and_needs_validation():
    table = hand_table(drop=0.10)
    gate = passing_gate(("fa",))
    report = build(table=table, gate=gate, delta=0.05, min_n=10)
    by = {e.language: e for e in report.effects}
    fa = by["fa"]
    assert fa.quality_status == "validated"
    # the candidate is 0.10 worse and delta is 0.05: the interval crosses -delta
    assert fa.non_inferiority == "not_established" and fa.p_value is not None
    assert fa.quality_diff.value == pytest.approx(-0.10)
    assert fa.cost_ratio.value == pytest.approx(0.2)  # 0.01 / 0.05
    for blocked in ("en", "all"):
        row = by[blocked]
        assert row.quality_status == "unvalidated"
        assert (row.non_inferiority, row.non_inferiority_reason) == (
            "not_evaluated",
            "unvalidated_quality",
        )
    close = build(table=hand_table(drop=0.01), gate=gate, delta=0.05, min_n=10)
    assert {e.language: e for e in close.effects}["fa"].non_inferiority == "established"


def test_delta_unset_and_bootstrap_unset_are_stated():
    gate = passing_gate(("fa",))
    no_delta = build(table=hand_table(0.0), gate=gate, delta=None, min_n=10)
    fa = {e.language: e for e in no_delta.effects}["fa"]
    assert (fa.non_inferiority, fa.non_inferiority_reason) == (
        "not_evaluated",
        "delta_unset",
    )
    no_boot = build(
        table=hand_table(0.0), gate=gate, delta=0.05, min_n=10, bootstrap=None
    )
    assert {e.non_inferiority_reason for e in no_boot.effects} == {"bootstrap_unset"}
    assert all(e.quality_diff.value is None for e in no_boot.effects)


def test_with_the_gate_unset_every_slice_is_unvalidated_with_the_reason():
    report = build(table=hand_table(0.0), delta=0.05, min_n=10)
    assert {e.quality_status for e in report.effects} == {"unvalidated"}
    assert {e.non_inferiority for e in report.effects} == {"not_evaluated"}
    assert {e.gate_reason for e in report.effects} == {"no_gate_result"}


# --- coverage: allocation and weighting apart ---------------------------------


def test_allocation_and_weighting_are_shown_separately():
    report = build(min_n=1)
    sampling = report.coverage["sampling"]
    rows = {r["value"]: r for r in sampling["shares_by_slice"]["language"]}
    # the quota oversamples English: its sample share exceeds its population share
    assert rows["en"]["sample_share"] > rows["en"]["population_share"]
    # the weighted share is what recovers the population
    assert rows["en"]["weighted_share"] == pytest.approx(rows["en"]["population_share"])
    assert "neither is the other" in sampling["note"]
    md = to_markdown(report)
    assert "sample share (allocation)" in md and "weighted share" in md
    assert sampling["quotas"][0]["status"] == "met"
    assert (sampling["requested_total"], sampling["over_budget_by"]) == (24, 0)


def test_coverage_lists_run_judge_and_image_exclusions():
    report = build()
    assert (
        report.coverage["run"]["executed_calls"]
        == report.coverage["run"]["planned_calls"]
    )
    assert report.coverage["run"]["halts"] == []
    judge = report.coverage["judge"]
    assert judge["cost_kind"] == "evaluation" and judge["judged"] == 24
    assert report.coverage["image_exclusions"] == {"vision_capability_unset": 0}


# --- scenarios and open items ---------------------------------------------------


def test_unset_scenarios_are_not_evaluated_with_their_reasons():
    report = build()
    by_reading = {}
    for s in report.scenarios:
        by_reading.setdefault(s.reading, []).append(s)
    assert {s.reason for s in by_reading["not_evaluated"]} == {
        "no_output_scenarios_configured",
        "no_cache_scenarios_configured",
    }
    inputs = by_reading["lower_bound_input_only"]
    assert {s.provenance for s in inputs} == {"estimated"}
    assert all(s.total_usd is not None for s in inputs)
    assert "scenario" not in by_reading  # nothing was configured


def test_open_items_make_every_unset_decision_visible():
    items = {o.item: o for o in build().open_items}
    assert items["delta"].state == "unset" and items["min_n"].state == "unset"
    assert items["price_max_age"].state == "unset"
    assert items["bootstrap"].state == "set"
    ok = {o.item: o for o in build(delta=0.05, min_n=5, gate=passing_gate()).open_items}
    assert ok["delta"].state == "set" and ok["min_n"].state == "set"
    assert ok["judge_gate:fa"].state == "set"
    assert ok["judge_gate:en"].reason == "n_below_min_items"


# --- output ---------------------------------------------------------------------


def test_the_rendered_report_is_feature_only_and_withholds_numbers_it_cannot_support():
    report = build(min_n=12)
    data = json.dumps(to_plain(report))
    md = to_markdown(report)
    for text in (data, md):
        assert "[SYNTHETIC]" not in text and "fp1:" not in text
    assert "dominated_by_persian" in md
    assert "— (insufficient: n_below_minimum)" in md  # a withheld value shows why
    assert "## Open items" in md and "## Caveats" in md
    assert json.loads(data)["price_table_version"] == "prices-metis-2026-10-18-s75-g55"
    assert json.loads(data)["generated_on"] == "2026-10-30"
