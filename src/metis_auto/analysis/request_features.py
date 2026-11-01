"""One session's messages → one feature row per USER message (pure; no I/O).

Features are deterministic and heuristic. Rule labels are proposals for human review,
never ground truth (ADR-0028). Nothing returned holds message text; family IDs are
local grouping hashes that stay in the database and are never exported.

Traces: FR-REQ-03/04, FR-DATA-07/08, ADR-0006, ADR-0025, ADR-0028.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from metis_auto.analysis import prompt_labels as pl
from metis_auto.analysis import session_config as sc
from metis_auto.analysis.pairing import CONVERSATIONAL, pair_ordered
from metis_auto.analysis.text_features import language_label, script_counts
from metis_auto.domain.caching.normalise import normalise

FOLD = "persian_fold_v1"
BOT_CLASS = {
    sc.BOTH: "instruction_rag",
    sc.INSTRUCTION_ONLY: "instruction_only",
    sc.RAG_ONLY: "rag_only",
    sc.DIRECT: "blank_no_config",
    sc.UNKNOWN: "workflow_unknown_config",
}


@dataclass(frozen=True)
class BotContext:
    bot_id: str
    instruction_evidence: str
    rag_config: str
    instruction_chars: int


class Vocabulary:
    """Compiled word lists from ``[rules]`` of the sampling config."""

    def __init__(self, rules: Mapping[str, Any]):
        self.rules = rules
        self.greetings = {normalise(w, FOLD).casefold() for w in rules["greetings"]}
        self.patterns = {
            k: self._compile(v)
            for k, v in rules.items()
            if isinstance(v, list) and k != "greetings"
        }

    @staticmethod
    def _compile(words: Sequence[str]) -> re.Pattern[str]:
        body = "|".join(re.escape(normalise(w, FOLD)) for w in words)
        return re.compile(rf"(?<![^\W_])(?:{body})(?![^\W_])", re.I)

    def hit(self, name: str, folded: str) -> bool:
        return bool(self.patterns[name].search(folded))

    def is_greeting(self, folded: str) -> bool:
        stripped = re.sub(r"[^\w\s]", " ", folded).strip()
        stripped = re.sub(r"\s+", " ", stripped).casefold()
        return (
            len(stripped) <= self.rules["greeting_max_chars"]
            and stripped in self.greetings
        )


def language_group(text: str, label: str, groups: Mapping[str, str]) -> str:
    """Quota group; a label too short to classify follows its dominant script."""
    if label != "short_uncertain":
        return groups[label]
    c = script_counts(text)
    if (
        c["n_arabic_script"] > c["n_latin"]
        and c["n_arabic_script"] >= c["n_other_alpha"]
    ):
        return groups["short_uncertain_arabic"]
    if c["n_latin"] > c["n_arabic_script"] and c["n_latin"] >= c["n_other_alpha"]:
        return groups["short_uncertain_latin"]
    return groups["short_uncertain_other"]


def primary_intent(
    category: str, history_signal: str, intent_map: Mapping[str, str]
) -> str:
    if category == pl.UNKNOWN:
        return (
            "ambiguous_context_dependent"
            if history_signal == "likely_dependent"
            else "other_unclassified"
        )
    return intent_map[category]


def complexity_proxy(
    *,
    intent: str,
    reasoning: str,
    chars: int,
    history_chars: int,
    complex_chars: int,
    average_chars: int,
    complex_history: int,
) -> str:
    """A selection proxy to oversample likely hard requests; never a label."""
    if (
        (reasoning == "high" and intent in ("coding", "math_reasoning"))
        or chars >= complex_chars
        or history_chars >= complex_history
    ):
        return "complex"
    if reasoning == "high" or chars >= average_chars:
        return "average"
    return "simple"


def family_ids(bot_id: str, text: str) -> tuple[str | None, str | None]:
    """(exact family under the fold, order-insensitive token family); local only."""
    folded = normalise(text, FOLD)
    if not folded.strip():
        return None, None
    exact = hashlib.blake2b(f"{bot_id}|{folded}".encode(), digest_size=16).hexdigest()
    tokens = " ".join(sorted(set(folded.casefold().split())))
    near = hashlib.blake2b(f"{bot_id}|{tokens}".encode(), digest_size=16).hexdigest()
    return exact, near


def bigrams(text: str) -> frozenset[tuple[str, str]]:
    words = normalise(text, FOLD).casefold().split()
    return frozenset(zip(words, words[1:], strict=False))


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def session_class(
    bot: BotContext, messages: Sequence[Mapping[str, Any]]
) -> sc.SessionClass:
    ai = [m for m in messages if m["type"] == "AI"]
    return sc.classify_session(
        bot.instruction_evidence,
        bot.rag_config,
        sum(1 for m in ai if m.get("rag_n_chunks", 0) > 0),
        sum(
            1
            for m in ai
            if m.get("rag_n_queries", 0) > 0 and m.get("rag_n_chunks", 0) == 0
        ),
        len(ai),
    )


def session_requests(
    messages: Sequence[Mapping[str, Any]],
    *,
    bot: BotContext,
    cohort: str,
    vocab: Vocabulary,
    groups: Mapping[str, str],
    intent_map: Mapping[str, str],
    thresholds: Mapping[str, int],
    feature_version: str,
) -> list[dict[str, Any]]:
    """Feature rows, oldest first. ``messages`` are in (timestamp, source_ordinal)
    order with null timestamps last, and hold ``message_id, type, content,
    timestamp_is_null, finish_reason, attachment_types, input_state, rag_n_queries,
    rag_n_chunks, rag_chunk_chars``.
    """
    conv = [m for m in messages if m["type"] in CONVERSATIONAL]
    pairs = pair_ordered([m["type"] for m in conv], [m["message_id"] for m in conv])
    answer_of = {p.user_message_id: p for p in pairs if p.user_message_id}
    by_id = {m["message_id"]: m for m in conv}
    cls = session_class(bot, messages)
    bot_class = BOT_CLASS[cls.group]

    rows: list[dict[str, Any]] = []
    turn, history_chars, n_prior = 0, 0, 0
    previous: Mapping[str, Any] | None = None
    for msg in conv:
        if msg["type"] == "USER":
            turn += 1
            rows.append(
                _row(
                    msg,
                    answer_of.get(msg["message_id"]),
                    by_id,
                    turn=turn,
                    n_prior=n_prior,
                    history_chars=history_chars,
                    previous=previous,
                    bot=bot,
                    bot_class=bot_class,
                    cohort=cohort,
                    vocab=vocab,
                    groups=groups,
                    intent_map=intent_map,
                    thresholds=thresholds,
                    feature_version=feature_version,
                )
            )
        n_prior += 1
        history_chars += len(msg.get("content") or "")
        previous = msg
    return rows


def _row(
    msg,
    pair,
    by_id,
    *,
    turn,
    n_prior,
    history_chars,
    previous,
    bot,
    bot_class,
    cohort,
    vocab,
    groups,
    intent_map,
    thresholds,
    feature_version,
) -> dict[str, Any]:
    text = msg.get("content") or ""
    answer = by_id.get(pair.ai_message_id) if pair else None
    flag = pair.pair_flag if pair else "unanswered"
    label = language_label(text)
    folded = normalise(text, FOLD)
    category, _ = pl.primary_category(text)
    history_signal = pl.history_dependence(text, turn - 1)
    intent = primary_intent(category, history_signal, intent_map)
    reasoning = pl.reasoning_demand(text, category)
    greeting = vocab.is_greeting(folded)
    if greeting:
        intent = "conversational_smalltalk"
    att_types = list(msg.get("attachment_types") or [])
    after_widget = bool(previous and previous.get("input_state") == "ok")
    rag_chunks = (answer or {}).get("rag_n_chunks", 0)
    rag_queries = (answer or {}).get("rag_n_queries", 0)
    strict = pl.has_format_constraint(text)
    structured = vocab.hit("structured_output", folded)
    custom_instruction = bot.instruction_evidence == "custom"
    tags = {
        "pure_greeting": greeting,
        "time_sensitive": vocab.hit("time_sensitive", folded),
        "current_info_dependent": vocab.hit("current_info", folded),
        "strict_format": strict,
        "structured_output": structured,
        "format_or_structured": strict or structured,
        "attachment_dependent": bool(att_types),
        "instruction_dependent": custom_instruction
        and intent in ("bot_service_support", "ambiguous_context_dependent"),
        "rag_dependent": rag_chunks > 0,
        "history_recent": history_signal == "likely_dependent",
        "history_distant": history_signal == "likely_dependent"
        and turn >= thresholds["distant_history_min_turn"],
        "after_widget": after_widget,
        "advanced_reasoning_proxy": reasoning == "high",
    }
    tags["multi_context"] = (
        sum(
            tags[k]
            for k in ("instruction_dependent", "rag_dependent", "history_recent")
        )
        >= 2
    )
    domains = [
        d
        for d in ("medical", "legal", "finance", "engineering", "science", "academic")
        if vocab.hit(f"domain_{d}", folded)
    ]
    tags["domain_subtypes"] = domains
    tags["domain_specialized"] = bool(domains)
    exact, near = family_ids(bot.bot_id, text)
    reason = exclusion_reason(msg, answer, flag, text)
    return {
        "request_id": msg["message_id"],
        "session_id": msg["session_id"],
        "bot_id": bot.bot_id,
        "owner_cohort": cohort,
        "turn_index": turn,
        "answer_message_id": answer["message_id"] if answer else None,
        "pair_flag": flag,
        "eligible": reason is None,
        "exclusion_reason": reason,
        "language_label": label,
        "language_group": language_group(text, label, groups),
        "language_method": "analysis.text_features.language_label",
        "target_chars": len(text),
        "target_words": len(text.split()),
        "n_prior_messages": n_prior,
        "history_chars": history_chars,
        "instruction_chars": bot.instruction_chars,
        "rag_chunk_chars": (answer or {}).get("rag_chunk_chars", 0),
        "bot_class": bot_class,
        "instruction_evidence": bot.instruction_evidence,
        "rag_config": bot.rag_config,
        "config_unknown": bot_class == "workflow_unknown_config",
        "attachment_count": len(att_types),
        "attachment_types": att_types,
        "after_widget": after_widget,
        "answer_finish_reason": answer.get("finish_reason") if answer else None,
        "rag_observed_on_answer": rag_chunks + rag_queries > 0,
        "rule_intent": intent,
        "rule_tags": tags,
        "complexity_proxy": complexity_proxy(
            intent=intent,
            reasoning=reasoning,
            chars=len(text),
            history_chars=history_chars,
            complex_chars=thresholds["complex_chars"],
            average_chars=thresholds["average_chars"],
            complex_history=thresholds["complex_history"],
        ),
        "exact_family_id": exact,
        "near_family_id": near,
        "family_size": None,
        "timestamp_is_null": bool(msg.get("timestamp_is_null")),
        "feature_version": feature_version,
    }


def exclusion_reason(msg, answer, flag, text) -> str | None:
    """First reason a USER message cannot be a record; ``None`` means eligible."""
    if not text.strip():
        return "blank_target"
    if msg.get("timestamp_is_null"):
        return "null_target_timestamp"
    if flag != "clean":
        return f"pair_{flag}"
    if not (answer.get("content") or "").strip():
        return "blank_answer"
    if answer.get("timestamp_is_null"):
        return "null_answer_timestamp"
    if answer.get("finish_reason") != "STOP":
        return "answer_not_stop"
    return None
