"""Inferred session classes and strict configuration fingerprints (pure).

A session's class is an **inference** from bot configuration and observed
retrieval, not proof of product usage. Missing metadata is never read as absent:

- instruction evidence: ``custom``, ``absent`` (blank), ``unknown`` (null or
  malformed) or ``platform_default`` (a data-identified placeholder that says
  nothing about the real configuration).
- RAG evidence: positive if a corpus is configured or retrieval was observed on
  any turn; ``absent`` only if the corpus list is explicitly empty and nothing
  was observed; otherwise ``unknown``.

Fingerprints are strict: no trimming, case folding or character normalisation.
A fingerprint identifies a configuration, not a chatbot. Model identity is never
part of the key.

Traces: FR-DATA-07/08, ADR-0007, ADR-0008, ADR-0015 (analysis-time hashes only).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

DIRECT = "a_direct_llm_inferred"
INSTRUCTION_ONLY = "b_instruction_only"
RAG_ONLY = "c_rag_only"
BOTH = "d_instruction_and_rag"
UNKNOWN = "e_unknown_or_ambiguous"
CHATBOT_GROUPS = (INSTRUCTION_ONLY, RAG_ONLY, BOTH)


def _missing(value: Any) -> bool:
    return value is None or (not isinstance(value, str) and value != value)


def strict_hash(text: str) -> str:
    """SHA-256 of the exact text, with no normalisation of any kind."""
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def text_state(value: Any) -> str:
    """``null``, ``blank`` (empty or whitespace only) or ``text``."""
    if _missing(value):
        return "null"
    return "text" if str(value).strip() else "blank"


def json_field_state(value: Any) -> tuple[str, Any]:
    """Parse a possibly serialised JSON field.

    Returns (state, parsed): ``null``, ``empty`` (blank string, ``[]``, ``{}`` or
    JSON ``null``), ``nonempty`` or ``malformed``. Lists and dicts are accepted
    directly as well as serialised.
    """
    if _missing(value):
        return "null", None
    parsed = value
    if isinstance(value, str):
        if not value.strip():
            return "empty", None
        try:
            parsed = json.loads(value)
        except ValueError:
            return "malformed", None
    if parsed is None or parsed == [] or parsed == {} or parsed == "":
        return "empty", None
    return "nonempty", parsed


def canonical_json(value: Any) -> str:
    """Deterministic serialisation: sorted object keys, array order preserved."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def rag_fingerprint(corpus_ids: Any) -> str | None:
    """Hash of the configured knowledge-base reference (the corpus ID list).

    ``None`` for null, empty or malformed lists, so absent and unknown never
    collide with a real configuration. List order is preserved: the export does
    not say whether it is meaningful.
    """
    state, parsed = json_field_state(corpus_ids)
    return strict_hash(canonical_json(parsed)) if state == "nonempty" else None


def platform_default_hashes(
    rows: Iterable[tuple[Any, str, str]], default_provider: str, min_owners: int
) -> set[str]:
    """Instruction hashes identified as platform placeholders from the data.

    ``rows`` are (instructions, owner, provider). A text qualifies only if every
    bot using it has ``default_provider`` and at least ``min_owners`` different
    owners use it. No list of default phrases is assumed.
    """
    owners: dict[str, set[str]] = {}
    providers: dict[str, set[str]] = {}
    for text, owner, provider in rows:
        if text_state(text) != "text":
            continue
        h = strict_hash(text)
        owners.setdefault(h, set()).add(owner)
        providers.setdefault(h, set()).add(provider)
    return {
        h
        for h, o in owners.items()
        if len(o) >= min_owners and providers[h] == {default_provider}
    }


def instruction_evidence(text: Any, default_hashes: set[str]) -> str:
    state = text_state(text)
    if state == "null":
        return "unknown"
    if state == "blank":
        return "absent"
    return "platform_default" if strict_hash(text) in default_hashes else "custom"


def rag_config_evidence(corpus_ids: Any) -> str:
    """``configured``, ``not_configured`` or ``unknown`` (null or malformed)."""
    state, _ = json_field_state(corpus_ids)
    return {"nonempty": "configured", "empty": "not_configured"}.get(state, "unknown")


@dataclass(frozen=True)
class SessionClass:
    group: str
    subtype: str
    rag_positive: bool
    mixed_rag: bool
    """RAG observed on some AI turns and not on others."""
    config_observed_disagree: bool
    """Retrieval observed without a configured corpus."""


def classify_session(
    instruction: str,
    rag_config: str,
    turns_with_chunks: int,
    turns_with_query_only: int,
    ai_turns: int,
) -> SessionClass:
    """Mutually exclusive class; any verified positive evidence on any turn counts.

    A query that returned no chunks is positive (retrieval ran). An AI turn without
    retrieval is never evidence that RAG is absent.
    """
    observed = turns_with_chunks + turns_with_query_only > 0
    rag_pos = observed or rag_config == "configured"
    rag_known_absent = not rag_pos and rag_config == "not_configured"
    if instruction == "custom":
        if rag_pos:
            group, sub = BOTH, "custom_and_rag"
        elif rag_known_absent:
            group, sub = INSTRUCTION_ONLY, "custom_no_rag"
        else:
            group, sub = UNKNOWN, "custom_rag_unknown"
    elif instruction == "absent":
        if rag_pos:
            group, sub = RAG_ONLY, "blank_and_rag"
        elif rag_known_absent:
            group, sub = DIRECT, "blank_no_rag"
        else:
            group, sub = UNKNOWN, "blank_rag_unknown"
    else:
        prefix = instruction
        group = UNKNOWN
        sub = f"{prefix}_rag_positive" if rag_pos else f"{prefix}_no_rag_evidence"
    return SessionClass(
        group=group,
        subtype=sub,
        rag_positive=rag_pos,
        mixed_rag=observed and turns_with_chunks + turns_with_query_only < ai_turns,
        config_observed_disagree=observed and rag_config != "configured",
    )


def extra_entities(group_sizes: Iterable[int]) -> int:
    """Entities beyond one per group, which differs from the total in repeats."""
    return sum(n - 1 for n in group_sizes if n > 1)
