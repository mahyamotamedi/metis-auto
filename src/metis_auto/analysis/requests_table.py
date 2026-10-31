"""Build the linked request-level table from message features.

One row per AI message ("candidate request-response pair"), joined to its
heuristic preceding USER message, session, bot configuration and billing.
Everything here is derived from content-free features plus local grouping
hashes; the table is git-ignored.

History columns describe what was *logged before* the request (available
history), not what was transmitted to the provider (unknown, A-17).
"""

from __future__ import annotations

import hashlib

import pandas as pd

from metis_auto.analysis.pairing import pair_session_messages


def order_messages(msgs: pd.DataFrame) -> pd.DataFrame:
    """Add ``order``: timestamp then source position; null timestamps sort last."""
    m = msgs.copy()
    m["_pos"] = range(len(m))
    m = m.sort_values(
        ["session_id", "timestamp", "_pos"], na_position="last", kind="stable"
    )
    m["order"] = m.groupby("session_id").cumcount()
    return m.drop(columns="_pos")


def history_columns(m: pd.DataFrame) -> pd.DataFrame:
    """Per message: prior conversational messages, chars, and a history-chain hash.

    ``hist_hash`` chains (type, normalised-content hash) of every earlier USER/AI
    message in the same session, so equal hashes mean equal logged history.
    Blank content hashes as its type only.
    """
    m = m.sort_values(["session_id", "order"])
    n_prior, chars_prior, hashes = [], [], []
    cur_sid, n, chars, chain = None, 0, 0, hashlib.blake2b(digest_size=12)
    for sid, typ, nch, hn in zip(
        m["session_id"], m["type"], m["n_chars"].fillna(0), m["h_norm"], strict=False
    ):
        if sid != cur_sid:
            cur_sid, n, chars, chain = sid, 0, 0, hashlib.blake2b(digest_size=12)
        n_prior.append(n)
        chars_prior.append(chars)
        hashes.append(chain.hexdigest())
        if typ in ("USER", "AI"):
            n += 1
            chars += int(nch)
            chain.update(f"{typ}:{hn if isinstance(hn, str) else ''};".encode())
    out = m[["message_id"]].copy()
    out["n_prior_msgs"], out["prior_chars"], out["hist_hash"] = (
        n_prior,
        chars_prior,
        hashes,
    )
    return out


def build_requests(
    msgs: pd.DataFrame,
    sessions: pd.DataFrame,
    bots: pd.DataFrame,
    rag_set_hash: pd.Series | None = None,
) -> pd.DataFrame:
    """Join pairs, user/AI features, session, bot and history into one table."""
    m = order_messages(msgs)
    pairs = pair_session_messages(m[["session_id", "message_id", "type", "order"]])
    hist = history_columns(m).set_index("message_id")
    mi = m.set_index("message_id")
    u_cols = [
        "timestamp",
        "n_chars",
        "lang",
        "h_exact",
        "h_norm",
        "att_n",
        "content_state",
    ]
    a_cols = [
        "timestamp",
        "n_chars",
        "lang",
        "h_norm",
        "finish_reason",
        "is_json",
        "billing_state",
        "bill_inputTokens",
        "bill_outputTokens",
        "bill_cachedInputTokens",
        "bill_totalCost",
        "bill_totalIncome",
        "bill_callCount",
        "n_items",
        "n_token_items",
        "n_per_call_only_items",
        "bill_webSearchCalls",
        "bill_cacheWriteTokens",
        "bill_max_item_input_tokens",
        "rag_state",
        "rag_n_queries",
        "rag_n_chunks",
        "rag_chunk_chars",
        "rag_max_chunk_chars",
        "input_state",
        "input_n_items",
        "tool_n_calls",
        "action_types",
        "citation_n",
        "order",
        "content_state",
    ]
    r = pairs.copy()
    u = mi.loc[r["user_message_id"].dropna(), u_cols].add_prefix("u_")
    u.index = r.index[r["user_message_id"].notna()]
    r = r.join(u)
    a = mi.loc[r["ai_message_id"], a_cols].add_prefix("a_")
    a.index = r.index
    r = r.join(a)
    h = hist.loc[r["ai_message_id"]]
    h.index = r.index
    r["n_prior_msgs"], r["prior_chars"], r["hist_hash"] = (
        h["n_prior_msgs"],
        h["prior_chars"],
        h["hist_hash"],
    )
    # hist_hash chains every logged message before this answer, user turn included.
    r = r.merge(
        sessions[["session_id", "user_id", "bot_id", "created_at"]],
        on="session_id",
        how="left",
    )
    r = r.merge(
        bots.add_prefix("bot_").rename(columns={"bot_bot_id": "bot_id"}),
        on="bot_id",
        how="left",
    )
    if rag_set_hash is not None:
        r["a_rag_set_hash"] = r["ai_message_id"].map(rag_set_hash)
    # turn index: count of earlier paired user messages in session
    r = r.sort_values(["session_id", "a_order"])
    r["turn"] = r.groupby("session_id").cumcount()
    return r.reset_index(drop=True)
