"""Rubric, rule proposals, label import checks and agreement (pure).

Rules propose. Complexity, ambiguity and dependency labels come only from human review.
``llm_assisted`` is a recognised method that is refused unless an explicit flag and a
recorded owner approval are given (ADR-0028). Nothing here calls a model.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

BOOL = ("yes", "no", "unsure")
SECONDARY = (
    "time_sensitive",
    "current_info_dependent",
    "domain_specialized",
    "strict_format",
    "structured_output",
    "attachment_dependent",
    "instruction_dependent",
    "rag_dependent",
    "history_recent",
    "history_distant",
    "multi_context",
    "advanced_reasoning_required",
    "cache_suitable",
    "cache_invalidation_risk",
)
RUBRIC: dict[str, tuple[str, ...]] = {
    "primary_intent": (
        "factual_qa",
        "bot_service_support",
        "conversational_smalltalk",
        "writing_creative",
        "translation",
        "coding",
        "advice_recommendation",
        "math_reasoning",
        "summarization_extraction_structured",
        "media_generation",
        "ambiguous_context_dependent",
        "other_unclassified",
    ),
    "complexity": ("simple", "average", "complex"),
    "answerable_without_clarification": BOOL,
    "domain_subtype": (
        "none",
        "science",
        "engineering",
        "medical",
        "legal",
        "finance",
        "academic",
    ),
    **{name: BOOL for name in SECONDARY},
}
RATIONALE_CODES = (
    "one_operation",
    "two_to_four_steps",
    "five_or_more_steps",
    "specialised_knowledge",
    "multi_constraint",
    "context_integration",
    "multi_part_code",
    "rule_match",
    "other",
)
HUMAN_REQUIRED = (
    "primary_intent",
    "complexity",
    "time_sensitive",
    "history_recent",
    "instruction_dependent",
    "cache_suitable",
)
RULE_TAG_DIMENSIONS = (
    "time_sensitive",
    "current_info_dependent",
    "domain_specialized",
    "strict_format",
    "structured_output",
    "attachment_dependent",
    "instruction_dependent",
    "rag_dependent",
    "history_recent",
    "history_distant",
    "multi_context",
)
METHODS = ("rule", "human", "llm_assisted")


@dataclass(frozen=True)
class LabelRow:
    record_id: str
    dimension: str
    value: str
    annotator_pseudonym: str
    method: str = "human"
    confidence: float | None = None
    rationale_code: str | None = None


def rule_annotations(
    record_id: str, request: Mapping[str, Any], rubric_version: str
) -> list[dict[str, Any]]:
    """Rule proposals (``review_status = proposed``). Never complexity."""
    tags = request["rule_tags"]
    rows = [("primary_intent", request["rule_intent"])]
    rows += [(d, "yes" if tags.get(d) else "no") for d in RULE_TAG_DIMENSIONS]
    return [
        {
            "record_id": record_id,
            "dimension": dim,
            "value": value,
            "method": "rule",
            "annotator_pseudonym": "rules-v1",
            "rubric_version": rubric_version,
            "confidence": None,
            "review_status": "proposed",
            "rationale_code": "rule_match",
        }
        for dim, value in rows
    ]


def label_errors(
    rows: Iterable[LabelRow],
    known_records: set[str],
    *,
    llm_approved: bool = False,
) -> list[str]:
    """Plain problems; empty means every row may be imported."""
    errors = []
    for i, row in enumerate(rows):
        where = f"row {i}"
        if row.record_id not in known_records:
            errors.append(f"{where}: unknown record id")
        if row.dimension not in RUBRIC:
            errors.append(f"{where}: unknown dimension {row.dimension}")
        elif row.value not in RUBRIC[row.dimension]:
            errors.append(f"{where}: value not in the rubric for {row.dimension}")
        if row.method not in METHODS:
            errors.append(f"{where}: unknown method {row.method}")
        if row.method == "llm_assisted" and not llm_approved:
            errors.append(f"{where}: llm_assisted needs recorded owner approval")
        if row.rationale_code and row.rationale_code not in RATIONALE_CODES:
            errors.append(f"{where}: rationale code not in the controlled list")
        if not row.annotator_pseudonym:
            errors.append(f"{where}: annotator pseudonym is empty")
    return errors


def percent_agreement(pairs: Sequence[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    return sum(a == b for a, b in pairs) / len(pairs)


def weighted_kappa(
    pairs: Sequence[tuple[str, str]], order: Sequence[str] = RUBRIC["complexity"]
) -> float | None:
    """Linear weighted Cohen's kappa; ``None`` when undefined."""
    if not pairs:
        return None
    pos = {v: i for i, v in enumerate(order)}
    span = max(len(order) - 1, 1)
    n = len(pairs)
    left, right = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    disagree = sum(abs(pos[a] - pos[b]) / span for a, b in pairs) / n
    expected = sum(
        left[a] * right[b] * abs(pos[a] - pos[b]) / span for a in order for b in order
    ) / (n * n)
    return None if expected == 0 else 1 - disagree / expected


def double_annotation_ids(
    record_strata: Mapping[str, str], share: float, rank: Mapping[str, str]
) -> list[str]:
    """A stratified share (at least the requested share of each stratum, rounded up)."""
    groups: dict[str, list[str]] = {}
    for record, stratum in record_strata.items():
        groups.setdefault(stratum, []).append(record)
    out: list[str] = []
    for stratum in sorted(groups):
        members = sorted(groups[stratum], key=lambda r: (rank[r], r))
        out += members[: max(1, -(-len(members) * int(share * 1000) // 1000))]
    return sorted(out)
