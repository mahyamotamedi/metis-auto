"""View model of the lever results for the demo (CMP-20; final plan D-1, D-2).

Responsibility: turn ``reports/levers/<lever_id>.json`` files (ADR-0032) into
what the demo page shows, with no Streamlit import and no replay logic:
- ``load_view``: every ``*.json`` in one folder through the shared loader
  ``LeverResult.from_json``; other files are never opened, and JSON that is not
  a ``LeverResult`` is counted as skipped. No folder or no result gives an
  empty view with a message, not an error.
- ``waterfall``: one result's baseline, saving and after-cost per cost block
  (``levers.BLOCKS``: ``fees``, ``token_cost``), with totals that are the sum
  of the rows. The unit comes from the baseline (``compare.BASELINES``):
  recorded or repriced, never mixed; ``for_baseline`` picks one baseline.
- ``slice_rows``: the slices to display. Rank slices become labels such as
  ``bot-07``; a slice name outside the known forms is dropped, so no bot or
  user ID can reach a screen (licence: aggregates only).

Traceability: QA-PRIV (content- and ID-free screens), QA-COST and FR-ACCT-05
(savings per block against a named baseline), FR-REQ-04 (unknown is shown as
unknown, never 0), QA-REPRO (results carry their manifest).
Called by: tests; scripts/demo_ui.py in D-2. Calls: analysis.{lever_result,
levers, compare} (read only).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from metis_auto.analysis.compare import BASELINES
from metis_auto.analysis.lever_result import LeverResult
from metis_auto.analysis.levers import BLOCKS

LEVERS_DIR = Path("reports") / "levers"

EMPTY_MESSAGE = (
    "No lever results yet. A replay writes them to reports/levers/<lever_id>.json."
)

_RANK = re.compile(r"^(bot|tenant)_rank:([1-9][0-9]{0,3})$")
_LANG = re.compile(r"^lang:[a-z_]{1,16}$")
_PLAIN_SLICES = ("all", "llm_only", "traffic_weighted", "over_8k")
_UNITS = {b.key: "recorded" if b.recorded else "repriced" for b in BASELINES}


@dataclass(frozen=True)
class LeverView:
    results: tuple[LeverResult, ...]
    """Sorted by ``lever_id``."""
    skipped: int
    """``*.json`` files that are not a valid ``LeverResult``."""

    @property
    def empty(self) -> bool:
        return not self.results

    @property
    def message(self) -> str | None:
        return EMPTY_MESSAGE if self.empty else None

    @property
    def baselines(self) -> tuple[str, ...]:
        return tuple(sorted({r.baseline for r in self.results}))

    def for_baseline(self, baseline: str) -> tuple[LeverResult, ...]:
        return tuple(r for r in self.results if r.baseline == baseline)


def load_view(folder: Path) -> LeverView:
    results: list[LeverResult] = []
    skipped = 0
    paths = sorted(folder.glob("*.json")) if folder.is_dir() else []
    for path in paths:
        try:
            results.append(LeverResult.from_json(path.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, ValidationError):
            skipped += 1
    results.sort(key=lambda r: r.lever_id)
    return LeverView(results=tuple(results), skipped=skipped)


def cost_unit(baseline: str) -> str:
    """``recorded``, ``repriced``, or ``unknown`` for a baseline not in the list."""
    return _UNITS.get(baseline, "unknown")


@dataclass(frozen=True)
class WaterfallRow:
    block: str
    baseline: Decimal | None
    saving: Decimal | None
    after: Decimal | None


@dataclass(frozen=True)
class Waterfall:
    lever_id: str
    baseline: str
    unit: str
    rows: tuple[WaterfallRow, ...]
    baseline_total: Decimal | None
    saving_total: Decimal | None
    after_total: Decimal | None


def _total(values: list[Decimal | None], declared: Decimal | None) -> Decimal | None:
    if any(v is None for v in values):
        return None
    total = sum(values, Decimal(0))
    if declared is not None and declared != total:
        raise ValueError(f"blocks sum to {total}, but the result's total is {declared}")
    return total


def waterfall(result: LeverResult) -> Waterfall:
    """Rows per cost block; a missing block is unknown, and so is every total."""
    rows = []
    for block in BLOCKS:
        base = result.baseline_cost.get(block)
        save = result.saving.get(block)
        after = None if base is None or save is None else base - save
        rows.append(WaterfallRow(block, base, save, after))
    baseline_total = _total(
        [r.baseline for r in rows], result.baseline_cost.get("total")
    )
    saving_total = _total([r.saving for r in rows], result.saving.get("total"))
    after_total = _total([r.after for r in rows], None)
    return Waterfall(
        lever_id=result.lever_id,
        baseline=result.baseline,
        unit=cost_unit(result.baseline),
        rows=tuple(rows),
        baseline_total=baseline_total,
        saving_total=saving_total,
        after_total=after_total,
    )


def rank_label(kind: str, rank: int) -> str:
    return f"{kind}-{rank:02d}"


def slice_label(name: str) -> str | None:
    """Display label of a slice name, or None if it must not be shown."""
    if name in _PLAIN_SLICES or _LANG.match(name):
        return name
    rank = _RANK.match(name)
    return rank_label(rank[1], int(rank[2])) if rank else None


def slice_rows(result: LeverResult) -> list[tuple[str, dict[str, Decimal]]]:
    """(label, values) for every showable slice, in the result's sorted order."""
    rows = []
    for name in sorted(result.slices):
        label = slice_label(name)
        if label is not None:
            rows.append((label, dict(result.slices[name])))
    return rows
