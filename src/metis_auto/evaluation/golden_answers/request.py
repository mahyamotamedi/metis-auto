"""A record's request, as golden defines its components (pure, ADR-0030).

Membership, availability and the transmitted flags come from the dataset's
``routing_input_post_retrieval_v1`` rows. Two send orders, chosen by a setting
that is part of the settings hash:

- ``dataset_positions`` (the owner's choice, 2026-11-01): the recorded component
  positions, as Metis sent it. In the dataset the retrieved chunks come after the
  target message.
- ``pass_through``: the project's own order (instructions, history, retrieved,
  user), as ``domain.context.pass_through`` builds it.

No extra system prompt is added: the model answers as the bot would.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from metis_auto.contracts import ComponentName, InputPart, PartRole

LAYOUTS = ("dataset_positions", "pass_through")

_HISTORY = {"USER": PartRole.USER, "AI": PartRole.ASSISTANT}


@dataclass(frozen=True)
class BuiltRequest:
    parts: tuple[InputPart, ...]
    caveats: tuple[str, ...]


def build_request(
    rows: Iterable[Mapping[str, Any]],
    all_kinds: Iterable[str],
    layout: str = "dataset_positions",
) -> BuiltRequest:
    """``rows``: the view rows of one record (kind, role, content, metadata,
    position). ``all_kinds``: every component kind the record has, including
    those in neither profile. Raises if the record has no target message."""
    if layout not in LAYOUTS:
        raise ValueError(f"layout must be one of {LAYOUTS}")
    ordered = sorted(rows, key=lambda r: r["position"])
    kinds = set(all_kinds)
    instructions = [
        r for r in ordered if r["kind"] == "bot_instruction" and _text(r["content"])
    ]
    history = [r for r in ordered if r["kind"] == "earlier_message"]
    chunks = [r for r in ordered if r["kind"] == "target_rag_chunk"]
    targets = [r for r in ordered if r["kind"] == "target_user_message"]
    if len(targets) != 1 or not _text(targets[0]["content"]):
        raise ValueError("a record needs exactly one non-empty target message")

    if layout == "dataset_positions":
        parts = _by_position(ordered)
        return BuiltRequest(tuple(parts), _caveats(ordered, kinds, bool(instructions)))

    parts: list[InputPart] = [
        InputPart(
            role=PartRole.INSTRUCTIONS,
            text=r["content"],
            component=ComponentName.INSTRUCTIONS,
        )
        for r in instructions
    ]
    for i, r in enumerate(x for x in history if _text(x["content"])):
        parts.append(
            InputPart(
                role=_HISTORY[r["role"]],
                text=r["content"],
                component=ComponentName.HISTORY,
                item_index=i,
            )
        )
    for i, r in enumerate(x for x in chunks if _text(x["content"])):
        parts.append(
            InputPart(
                role=PartRole.RETRIEVED,
                text=r["content"],
                component=ComponentName.RETRIEVED,
                item_index=i,
            )
        )
    parts.append(
        InputPart(
            role=PartRole.USER,
            text=targets[0]["content"],
            component=ComponentName.MESSAGE,
        )
    )
    return BuiltRequest(tuple(parts), _caveats(ordered, kinds, bool(instructions)))


def _by_position(ordered: Sequence[Mapping[str, Any]]) -> list[InputPart]:
    """Every text component in its recorded position; components without text
    (bot configuration, input widget) are not parts."""
    parts: list[InputPart] = []
    seen_history = seen_chunks = 0
    for r in ordered:
        if not _text(r["content"]):
            continue
        kind = r["kind"]
        if kind == "bot_instruction":
            parts.append(
                InputPart(
                    role=PartRole.INSTRUCTIONS,
                    text=r["content"],
                    component=ComponentName.INSTRUCTIONS,
                )
            )
        elif kind == "earlier_message":
            parts.append(
                InputPart(
                    role=_HISTORY[r["role"]],
                    text=r["content"],
                    component=ComponentName.HISTORY,
                    item_index=seen_history,
                )
            )
            seen_history += 1
        elif kind == "target_rag_chunk":
            parts.append(
                InputPart(
                    role=PartRole.RETRIEVED,
                    text=r["content"],
                    component=ComponentName.RETRIEVED,
                    item_index=seen_chunks,
                )
            )
            seen_chunks += 1
        elif kind == "target_user_message":
            parts.append(
                InputPart(
                    role=PartRole.USER,
                    text=r["content"],
                    component=ComponentName.MESSAGE,
                )
            )
    return parts


def _caveats(
    rows: Sequence[Mapping[str, Any]], kinds: set[str], has_instructions: bool
) -> tuple[str, ...]:
    found = []
    if not has_instructions:
        found.append("no_instructions")
    if any(
        r["kind"] == "bot_configuration" and (r["metadata"] or {}).get("config_unknown")
        for r in rows
    ):
        found.append("config_unknown")
    if "input_widget_definition" in kinds:
        found.append("input_widget_not_sent")
    if "attachment_metadata" in kinds:
        found.append("attachments_not_sent")
    if "earlier_rag_chunk" in kinds:
        found.append("earlier_rag_not_sent")
    return tuple(found)


def prompt_fingerprint(parts: Sequence[InputPart], layout: str) -> str:
    """Hash of the layout and the ordered (role, text) pairs. The prompt itself is
    never stored."""
    items = [
        [p.role.value, hashlib.sha256(p.text.encode("utf-8")).hexdigest()]
        for p in parts
    ]
    text = json.dumps([layout, items], separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def _text(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""
