"""The ID mapping between a dataset and the one it was derived from (pure, ADR-0029).

IDs only: no text, no labels' rationale. A derived dataset keeps every record of its
base except the removed ones, and each removed record gets a replacement in its cell,
so reviewed labels of the unchanged records can carry over.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any


def build_mapping(
    base: Mapping[str, str],
    new: Mapping[str, str],
    replacements: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Rows linking record ids. ``base`` and ``new`` map request id → record id;
    ``replacements`` are the selection's moves (``removed`` and ``replacement``
    request ids; a move without ``replacement`` found no candidate)."""
    replaced = {
        m["removed"]: m.get("replacement") for m in replacements if "removed" in m
    }
    taken = {r for r in replaced.values() if r}
    rows: list[dict[str, Any]] = []
    for request_id in sorted(base):
        if request_id in new:
            rows.append(
                {
                    "base_record_id": base[request_id],
                    "record_id": new[request_id],
                    "request_id": request_id,
                    "status": "same",
                }
            )
            continue
        target = replaced.get(request_id)
        rows.append(
            {
                "base_record_id": base[request_id],
                "record_id": None,
                "request_id": request_id,
                "status": "removed",
                "replaced_by": new.get(target) if target else None,
            }
        )
    for request_id in sorted(taken):
        rows.append(
            {
                "base_record_id": None,
                "record_id": new[request_id],
                "request_id": request_id,
                "status": "replacement",
                "replaces": next(
                    base[removed]
                    for removed, got in sorted(replaced.items())
                    if got == request_id
                ),
            }
        )
    return rows


def carry_labels(
    lines: Iterable[str], mapping: Iterable[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """Base labels re-keyed to the derived dataset's record ids. Labels of removed
    records are dropped; their count is returned so the caller can report it."""
    ids = {
        m["base_record_id"]: m["record_id"]
        for m in mapping
        if m["status"] == "same" and m["record_id"]
    }
    carried, dropped = [], 0
    for line in lines:
        if not line.strip():
            continue
        row = json.loads(line)
        new_id = ids.get(row["record_id"])
        if new_id is None:
            dropped += 1
            continue
        carried.append({**row, "record_id": new_id})
    return carried, dropped
