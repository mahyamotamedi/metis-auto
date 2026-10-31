"""Row-level feature extraction for the full dataset (content-free outputs plus
local-only grouping hashes).

``message_features`` maps one ``chat_message`` row to a flat dict of derived
features; nothing returned holds message text. Hash columns (``h_*``) are
unkeyed grouping keys and live only in git-ignored derived tables.

Traces: FR-DATA-02/03/07, ADR-0008.
"""

from __future__ import annotations

import json
from typing import Any

from metis_auto.analysis.billing import parse_billing
from metis_auto.analysis.text_features import fingerprint, normalize_safe, text_features


def _nn(v: Any) -> Any:
    """Map pandas/NumPy missing values (NaN, NA, NaT) to ``None``."""
    return None if v is None or (not isinstance(v, str) and v != v) else v


def _loads(raw: str | None) -> tuple[str, Any]:
    """Return (state, value): state in null | empty | malformed | ok."""
    raw = _nn(raw)
    if raw is None:
        return "null", None
    s = raw.strip()
    if s in ("", "[]", "{}", "null"):
        return "empty", None
    try:
        return "ok", json.loads(s)
    except ValueError:
        return "malformed", None


def content_features(text: str | None, prefix: str = "") -> dict[str, object]:
    text = _nn(text)
    f = text_features(text)
    out = {f"{prefix}{k}": v for k, v in f.items()}
    if text and text.strip():
        out[f"{prefix}h_exact"] = fingerprint(text.strip())
        out[f"{prefix}h_norm"] = fingerprint(normalize_safe(text))
    return out


def attachment_features(raw: str | None) -> dict[str, object]:
    state, val = _loads(raw)
    out: dict[str, object] = {"att_state": state, "att_n": 0, "att_types": ""}
    if state == "ok" and isinstance(val, list):
        types: dict[str, int] = {}
        total = 0
        for a in val:
            if isinstance(a, dict):
                t = str(a.get("contentType"))
                types[t] = types.get(t, 0) + 1
                c = a.get("content")
                total += len(c) if isinstance(c, str) else 0
        out["att_n"] = len(val)
        out["att_types"] = ",".join(f"{k}:{v}" for k, v in sorted(types.items()))
        out["att_payload_chars"] = total
    return out


def rag_features(raw: str | None) -> dict[str, object]:
    """RAG per message: queries, chunks, characters (content-free)."""
    state, val = _loads(raw)
    out: dict[str, object] = {"rag_state": state, "rag_n_queries": 0, "rag_n_chunks": 0}
    if state != "ok" or not isinstance(val, list):
        return out
    n_chunks, chars, max_chunk, q_chars = 0, 0, 0, 0
    for it in val:
        if not isinstance(it, dict):
            continue
        q = it.get("query")
        q_chars += len(q) if isinstance(q, str) else 0
        for ch in it.get("relevantChunks") or []:
            c = ch.get("content") if isinstance(ch, dict) else None
            n = len(c) if isinstance(c, str) else 0
            n_chunks += 1
            chars += n
            max_chunk = max(max_chunk, n)
    out.update(
        rag_n_queries=len(val),
        rag_n_chunks=n_chunks,
        rag_chunk_chars=chars,
        rag_max_chunk_chars=max_chunk,
        rag_query_chars=q_chars,
    )
    return out


def message_features(row: dict[str, Any]) -> dict[str, object]:
    row = {k: _nn(v) for k, v in row.items()}
    out: dict[str, object] = {
        "message_id": row["message_id"],
        "session_id": row["session_id"],
        "type": row["type"],
        "timestamp": row["timestamp"],
        "finish_reason": row.get("finish_reason"),
    }
    out.update(content_features(row.get("content")))
    out.update(attachment_features(row.get("attachments")))
    out.update(rag_features(row.get("rag")))
    out.update(parse_billing(row.get("billing")))
    st, inp = _loads(row.get("input"))
    items = inp.get("items") if st == "ok" and isinstance(inp, dict) else None
    out["input_state"] = st
    out["input_n_items"] = len(items) if isinstance(items, list) else 0
    st, tc = _loads(row.get("tool_calls"))
    out["tool_state"] = st
    out["tool_n_calls"] = len(tc) if st == "ok" and isinstance(tc, list) else 0
    st, ac = _loads(row.get("actions"))
    out["action_state"] = st
    out["action_types"] = (
        ",".join(sorted({str(a.get("type")) for a in ac if isinstance(a, dict)}))
        if st == "ok" and isinstance(ac, list)
        else ""
    )
    st, ci = _loads(row.get("citations"))
    out["citation_n"] = len(ci) if st == "ok" and isinstance(ci, list) else 0
    out["has_google_query"] = bool(row.get("google_search_query"))
    return out


def bot_features(row: dict[str, Any]) -> dict[str, object]:
    row = {k: _nn(v) for k, v in row.items()}
    ins = row.get("instructions")
    out: dict[str, object] = {
        k: row.get(k)
        for k in (
            "bot_id",
            "user_id",
            "created_at",
            "updated_at",
            "deleted_at",
            "provider_name",
            "provider_model",
            "enabled",
            "public",
            "bot_type",
            "memory_enabled",
            "google_search_enabled",
            "rag_top_k",
            "rag_reranking",
            "summarizer_mode",
            "summarizer_provider_name",
            "summarizer_provider_model",
            "independent_function_call",
            "auto_generate_headline",
        )
    }
    out.update(content_features(ins, "ins_"))
    for k in (
        "corpus_ids",
        "functions",
        "provider_args",
        "async_webhook",
        "description",
    ):
        out[f"{k}_state"] = (
            _loads(row.get(k))[0]
            if k != "description"
            else (
                "null"
                if row.get(k) is None
                else ("blank" if not str(row[k]).strip() else "ok")
            )
        )
    st, ids = _loads(row.get("corpus_ids"))
    out["n_corpora"] = len(ids) if st == "ok" and isinstance(ids, list) else 0
    st, fn = _loads(row.get("functions"))
    out["n_functions"] = len(fn) if st == "ok" and isinstance(fn, list) else 0
    return out
