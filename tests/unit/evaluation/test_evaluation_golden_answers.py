"""Offline tests for the golden-answer run (ADR-0030): request building, the loop's
independence, resume, retries and refusals, the summary, the approval flag.

All text is [SYNTHETIC]. A fake client answers; no provider, no key, no database.
"""

import json
import tomllib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from metis_auto.adapters.system import FakeClock
from metis_auto.contracts import (
    AnswerSource,
    ComponentName,
    ErrorClass,
    Fidelity,
    FinishReason,
    InputPart,
    ModelError,
    ModelResponse,
    PartRole,
    TokenCount,
    TokenUsage,
)
from metis_auto.evaluation.golden_answers.config import (
    RETRYABLE,
    AnswerSettings,
    SettingsError,
    parse_settings,
)
from metis_auto.evaluation.golden_answers.request import (
    LAYOUT_VERSION,
    build_request,
    prompt_fingerprint,
)
from metis_auto.evaluation.golden_answers.runner import (
    AnswerRow,
    Task,
    run_answers,
    select_pilot,
)
from metis_auto.evaluation.golden_answers.summary import (
    MEDIA_CAVEAT,
    language_mismatch,
    quantile,
    summarise,
)
from metis_auto.settings import load_settings
from metis_auto.wiring.golden_answers import GoldenAnswers, RunRefused

ROOT = Path(__file__).resolve().parents[3]
RAW = tomllib.loads((ROOT / "config/evaluation/golden_answers.toml").read_text())


def settings(**run) -> AnswerSettings:
    raw = json.loads(json.dumps(RAW, default=str))
    raw["run"].update(run)
    return parse_settings(raw)


@pytest.fixture(scope="module")
def loaded():
    return load_settings(environ={}, dotenv=None, runtime=None)


@pytest.fixture(scope="module")
def entry(loaded):
    return next(
        e for e in loaded.reference.catalogue.entries if e.model_id == "gpt-5.5"
    )


# --- settings ----------------------------------------------------------------------


def test_the_committed_settings_are_the_owners_decision():
    s = parse_settings(RAW)
    assert (s.model_id, s.reasoning_effort, s.max_output_tokens) == (
        "gpt-5.5",
        "medium",
        8192,
    )
    assert s.dataset_id == "golden-v2"
    assert s.context_window == 1_050_000 and s.model_output_limit == 128_000


def test_the_settings_hash_changes_with_any_setting_that_shapes_an_answer():
    base = settings().settings_hash
    assert settings().settings_hash == base
    assert settings(reasoning_effort="high").settings_hash != base
    assert settings(max_output_tokens=4096).settings_hash != base
    assert parse_settings(RAW).manifest()["settings_hash"] == base


def test_impossible_settings_are_rejected():
    with pytest.raises(SettingsError, match="output limit"):
        settings(max_output_tokens=200_000)
    raw = json.loads(json.dumps(RAW, default=str))
    raw["retry"]["backoff_seconds"] = [1]
    with pytest.raises(SettingsError, match="one wait per retry"):
        parse_settings(raw)


def test_content_filter_overflow_and_unknown_model_are_not_retried():
    assert RETRYABLE == {"timeout", "rate_limited", "unavailable", "connection"}
    for fatal in ("content_filtered", "context_overflow", "invalid_request", "auth"):
        assert fatal not in RETRYABLE


# --- request -----------------------------------------------------------------------


def row(pos, kind, role="", content=None, metadata=None):
    return {
        "position": pos,
        "kind": kind,
        "role": role,
        "content": content,
        "metadata": metadata or {},
    }


def view_rows():
    return [
        row(1, "bot_instruction", "system", "[SYNTHETIC] instructions"),
        row(2, "bot_configuration", metadata={"config_unknown": False}),
        row(3, "earlier_message", "USER", "[SYNTHETIC] earlier question"),
        row(4, "earlier_message", "AI", "[SYNTHETIC] earlier answer"),
        row(5, "target_user_message", "USER", "[SYNTHETIC] the question"),
        row(6, "target_rag_chunk", "", "[SYNTHETIC] chunk one"),
        row(7, "target_rag_chunk", "", "[SYNTHETIC] chunk two"),
    ]


def test_parts_follow_the_pass_through_order_and_add_no_system_prompt():
    built = build_request(view_rows(), {"bot_instruction", "target_user_message"})
    assert [p.role for p in built.parts] == [
        PartRole.INSTRUCTIONS,
        PartRole.USER,
        PartRole.ASSISTANT,
        PartRole.RETRIEVED,
        PartRole.RETRIEVED,
        PartRole.USER,
    ]
    assert built.parts[-1].text == "[SYNTHETIC] the question"
    assert len(built.parts) == 6  # one part per component text, nothing extra
    assert LAYOUT_VERSION == "pass_through_v1"


def test_the_order_matches_the_projects_pass_through_strategy():
    # the retrieved chunks sit after the user message in the dataset's positions,
    # but are sent before it, as domain.context.pass_through does
    built = build_request(view_rows(), set())
    comps = [p.component for p in built.parts]
    assert comps.index(ComponentName.RETRIEVED) < comps.index(ComponentName.MESSAGE)
    assert comps[0] == ComponentName.INSTRUCTIONS


def test_blank_instructions_are_skipped_and_flagged_not_replaced():
    rows = view_rows()
    rows[0] = row(1, "bot_instruction", "system", "   ")
    built = build_request(rows, set())
    assert PartRole.INSTRUCTIONS not in [p.role for p in built.parts]
    assert "no_instructions" in built.caveats


def test_caveats_carry_the_datasets_flags():
    rows = view_rows()
    rows[1] = row(2, "bot_configuration", metadata={"config_unknown": True})
    built = build_request(
        rows,
        {"input_widget_definition", "attachment_metadata", "earlier_rag_chunk"},
    )
    assert set(built.caveats) == {
        "config_unknown",
        "input_widget_not_sent",
        "attachments_not_sent",
        "earlier_rag_not_sent",
    }


def test_a_record_without_exactly_one_target_is_refused():
    with pytest.raises(ValueError, match="exactly one"):
        build_request(view_rows()[:4], set())


def test_the_prompt_fingerprint_is_stable_ordered_and_hides_text():
    parts = build_request(view_rows(), set()).parts
    assert prompt_fingerprint(parts) == prompt_fingerprint(parts)
    assert prompt_fingerprint(parts) != prompt_fingerprint(parts[::-1])
    assert "SYNTHETIC" not in prompt_fingerprint(parts)


# --- loop --------------------------------------------------------------------------


def task(i, language="persian", intent="factual_qa", caveats=()):
    text = f"[SYNTHETIC] question {i}"
    parts = (InputPart(role=PartRole.USER, text=text, component=ComponentName.MESSAGE),)
    return Task(
        record_id=f"gv2-m_{i:03d}",
        parts=parts,
        caveats=tuple(caveats),
        fingerprint=prompt_fingerprint(parts),
        input_tokens=TokenCount(
            tokens=1000, fidelity=Fidelity.EXACT_LOCAL, method="test@1"
        ),
        strata={"language_group": language, "primary_intent": intent},
    )


def usage(inp=1000, out=500, reasoning=300):
    return TokenUsage(
        model_id="gpt-5.5",
        input=TokenCount(
            tokens=inp, fidelity=Fidelity.PROVIDER_REPORTED, method="usage"
        ),
        output=TokenCount(
            tokens=out, fidelity=Fidelity.PROVIDER_REPORTED, method="usage"
        ),
        reasoning=TokenCount(
            tokens=reasoning, fidelity=Fidelity.PROVIDER_REPORTED, method="usage"
        ),
    )


def reply(text="[SYNTHETIC] answer", finish=FinishReason.COMPLETE):
    return ModelResponse(
        text=text,
        finish_reason=finish,
        usage=usage(),
        provider_latency_ms=120.0,
        provider_model_version="gpt-5.5-test",
        source=AnswerSource.LIVE,
    )


def error(cls, retryable=None):
    return ModelError(
        error_class=cls,
        retryable=cls.value in RETRYABLE if retryable is None else retryable,
        source=AnswerSource.LIVE,
    )


class FakeClient:
    """Scripted per request text: a list of results, consumed in order."""

    source = AnswerSource.LIVE

    def __init__(self, script=None):
        self.script = script or {}
        self.invocations = []

    def invoke(self, invocation):
        self.invocations.append(invocation)
        key = invocation.parts[-1].text
        queue = self.script.get(key)
        if queue:
            return queue.pop(0)
        return reply()


class MemoryStore:
    def __init__(self):
        self.rows: dict[str, AnswerRow] = {}
        self.order = []

    def terminal(self, run_id):
        return {k: (r.status, r.error_class) for k, r in self.rows.items()}

    def save(self, row):
        self.order.append(("db", row.record_id))
        self.rows[row.record_id] = row


class FakeSpend:
    def __init__(self, budget=Decimal("1000")):
        self.budget = budget
        self.stopped = None
        self.actual, self.estimated = [], []

    def allows(self, estimate):
        return estimate.cost.amount.amount <= self.budget

    def charge_actual(self, cost, estimate):
        self.budget -= cost.amount.amount
        self.actual.append(cost.amount.amount)

    def charge_estimate(self, estimate):
        self.budget -= estimate.cost.amount.amount
        self.estimated.append(estimate.cost.amount.amount)


def go(tasks, entry, loaded, client=None, store=None, spend=None, **kw):
    store = store if store is not None else MemoryStore()
    client = client or FakeClient()
    spend = spend or FakeSpend()
    clock = kw.pop("clock", FakeClock(datetime(2026, 11, 1, tzinfo=UTC)))
    report = run_answers(
        tasks,
        run_id="run-test",
        client=client,
        entry=entry,
        prices=loaded.reference.prices,
        settings=kw.pop("settings", settings()),
        store=store,
        spend=spend,
        clock=clock,
        classify_language=kw.pop("classify", lambda t: "english"),
        **kw,
    )
    return report, client, store, spend


def test_every_record_gets_its_own_fresh_call_with_only_its_own_parts(entry, loaded):
    tasks = [task(i) for i in range(5)]
    report, client, store, _ = go(tasks, entry, loaded)
    assert report.answered == 5 and report.calls == 5
    sent = [[p.text for p in inv.parts] for inv in client.invocations]
    assert sent == [[f"[SYNTHETIC] question {i}"] for i in range(5)]
    ids = {inv.request_id for inv in client.invocations}
    assert len(ids) == 5  # no shared request or conversation id
    for inv in client.invocations:
        assert inv.model_id == "gpt-5.5" and inv.effort == "medium"
        assert inv.max_output_tokens == 8192
        assert inv.attachments == () and inv.case_id is None  # no replay lookup


def test_a_rerun_makes_no_second_call_for_stored_records(entry, loaded):
    tasks = [task(i) for i in range(4)]
    store = MemoryStore()
    go(tasks, entry, loaded, store=store)
    report, client, _, _ = go(tasks, entry, loaded, store=store)
    assert client.invocations == [] and report.skipped == 4 and report.answered == 0


def test_a_crash_midway_costs_only_the_unfinished_records(entry, loaded):
    tasks = [task(i) for i in range(6)]
    store = MemoryStore()
    go(tasks, entry, loaded, store=store, limit=3)  # "crashes" after three
    assert len(store.rows) == 3
    report, client, _, _ = go(tasks, entry, loaded, store=store)
    assert report.answered == 3 and len(client.invocations) == 3
    assert {i.parts[-1].text for i in client.invocations} == {
        f"[SYNTHETIC] question {i}" for i in (3, 4, 5)
    }


def test_a_retryable_error_is_retried_with_backoff_then_answered(entry, loaded):
    client = FakeClient(
        {"[SYNTHETIC] question 0": [error(ErrorClass.RATE_LIMITED), reply()]}
    )
    clock = FakeClock(datetime(2026, 11, 1, tzinfo=UTC))
    report, _, store, _ = go([task(0)], entry, loaded, client=client, clock=clock)
    assert report.calls == 2 and report.answered == 1
    assert store.rows["gv2-m_000"].attempts == 2
    assert clock.monotonic_ms() >= 5000  # waited the first backoff


def test_retries_stop_at_the_limit_and_a_rerun_tries_again(entry, loaded):
    always = [error(ErrorClass.UNAVAILABLE)] * 3
    client = FakeClient({"[SYNTHETIC] question 0": list(always)})
    _, _, store, _ = go([task(0)], entry, loaded, client=client)
    assert store.rows["gv2-m_000"].status == "failed"
    assert store.rows["gv2-m_000"].error_class == "unavailable"
    assert store.rows["gv2-m_000"].attempts == 3
    # retryable failures are not terminal: the next run tries the record again
    report, _, store, _ = go([task(0)], entry, loaded, store=store)
    assert report.answered == 1 and store.rows["gv2-m_000"].status == "answered"


@pytest.mark.parametrize(
    "cls",
    [ErrorClass.CONTEXT_OVERFLOW, ErrorClass.INVALID_REQUEST, ErrorClass.AUTH],
)
def test_other_errors_are_recorded_once_and_never_retried(entry, loaded, cls):
    client = FakeClient({"[SYNTHETIC] question 0": [error(cls), reply()]})
    report, _, store, _ = go([task(0)], entry, loaded, client=client)
    assert report.calls == 1 and report.failed == 1
    assert store.rows["gv2-m_000"].error_class == cls.value
    rerun, client2, _, _ = go([task(0)], entry, loaded, store=store)
    assert client2.invocations == [] and rerun.skipped == 1  # terminal


def test_a_content_filter_response_is_a_recorded_failure(entry, loaded):
    client = FakeClient(
        {"[SYNTHETIC] question 0": [reply("", FinishReason.CONTENT_FILTER)]}
    )
    _, _, store, _ = go([task(0)], entry, loaded, client=client)
    row = store.rows["gv2-m_000"]
    assert (row.status, row.error_class, row.answer) == (
        "failed",
        "content_filtered",
        None,
    )


def test_a_truncated_answer_is_kept_and_flagged_by_its_finish_reason(entry, loaded):
    client = FakeClient(
        {"[SYNTHETIC] question 0": [reply("[SYNTHETIC] cut", FinishReason.LENGTH)]}
    )
    _, _, store, _ = go([task(0)], entry, loaded, client=client)
    row = store.rows["gv2-m_000"]
    assert (row.status, row.finish_reason) == ("answered", "length")
    assert row.reasoning_tokens == 300 and row.output_tokens == 500


def test_a_timeout_is_charged_at_its_estimate_other_errors_are_not(entry, loaded):
    client = FakeClient(
        {
            "[SYNTHETIC] question 0": [error(ErrorClass.TIMEOUT), reply()],
            "[SYNTHETIC] question 1": [error(ErrorClass.RATE_LIMITED), reply()],
        }
    )
    _, _, _, spend = go([task(0), task(1)], entry, loaded, client=client)
    assert len(spend.estimated) == 1 and len(spend.actual) == 2


def test_the_cap_stops_the_run_before_the_call_not_after(entry, loaded):
    report, client, store, _ = go(
        [task(0), task(1)], entry, loaded, spend=FakeSpend(Decimal("0.001"))
    )
    assert client.invocations == [] and store.rows == {}
    assert report.halts and report.halts[0].reason == "cap_would_be_exceeded"


def test_consecutive_failures_halt_the_run(entry, loaded):
    script = {
        f"[SYNTHETIC] question {i}": [error(ErrorClass.INVALID_REQUEST)]
        for i in range(10)
    }
    report, client, _, _ = go(
        [task(i) for i in range(10)],
        entry,
        loaded,
        client=FakeClient(script),
        halt_after_failed_records=3,
    )
    assert len(client.invocations) == 3
    assert report.halts[-1].reason == "consecutive_failures"


def test_the_local_backup_is_written_before_the_database(entry, loaded):
    store = MemoryStore()
    go(
        [task(0)],
        entry,
        loaded,
        store=store,
        backup=lambda row: store.order.append(("backup", row.record_id)),
    )
    assert store.order == [("backup", "gv2-m_000"), ("db", "gv2-m_000")]


def test_no_reserve_is_ever_swapped_in(entry, loaded):
    script = {"[SYNTHETIC] question 1": [error(ErrorClass.CONTEXT_OVERFLOW)]}
    _, client, store, _ = go(
        [task(0), task(1), task(2)], entry, loaded, client=FakeClient(script)
    )
    assert set(store.rows) == {"gv2-m_000", "gv2-m_001", "gv2-m_002"}
    assert store.rows["gv2-m_001"].status == "failed"
    assert len(client.invocations) == 3  # no replacement record was asked for


def test_the_row_records_settings_fingerprint_usage_cost_and_caveats(entry, loaded):
    t = task(0, caveats=("config_unknown", MEDIA_CAVEAT))
    _, _, store, _ = go([t], entry, loaded)
    row = store.rows[t.record_id]
    assert row.settings_hash == settings().settings_hash
    assert row.prompt_fingerprint == t.fingerprint
    assert (row.input_tokens, row.output_tokens) == (1000, 500)
    assert row.cost_usd and row.cost_usd > 0 and row.cost_state == "reported"
    assert row.provider_model_version == "gpt-5.5-test"
    assert row.caveats == ("config_unknown", MEDIA_CAVEAT)
    assert row.answer_language_group == "english"


# --- pilot -------------------------------------------------------------------------


def varied(n=30):
    langs = ["persian", "english", "mixed", "persian", "persian", "structured"]
    intents = ["factual_qa", "coding", "translation", "math_reasoning"]
    return [task(i, langs[i % 6], intents[i % 4]) for i in range(n)]


def test_the_pilot_covers_strata_and_is_deterministic_and_order_free():
    tasks = varied()
    first = select_pilot(tasks, 10, "seed")
    again = select_pilot(list(reversed(tasks)), 10, "seed")
    assert [t.record_id for t in first] == [t.record_id for t in again]
    langs = {t.strata["language_group"] for t in first}
    intents = {t.strata["primary_intent"] for t in first}
    assert langs == {"persian", "english", "mixed", "structured"}
    assert len(intents) == 4 and len({t.record_id for t in first}) == 10


def test_a_different_seed_may_pick_different_records():
    tasks = varied()
    a = [t.record_id for t in select_pilot(tasks, 10, "one")]
    b = [t.record_id for t in select_pilot(tasks, 10, "two")]
    assert a != b


# --- summary -----------------------------------------------------------------------


def stored(status="answered", language="persian", answer_lang="persian", **kw):
    return {
        "record_id": "r",
        "status": status,
        "error_class": None if status == "answered" else "context_overflow",
        "finish_reason": "complete",
        "answer_language_group": answer_lang if status == "answered" else None,
        "latency_ms": 100.0,
        "input_tokens": 10,
        "cached_input_tokens": 0,
        "output_tokens": 5,
        "reasoning_tokens": 2,
        "cost_usd": Decimal("0.01"),
        "cost_state": "reported",
        "caveats": (),
        "strata": {"language_group": language, "primary_intent": "factual_qa"},
        **kw,
    }


def test_the_summary_counts_failures_truncation_language_and_cost():
    rows = [
        stored(),
        stored(finish_reason="length"),
        stored(answer_lang="english"),
        stored(status="failed"),
        stored(language="mixed", answer_lang="english"),
    ]
    out = summarise(rows, run_id="r1", manifest={"m": 1}, planned=10)
    assert out["records"] == {
        "planned": 10,
        "stored": 5,
        "answered": 4,
        "failed": 1,
        "not_yet_run": 5,
    }
    assert out["failures_by_reason"] == {"context_overflow": 1}
    assert out["truncated"] == {"count": 1, "rate": 0.25}
    lang = out["language_mismatch"]
    assert (lang["evaluated"], lang["mismatches"]) == (3, 1)  # mixed not evaluated
    assert out["cost_usd"] == "0.05"
    assert out["by_stratum"]["language_group"]["persian"] == {
        "answered": 3,
        "failed": 1,
    }


def test_media_records_are_reported_separately():
    rows = [stored(caveats=(MEDIA_CAVEAT,)), stored(), stored(caveats=(MEDIA_CAVEAT,))]
    out = summarise(rows, run_id="r1", manifest={}, planned=3)
    assert out["media_generation_reported_apart"]["records"] == 2
    assert out["caveats"] == {MEDIA_CAVEAT: 2}


def test_a_caveat_listed_twice_on_one_record_counts_once():
    rows = [stored(caveats=(MEDIA_CAVEAT, MEDIA_CAVEAT, "config_unknown"))]
    out = summarise(rows, run_id="r1", manifest={}, planned=1)
    assert out["caveats"] == {MEDIA_CAVEAT: 1, "config_unknown": 1}
    assert out["media_generation_reported_apart"]["records"] == 1


def test_latency_quantiles_use_nearest_rank():
    assert quantile([1, 2, 3, 4], 0.5) == 2 and quantile([1, 2, 3, 4], 0.99) == 4
    assert quantile([], 0.5) is None
    assert language_mismatch("persian", "persian") is False
    assert language_mismatch("persian", "english") is True
    assert language_mismatch("structured", "english") is None


def test_the_summary_holds_no_prompt_or_answer_text(entry, loaded):
    store = MemoryStore()
    go([task(i) for i in range(3)], entry, loaded, store=store)
    rows = [
        {
            **{
                k: getattr(r, k)
                for k in (
                    "status",
                    "error_class",
                    "finish_reason",
                    "answer_language_group",
                    "latency_ms",
                    "input_tokens",
                    "cached_input_tokens",
                    "output_tokens",
                    "reasoning_tokens",
                    "cost_usd",
                    "cost_state",
                    "caveats",
                )
            },
            "strata": {"language_group": "persian"},
        }
        for r in store.rows.values()
    ]
    dumped = json.dumps(
        summarise(rows, run_id="r", manifest=settings().manifest(), planned=3),
        default=str,
    )
    assert "SYNTHETIC" not in dumped and "question" not in dumped


# --- approval flag -----------------------------------------------------------------


def test_real_data_is_not_approved_by_default(loaded):
    assert loaded.settings.golden_answers.real_data_approved is False


def test_an_experiment_file_cannot_set_the_approval(tmp_path):
    from metis_auto.settings import SettingsError as ConfigError

    exp = tmp_path / "exp.toml"
    exp.write_text("[golden_answers]\nreal_data_approved = true\n")
    with pytest.raises(ConfigError):
        load_settings(experiment=exp, environ={}, dotenv=None, runtime=None)


def test_a_live_run_is_refused_without_approval_before_any_call(loaded):
    answers = GoldenAnswers(engine=object(), loaded=loaded, log=lambda _m: None)
    with pytest.raises(RunRefused) as info:
        answers.check_live(loaded)
    assert "real_data_approved is false" in str(info.value)
    assert "live.enabled is false" in str(info.value)


def test_approval_alone_is_not_enough_the_other_keys_are_still_needed():
    approved = load_settings(
        overrides={"golden_answers.real_data_approved": True},
        environ={},
        dotenv=None,
        runtime=None,
    )
    answers = GoldenAnswers(engine=object(), loaded=approved, log=lambda _m: None)
    with pytest.raises(RunRefused) as info:
        answers.check_live(approved)
    assert "real_data_approved" not in str(info.value)
    assert "METIS_API_KEY is not set" in str(info.value)
