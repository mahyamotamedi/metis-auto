"""Decision 7, one shared spend total: content-free ledger summaries, the merge,
and ``SharedSpendLedger`` bounding this machine's spend by the team total
(fails closed). Plus ``ReplayFirstClient``: a recorded answer replays, a new
input goes live. ADR-0053. SYNTHETIC ledgers; no
network; no real ledger is touched."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from metis_auto.adapters.providers import FakeModelClient
from metis_auto.adapters.providers.recording import RecordingModelClient
from metis_auto.adapters.providers.replay import ReplayModelClient
from metis_auto.adapters.providers.replay_first import ReplayFirstClient
from metis_auto.adapters.system import FileSpendLedger
from metis_auto.adapters.system.shared_spend import (
    LedgerSummary,
    SharedSpendError,
    SharedSpendLedger,
    merge_summaries,
    summarise_ledger,
)
from metis_auto.contracts import (
    AnswerSource,
    AttemptKind,
    ComponentName,
    FinishReason,
    InputPart,
    ModelInvocation,
    ModelResponse,
    Money,
    PartRole,
)

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
USD = "USD"


def _write_ledger(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps({"v": 1, "time": t, "run_id": r, "amount": a, "currency": USD})
            + "\n"
            for t, r, a in rows
        ),
        encoding="utf-8",
    )


def test_summary_is_read_only_content_free_and_per_run(tmp_path):
    path = tmp_path / "ledger.jsonl"
    _write_ledger(
        path,
        [
            ("2026-11-01T10:00:00+00:00", "golden-answers", "12.0"),
            ("2026-11-03T09:00:00+00:00", "router-live-check", "0.0016"),
            ("2026-11-03T09:30:00+00:00", "golden-answers", "0.03"),
        ],
    )
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    s = summarise_ledger(path, machine="syn-m1", currency=USD, created_at=NOW)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before  # untouched
    assert s.total == Decimal("12.0316") and s.charges == 3
    assert s.by_run == {
        "golden-answers": Decimal("12.03"),
        "router-live-check": Decimal("0.0016"),
    }
    assert s.newest_charge == "2026-11-03T09:30:00+00:00"
    assert s.ledger_sha256 == before
    data = s.to_json()
    assert set(data) == {
        "format",
        "machine",
        "currency",
        "total",
        "charges",
        "by_run",
        "newest_charge",
        "created_at",
        "ledger_sha256",
    }
    assert LedgerSummary.from_json(data) == s


def test_missing_ledger_is_zero_and_a_bad_line_refuses(tmp_path):
    empty = summarise_ledger(
        tmp_path / "none.jsonl", machine="m", currency=USD, created_at=NOW
    )
    assert empty.total == 0 and empty.charges == 0 and empty.ledger_sha256 is None
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"amount": "x"}\n', encoding="utf-8")
    with pytest.raises(SharedSpendError, match="line 1"):
        summarise_ledger(bad, machine="m", currency=USD, created_at=NOW)
    with pytest.raises(SharedSpendError):
        LedgerSummary.from_json({"format": "other"})


def _summary(machine, total, created=NOW):
    return LedgerSummary(
        machine=machine,
        currency=USD,
        total=Decimal(total),
        charges=1,
        created_at=created.isoformat(),
    )


def test_merge_keeps_the_newest_summary_per_machine():
    merged = merge_summaries(
        [
            _summary("m1", "1", NOW - timedelta(hours=2)),
            _summary("m1", "2", NOW),
            _summary("m2", "12.03", NOW),
        ]
    )
    assert merged["team_total"] == "14.03"
    assert merged["machines"]["m1"]["total"] == "2"
    with pytest.raises(SharedSpendError, match="currencies"):
        merge_summaries(
            [
                _summary("m1", "1"),
                LedgerSummary("m2", "EUR", Decimal(1), 1, created_at="x"),
            ]
        )


def _local(tmp_path, spent="0.5", cap="20", run_cap="1"):
    path = tmp_path / "local.jsonl"
    if spent != "0":
        _write_ledger(path, [("2026-11-03T08:00:00+00:00", "older-run", spent)])
    return FileSpendLedger(
        path,
        run_id="bench-run",
        lifetime_cap=Money(amount=Decimal(cap), currency=USD),
        run_cap=Money(amount=Decimal(run_cap), currency=USD),
    )


def _shared(local, others, **kw):
    args = dict(
        machine="me",
        others=others,
        expected_machines=["me", "m2", "m3"],
        ceiling=Money(amount=Decimal("20"), currency=USD),
        now=NOW,
        max_age=timedelta(hours=12),
    )
    args.update(kw)
    return SharedSpendLedger(local, **args)


def test_shared_ledger_bounds_spend_by_the_team_total(tmp_path):
    local = _local(tmp_path, spent="0.5", run_cap="5")
    shared = _shared(local, [_summary("m2", "12.03"), _summary("m3", "7")])
    # 20 - (12.03 + 7 + 0.5) = 0.47, less than the local 5 USD run cap
    assert shared.team_total() == Decimal("19.53")
    assert shared.remaining().amount == Decimal("0.47")
    shared.charge(Money(amount=Decimal("0.4"), currency=USD))
    assert shared.remaining().amount == Decimal("0.07")
    assert local.status().run_spent == Decimal("0.4")  # charged locally only
    over = _shared(local, [_summary("m2", "15"), _summary("m3", "7")])
    assert over.remaining().amount == 0  # never negative


def test_local_caps_still_apply_when_the_team_is_far_below(tmp_path):
    local = _local(tmp_path, spent="0", run_cap="1")
    shared = _shared(local, [_summary("m2", "0.1"), _summary("m3", "0.1")])
    assert shared.remaining().amount == Decimal("1")


def test_shared_ledger_fails_closed(tmp_path):
    local = _local(tmp_path)
    with pytest.raises(SharedSpendError, match="no ledger summary from: m3"):
        _shared(local, [_summary("m2", "1")])
    with pytest.raises(SharedSpendError, match="old"):
        _shared(
            local, [_summary("m2", "1"), _summary("m3", "1", NOW - timedelta(hours=13))]
        )
    with pytest.raises(SharedSpendError, match="counted twice"):
        _shared(local, [_summary("me", "1"), _summary("m2", "1"), _summary("m3", "1")])


# --- replay first -----------------------------------------------------------------


def _inv(text, model="syn-model"):
    return ModelInvocation(
        request_id="syn-req",
        attempt_id="syn-att",
        attempt_kind=AttemptKind.PRIMARY,
        model_id=model,
        parts=(
            InputPart(role=PartRole.USER, text=text, component=ComponentName.MESSAGE),
        ),
        max_output_tokens=32,
    )


class Live:
    def __init__(self):
        self.calls = 0

    @property
    def source(self):
        return AnswerSource.LIVE

    def invoke(self, invocation):
        self.calls += 1
        return ModelResponse(
            text="[SYNTHETIC] live answer",
            finish_reason=FinishReason.COMPLETE,
            source=AnswerSource.LIVE,
        )


def test_replay_first_replays_recorded_inputs_and_calls_live_once(tmp_path):
    live = Live()
    recorder = RecordingModelClient(live, tmp_path / "live-run.jsonl", run_id="r1")
    recorder.invoke(_inv("[SYNTHETIC] q1"))
    assert live.calls == 1
    client = ReplayFirstClient(ReplayModelClient.recorded_from(tmp_path), recorder)
    assert client.source == AnswerSource.LIVE  # the run still needs approval
    again = client.invoke(_inv("[SYNTHETIC] q1"))
    assert again.source == AnswerSource.RECORDED and live.calls == 1
    fresh = client.invoke(_inv("[SYNTHETIC] q2"))
    assert fresh.source == AnswerSource.LIVE and live.calls == 2
    assert (client.replayed, client.live_calls) == (1, 1)


class CutOffLive(Live):
    def invoke(self, invocation):
        self.calls += 1
        return ModelResponse(
            text="" if self.calls == 1 else "[SYNTHETIC] verdict",
            finish_reason=(
                FinishReason.LENGTH if self.calls == 1 else FinishReason.COMPLETE
            ),
            source=AnswerSource.LIVE,
        )


def test_replay_first_asks_again_after_a_cut_off_empty_recording(tmp_path):
    live = CutOffLive()
    recorder = RecordingModelClient(live, tmp_path / "live-run.jsonl", run_id="r1")
    recorder.invoke(_inv("[SYNTHETIC] q1"))
    client = ReplayFirstClient(ReplayModelClient.recorded_from(tmp_path), recorder)
    again = client.invoke(_inv("[SYNTHETIC] q1"))
    assert again.text == "[SYNTHETIC] verdict" and live.calls == 2
    assert (client.replayed, client.live_calls) == (0, 1)


def test_replay_first_needs_a_recorded_replay():
    with pytest.raises(ValueError):
        ReplayFirstClient(FakeModelClient(), Live())
