"""Strata of slice candidates (pure, content-free outputs).

Pass 1 knows structure only (position, lengths, attachments, billing, RAG on
the answer, cohort, the bot's instruction evidence); pass 2 adds the golden
feature row from ``analysis.request_features.session_requests`` (language
group, rule intent, greeting, bot class, families). Values are codes, never
text. Traces: FR-DATA-06, ADR-0028 (shared definitions),
ADR-XXXX (system-one-decision-router).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .config import SliceConfig
from .select import Candidate


@dataclass(frozen=True)
class PassOneTarget:
    """One eligible USER target from the structural index (no text)."""

    message_id: str
    session_id: str
    bot_id: str
    turn_index: int
    target_chars: int
    attachment_count: int
    answer_message_id: str
    answer_input_tokens: int | None
    rag_on_answer: bool
    cohort: str
    instructions: str
    """``present``, ``absent`` or ``unknown`` (bot-level evidence)."""


def position(turn_index: int) -> str:
    return "first" if turn_index == 1 else "follow_up"


def instructions_class(evidence: str) -> str:
    return {"custom": "present", "absent": "absent"}.get(evidence, "unknown")


def pass_one_flags(t: PassOneTarget, cfg: SliceConfig) -> frozenset[str]:
    th = cfg.thresholds
    flags = set()
    if t.turn_index > 1 and t.target_chars <= th.short_followup_max_chars:
        flags.add("short_followup")
    if t.target_chars >= th.long_message_min_chars:
        flags.add("long_message")
    if t.attachment_count > 0:
        flags.add("attachments")
    if (t.answer_input_tokens or 0) > th.high_input_min_tokens:
        flags.add("high_input")
    if t.rag_on_answer:
        flags.add("rag_on_answer")
    return frozenset(flags)


_SHARED: dict[object, object] = {}


def _shared(value: object) -> object:
    """One object per distinct strata dict or flag set: about 300k pass-1
    candidates share a few hundred of them (memory, not behaviour)."""
    key = tuple(sorted(value.items())) if isinstance(value, dict) else value
    return _SHARED.setdefault(key, value)


def pass_one_candidate(t: PassOneTarget, cfg: SliceConfig) -> Candidate:
    strata = {
        "position": position(t.turn_index),
        "cohort": t.cohort,
        "instructions": t.instructions,
    }
    return Candidate(
        key=t.message_id,
        session_id=t.session_id,
        bot_id=t.bot_id,
        strata=_shared(strata),  # type: ignore[arg-type]
        flags=_shared(pass_one_flags(t, cfg)),  # type: ignore[arg-type]
    )


def final_flags(
    row: Mapping[str, Any], answer_input_tokens: int | None, cfg: SliceConfig
) -> frozenset[str]:
    th = cfg.thresholds
    tags = row.get("rule_tags") or {}
    chars = int(row["target_chars"])
    flags = set()
    if row["turn_index"] > 1 and chars <= th.short_followup_max_chars:
        flags.add("short_followup")
    if row["language_label"] == "short_uncertain":
        flags.add("short_uncertain")
    if tags.get("pure_greeting"):
        flags.add("greeting")
    if row["rule_intent"] == "coding":
        flags.add("coding")
    if chars >= th.long_message_min_chars:
        flags.add("long_message")
    if row["attachment_count"]:
        flags.add("attachments")
    if (answer_input_tokens or 0) > th.high_input_min_tokens:
        flags.add("high_input")
    if row["rag_observed_on_answer"]:
        flags.add("rag_on_answer")
    return frozenset(flags)


def final_candidate(
    row: Mapping[str, Any],
    answer_input_tokens: int | None,
    cfg: SliceConfig,
    *,
    duplicate_group: str | None = None,
) -> Candidate:
    """``duplicate_group``: the cross-bot group of ``evaluation.grouping`` (same
    text after the Persian fold, whatever the bot); the golden families are
    per bot."""
    families = tuple(
        f"{kind}:{row[col]}"
        for kind, col in (("exact", "exact_family_id"), ("near", "near_family_id"))
        if row.get(col)
    ) + ((f"dup:{duplicate_group}",) if duplicate_group else ())
    return Candidate(
        key=row["request_id"],
        session_id=row["session_id"],
        bot_id=row["bot_id"],
        strata={
            "language_group": row["language_group"],
            "position": position(row["turn_index"]),
            "bot_class": row["bot_class"],
            "cohort": row["owner_cohort"],
        },
        flags=final_flags(row, answer_input_tokens, cfg),
        families=families,
    )
