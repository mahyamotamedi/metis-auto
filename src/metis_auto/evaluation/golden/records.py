"""Build a record's ordered input components and its reference (pure).

Components hold references and hashes, never text. Availability stages say when each
piece could have been known. The reference answer is not a component: it goes to a
separate table, outside every routing-input view (ADR-0028).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

REQUEST_ARRIVAL = "request_arrival"
CONFIG_SNAPSHOT = "configuration_snapshot"
RETRIEVAL_UNKNOWN = "retrieval_order_unknown"
UNKNOWN = "unknown"
NOT_APPLICABLE = "not_applicable"


def order_key(msg: Mapping[str, Any]) -> tuple:
    """(timestamp, source_ordinal), null timestamps after every real one."""
    ts = msg.get("timestamp")
    return (ts is None, ts if ts is not None else 0, msg["source_ordinal"])


def earlier_messages(
    session: Sequence[Mapping[str, Any]], target_id: str
) -> list[Mapping[str, Any]]:
    """USER/AI messages before the target. Null timestamps are never earlier."""
    target = next(m for m in session if m["message_id"] == target_id)
    key = order_key(target)
    return sorted(
        (
            m
            for m in session
            if m["type"] in ("USER", "AI")
            and m["message_id"] != target_id
            and m.get("timestamp") is not None
            and order_key(m) < key
        ),
        key=order_key,
    )


def build_components(
    *,
    target: Mapping[str, Any],
    session: Sequence[Mapping[str, Any]],
    bot: Mapping[str, Any],
    answer_chunks: Sequence[Mapping[str, Any]],
    earlier_chunks: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """Ordered components: bot configuration, history, target, then chunks."""
    out: list[dict[str, Any]] = []

    def add(
        kind, stage, source_kind, *, role=None, pre=True, post=True, sent=UNKNOWN, **kw
    ):
        out.append(
            {
                "position": len(out),
                "kind": kind,
                "role": role,
                "source_kind": source_kind,
                "source_message_id": kw.get("message_id"),
                "source_bot_id": kw.get("bot_id"),
                "source_chunk_file_id": kw.get("chunk_file"),
                "source_chunk_row": kw.get("chunk_row"),
                "availability_stage": stage,
                "included_pre_retrieval": pre,
                "included_post_retrieval": post,
                "transmitted_to_provider": sent,
                "content_sha256": kw.get("sha"),
                "metadata": kw.get("metadata"),
            }
        )

    if bot.get("instructions_sha256"):
        add(
            "bot_instruction",
            CONFIG_SNAPSHOT,
            "bot_instruction",
            role="system",
            bot_id=bot["bot_id"],
            sha=bot["instructions_sha256"],
            metadata={"may_postdate_request": True},
        )
    # Model and provider labels are reference data, not routing input.
    add(
        "bot_configuration",
        CONFIG_SNAPSHOT,
        "metadata",
        metadata={
            "may_postdate_request": True,
            "corpus_ids": bot.get("corpus_ids"),
            "rag_top_k": bot.get("rag_top_k"),
            "rag_reranking": bot.get("rag_reranking"),
            "memory_enabled": bot.get("memory_enabled"),
            "summarizer_mode": bot.get("summarizer_mode"),
            "config_unknown": bot.get("config_unknown"),
        },
    )
    history = earlier_messages(session, target["message_id"])
    for msg in history:
        add(
            "earlier_message",
            REQUEST_ARRIVAL,
            "message",
            role=msg["type"],
            message_id=msg["message_id"],
            sha=msg.get("content_sha256"),
        )
    if history and history[-1].get("input_state") == "ok":
        add(
            "input_widget_definition",
            REQUEST_ARRIVAL,
            "metadata",
            metadata={"from_message_id": history[-1]["message_id"]},
        )
    if target.get("attachment_types"):
        add(
            "attachment_metadata",
            REQUEST_ARRIVAL,
            "metadata",
            metadata={
                "types": list(target["attachment_types"]),
                "count": len(target["attachment_types"]),
            },
        )
    add(
        "target_user_message",
        REQUEST_ARRIVAL,
        "message",
        role="USER",
        message_id=target["message_id"],
        sent="yes",
        sha=target.get("content_sha256"),
    )
    for chunk in answer_chunks:
        add(
            "target_rag_chunk",
            RETRIEVAL_UNKNOWN,
            "rag_chunk",
            pre=False,
            chunk_file=chunk["file_id"],
            chunk_row=chunk["row"],
            sha=chunk.get("content_sha256"),
        )
    for msg in history:
        for chunk in earlier_chunks.get(msg["message_id"], ()):
            # Stored but in neither profile: whether chunks are resent is unknown.
            add(
                "earlier_rag_chunk",
                RETRIEVAL_UNKNOWN,
                "rag_chunk",
                pre=False,
                post=False,
                chunk_file=chunk["file_id"],
                chunk_row=chunk["row"],
                sha=chunk.get("content_sha256"),
                metadata={"from_message_id": msg["message_id"]},
            )
    return out


def leakage_errors(
    components: Sequence[Mapping[str, Any]],
    *,
    target_id: str,
    answer_id: str,
    session: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Empty means clean. Checks message components against the true session order."""
    errors = []
    by_id = {m["message_id"]: m for m in session}
    target_key = order_key(by_id[target_id])
    ids = [c["source_message_id"] for c in components if c["source_kind"] == "message"]
    if not ids or ids[-1] != target_id:
        errors.append("target is not the last message component")
    if answer_id in ids:
        errors.append("the reference answer is a component")
    if len(ids) != len(set(ids)):
        errors.append("a message appears twice")
    for mid in ids:
        if mid != target_id:
            msg = by_id.get(mid)
            if msg is None:
                errors.append("a component message is outside the session")
            elif order_key(msg) >= target_key:
                errors.append("a component message is not before the target")
    for c in components:
        if c["availability_stage"] == "post_generation":
            errors.append("a post-generation item is a component")
        if c["included_pre_retrieval"] and c["availability_stage"] == RETRIEVAL_UNKNOWN:
            errors.append("a retrieved chunk is in the pre-retrieval profile")
    return errors


def billing_summary(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Sums over logged billing items; a missing value stays missing, never zero."""

    def total(key: str) -> float | None:
        values = [i[key] for i in items if i.get(key) is not None]
        return sum(values) if values else None

    return {
        "items": len(items),
        "input_tokens": total("input_tokens"),
        "cached_input_tokens": total("cached_input_tokens"),
        "output_tokens": total("output_tokens"),
        "total_cost": total("total_cost"),
    }
