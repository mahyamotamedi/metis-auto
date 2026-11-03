"""The 60-item human spot-check of the judges (plan P-2).

``select_items`` picks judged pairs deterministically (keyed hash of ``seed``
and the item ID, round-robin over languages) and gives each an opaque
``spot_id`` (``s01``…). ``sheet_rows`` is the **ID-only** rating sheet: spot ID,
language and empty columns for the rater. Which answer is shown as A is drawn
from the hash; the key (spot ID → item, candidate side) and the text go only to
separate local files built by wiring under git-ignored ``runs/``, so a rater
cannot tell which answer is the reference. Nothing here holds text. Pure.
Traces: FR-EVAL-05, ADR-0006 (judge calibration), QA-PRIV,
ADR-0053. Status: provisional.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from metis_auto.evaluation.judging.pairwise import PairOutcome

SHEET_COLUMNS = ("spot_id", "language", "rater", "rating", "note")
"""``rating``: ``a``, ``b`` or ``tie`` (the answers as labelled A and B in the
local text file)."""


@dataclass(frozen=True)
class SpotItem:
    spot_id: str
    item_id: str
    case_id: str
    language: str
    candidate_first: bool
    """True: the candidate's answer is shown as A."""


def _h(seed: str, value: str) -> str:
    return hashlib.blake2b(f"{seed}\x1f{value}".encode(), digest_size=16).hexdigest()


def select_items(
    outcomes: Sequence[PairOutcome], *, size: int, seed: str
) -> tuple[SpotItem, ...]:
    if size <= 0 or not seed:
        raise ValueError("size and seed are required")
    groups: dict[str, list[PairOutcome]] = defaultdict(list)
    for o in sorted(
        (o for o in outcomes if o.state == "judged"),
        key=lambda o: _h(seed, o.item.item_id),
    ):
        groups[o.item.language].append(o)
    order = sorted(groups, key=lambda g: (-len(groups[g]), g))
    picked: list[SpotItem] = []
    while len(picked) < size and any(groups.values()):
        for g in order:
            if len(picked) >= size or not groups[g]:
                continue
            o = groups[g].pop(0)
            side = int(_h(seed + ":side", o.item.item_id)[:2], 16) % 2 == 0
            spot = f"s{len(picked) + 1:02d}"
            picked.append(SpotItem(spot, o.item.item_id, o.item.case_id, g, side))
    return tuple(picked)


def sheet_rows(items: Sequence[SpotItem]) -> list[dict[str, str]]:
    """The ID-only rating sheet (no text, no hidden side)."""
    return [
        {
            "spot_id": i.spot_id,
            "language": i.language,
            "rater": "",
            "rating": "",
            "note": "",
        }
        for i in items
    ]
