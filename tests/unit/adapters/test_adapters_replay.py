"""Replay client: logged-match and recorded sources (Stage 8, ADR-0014). SYNTHETIC."""

import json

import pytest

from metis_auto.adapters.providers import ReplayModelClient
from metis_auto.adapters.providers.fake import FakeModelClient
from metis_auto.adapters.providers.recording import RecordingModelClient
from metis_auto.contracts import (
    AnswerSource,
    AttemptKind,
    ComponentName,
    InputPart,
    ModelInvocation,
    ModelNoAnswer,
    ModelResponse,
    NoAnswerReason,
    PartRole,
)


def inv(model="gpt-4o-mini", case="case:1", text="[SYNTHETIC] hi"):
    return ModelInvocation(
        request_id="req-1",
        attempt_id="att-1",
        attempt_kind=AttemptKind.PRIMARY,
        model_id=model,
        parts=(
            InputPart(role=PartRole.USER, text=text, component=ComponentName.MESSAGE),
        ),
        case_id=case,
    )


def logged():
    refs = {
        "case:1": [("gpt-4o-mini", "[SYNTHETIC] logged answer")],
        "case:2": [("claude-x", "[SYNTHETIC] other")],
        "case:3": [(None, "[SYNTHETIC] unknown label")],
        "case:4": [],
    }
    return ReplayModelClient.logged(
        refs, {"gpt-4o-mini": "gpt-4o-mini", "deepseek-chat": "deepseek-v4-flash"}
    )


def test_logged_answer_only_for_the_mapped_model():
    client = logged()
    got = client.invoke(inv())
    assert isinstance(got, ModelResponse) and got.source == AnswerSource.LOGGED
    assert got.usage is None  # counted by the pipeline (A-40)
    other = client.invoke(inv(model="gpt-5-nano"))
    assert (
        isinstance(other, ModelNoAnswer)
        and other.reason == NoAnswerReason.TARGET_NOT_LOGGED_MODEL
    )


def test_logged_no_answer_reasons():
    client = logged()
    assert client.invoke(inv(case="case:2")).reason == NoAnswerReason.LABEL_UNMAPPED
    assert client.invoke(inv(case="case:3")).reason == NoAnswerReason.LABEL_UNMAPPED
    assert client.invoke(inv(case="case:4")).reason == NoAnswerReason.NOT_RECORDED
    assert client.invoke(inv(case="case:missing")).reason == NoAnswerReason.NOT_RECORDED


class _Live(FakeModelClient):
    @property
    def source(self):
        return AnswerSource.LIVE


def test_recorded_lookup_by_model_and_exact_input(tmp_path):
    path = tmp_path / "live-run.jsonl"
    recorder = RecordingModelClient(_Live(), path, run_id="run-x")
    recorder.invoke(inv(case=None))
    client = ReplayModelClient.recorded_from(tmp_path)
    assert client.size == 1
    hit = client.invoke(inv(case="case:any"))  # the case ID is not needed
    assert isinstance(hit, ModelResponse) and hit.source == AnswerSource.RECORDED
    assert client.invoke(inv(model="gpt-5-nano")).reason == NoAnswerReason.NOT_RECORDED
    assert (
        client.invoke(inv(text="[SYNTHETIC] other")).reason
        == NoAnswerReason.NOT_RECORDED
    )


def test_recorded_skips_errors_and_prefers_complete(tmp_path):
    base = inv(case=None).model_dump(mode="json")
    lines = [
        {
            "v": 1,
            "time": "t",
            "run_id": "r",
            "invocation": base,
            "result": {
                "outcome": "response",
                "text": "[SYNTHETIC] full",
                "finish_reason": "complete",
                "source": "live",
            },
        },
        {
            "v": 1,
            "time": "t",
            "run_id": "r",
            "invocation": base,
            "result": {
                "outcome": "response",
                "text": "[SYNTHETIC] cut",
                "finish_reason": "length",
                "source": "live",
            },
        },
        {
            "v": 1,
            "time": "t",
            "run_id": "r",
            "invocation": base,
            "result": {
                "outcome": "error",
                "error_class": "timeout",
                "retryable": True,
                "source": "live",
            },
        },
    ]
    (tmp_path / "a.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    got = ReplayModelClient.recorded_from(tmp_path).invoke(inv())
    assert got.text == "[SYNTHETIC] full"


# --- provenance: only records made live are ever replayed as recorded ---------


def _record(source, *, marker=None, text="[SYNTHETIC] a"):
    line = {
        "v": 1,
        "time": "t",
        "run_id": "r",
        "invocation": inv(case=None).model_dump(mode="json"),
        "result": {
            "outcome": "response",
            "text": text,
            "finish_reason": "complete",
            "source": source,
        },
    }
    if marker is not None:
        line["client_source"] = marker
    return json.dumps(line)


@pytest.mark.parametrize(
    "source, marker",
    [
        ("fake", None),
        ("fake", "fake"),
        ("recorded", None),
        ("logged", None),
        ("live", "fake"),
    ],
)
def test_non_live_records_are_skipped_not_relabelled_as_recorded(
    tmp_path, source, marker
):
    (tmp_path / "x.jsonl").write_text(_record(source, marker=marker) + "\n")
    client = ReplayModelClient.recorded_from(tmp_path)
    assert (client.size, client.skipped_non_live) == (0, 1)
    assert client.invoke(inv()).reason == NoAnswerReason.NOT_RECORDED


@pytest.mark.parametrize(
    "source, marker", [("live", None), ("live", "live"), ("fake", "live")]
)
def test_records_made_live_are_still_replayed(tmp_path, source, marker):
    """``("fake", "live")`` is the recorder's own marker around a stand-in client
    (the existing recorder tests do this); the marker, not the stand-in's result
    source, says the record was made live."""
    (tmp_path / "x.jsonl").write_text(_record(source, marker=marker) + "\n")
    client = ReplayModelClient.recorded_from(tmp_path)
    assert (client.size, client.skipped_non_live) == (1, 0)
    hit = client.invoke(inv())
    assert isinstance(hit, ModelResponse) and hit.source == AnswerSource.RECORDED


def test_live_and_non_live_records_in_one_directory_keep_only_the_live_ones(tmp_path):
    lines = [
        _record("fake", text="[SYNTHETIC] simulated"),
        _record("live", text="[SYNTHETIC] real"),
    ]
    (tmp_path / "mixed.jsonl").write_text("\n".join(lines) + "\n")
    client = ReplayModelClient.recorded_from(tmp_path)
    assert client.skipped_non_live == 1
    assert client.invoke(inv()).text == "[SYNTHETIC] real"


def test_the_recorder_marks_what_it_writes_as_live(tmp_path):
    path = tmp_path / "live-run.jsonl"
    RecordingModelClient(_Live(), path, run_id="run-x").invoke(inv(case=None))
    assert json.loads(path.read_text())["client_source"] == "live"
