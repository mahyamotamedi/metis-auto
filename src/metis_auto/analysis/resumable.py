"""Cheap, resumable re-runs of slow offline steps (Gap 3, sprint close).

Three small helpers, no I/O beyond the folders they are given:

- ``Progress``: a count, the share done and an **estimated** time left from the
  elapsed time (a straight-line estimate, never a guarantee); ``max_eta_s``
  stops a run whose estimate is over a budget (``TooSlow``) so a re-run that
  would not finish in time is abandoned early, not after half an hour.
- ``ResumeLedger``: which named parts of a run are finished, valid only for the
  same ``key`` (a hash of the settings), so a changed candidate list never
  resumes old parts. Without ``resume`` nothing old is trusted.
- ``NeighbourCache`` and ``cached_blocks``: the heavy nearest-neighbour step is
  split into blocks of queries, each stored as one ``.npy`` file under a name
  that hashes the training data, the block and ``k``; an interrupted search
  keeps its finished blocks, and a second variant of the same search (another
  candidate list) reads them instead of recomputing. Entries from an earlier
  run are read only with ``resume``.

Content-free: arrays of row positions only, in git-ignored ``runs/``. Pure
apart from the folders given. Traces: QA-REPRO, QA-COST. Status: provisional.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np


class TooSlow(RuntimeError):
    """The estimated time left is over the budget; the run was stopped."""

    def __init__(self, eta_s: float, max_eta_s: float) -> None:
        super().__init__(
            f"estimated {eta_s / 60:.1f} min left, "
            f"over the {max_eta_s / 60:.1f} min budget"
        )
        self.eta_s = eta_s
        self.max_eta_s = max_eta_s


def block_ranges(n: int, size: int) -> list[tuple[int, int]]:
    if size < 1:
        raise ValueError("size must be at least 1")
    return [(a, min(a + size, n)) for a in range(0, n, size)]


class Progress:
    def __init__(
        self,
        label: str,
        *,
        total: int,
        every_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        emit: Callable[[str], None] = print,
        max_eta_s: float | None = None,
    ) -> None:
        self.label, self.total, self.done = label, total, 0
        self._every, self._clock, self._emit = every_s, clock, emit
        self._max_eta = max_eta_s
        self._start = clock()
        self._last = float("-inf")

    def eta_s(self) -> float | None:
        elapsed = self._clock() - self._start
        if self.done <= 0 or elapsed <= 0:
            return None
        return elapsed * (self.total - self.done) / self.done

    def update(self, n: int = 1) -> None:
        self.done += n
        now = self._clock()
        eta = self.eta_s()
        if now - self._last >= self._every:
            self._last = now
            tail = "" if eta is None else f", ETA {eta:.0f}s"
            self._emit(f"{self.label}: {self.done}/{self.total}{tail}")
        if self._max_eta is not None and eta is not None and eta > self._max_eta:
            raise TooSlow(eta, self._max_eta)


class ResumeLedger:
    def __init__(self, path: Path, *, key: str, resume: bool) -> None:
        self._path, self._key = path, key
        self._done: set[str] = set()
        if resume and path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("key") == key:
                    self._done = set(data.get("done", []))
            except (ValueError, OSError):
                self._done = set()
        elif path.is_file():
            path.unlink()

    def done(self, name: str) -> bool:
        return name in self._done

    def mark(self, name: str) -> None:
        self._done.add(name)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"key": self._key, "done": sorted(self._done)}),
            encoding="utf-8",
        )
        os.replace(tmp, self._path)


class NeighbourCache:
    def __init__(self, folder: Path, *, resume: bool) -> None:
        self._folder, self._resume = folder, resume
        self._written: set[str] = set()

    @staticmethod
    def name(train_hash: str, a: int, b: int, k: int) -> str:
        digest = hashlib.sha256(f"{train_hash}|{a}|{b}|{k}".encode()).hexdigest()
        return f"{digest[:32]}.npy"

    def get(self, name: str) -> np.ndarray | None:
        if name not in self._written and not self._resume:
            return None
        path = self._folder / name
        if not path.is_file():
            return None
        try:
            return np.load(path)
        except (ValueError, OSError):
            return None

    def put(self, name: str, value: np.ndarray) -> None:
        self._folder.mkdir(parents=True, exist_ok=True)
        tmp = self._folder / (name + ".tmp")
        with tmp.open("wb") as handle:
            np.save(handle, value)
        os.replace(tmp, self._folder / name)
        self._written.add(name)


def cached_blocks(
    cache: NeighbourCache,
    train_hash: str,
    n: int,
    size: int,
    compute: Callable[[int, int], np.ndarray],
    *,
    k: int,
    progress: Progress | None = None,
) -> np.ndarray:
    """``compute(a, b)`` for each block of ``size`` queries, read from the cache
    when present, stacked in order. ``n == 0`` gives an empty ``(0, k)`` array."""
    parts = []
    for a, b in block_ranges(n, size):
        name = cache.name(train_hash, a, b, k)
        block = cache.get(name)
        if block is None:
            block = compute(a, b)
            cache.put(name, block)
        parts.append(block)
        if progress is not None:
            progress.update(b - a)
    if not parts:
        return np.empty((0, k), dtype=np.int64)
    return np.concatenate(parts)
