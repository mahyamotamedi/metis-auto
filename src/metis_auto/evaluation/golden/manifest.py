"""Golden-set manifest entries, built without target-answer or future leakage (pure).

An evaluation sample is one target user turn plus the context available when it
was answered. The historical answer and every later message are structurally
excluded from ``input_messages``. Reference and review fields start empty.
Manifests that hold message text stay in git-ignored ``runs/``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

MANIFEST_SCHEMA_VERSION = "golden-candidate-0.1"
# Shareable golden-v1 export (wiring.golden). golden-candidate-0.1 stays readable.
GOLDEN_V1_SCHEMA_VERSION = "golden-v1-0.2"
STATUS_PROPOSED = "proposed_candidate"

MANIFEST_FIELDS = (
    "schema_version",
    "status",
    "sample_id",
    "source",
    "input_messages",
    "system_instruction",
    "rag_context_available",
    "primary_category",
    "secondary_tags",
    "cohort",
    "selection",
    "reference_answer",
    "reference_model",
    "reference_settings",
    "review",
)


def build_manifest_entry(
    session_messages: Sequence[Mapping[str, Any]],
    target_message_id: str,
    system_instruction: str | None,
    labels: Mapping[str, Any],
    selection: Mapping[str, Any],
    source: Mapping[str, Any],
) -> dict[str, Any]:
    """One candidate. ``session_messages`` are ordered oldest first.

    Each message has ``message_id``, ``role`` and ``content``. Raises if the target
    is absent or is not a USER message.
    """
    ids = [m["message_id"] for m in session_messages]
    if target_message_id not in ids:
        raise ValueError("target turn is not in the session")
    idx = ids.index(target_message_id)
    if session_messages[idx]["role"] != "USER":
        raise ValueError("target must be a USER turn")
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "status": STATUS_PROPOSED,
        "sample_id": f"gc-{target_message_id}",
        "source": {
            **source,
            "target_message_id": target_message_id,
            "turn_position": idx,
        },
        "input_messages": [
            {"message_id": m["message_id"], "role": m["role"], "content": m["content"]}
            for m in session_messages[: idx + 1]
        ],
        "system_instruction": system_instruction,
        "rag_context_available": labels.get("rag_context_available", "unknown"),
        "primary_category": labels["primary_category"],
        "secondary_tags": dict(labels.get("secondary_tags", {})),
        "cohort": labels["cohort"],
        "selection": dict(selection),
        "reference_answer": None,
        "reference_model": None,
        "reference_settings": None,
        "review": {
            "status": "not_reviewed",
            "reviewer": None,
            "factual_correctness": None,
            "persian_quality": None,
            "instruction_compliance": None,
            "rag_grounding": None,
            "uncertainty_handling": None,
            "notes": None,
        },
    }


def manifest_errors(
    entry: Mapping[str, Any], session_order: Sequence[str]
) -> list[str]:
    """Leakage check against the session's full message order; empty means clean."""
    target = entry["source"]["target_message_id"]
    ids = [m["message_id"] for m in entry["input_messages"]]
    errs: list[str] = []
    if not ids or ids[-1] != target:
        errs.append(f"{target}: target is not the last input message")
    if entry["input_messages"] and entry["input_messages"][-1]["role"] != "USER":
        errs.append(f"{target}: last input message is not USER")
    if ids != list(session_order[: session_order.index(target) + 1]):
        errs.append(f"{target}: input is not exactly the turns up to the target")
    if entry.get("reference_answer") is not None:
        errs.append(f"{target}: reference answer is already filled")
    return errs
