"""THX-01 in process (ADR-XXXX (system-one-decision-router); R5), with a fake agent in
place of thx01 and torch: availability reasons, sha256 pins checked before load, a work
copy so nothing pinned is ever written, contained stdout, answer parsing, timeouts and
calibration. The real model runs only on the owner's machine (the benchmark). SYNTHETIC
text."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fixtures.synthetic import contract_examples as ex

from metis_auto.adapters.routers.thx01_local import PinnedFile, Thx01LocalBackend
from metis_auto.adapters.system import FakeClock
from metis_auto.contracts import (
    AvailabilityReason,
    Component,
    ComponentState,
    DecisionError,
    DecisionResult,
    DecisionState,
    ErrorClass,
    Language,
    LastAssistantTurnKind,
    QuestionLanguage,
)
from metis_auto.settings import load_settings

QUESTIONS = load_settings(
    environ={}, dotenv=None, runtime=None
).reference.router_questions.get("routing_qs_v1", QuestionLanguage.PERSIAN)
REV = "b" * 40


def state() -> DecisionState:
    return DecisionState(
        message="[SYNTHETIC] ساعت کاری فروشگاه چیست؟",
        previous_user_turn=Component.present("[SYNTHETIC] سلام"),
        last_assistant_turn_kind=LastAssistantTurnKind.ANSWER,
        retrieved_state=ComponentState.UNKNOWN,
        language=Language.PERSIAN,
        turn_depth=1,
        dataset_derived=True,
    )


def good_answers() -> dict:
    return {
        "complexity": {
            "type": "score",
            "score": 0.4,
            "probabilities": {"0": 0.7, "1": 0.2, "2": 0.05, "3": 0.05},
            "confidence": 0.66,
            "legend": {},
        },
        "needs_reasoning": {
            "type": "noul",
            "noul": 0.12,
            "confidence": 0.88,
            "action": {},
        },
        "cheap_model_ok": {"type": "noul", "noul": 0.91, "confidence": 0.91},
        "intent": {
            "type": "choice",
            "choice": "factual_qa",
            "probabilities": {"factual_qa": 0.8, "other": 0.2},
            "confidence": 0.7,
        },
        "depends_on_history": {"type": "noul", "noul": 0.3, "confidence": 0.7},
    }


class FakeAgent:
    def __init__(
        self, directory: Path, clock: FakeClock, *, latency_ms=12.0, answers=None
    ):
        self.directory = directory
        self.clock = clock
        self.latency_ms = latency_ms
        self.answers = answers if answers is not None else good_answers()
        self.seen = []
        self.temperature_by_options_raw = {"choice:6-10": 1.2, "choice:11+": 0.1006}
        self.temperature_by_options = {"choice:6-10": 1.2, "choice:11+": 0.5}
        # Like thx01's _fix_tokenizer_config: rewrite a file in the directory.
        cfg = directory / "tokenizer" / "tokenizer_config.json"
        cfg.write_text(json.dumps({"tokenizer_class": "PreTrainedTokenizerFast"}))
        print("Warning: thx01 says something on stdout")

    def system_one(self, state, questions):
        self.seen.append((state, questions))
        print("noise during a call")
        self.clock.advance(self.latency_ms)
        return {
            "model": "THX-01",
            "answers": self.answers,
            "usage": {"input_tokens": 431, "output_tokens": 0},
        }


FILES = {
    "rl_agent_config.json": b'{"encoder": "x"}',
    "model.safetensors": b"SYNTHETIC" * 120_000,  # > 1 MiB: never copied
    "tokenizer/tokenizer.json": b"{}" * 600_000,  # > 1 MiB: never copied
    "tokenizer/tokenizer_config.json": b'{"tokenizer_class": null}',
    "encoder/config.json": b"{}",
}


@pytest.fixture
def checkpoint(tmp_path):
    directory = tmp_path / "thx01" / REV
    pins = []
    for rel, data in FILES.items():
        path = directory / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        pins.append(PinnedFile(rel, hashlib.sha256(data).hexdigest(), len(data)))
    return directory, pins


def backend(checkpoint, *, clock=None, extra=True, revision=REV, **agent_kw):
    directory, pins = checkpoint
    clock = clock or FakeClock(ex.NOW)
    made = []

    def factory(work: Path):
        agent = FakeAgent(work, clock, **agent_kw)
        made.append(agent)
        return agent

    b = Thx01LocalBackend(
        clock,
        name="thx01",
        model_dir=directory,
        revision=revision,
        files=pins if revision else [],
        agent_factory=factory,
        extra_installed=lambda: extra,
    )
    return b, made


def test_availability_reasons(checkpoint):
    assert (
        backend(checkpoint, extra=False)[0].available().reason
        == AvailabilityReason.MISSING_EXTRA
    )
    assert (
        backend(checkpoint, revision=None)[0].available().reason
        == AvailabilityReason.MISSING_ASSETS
    )
    directory, _ = checkpoint
    b, _ = backend(checkpoint)
    assert b.available().available
    (directory / "encoder" / "config.json").unlink()
    assert b.available().reason == AvailabilityReason.MISSING_ASSETS
    onnx = Thx01LocalBackend(
        FakeClock(ex.NOW),
        name="t",
        model_dir=directory,
        revision=REV,
        files=[],
        runtime="onnx",
    )
    assert onnx.available().reason == AvailabilityReason.NOT_CONFIGURED


def test_a_changed_pinned_file_is_refused_before_loading(checkpoint):
    directory, _ = checkpoint
    (directory / "model.safetensors").write_bytes(b"X" + FILES["model.safetensors"][1:])
    b, made = backend(checkpoint)
    report = b.load()
    assert not report.ok and report.reason == AvailabilityReason.SHA_MISMATCH
    assert made == [] and b.available().reason == AvailabilityReason.SHA_MISMATCH
    out = b.decide(state(), QUESTIONS, timeout_ms=60)
    assert isinstance(out, DecisionError) and out.error_class == ErrorClass.UNAVAILABLE


def test_load_uses_a_work_copy_so_pinned_files_never_change(checkpoint, capsys):
    directory, pins = checkpoint
    b, made = backend(checkpoint)
    report = b.load()
    assert report.ok and b.loaded and report.warnings >= 1
    assert capsys.readouterr().out == ""  # thx01's prints are contained
    assert made[0].directory != directory
    for p in pins:  # the agent rewrote its copy, not the pinned file
        assert hashlib.sha256((directory / p.path).read_bytes()).hexdigest() == p.sha256
    assert report.calibrated is False  # a clamped bucket: treat as uncalibrated


def test_the_weights_are_linked_never_copied(checkpoint):
    """A-107 (owner): only the small files thx01 may rewrite are copied; the
    weights and the large tokenizer are hard links to the pinned files."""
    directory, pins = checkpoint
    b, made = backend(checkpoint)
    report = b.load()
    work = made[0].directory
    assert report.linked == 2 and report.copied == 3
    small = sum(p.size_bytes for p in pins if p.size_bytes <= 1 << 20)
    assert report.copied_bytes == small < 1024
    for big in ("model.safetensors", "tokenizer/tokenizer.json"):
        assert (work / big).samefile(directory / big)  # the same file on disk
    assert not (work / "tokenizer" / "tokenizer_config.json").samefile(
        directory / "tokenizer" / "tokenizer_config.json"
    )


def test_if_the_weights_cannot_be_linked_nothing_is_copied(checkpoint, monkeypatch):
    import metis_auto.adapters.routers.thx01_local as module

    def refuse(*_a, **_k):
        raise OSError("links refused")

    monkeypatch.setattr(module.os, "link", refuse)
    monkeypatch.setattr(module.os, "symlink", refuse)
    directory, _ = checkpoint
    b, made = backend(checkpoint)
    report = b.load()
    assert not report.ok and made == []
    assert report.reason == AvailabilityReason.MISSING_ASSETS
    assert "never copied" in report.detail
    work = directory.parent / f"{directory.name}.work"
    assert not (work / "model.safetensors").exists()


def test_decide_sends_the_wire_shape_and_parses_typed_answers(checkpoint, capsys):
    b, made = backend(checkpoint, latency_ms=25)
    b.load()
    out = b.decide(state(), QUESTIONS, timeout_ms=60)
    assert capsys.readouterr().out == ""
    assert isinstance(out, DecisionResult)
    assert out.model_revision == REV and out.latency_ms == 25
    assert out.usage.input.tokens == 431 and out.cost.amount.amount == 0
    by = {a.question_id: a for a in out.answers}
    assert by["intent"].choice == "factual_qa" and by["cheap_model_ok"].p_yes == 0.91
    assert by["complexity"].score == 0.4 and by["needs_reasoning"].confidence == 0.88
    sent_state, sent_questions = made[0].seen[0]
    assert isinstance(sent_state, str) and "Message:" in sent_state
    assert sent_questions["intent"]["type"] == "choice"
    assert len(sent_questions["intent"]["criteria"]) == 10
    assert isinstance(sent_questions["complexity"]["criteria"], list)
    assert "criteria" not in sent_questions["needs_reasoning"]


def test_a_slow_call_is_a_timeout_with_its_real_duration(checkpoint):
    b, _ = backend(checkpoint, latency_ms=90)
    out = b.decide(state(), QUESTIONS, timeout_ms=60)
    assert isinstance(out, DecisionError) and out.error_class == ErrorClass.TIMEOUT
    assert out.latency_ms == 90


@pytest.mark.parametrize(
    "answers",
    [
        {},
        {
            **good_answers(),
            "intent": {
                "type": "choice",
                "choice": "not_an_option",
                "probabilities": {},
            },
        },
        {**good_answers(), "needs_reasoning": {"type": "noul"}},
        "not an object",
    ],
)
def test_malformed_answers_are_an_invalid_response(checkpoint, answers):
    b, _ = backend(checkpoint, answers=answers)
    out = b.decide(state(), QUESTIONS, timeout_ms=60)
    if isinstance(out, DecisionResult):
        # An unknown option passes parsing but not the cascade's check_result.
        from metis_auto.domain.routing.decision import check_result

        assert check_result(out, QUESTIONS) == "unknown_option"
    else:
        assert out.invalid_response


class _Param:
    def __init__(self, dtype):
        self.dtype = dtype


class _Model:
    """A stand-in for the torch module: dtypes as torch prints them."""

    def __init__(self, dtype):
        self.dtype = dtype
        self.training = True
        self.cast = False

    def parameters(self):
        return [_Param(self.dtype), _Param("torch.int64")]

    def buffers(self):
        return []

    def float(self):
        self.cast = True
        self.dtype = "torch.float32"

    def eval(self):
        self.training = False


def test_half_precision_weights_are_cast_to_float32_on_cpu():
    """R5 latency fix (owner, 2026-11-03): F16 weights on CPU are cast to
    float32 at load and recorded; float32 weights are left alone."""
    from metis_auto.adapters.routers.thx01_local import _float32

    class Agent:
        model = _Model("torch.float16")

    agent = Agent()
    found, cast = _float32(agent)
    assert found == ("float16",) and cast is True
    assert agent.model.cast and agent.model.training is False
    again = Agent()
    again.model = _Model("torch.float32")
    assert _float32(again) == (("float32",), False) and not again.model.cast
    assert _float32(object()) == ((), False)  # a fake agent without a model


def test_the_load_report_records_dtypes_and_no_cast_for_a_fake(checkpoint):
    b, _ = backend(checkpoint)
    report = b.load()
    assert report.ok and report.param_dtypes == () and report.cast_to_float32 is False
