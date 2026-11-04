"""Resume logic of the slow re-runs (Gap 3, sprint close; QA-REPRO). SYNTHETIC
arrays and a fake clock; no data, no network."""

from __future__ import annotations

import numpy as np
import pytest

from metis_auto.analysis.resumable import (
    NeighbourCache,
    Progress,
    ResumeLedger,
    TooSlow,
    block_ranges,
    cached_blocks,
)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_block_ranges_cover_everything_once():
    assert block_ranges(0, 4) == []
    assert block_ranges(10, 4) == [(0, 4), (4, 8), (8, 10)]
    with pytest.raises(ValueError):
        block_ranges(5, 0)


def test_progress_reports_share_and_eta_from_the_clock():
    clock, lines = Clock(), []
    p = Progress("syn", total=100, every_s=0, clock=clock, emit=lines.append)
    clock.t = 10.0
    p.update(25)
    assert p.eta_s() == pytest.approx(30.0)
    assert "25/100" in lines[-1] and "ETA 30s" in lines[-1]
    clock.t = 20.0
    p.update(25)
    assert p.eta_s() == pytest.approx(20.0)


def test_progress_has_no_eta_before_work_and_aborts_when_too_slow():
    clock = Clock()
    p = Progress("syn", total=100, every_s=0, clock=clock, emit=lambda s: None)
    assert p.eta_s() is None
    clock.t = 60.0
    slow = Progress(
        "syn", total=100, every_s=0, clock=Clock(), emit=lambda s: None, max_eta_s=60
    )
    slow._clock = clock
    with pytest.raises(TooSlow) as err:
        slow.update(1)
    assert err.value.eta_s > 60


def test_ledger_resumes_only_with_the_same_key(tmp_path):
    path = tmp_path / "ledger.json"
    first = ResumeLedger(path, key="cfg-1", resume=True)
    assert not first.done("k5")
    first.mark("k5")
    assert ResumeLedger(path, key="cfg-1", resume=True).done("k5")
    assert not ResumeLedger(path, key="cfg-2", resume=True).done("k5")
    fresh = ResumeLedger(path, key="cfg-1", resume=False)
    assert not fresh.done("k5")
    fresh.mark("k15")
    again = ResumeLedger(path, key="cfg-1", resume=True)
    assert again.done("k15") and not again.done("k5")


def test_ledger_ignores_a_corrupt_file(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("{not json", encoding="utf-8")
    assert not ResumeLedger(path, key="x", resume=True).done("a")


def test_blocks_resume_after_a_crash(tmp_path):
    calls = []
    state = {"crash": True}

    def compute(a, b):
        calls.append((a, b))
        if len(calls) == 3 and state["crash"]:
            raise RuntimeError("interrupted")
        return np.arange(a, b)[:, None] * np.ones((1, 2), dtype=np.int64)

    with pytest.raises(RuntimeError):
        cached_blocks(NeighbourCache(tmp_path, resume=True), "t", 10, 4, compute, k=2)
    assert calls == [(0, 4), (4, 8), (8, 10)]
    calls.clear()
    state["crash"] = False
    out = cached_blocks(NeighbourCache(tmp_path, resume=True), "t", 10, 4, compute, k=2)
    assert calls == [(8, 10)]
    assert out.shape == (10, 2) and out[9, 0] == 9


def test_old_entries_need_resume_but_a_run_shares_its_own(tmp_path):
    seen = []

    def compute(a, b):
        seen.append((a, b))
        return np.zeros((b - a, 1), dtype=np.int64)

    cached_blocks(NeighbourCache(tmp_path, resume=True), "t", 4, 4, compute, k=1)
    seen.clear()
    fresh = NeighbourCache(tmp_path, resume=False)
    cached_blocks(fresh, "t", 4, 4, compute, k=1)
    assert seen == [(0, 4)]
    seen.clear()
    cached_blocks(fresh, "t", 4, 4, compute, k=1)  # e.g. the second variant
    assert seen == []


def test_different_k_or_training_hash_never_share_an_entry(tmp_path):
    seen = []

    def compute(a, b):
        seen.append((a, b))
        return np.zeros((b - a, 1), dtype=np.int64)

    c = NeighbourCache(tmp_path, resume=True)
    cached_blocks(c, "t1", 4, 4, compute, k=1)
    cached_blocks(c, "t2", 4, 4, compute, k=1)
    cached_blocks(c, "t1", 4, 4, compute, k=2)
    assert len(seen) == 3


def test_empty_query_set_gives_an_empty_k_wide_array(tmp_path):
    out = cached_blocks(
        NeighbourCache(tmp_path, resume=True), "t", 0, 4, lambda a, b: None, k=3
    )
    assert out.shape == (0, 3)
