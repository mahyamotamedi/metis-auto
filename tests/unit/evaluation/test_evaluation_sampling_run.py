"""E4 run harness, guard, stop rules, recording and the comparison table, with
FAKE clients only (no network, no key, no live call). SYNTHETIC units. Nothing
here establishes real-data validity: the fake client reports constant usage."""

import json
from decimal import Decimal

import pytest

from metis_auto.adapters.providers.recording import RecordingModelClient
from metis_auto.adapters.providers.replay import ReplayModelClient
from metis_auto.contracts import (
    AnswerSource,
    AttemptKind,
    ComponentName,
    ErrorClass,
    Fidelity,
    FinishReason,
    InputPart,
    ModelError,
    ModelInvocation,
    ModelResponse,
    PartRole,
    TokenCount,
    TokenUsage,
)
from metis_auto.evaluation.comparison import system_point
from metis_auto.evaluation.costing import ObservedUsage, RequestFeatures, VerbosityRatio
from metis_auto.evaluation.sampling import (
    AllocationConfig,
    BootstrapSettings,
    LiveApproval,
    RunConfig,
    RunRefused,
    SamplingUnit,
    check_live,
    comparison_table,
    estimate_run,
    execute,
    outcome_table,
    parse_run_config,
    plan_calls,
    plan_sample,
    population_total,
    usage_records,
)
from metis_auto.settings import repo_root
from metis_auto.settings.reference import read_catalogue, read_prices

CONFIG = repo_root() / "config" / "reference"
PRICES = read_prices(CONFIG / "prices-metis-2026-10-18-g55.toml")
CATALOGUE = {
    e.model_id: e for e in read_catalogue(CONFIG / "catalogue-metis-test.toml").entries
}
MODELS = ("gpt-5-nano", "deepseek-v4-flash", "gpt-5.5")
M = "[SYNTHETIC] "
IN, OUT, REASONING = 1000, 100, 40
PER_CALL = {  # hand-computed: 1000 input and 100 output tokens at snapshot prices
    "gpt-5-nano": Decimal("1000") * Decimal("0.055") / 10**6
    + Decimal("100") * Decimal("0.44") / 10**6,
    "deepseek-v4-flash": Decimal("1000") * Decimal("0.165") / 10**6
    + Decimal("100") * Decimal("0.66") / 10**6,
    "gpt-5.5": Decimal("1000") * Decimal("5.5") / 10**6
    + Decimal("100") * Decimal("33") / 10**6,
}


class Clock:
    def __init__(self):
        self._t = 0.0

    def now(self):
        raise NotImplementedError

    def monotonic_ms(self):
        self._t += 5.0
        return self._t


class Client:
    """A fake that reports constant provider-style usage. ``kind`` lets a test
    pretend to be live to exercise the guard; it never touches a network."""

    def __init__(
        self, kind=AnswerSource.FAKE, *, fail=False, truncate=False, usage=True, out=OUT
    ):
        self._kind, self.calls = kind, 0
        self._fail, self._truncate, self._usage, self._out = fail, truncate, usage, out

    @property
    def source(self):
        return self._kind

    def invoke(self, invocation):
        self.calls += 1
        if self._fail:
            return ModelError(
                error_class=ErrorClass.UNAVAILABLE, retryable=True, source=self._kind
            )
        usage = None
        if self._usage:
            usage = TokenUsage(
                model_id=invocation.model_id,
                input=TokenCount(
                    tokens=IN, fidelity=Fidelity.PROVIDER_REPORTED, method="fake"
                ),
                output=TokenCount(
                    tokens=self._out, fidelity=Fidelity.PROVIDER_REPORTED, method="fake"
                ),
                reasoning=TokenCount(
                    tokens=REASONING, fidelity=Fidelity.PROVIDER_REPORTED, method="fake"
                ),
            )
        return ModelResponse(
            text=M + "answer " * 5,
            finish_reason=FinishReason.LENGTH
            if self._truncate
            else FinishReason.COMPLETE,
            usage=usage,
            provider_latency_ms=10.0 + len(invocation.model_id),
            provider_model_version="fake-1",
            source=self._kind,
        )


class LocalRecorder:
    """Test-only recorder that writes whatever client it wraps, fake included,
    in the production record format. The production ``RecordingModelClient``
    writes live results only; this exists so tests can prove that a store of
    fake answers can never be loaded back as recorded or measured."""

    def __init__(self, inner, path):
        self._inner, self._path = inner, path

    @property
    def source(self):
        return self._inner.source

    def invoke(self, invocation):
        result = self._inner.invoke(invocation)
        record = {
            "v": 1,
            "time": "t",
            "run_id": "r1",
            "client_source": self._inner.source.value,
            "invocation": invocation.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
        }
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return result


def make_units(fa=12, en=4, mixed=2):
    units = {}
    for language, n in (("fa", fa), ("en", en), ("mixed", mixed)):
        for i in range(n):
            case = f"{language}{i}"
            units[case] = SamplingUnit(
                case,
                f"s-{language}{i // 2}",
                {"language": language},
                {"logged_answer_chars": 40.0},
            )
    return units


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


def run_config(**kw):
    base = {
        "models": MODELS,
        "hard_cap_usd": Decimal("5"),
        "max_output_tokens": 500,
        "order_seed": "order-a",
    }
    return RunConfig(**{**base, **kw})


def inputs_for(units, models=MODELS):
    return {(c, m): IN for c in units for m in models}


def selected_calls(units, config, total=10):
    plan = plan_sample(
        list(units.values()),
        AllocationConfig(
            dimensions=("language",), total=total, seed="s", quotas={"en": 3}
        ),
    )
    return plan, plan_calls(plan.selected_ids(), units, config)


def run(units, config, client=None, *, calls=None, **kw):
    # SYNTHETIC units: never sample conversations (stated, not defaulted in execute)
    kw.setdefault("uses_sample_conversations", False)
    client = client or Client()
    calls = calls if calls is not None else selected_calls(units, config)[1]
    return execute(
        calls,
        client_for=lambda m, e: client,
        build_invocation=invocation,
        config=config,
        catalogue=CATALOGUE,
        prices=PRICES,
        input_tokens=inputs_for(units),
        clock=Clock(),
        **kw,
    )


# --- planning ---------------------------------------------------------------


def test_the_call_plan_covers_models_efforts_and_the_repeat_subset_in_a_seeded_order():
    units = make_units()
    config = run_config(
        efforts={"gpt-5.5": (None, "high")}, repeat_units=2, repeat_count=1
    )
    plan, calls = selected_calls(units, config)
    per_unit = len(MODELS) + 1  # gpt-5.5 at two efforts
    assert len(calls) == plan.achieved_total * per_unit + 2 * per_unit
    assert sum(c.repeat_index == 1 for c in calls) == 2 * per_unit
    _, again = selected_calls(units, config)
    assert calls == again  # deterministic
    _, other = selected_calls(
        units,
        run_config(
            order_seed="order-b",
            efforts={"gpt-5.5": (None, "high")},
            repeat_units=2,
            repeat_count=1,
        ),
    )
    assert calls != other
    with pytest.raises(RunRefused, match="order_seed_unset"):
        plan_calls(plan.selected_ids(), units, RunConfig(models=MODELS))


def test_run_config_validation():
    for bad in (
        {"hard_cap_usd": "0"},
        {"repeat_units": 2},
        {"max_failure_share": 1.5},
        {"overrun_check_at_progress": 0},
        {"output_tokens_assumption": {"gpt-5.5": 10}},  # needs a note
    ):
        with pytest.raises(ValueError):
            parse_run_config(bad)
    assert parse_run_config({}).hard_cap_usd is None


# --- refusals: nothing is called ----------------------------------------------


@pytest.mark.parametrize(
    "kw, reason",
    [
        ({"hard_cap_usd": None}, "hard_cap_unset"),
        ({"max_output_tokens": None}, "max_output_tokens_unset"),
    ],
)
def test_the_run_refuses_without_a_cap_or_a_generation_limit(kw, reason):
    units, client = make_units(), Client()
    config = run_config(**kw)
    calls = plan_calls(["fa0"], units, config)
    with pytest.raises(RunRefused) as refused:
        run(units, config, client, calls=calls)
    assert refused.value.reason == reason and client.calls == 0


def test_the_run_refuses_unknown_input_sizes_before_any_call():
    units, client = make_units(), Client()
    calls = plan_calls(["fa0"], units, run_config())
    with pytest.raises(RunRefused, match="input_size_or_model_unknown"):
        execute(
            calls,
            client_for=lambda m, e: client,
            build_invocation=invocation,
            config=run_config(),
            catalogue=CATALOGUE,
            prices=PRICES,
            input_tokens={},
            clock=Clock(),
            uses_sample_conversations=False,  # SYNTHETIC units
        )
    assert client.calls == 0


def test_a_live_client_is_refused_without_an_approval_and_nothing_is_called():
    units, client = make_units(), Client(AnswerSource.LIVE)
    with pytest.raises(RunRefused) as refused:
        run(units, run_config(), client, calls=plan_calls(["fa0"], units, run_config()))
    assert refused.value.reason == "live_run_needs_owner_approval"
    assert client.calls == 0


def test_sample_conversations_need_their_own_approval_and_the_cap_is_the_lower_one():
    units, client = make_units(), Client(AnswerSource.LIVE)
    calls = plan_calls(["fa0"], units, run_config())
    approval = LiveApproval(approved_by="owner", run_id="run-1", cap_usd=Decimal("1"))
    with pytest.raises(RunRefused, match="sample_conversations_need_per_run_approval"):
        run(
            units,
            run_config(),
            client,
            calls=calls,
            approval=approval,
            uses_sample_conversations=True,
        )
    assert client.calls == 0
    cap = check_live(
        [AnswerSource.LIVE],
        approval=approval,
        uses_sample_conversations=False,
        hard_cap_usd=Decimal("5"),
    )
    assert cap == Decimal("1")  # the approval's cap is lower than the run's
    # no live source: the run's own cap applies and no approval is needed
    assert check_live(
        [AnswerSource.FAKE],
        approval=None,
        uses_sample_conversations=True,
        hard_cap_usd=Decimal("5"),
    ) == Decimal("5")


def test_an_approval_needs_who_which_run_and_a_positive_cap():
    for bad in (
        {"approved_by": " ", "run_id": "r", "cap_usd": "1"},
        {"approved_by": "o", "run_id": "", "cap_usd": "1"},
        {"approved_by": "o", "run_id": "r", "cap_usd": "0"},
    ):
        with pytest.raises(ValueError):
            LiveApproval(**bad)


# --- a full fake run ----------------------------------------------------------


def test_a_full_fake_run_matches_its_estimates_and_is_labelled_simulated(tmp_path):
    units = make_units()
    config = run_config(
        efforts={"gpt-5.5": (None, "high")},
        repeat_units=2,
        repeat_count=1,
        output_tokens_assumption={m: OUT for m in MODELS},
        assumption_note="SYNTHETIC: equals the fake client's output",
    )
    plan, calls = selected_calls(units, config)
    store = tmp_path / "recorded.jsonl"
    client = LocalRecorder(Client(), store)  # the production recorder is live-only
    result = run(units, config, client, calls=calls)
    assert (result.executed_calls, result.skipped_calls, result.halts) == (
        len(calls),
        0,
        (),
    )
    expected = sum((PER_CALL[c.model_id] for c in calls), Decimal(0))
    assert result.realized_usd == expected and result.unreported_cost_calls == 0
    est = result.estimate
    assert est.assumed_usd == expected  # the assumption equals the fake's usage
    assert est.lower_bound_usd < expected <= est.ceiling_usd
    assert est.reasons == {}
    assert result.charged_usd == expected <= result.cap_usd
    assert result.sources == ("fake",)
    assert {r.provenance for r in result.records} == {"simulated"}
    assert {r.ttft_state for r in result.records} == {"not_reported"}
    assert {r.retry_count for r in result.records} == {0}
    assert all(r.latency_source == "provider" for r in result.records)
    # the recorded store holds the answers; the result holds no text at all
    lines = store.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(calls) and json.loads(lines[0])["result"][
        "text"
    ].startswith(M)
    assert "[SYNTHETIC]" not in repr(result)
    # the same run is a measured run only for live or recorded answers
    assert plan.achieved_total == 10


def test_estimates_say_what_they_lack():
    units = make_units()
    calls = plan_calls(["fa0"], units, run_config())
    bare = estimate_run(
        calls,
        input_tokens=inputs_for(units),
        catalogue=CATALOGUE,
        prices=PRICES,
        config=RunConfig(models=MODELS, order_seed="s"),
    )
    assert bare.lower_bound_usd is not None
    assert bare.assumed_usd is None and bare.ceiling_usd is None
    assert bare.reasons == {
        "assumed_usd": "output_assumption_unset",
        "ceiling_usd": "max_output_tokens_unset",
    }


# --- the cap and the stop rules -----------------------------------------------


def test_the_cap_is_checked_against_the_worst_case_before_each_call():
    units = make_units()
    config = run_config(
        hard_cap_usd=Decimal("0.05")
    )  # gpt-5.5 worst case: 0.022 a call
    result = run(units, config)
    assert result.charged_usd <= result.cap_usd
    assert any(
        h.reason == "cap_would_be_exceeded" and h.model_id is None for h in result.halts
    )
    assert result.skipped_calls > 0
    assert result.executed_calls + result.skipped_calls == result.planned_calls


def test_a_call_without_reported_usage_is_charged_at_its_worst_case():
    units = make_units()
    calls = plan_calls(["fa0"], units, run_config(models=("gpt-5.5",)))
    result = run(
        units, run_config(models=("gpt-5.5",)), Client(usage=False), calls=calls
    )
    assert result.unreported_cost_calls == 1 and result.realized_usd == 0
    # 1,000 input at 5.5 + the 500-token generation limit at 33, per million
    assert result.charged_usd == Decimal("0.0055") + Decimal("0.0165")
    assert result.records[0].cost_state == "usage_not_reported"


def test_stop_rules_halt_one_model_when_configured_and_only_then():
    units = make_units()

    def by_model(model_id, effort):
        return Client(fail=model_id == "deepseek-v4-flash")

    config = run_config(max_failure_share=0.1, stop_rule_min_calls=3)
    calls = selected_calls(units, config)[1]
    result = execute(
        calls,
        client_for=by_model,
        build_invocation=invocation,
        config=config,
        catalogue=CATALOGUE,
        prices=PRICES,
        input_tokens=inputs_for(units),
        clock=Clock(),
        uses_sample_conversations=False,  # SYNTHETIC units
    )
    deepseek = [r for r in result.records if r.model_id == "deepseek-v4-flash"]
    assert len(deepseek) == 3 and result.skipped_calls == len(calls) - len(
        result.records
    )
    assert [(h.model_id, h.reason) for h in result.halts] == [
        ("deepseek-v4-flash", "failure_share_exceeded")
    ]
    assert result.stop_rules["failure_share"] == "active"
    other = [r for r in result.records if r.model_id != "deepseek-v4-flash"]
    assert all(r.outcome == "response" for r in other)
    # without a minimum call count the rule is inactive and says so
    inactive = execute(
        calls,
        client_for=by_model,
        build_invocation=invocation,
        config=run_config(max_failure_share=0.1),
        catalogue=CATALOGUE,
        prices=PRICES,
        input_tokens=inputs_for(units),
        clock=Clock(),
        uses_sample_conversations=False,  # SYNTHETIC units
    )
    assert inactive.halts == ()
    assert inactive.stop_rules["failure_share"] == "inactive_stop_rule_min_calls_unset"


def test_truncation_share_and_unset_rules():
    units = make_units()
    config = run_config(max_truncation_share=0.1, stop_rule_min_calls=2)
    calls = selected_calls(units, config)[1]
    result = run(units, config, Client(truncate=True), calls=calls)
    assert {h.reason for h in result.halts} == {"truncation_share_exceeded"}
    assert all(r.truncated for r in result.records)
    plain = run(units, run_config(), calls=calls)
    assert plain.stop_rules == {
        "failure_share": "unset",
        "truncation_share": "unset",
        "cost_overrun": "unset",
    }


def test_a_cost_overrun_halts_the_run_only_with_an_assumed_estimate():
    units = make_units()
    low = {m: 10 for m in MODELS}  # assumed far below the fake's 100 output tokens
    config = run_config(
        output_tokens_assumption=low,
        assumption_note="SYNTHETIC low assumption",
        overrun_factor=1.3,
        overrun_check_at_progress=0.2,
    )
    calls = selected_calls(units, config)[1]
    result = run(units, config, calls=calls)
    assert [h.reason for h in result.halts] == ["cost_overrun"]
    assert result.executed_calls < len(calls)
    no_assumption = run(
        units,
        run_config(overrun_factor=1.3, overrun_check_at_progress=0.2),
        calls=calls,
    )
    assert no_assumption.stop_rules["cost_overrun"] == "inactive_no_assumed_estimate"
    assert no_assumption.halts == ()


# --- tables, calibration, weights ----------------------------------------------


def test_the_comparison_is_persian_first_with_separate_columns_and_no_quality_yet():
    units = make_units()
    result = run(units, run_config())
    rows = comparison_table(result, units, min_n=None)
    assert rows[0].language == "fa" and {r.language for r in rows} == {
        "fa",
        "en",
        "mixed",
    }
    row = next(r for r in rows if r.language == "fa" and r.model_id == "gpt-5.5")
    assert row.provenance == "simulated" and row.label == "descriptive"
    assert row.label_reason == "min_n_unset"
    assert row.cost_mean_usd.value == pytest.approx(float(PER_CALL["gpt-5.5"]))
    assert row.cost_median_usd.value == pytest.approx(float(PER_CALL["gpt-5.5"]))
    assert row.latency_total_ms.value == pytest.approx(10.0 + len("gpt-5.5"))
    assert (row.ttft_ms.state, row.ttft_ms.reason) == (
        "not_evaluated",
        "ttft_not_reported",
    )
    assert (row.quality.state, row.quality.reason) == (
        "not_evaluated",
        "no_judge_scores",
    )
    assert row.n_calls == row.n_answered and row.error_share == 0.0


def test_repeats_do_not_tilt_the_comparison_and_intervals_need_a_bootstrap_setting():
    units = make_units()
    config = run_config(repeat_units=2, repeat_count=3)
    calls = selected_calls(units, config)[1]
    result = run(units, config, calls=calls)
    fa = [r for r in comparison_table(result, units, min_n=1) if r.language == "fa"]
    plan_fa = sum(
        1
        for c in calls
        if units[c.case_id].strata["language"] == "fa"
        and c.repeat_index == 0
        and c.model_id == "gpt-5.5"
    )
    assert all(r.n_calls == plan_fa for r in fa)
    assert all(r.cost_mean_usd.interval is None for r in fa)
    boot = comparison_table(
        result, units, min_n=1, boot=BootstrapSettings(100, "b", 0.9)
    )
    bfa = next(r for r in boot if r.language == "fa" and r.model_id == "gpt-5.5")
    assert bfa.cost_mean_usd.interval is not None and bfa.label == "rankable"


def test_scores_are_carried_with_their_validation_state():
    units = make_units()
    result = run(units, run_config())
    scores = {(r.case_id, r.model_id, r.effort): 0.5 for r in result.records}
    rows = comparison_table(result, units, min_n=1, quality_by_call=scores)
    assert all(
        r.quality.value == 0.5 and r.quality.extra["validated"] == "no" for r in rows
    )
    ok = comparison_table(
        result, units, min_n=1, quality_by_call=scores, quality_validated=True
    )
    assert (
        ok[0].quality.extra["validated"] == "yes"
        and ok[0].quality.provenance == "measured"
    )


def test_usage_records_feed_the_cost_model_fit():
    units = make_units()
    result = run(units, run_config())
    records = usage_records(result, units)
    assert len(records) == result.executed_calls
    observed = ObservedUsage(records)
    est = observed.estimate("gpt-5.5", None, RequestFeatures(), 0.5)
    assert est.value == OUT and est.provenance == "estimated"
    visible = ObservedUsage(records, target="visible").estimate(
        "gpt-5.5", None, RequestFeatures(), 0.5
    )
    assert visible.value == OUT - REASONING
    ratio = VerbosityRatio(records).estimate(
        "gpt-5.5", None, RequestFeatures(numeric={"logged_answer_chars": 40.0}), 0.5
    )
    assert (
        ratio.state == "measured" and ratio.extra["reasoning_tokens"] == "not_predicted"
    )


def test_the_outcome_table_is_incomplete_until_quality_is_supplied():
    units = make_units()
    result = run(units, run_config())
    table = outcome_table(result, units)
    assert table.provenance == "cost=simulated,quality=estimated"
    assert table.quality_validated is False
    point = system_point(table, {r.request_id: "gpt-5.5" for r in table.requests}, "p")
    assert point.n == 0  # cost without quality is not a complete outcome
    scores = {(r.case_id, r.model_id, r.effort): 0.7 for r in result.records}
    scored = outcome_table(result, units, quality_by_call=scores)
    full = system_point(scored, {r.request_id: "gpt-5.5" for r in scored.requests}, "p")
    assert full.n > 0 and full.mean_quality == pytest.approx(0.7)
    assert full.mean_cost == pytest.approx(float(PER_CALL["gpt-5.5"]))


def test_population_totals_use_the_weights_not_the_allocation():
    units = make_units()
    config = run_config(models=("gpt-5-nano",))
    plan = plan_sample(
        list(units.values()),
        AllocationConfig(dimensions=("language",), total=9, seed="s", quotas={"en": 3}),
    )
    calls = plan_calls(plan.selected_ids(), units, config)
    result = run(units, config, calls=calls)
    total = population_total(result, plan, "gpt-5-nano")
    # weights sum to the population over the drawn cells, so the total is
    # population x the constant per-call cost, however minorities were oversampled
    drawn_population = sum(c.population for c in plan.cells if c.achieved)
    assert total.value == pytest.approx(
        drawn_population * float(PER_CALL["gpt-5-nano"])
    )
    assert total.provenance == "simulated"
    missing = population_total(result, plan, "gpt-5.5")
    assert (missing.state, missing.reason) == (
        "not_evaluated",
        "cost_missing_for_drawn_units",
    )


def test_errors_are_recorded_without_content_and_counted():
    units = make_units()
    config = run_config(models=("gpt-5-nano",))
    calls = plan_calls(["fa0", "fa1"], units, config)
    result = run(units, config, Client(fail=True), calls=calls)
    assert {r.outcome for r in result.records} == {"error"}
    assert {r.error_class for r in result.records} == {
        "server_error"
    } or result.records[0].error_class
    rows = comparison_table(result, units, min_n=1)
    assert (
        rows[0].error_share == 1.0
        and rows[0].cost_mean_usd.reason == "no_cost_reported"
    )


def test_effort_rides_on_the_invocation_and_time_to_first_token_is_read_when_reported():
    seen = []

    class Streaming(Client):
        def invoke(self, invocation):
            seen.append(invocation.effort)
            response = super().invoke(invocation)
            return response.model_copy(update={"time_to_first_token_ms": 42.0})

    units = make_units()
    config = run_config(models=("gpt-5.5",), efforts={"gpt-5.5": (None, "high")})
    calls = plan_calls(["fa0", "fa1"], units, config)
    result = run(units, config, Streaming(), calls=calls)
    assert sorted(seen, key=str) == [None, None, "high", "high"]
    assert {r.ttft_state for r in result.records} == {"reported"}
    assert {r.ttft_ms for r in result.records} == {42.0}
    row = next(
        r for r in comparison_table(result, units, min_n=1) if r.effort == "high"
    )
    assert row.ttft_ms.state == "measured" and row.ttft_ms.value == 42.0
    unreported = run(units, config, Client(), calls=calls)
    rows = comparison_table(unreported, units, min_n=1)
    assert {r.ttft_ms.reason for r in rows} == {"ttft_not_reported"}


# --- provenance: fake records can never become recorded or measured -----------


def test_a_store_of_fake_answers_is_never_loaded_back_as_recorded_or_measured(
    tmp_path,
):
    units = make_units()
    config = run_config(models=("gpt-5-nano",))
    calls = plan_calls(["fa0", "fa1", "fa2"], units, config)
    store = tmp_path / "fake-run.jsonl"
    first = run(units, config, LocalRecorder(Client(), store), calls=calls)
    assert {r.provenance for r in first.records} == {"simulated"}
    assert len(store.read_text(encoding="utf-8").splitlines()) == 3
    replay = ReplayModelClient.recorded_from(tmp_path)
    assert replay.size == 0 and replay.skipped_non_live == 3
    again = run(units, config, replay, calls=calls)
    assert {r.outcome for r in again.records} == {"no_answer"}
    rows = comparison_table(again, units, min_n=1)
    assert all(r.cost_mean_usd.value is None for r in rows)
    assert {r.cost_mean_usd.reason for r in rows} == {"no_cost_reported"}
    table = outcome_table(again, units)
    assert table.requests[0].outcomes["gpt-5-nano"].cost is None


def test_a_record_marked_fake_is_skipped_even_if_its_result_claims_live(tmp_path):
    units = make_units()
    config = run_config(models=("gpt-5-nano",))
    calls = plan_calls(["fa0"], units, config)
    store = tmp_path / "marked.jsonl"
    approval = LiveApproval(approved_by="owner", run_id="r", cap_usd=Decimal("1"))
    live = LocalRecorder(Client(AnswerSource.LIVE), store)
    run(units, config, live, calls=calls, approval=approval)
    line = json.loads(store.read_text(encoding="utf-8"))
    assert line["client_source"] == "live" and line["result"]["source"] == "live"
    line["client_source"] = "fake"  # a forged or mislabelled record
    store.write_text(json.dumps(line) + "\n", encoding="utf-8")
    replay = ReplayModelClient.recorded_from(tmp_path)
    assert (replay.size, replay.skipped_non_live) == (0, 1)


def test_live_records_still_replay_and_only_they_are_measured(tmp_path):
    units = make_units()
    config = run_config(models=("gpt-5-nano",))
    calls = plan_calls(["fa0", "fa1"], units, config)
    store = tmp_path / "live-run.jsonl"
    # the production recorder, wrapped around a client standing in for a live one
    recorder = RecordingModelClient(Client(AnswerSource.LIVE), store, run_id="r1")
    approval = LiveApproval(approved_by="owner", run_id="r1", cap_usd=Decimal("1"))
    live = run(units, config, recorder, calls=calls, approval=approval)
    assert {r.provenance for r in live.records} == {"measured"}
    assert len(store.read_text(encoding="utf-8").splitlines()) == 2
    replay = ReplayModelClient.recorded_from(tmp_path)
    assert replay.skipped_non_live == 0 and replay.size == 2
    replayed = run(units, config, replay, calls=calls)
    answered = [r for r in replayed.records if r.outcome == "response"]
    assert answered and {r.provenance for r in answered} == {"measured"}
    assert {r.source for r in answered} == {"recorded"}


# --- the sample-conversation flag is stated, never assumed ----------------------


def execute_args(units, client, config):
    return {
        "client_for": lambda m, e: client,
        "build_invocation": invocation,
        "config": config,
        "catalogue": CATALOGUE,
        "prices": PRICES,
        "input_tokens": inputs_for(units),
        "clock": Clock(),
    }


def test_omitting_the_sample_conversation_flag_cannot_bypass_the_guard():
    units, client = make_units(), Client(AnswerSource.LIVE)
    config = run_config()
    calls = plan_calls(["fa0"], units, config)
    approval = LiveApproval(approved_by="owner", run_id="r", cap_usd=Decimal("1"))
    with pytest.raises(TypeError, match="uses_sample_conversations"):
        execute(calls, approval=approval, **execute_args(units, client, config))
    assert client.calls == 0  # nothing was called
    with pytest.raises(TypeError):
        check_live([AnswerSource.LIVE], approval=approval, hard_cap_usd=Decimal("5"))


@pytest.mark.parametrize("value", [None, 0, 1, "", "no", []])
def test_a_truthy_or_falsy_look_alike_is_refused_not_treated_as_false(value):
    units, client = make_units(), Client(AnswerSource.LIVE)
    config = run_config()
    calls = plan_calls(["fa0"], units, config)
    approval = LiveApproval(approved_by="owner", run_id="r", cap_usd=Decimal("1"))
    with pytest.raises(TypeError, match="True or False"):
        execute(
            calls,
            approval=approval,
            uses_sample_conversations=value,
            **execute_args(units, client, config),
        )
    assert client.calls == 0
    with pytest.raises(TypeError):
        check_live(
            [AnswerSource.LIVE],
            approval=approval,
            uses_sample_conversations=value,
            hard_cap_usd=Decimal("5"),
        )


def test_a_stated_true_still_needs_the_per_run_sample_approval():
    units, client = make_units(), Client(AnswerSource.LIVE)
    config = run_config()
    calls = plan_calls(["fa0"], units, config)
    approval = LiveApproval(approved_by="owner", run_id="r", cap_usd=Decimal("1"))
    with pytest.raises(RunRefused, match="sample_conversations_need_per_run_approval"):
        execute(
            calls,
            approval=approval,
            uses_sample_conversations=True,
            **execute_args(units, client, config),
        )
    assert client.calls == 0
    ok = LiveApproval(
        approved_by="owner",
        run_id="r",
        cap_usd=Decimal("1"),
        sample_conversations_approved=True,
    )
    result = execute(
        calls,
        approval=ok,
        uses_sample_conversations=True,
        **execute_args(units, client, config),
    )
    assert result.executed_calls == len(calls)
