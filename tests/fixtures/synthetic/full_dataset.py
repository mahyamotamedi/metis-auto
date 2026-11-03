"""A SYNTHETIC miniature of the full dataset with the real Parquet schema.

Generated in the test (never copied from the data): the column names and
types come from ``config/evaluation/source_v1.toml``; every text carries the
``[SYNTHETIC]`` marker. Shapes the slice builder must handle: workflow bots,
the platform-default placeholder (one text on workflow bots of five owners),
blank instructions, consecutive USER messages, a non-STOP answer, a null
timestamp, attachments, RAG chunks and billing, a golden record, and
duplicate messages.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

MARKER = "[SYNTHETIC]"
REVISION = "0" * 40
PLACEHOLDER = f"{MARKER} <WORKFLOW INSTRUCTIONS>"
REPO = Path(__file__).resolve().parents[3]

TYPES = {
    "large_string": pa.large_string(),
    "timestamp[us]": pa.timestamp("us"),
    "bool": pa.bool_(),
    "int64": pa.int64(),
    "double": pa.float64(),
    "null": pa.null(),
}

PERSIAN = [
    "لطفا ساعت کاری فروشگاه را بگویید",
    "این متن را خلاصه کن",
    "چطور می توانم سفارش را لغو کنم",
    "یک ایمیل رسمی بنویس",
    "قیمت این محصول چقدر است",
]
ENGLISH = [
    "please explain how the refund works",
    "write a python function that sorts a list",
    "translate this sentence into french",
]


def _schema(spec: list[list[str]]) -> pa.Schema:
    return pa.schema([(name, TYPES[t]) for name, t in spec])


def _table(spec: list[list[str]], rows: list[dict[str, Any]]) -> pa.Table:
    schema = _schema(spec)
    return pa.Table.from_pylist(
        [{n: r.get(n) for n in schema.names} for r in rows], schema=schema
    )


def write_dataset(root: Path, *, sessions: int = 260, seed: int = 7) -> dict[str, Any]:
    """Write the miniature under ``root`` and return facts the tests check."""
    with (REPO / "config" / "evaluation" / "source_v1.toml").open("rb") as h:
        spec = tomllib.load(h)["tables"]
    data = root / "data"
    (data / "derived").mkdir(parents=True, exist_ok=True)
    meta = root / ".cache" / "huggingface" / "download" / "data"
    meta.mkdir(parents=True, exist_ok=True)

    owners = [f"owner-{i}" for i in range(12)]
    bots: list[dict[str, Any]] = []
    for i in range(40):
        owner = owners[i % len(owners)]
        if i < 5:  # five workflow bots of five owners share the placeholder
            bots.append(
                {
                    "bot_id": f"bot-{i:02d}",
                    "user_id": owner,
                    "provider_name": "workflow",
                    "provider_model": "default",
                    "instructions": PLACEHOLDER,
                    "corpus_ids": None,
                }
            )
        elif i < 8:
            bots.append(
                {
                    "bot_id": f"bot-{i:02d}",
                    "user_id": owner,
                    "provider_name": "openai",
                    "provider_model": "gpt-4o-mini",
                    "instructions": "   ",
                    "corpus_ids": "[]",
                }
            )
        else:
            bots.append(
                {
                    "bot_id": f"bot-{i:02d}",
                    "user_id": owner,
                    "provider_name": "openai",
                    "provider_model": "gpt-4o-mini" if i % 2 else "gemini-2.5-flash",
                    "instructions": f"{MARKER} You are support bot {i}.",
                    "corpus_ids": '["c1"]' if i % 3 == 0 else "[]",
                }
            )

    t0 = datetime(2026, 5, 1, 9, 0, 0)
    session_rows, messages, chunks, rag_queries, billing = [], [], [], [], []
    facts: dict[str, Any] = {
        "consecutive_user": set(),
        "not_stop": set(),
        "null_ts": set(),
        "workflow_targets": set(),
        "golden": None,
        "attachments": set(),
    }
    counter = 0

    def mid() -> str:
        nonlocal counter
        counter += 1
        return f"m-{counter:06d}"

    for s in range(sessions):
        sid = f"s-{s:05d}"
        bot = bots[(s * 7 + seed) % len(bots)]
        session_rows.append(
            {
                "session_id": sid,
                "user_id": bot["user_id"],
                "bot_id": bot["bot_id"],
                "created_at": t0,
                "last_update_date": t0,
                "dialogue_length": 4,
                "headline": f"{MARKER} headline",
            }
        )
        turns = 1 + (s % 3)
        ts = t0 + timedelta(minutes=s)
        for k in range(turns):
            lang = PERSIAN if (s + k) % 5 else ENGLISH
            text = f"{MARKER} {lang[(s + k) % len(lang)]} {s}-{k}"
            if s % 17 == 0 and k == 0:
                text = f"{MARKER} سلام"  # short, duplicated across sessions
            u = mid()
            row = {
                "message_id": u,
                "session_id": sid,
                "type": "USER",
                "timestamp": ts,
                "content": text,
                "finish_reason": None,
            }
            if s % 23 == 5 and k == 0:
                row["attachments"] = json.dumps(
                    [{"contentType": "image/png", "content": f"{MARKER} payload"}]
                )
                facts["attachments"].add(u)
            if s % 29 == 3 and k == 0:
                row["timestamp"] = None
                facts["null_ts"].add(u)
            messages.append(row)
            if bot["provider_name"] == "workflow":
                facts["workflow_targets"].add(u)
            ts += timedelta(seconds=30)
            if s % 31 == 7 and k == 0:  # a second USER message before the answer
                u2 = mid()
                messages.append(
                    {
                        "message_id": u2,
                        "session_id": sid,
                        "type": "USER",
                        "timestamp": ts,
                        "content": f"{MARKER} again {s}",
                        "finish_reason": None,
                    }
                )
                facts["consecutive_user"].update({u, u2})
                ts += timedelta(seconds=30)
            a = mid()
            finish = "LENGTH" if s % 37 == 11 and k == 0 else "STOP"
            if finish != "STOP":
                facts["not_stop"].add(u)
            messages.append(
                {
                    "message_id": a,
                    "session_id": sid,
                    "type": "AI",
                    "timestamp": ts,
                    "content": f"{MARKER} answer {s}-{k}",
                    "finish_reason": finish,
                    "input": json.dumps({"items": [{"type": "text"}]})
                    if s % 41 == 2
                    else None,
                }
            )
            ts += timedelta(seconds=30)
            if s % 4 == 0:
                rag_queries.append({"message_id": a, "query": f"{MARKER} query"})
                for c in range(2):
                    chunks.append(
                        {
                            "message_id": a,
                            "chunk_id": f"ch-{a}-{c}",
                            "content": f"{MARKER} chunk {c} of {a}",
                            "corpusId": "c1",
                            "relevancy": 0.5 + c / 10,
                        }
                    )
            billing.append(
                {
                    "message_id": a,
                    "callCount": 1,
                    "inputTokens": 9000 if s % 13 == 0 else 700,
                    "outputTokens": 120,
                    "cachedInputTokens": 0.0,
                    "totalCost": 0.0004,
                    "costBreakdown.per_call": 0.002 if s % 4 == 0 else None,
                    "providerAccount": "acct",
                }
            )
        if s == 50:
            facts["golden"] = messages[-2]["message_id"]

    tables = {
        "data/users.parquet": (
            "users",
            [
                {
                    "user_id": o,
                    "activated": True,
                    "owner_user_id": o,
                    "username_anon": f"{MARKER} user",
                }
                for o in owners
            ],
        ),
        "data/chat_bot.parquet": ("chat_bot", bots),
        "data/chat_session.parquet": ("chat_session", session_rows),
        "data/derived/chat_message_rag.parquet": ("rag_query", rag_queries),
        "data/derived/chat_message_billing.parquet": ("billing_item", billing),
        "data/derived/chat_message_input.parquet": ("input_item", []),
        "data/derived/chat_message_tool_calls.parquet": ("tool_call", []),
        "data/derived/chat_message_actions.parquet": ("action", []),
    }
    half = len(messages) // 2
    tables["data/chat_message-00000-of-00002.parquet"] = (
        "chat_message",
        messages[:half],
    )
    tables["data/chat_message-00001-of-00002.parquet"] = (
        "chat_message",
        messages[half:],
    )
    third = len(chunks) // 2
    tables["data/derived/chat_message_rag_chunks-00000-of-00002.parquet"] = (
        "rag_chunk",
        chunks[:third],
    )
    tables["data/derived/chat_message_rag_chunks-00001-of-00002.parquet"] = (
        "rag_chunk",
        chunks[third:],
    )

    pins: dict[str, list[dict[str, str]]] = {}
    rows_by_table: dict[str, int] = {}
    for rel, (logical, rows) in tables.items():
        path = root / rel
        pq.write_table(_table(spec[logical]["columns"], rows), path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        pins.setdefault(logical, []).append({"path": rel, "sha256": digest})
        rows_by_table[logical] = rows_by_table.get(logical, 0) + len(rows)
        (meta / (Path(rel).name + ".metadata")).write_text(
            f"{REVISION}\netag\n", encoding="utf-8"
        )

    facts["pins"] = pins
    facts["rows"] = rows_by_table
    facts["sessions"] = sessions
    facts["bots"] = bots
    return facts


def write_source_config(path: Path, facts: dict[str, Any]) -> None:
    lines = [
        "[source]",
        'repo = "synthetic/metis"',
        f'revision = "{REVISION}"',
        'raw_dir = "unused"',
        "",
    ]
    for logical, files in facts["pins"].items():
        lines += [
            f"[tables.{logical}]",
            f"expected_rows = {facts['rows'][logical]}",
            "",
        ]
        for f in files:
            lines += [
                f"[[tables.{logical}.files]]",
                f'path = "{f["path"]}"',
                f'sha256 = "{f["sha256"]}"',
                "",
            ]
    path.write_text("\n".join(lines), encoding="utf-8")
