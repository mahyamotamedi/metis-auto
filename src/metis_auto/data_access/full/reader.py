"""Column-projected, one-file-at-a-time reads of the full dataset
(ADR-XXXX (system-one-decision-router)).

Every Parquet file of the dataset is a single row group (R0 findings §3), so
a row filter cannot skip I/O: each function reads **one file at a time**,
**only the columns it needs**, filters in Arrow, and drops what it does not
keep before the next file. Text lengths and attachment counts are computed in
Arrow (``utf8_length``, ``count_substring``); message text is turned into
Python strings only for rows that passed a filter.

Never prints, logs or returns text except through ``session_messages`` and
``chunks_for`` (the targeted reads), whose callers keep it in memory and in
git-ignored files only (licence: educational use, no redistribution).
Called by: wiring.router_slice. Traces: FR-DATA-02/04/06, QA-PRIV.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

SHARD_FACTOR = 1_000_000_000
"""Source ordinal = shard index × this + row index (the PostgreSQL loader's rule)."""

MESSAGE_GLOB = "chat_message-*.parquet"
CHUNK_GLOB = "chat_message_rag_chunks-*.parquet"

Progress = Callable[[str], None]


def _quiet(_: str) -> None:
    return None


def message_shards(root: Path) -> list[Path]:
    return sorted((root / "data").glob(MESSAGE_GLOB))


def chunk_shards(root: Path) -> list[Path]:
    return sorted((root / "data" / "derived").glob(CHUNK_GLOB))


def _read(path: Path, columns: list[str]) -> pa.Table:
    return pq.read_table(path, columns=columns, use_threads=True)


# --- Pass 1: light, structural ----------------------------------------------------


def light_messages(
    root: Path, *, with_lengths: bool, progress: Progress = _quiet
) -> pa.Table:
    """Every message without its text: ``message_id, session_id, type,
    timestamp, finish_reason, ordinal`` and, when ``with_lengths``,
    ``content_chars`` (null when the text is null) and ``attachment_count``.

    ``with_lengths`` decodes the ``content`` column of each file only to
    measure it (``plan`` passes False and reads no text at all).
    """
    parts: list[pa.Table] = []
    shards = message_shards(root)
    for index, path in enumerate(shards):
        cols = ["message_id", "session_id", "type", "timestamp", "finish_reason"]
        table = _read(path, cols)
        ordinal = pa.array(
            [index * SHARD_FACTOR + i for i in range(table.num_rows)], pa.int64()
        )
        table = table.append_column("ordinal", ordinal)
        if with_lengths:
            content = _read(path, ["content"]).column("content")
            table = table.append_column(
                "content_chars", pc.utf8_length(content).cast(pa.int64())
            )
            del content
            attachments = _read(path, ["attachments"]).column("attachments")
            count = pc.count_substring(attachments, '"contentType"')
            table = table.append_column(
                "attachment_count", pc.fill_null(count, 0).cast(pa.int32())
            )
            del attachments
        parts.append(table)
        progress(f"pass 1: message file {index + 1}/{len(shards)}")
    return pa.concat_tables(parts)


def sessions(root: Path) -> pa.Table:
    """``session_id, user_id, bot_id`` (the headline is never read)."""
    return _read(
        root / "data" / "chat_session.parquet", ["session_id", "user_id", "bot_id"]
    )


def bots(root: Path, *, with_instructions: bool) -> list[dict[str, Any]]:
    """Bot configuration rows. ``instructions`` (content) only when asked; the
    caller derives evidence classes from it and keeps the text in memory."""
    cols = ["bot_id", "user_id", "provider_name", "provider_model", "corpus_ids"]
    if with_instructions:
        cols.append("instructions")
    return _read(root / "data" / "chat_bot.parquet", cols).to_pylist()


def users_count(root: Path) -> int:
    return pq.read_metadata(root / "data" / "users.parquet").num_rows


def rag_query_counts(root: Path) -> dict[str, int]:
    """RAG queries per message (``derived/chat_message_rag``), no query text."""
    table = _read(
        root / "data" / "derived" / "chat_message_rag.parquet", ["message_id"]
    )
    grouped = table.group_by("message_id").aggregate([("message_id", "count")])
    return dict(
        zip(
            grouped.column("message_id").to_pylist(),
            grouped.column("message_id_count").to_pylist(),
            strict=True,
        )
    )


def chunk_counts(root: Path, progress: Progress = _quiet) -> dict[str, int]:
    """Retrieved chunks per message, from the chunk files' ``message_id`` only."""
    counts: dict[str, int] = {}
    shards = chunk_shards(root)
    for index, path in enumerate(shards):
        grouped = (
            _read(path, ["message_id"])
            .group_by("message_id")
            .aggregate([("message_id", "count")])
        )
        for mid, n in zip(
            grouped.column("message_id").to_pylist(),
            grouped.column("message_id_count").to_pylist(),
            strict=True,
        ):
            counts[mid] = counts.get(mid, 0) + n
        progress(f"pass 1: chunk file {index + 1}/{len(shards)}")
    return counts


BILLING_SUMS = {
    "inputTokens": "billing_input_tokens",
    "outputTokens": "billing_output_tokens",
    "cachedInputTokens": "billing_cached_input_tokens",
    "callCount": "billing_call_count",
    "totalCost": "billing_total_cost",
    "costBreakdown.per_call": "billing_per_call_cost",
}


def billing_sums(
    root: Path,
    *,
    only: Collection[str] | None = None,
    fields: Collection[str] = tuple(BILLING_SUMS),
) -> dict[str, dict[str, float | int | None]]:
    """Recorded billing per message, summed over its billing items, for the
    messages in ``only`` (all when None) and the source ``fields`` asked for.
    Recorded units (currency unstated, EDA caveats); never mixed with repriced
    figures."""
    cols = [c for c in BILLING_SUMS if c in fields]
    table = _read(
        root / "data" / "derived" / "chat_message_billing.parquet",
        ["message_id", *cols],
    )
    if only is not None:
        wanted = pa.array(sorted(only), pa.large_string())
        mask = pc.is_in(
            table.column("message_id").cast(pa.large_string()), value_set=wanted
        )
        table = table.filter(pc.fill_null(mask, False))
    grouped = table.group_by("message_id").aggregate([(c, "sum") for c in cols])
    del table
    ids = grouped.column("message_id").to_pylist()
    out: dict[str, dict[str, float | int | None]] = {mid: {} for mid in ids}
    for col in cols:
        values = grouped.column(f"{col}_sum").to_pylist()
        for mid, value in zip(ids, values, strict=True):
            out[mid][BILLING_SUMS[col]] = value
    return out


def billing_input_tokens(root: Path) -> dict[str, int]:
    """Recorded billing input tokens per message (pass 1: one int per answer)."""
    sums = billing_sums(root, fields=("inputTokens",))
    return {
        mid: int(v["billing_input_tokens"])
        for mid, v in sums.items()
        if v.get("billing_input_tokens") is not None
    }


# --- Pass 2: targeted ------------------------------------------------------------


def json_state(raw: str | None) -> str:
    """``null``, ``empty``, ``malformed`` or ``ok`` (the PostgreSQL loader's rule)."""
    if raw is None:
        return "null"
    if not raw.strip():
        return "empty"
    try:
        parsed = json.loads(raw)
    except ValueError:
        return "malformed"
    return "empty" if parsed in ([], {}, None, "") else "ok"


def attachment_types(raw: str | None) -> list[str]:
    """``contentType`` of each attachment; the payload is never kept."""
    if json_state(raw) != "ok":
        return []
    value = json.loads(raw)  # type: ignore[arg-type]
    if not isinstance(value, list):
        return []
    return [str(a.get("contentType")) for a in value if isinstance(a, dict)]


MESSAGE_COLUMNS = [
    "message_id",
    "session_id",
    "type",
    "timestamp",
    "content",
    "finish_reason",
    "attachments",
    "input",
]


def session_messages(
    root: Path,
    session_ids: Collection[str],
    *,
    progress: Progress = _quiet,
) -> list[dict[str, Any]]:
    """Every message of the given sessions, as dicts with ``content`` (text),
    ``timestamp_is_null``, ``attachment_types``, ``input_state`` and
    ``ordinal``; the raw ``attachments`` and ``input`` JSON is dropped."""
    wanted = pa.array(sorted(session_ids), pa.large_string())
    out: list[dict[str, Any]] = []
    shards = message_shards(root)
    for index, path in enumerate(shards):
        sids = _read(path, ["session_id"]).column("session_id")
        mask = pc.is_in(sids.cast(pa.large_string()), value_set=wanted)
        rows = pc.indices_nonzero(pc.fill_null(mask, False))
        del sids, mask
        if len(rows):
            table = _read(path, MESSAGE_COLUMNS).take(rows)
            for i, row in zip(rows.to_pylist(), table.to_pylist(), strict=True):
                row["ordinal"] = index * SHARD_FACTOR + i
                row["timestamp_is_null"] = row["timestamp"] is None
                row["attachment_types"] = attachment_types(row.pop("attachments"))
                row["input_state"] = json_state(row.pop("input"))
                out.append(row)
            del table
        progress(f"pass 2: message file {index + 1}/{len(shards)}")
    return out


@dataclass
class ChunkRead:
    stats: dict[str, dict[str, int]]
    """message_id → ``rag_n_chunks``, ``rag_chunk_chars`` (all requested messages)."""
    texts: dict[str, list[dict[str, Any]]]
    """message_id → chunks in file order (``chunk_id``, ``content``, ``corpusId``,
    ``relevancy``), only for ``keep_text_for``."""


def chunks_for(
    root: Path,
    message_ids: Collection[str],
    keep_text_for: Collection[str],
    *,
    progress: Progress = _quiet,
) -> ChunkRead:
    """Retrieved chunks of the given messages, in file order."""
    wanted = pa.array(sorted(message_ids), pa.large_string())
    keep = set(keep_text_for)
    read = ChunkRead(stats={}, texts={})
    shards = chunk_shards(root)
    for index, path in enumerate(shards):
        mids = _read(path, ["message_id"]).column("message_id")
        mask = pc.is_in(mids.cast(pa.large_string()), value_set=wanted)
        rows = pc.indices_nonzero(pc.fill_null(mask, False))
        del mids, mask
        if len(rows):
            table = _read(
                path, ["message_id", "chunk_id", "content", "corpusId", "relevancy"]
            ).take(rows)
            lengths = pc.fill_null(pc.utf8_length(table.column("content")), 0)
            for mid, n in zip(
                table.column("message_id").to_pylist(), lengths.to_pylist(), strict=True
            ):
                s = read.stats.setdefault(
                    mid, {"rag_n_chunks": 0, "rag_chunk_chars": 0}
                )
                s["rag_n_chunks"] += 1
                s["rag_chunk_chars"] += int(n)
            kept = [r for r in table.to_pylist() if r["message_id"] in keep]
            for r in kept:
                read.texts.setdefault(r["message_id"], []).append(r)
            del table, kept
        progress(f"pass 2: chunk file {index + 1}/{len(shards)}")
    return read
