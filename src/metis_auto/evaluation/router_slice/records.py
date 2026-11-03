"""Slice records: build them from a selected target, and map them onto the
``Request`` contract (pure; FR-DATA-06, ADR-0028 rules,
ADR-0047).

A record is one target USER message with what a router may see (message,
earlier turns, instructions, retrieved chunks, attachment modalities) and, on
the **reference side**, what it must never see (the logged answer, the bot's
model label, recorded billing). Records hold content: they live only in the
git-ignored ``data/derived/`` file. Instructions are a configuration snapshot
that may postdate the request; retrieved chunks are those of the answer, so
routing may use them only in the ``post_retrieval`` profile.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from metis_auto.contracts import (
    AttachmentRef,
    Component,
    Modality,
    Request,
    RetrievedContext,
    RetrievedItem,
    Role,
    Turn,
)
from metis_auto.domain.routing.decision import WIDGET_NOT_LOADED

RECORD_VERSION = "router-slice-record-2"
"""2: adds ``cohort_traffic_share`` and ``traffic_weight`` (owner, 2026-11-02)."""
RETRIEVAL_AVAILABILITY = "retrieval_order_unknown"
_IDENT = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")

Profile = Literal["pre_retrieval", "post_retrieval"]


def record_id(prefix: str, message_id: str) -> str:
    return f"{prefix}-{message_id}"


def opaque_ref(kind: str, value: str) -> str:
    """A local opaque reference (not exported): the raw ID never appears."""
    return f"{kind}-" + hashlib.blake2b(value.encode(), digest_size=8).hexdigest()


def instructions_state(text: str | None, evidence: str) -> str:
    """ADR-0028: blank is absent; null or the workflow placeholder is unknown."""
    if evidence == "platform_default" or text is None:
        return "unknown"
    return "present" if text.strip() else "absent"


def modality_of(content_type: str) -> Modality:
    kind = content_type.split("/", 1)[0].lower()
    if kind == "image":
        return Modality.IMAGE
    if kind == "audio":
        return Modality.AUDIO
    if kind in ("application", "text"):
        return Modality.DOCUMENT
    return Modality.OTHER


def build_record(
    *,
    prefix: str,
    split: str,
    row: Mapping[str, Any],
    flags: Sequence[str],
    history: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
    answer: Mapping[str, Any],
    bot: Mapping[str, Any],
    chunks: Sequence[Mapping[str, Any]],
    billing: Mapping[str, Any] | None,
    mapped_model_id: str | None,
    mapping_fidelity: str | None,
    history_max_turns: int,
    cohort_traffic_share: float | None = None,
    traffic_weight: float | None = None,
) -> dict[str, Any]:
    """One record row (flat; nested values as JSON text)."""
    turns = [
        {
            "role": "user" if m["type"] == "USER" else "assistant",
            "text": m["content"] or "",
        }
        for m in history
        if m["type"] in ("USER", "AI")
    ]
    kept = turns[-history_max_turns:] if history_max_turns else []
    previous_ai = next((m for m in reversed(history) if m["type"] == "AI"), None)
    evidence = row["instruction_evidence"]
    billing = billing or {}
    return {
        "record_version": RECORD_VERSION,
        "slice_record_id": record_id(prefix, row["request_id"]),
        "split": split,
        "message_id": row["request_id"],
        "session_id": row["session_id"],
        "bot_id": row["bot_id"],
        "answer_message_id": row["answer_message_id"],
        # strata (codes)
        "language_group": row["language_group"],
        "language_label": row["language_label"],
        "turn_index": int(row["turn_index"]),
        "bot_class": row["bot_class"],
        "cohort": row["owner_cohort"],
        "rule_intent": row["rule_intent"],
        "complexity_proxy": row["complexity_proxy"],
        "flags": json.dumps(sorted(flags)),
        "target_chars": int(row["target_chars"]),
        # traffic weight of the record's cohort (codes; see weights.py)
        "cohort_traffic_share": cohort_traffic_share,
        "traffic_weight": traffic_weight,
        # what routing may see (content)
        "message": target["content"],
        "history_json": json.dumps(kept, ensure_ascii=False),
        "history_turns_total": len(turns),
        "history_truncated": len(kept) < len(turns),
        "previous_ai_input_state": previous_ai["input_state"] if previous_ai else None,
        "instructions_state": instructions_state(bot.get("instructions"), evidence),
        "instructions": bot.get("instructions")
        if instructions_state(bot.get("instructions"), evidence) == "present"
        else None,
        "instruction_evidence": evidence,
        "configuration_snapshot": True,
        "retrieved_json": json.dumps(
            [
                {
                    "chunk_id": c.get("chunk_id"),
                    "text": c.get("content") or "",
                    "relevancy": c.get("relevancy"),
                }
                for c in chunks
                if (c.get("content") or "").strip()
            ],
            ensure_ascii=False,
        ),
        "retrieved_availability": RETRIEVAL_AVAILABILITY,
        "attachment_types_json": json.dumps(list(target.get("attachment_types") or [])),
        # reference side (never visible to routing)
        "answer_text": answer["content"],
        "answer_finish_reason": answer.get("finish_reason"),
        "provider_name": bot.get("provider_name"),
        "provider_model": bot.get("provider_model"),
        "mapped_model_id": mapped_model_id,
        "mapping_fidelity": mapping_fidelity,
        "billing_input_tokens": billing.get("billing_input_tokens"),
        "billing_output_tokens": billing.get("billing_output_tokens"),
        "billing_cached_input_tokens": billing.get("billing_cached_input_tokens"),
        "billing_call_count": billing.get("billing_call_count"),
        "billing_total_cost": billing.get("billing_total_cost"),
        "billing_per_call_cost": billing.get("billing_per_call_cost"),
    }


def to_request(record: Mapping[str, Any], *, profile: Profile) -> Request:
    """The record as a ``Request``. ``pre_retrieval``: retrieved context is
    unknown (routing happens before retrieval); ``post_retrieval``: the
    answer's chunks, in file order, are present."""
    kept = tuple(
        Turn(role=Role.USER if t["role"] == "user" else Role.ASSISTANT, text=t["text"])
        for t in json.loads(record["history_json"])
        if t["text"].strip()
    )
    history: Component[tuple[Turn, ...]]
    if kept:
        history = Component.present(kept)
    elif record["history_turns_total"] == 0:
        history = Component.absent()  # a first turn: nothing came before
    else:
        history = Component.unknown("history_not_kept")

    state = record["instructions_state"]
    instructions: Component[str] = (
        Component.present(record["instructions"])
        if state == "present"
        else Component.absent()
        if state == "absent"
        else Component.unknown("configuration_unknown")
    )

    chunks = json.loads(record["retrieved_json"])
    retrieved: Component[RetrievedContext]
    if profile == "pre_retrieval":
        retrieved = Component.unknown("not_yet_retrieved")
    elif chunks:
        retrieved = Component.present(
            RetrievedContext(
                items=tuple(
                    RetrievedItem(
                        text=c["text"],
                        document_ref=c["chunk_id"]
                        if isinstance(c["chunk_id"], str)
                        and _IDENT.match(c["chunk_id"])
                        else None,
                        score=c["relevancy"],
                    )
                    for c in chunks
                )
            )
        )
    else:
        retrieved = Component.absent()

    types = json.loads(record["attachment_types_json"])
    attachments: Component[tuple[AttachmentRef, ...]] = (
        Component.present(tuple(AttachmentRef(modality=modality_of(t)) for t in types))
        if types
        else Component.absent()
    )
    structured = (
        Component.unknown(WIDGET_NOT_LOADED)
        if record["previous_ai_input_state"] == "ok"
        else Component.absent()
    )
    return Request(
        message=record["message"],
        history=history,
        instructions=instructions,
        retrieved=retrieved,
        attachments=attachments,
        structured_input=structured,
        session_ref=opaque_ref("rs1s", record["session_id"]),
        caller_request_ref=record["slice_record_id"],
    )
