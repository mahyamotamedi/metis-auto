"""Session classes, shared configurations, dominant accounts, golden-set proposal.

    python scripts/full_eda_sessions.py [--smoke] [--seed 20261101]

Needs data/full_data/raw and data/derived/full_eda (scripts/full_eda_ingest.py,
full_eda_requests.py). Runs locally and calls no service. Writes feature-only
tables to reports/full_eda/sessions/ and the claims ledger tag ``d``. Anything
holding text or real account IDs goes to git-ignored runs/full_eda/sessions/.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from metis_auto.analysis import prompt_labels as pl
from metis_auto.analysis import session_config as sc
from metis_auto.analysis.stats import Ledger
from metis_auto.evaluation.golden.allocation import joint_quotas, margin_quotas
from metis_auto.evaluation.golden.manifest import (
    MANIFEST_FIELDS,
    MANIFEST_SCHEMA_VERSION,
    build_manifest_entry,
    manifest_errors,
)

RAW = Path("data/full_data/raw/data")
DER = Path("data/derived/full_eda")
OUT = Path("reports/full_eda/sessions")
LOCAL = Path("runs/full_eda/sessions")
REVISION = "30f578f283b903cdbd06cd1b5f7f962f76452ded"
OBS, META, HEUR, SIM = (
    "observed fact",
    "metadata-derived",
    "heuristic label",
    "simulation",
)
LABEL_CHARS = 4000
GROUPS = (sc.DIRECT, sc.INSTRUCTION_ONLY, sc.RAG_ONLY, sc.BOTH, sc.UNKNOWN)
PSEUDO = ["User A", "User B", "User C", "User D", "User E"]
TOTAL_SAMPLES = 300
REMAINING_QUOTA = 60  # reserved for all accounts outside the top five
USER_FLOOR = 20
CATEGORY_FLOOR = 12
UNKNOWN_QUOTA = 12  # label-error audit only
BOT_CAP = 25  # at most this many samples from one bot
REMAINING = "Remaining accounts"


def short(h: str | None) -> str | None:
    return h[:12] if isinstance(h, str) else None


def save(name: str, df: pd.DataFrame) -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / f"{name}.csv", index=False)
    return df


def label_batch(rows: list[tuple[str, str, int]]) -> list[dict[str, object]]:
    out = []
    for mid, text, turn in rows:
        t = (text or "")[:LABEL_CHARS]
        cat, others = pl.primary_category(t)
        tags = pl.bot_tags(t)
        out.append(
            {
                "message_id": mid,
                "category": cat,
                "secondary": ",".join(others),
                "coding_subtags": ",".join(pl.coding_subtags(t))
                if cat == pl.CODING
                else "",
                "history_dep": pl.history_dependence(t, turn),
                "format_constraint": pl.has_format_constraint(t),
                "reasoning": pl.reasoning_demand(t, cat),
                "template_hint": pl.has_template_hint(t),
                "skeleton": pl.skeleton(t),
                "topics": ",".join(tags["roles"]),
            }
        )
    return out


def load(smoke: bool):
    bots = pd.read_parquet(RAW / "chat_bot.parquet")
    sess = pd.read_parquet(
        RAW / "chat_session.parquet",
        columns=["session_id", "user_id", "bot_id", "created_at", "dialogue_length"],
    )
    cols = [
        "message_id",
        "session_id",
        "type",
        "timestamp",
        "content_state",
        "n_chars",
        "h_exact",
        "h_norm",
        "lang",
        "att_n",
        "att_types",
        "rag_n_queries",
        "rag_n_chunks",
        "rag_chunk_chars",
        "input_n_items",
        "tool_n_calls",
        "shard_row",
    ]
    files = sorted(glob.glob(str(DER / "messages_*.parquet")))
    if smoke:
        files = files[:1]
    msgs = pd.concat(
        [pd.read_parquet(f, columns=cols) for f in files], ignore_index=True
    )
    if smoke:
        sess = sess[sess["session_id"].isin(msgs["session_id"])]
    msgs["_pos"] = range(len(msgs))
    msgs = msgs.sort_values(
        ["session_id", "timestamp", "_pos"], na_position="last", kind="stable"
    )
    msgs["order"] = msgs.groupby("session_id").cumcount()
    return bots, sess, msgs


def classify(L: Ledger, bots: pd.DataFrame, sess: pd.DataFrame, msgs: pd.DataFrame):
    """Bot evidence, session classes, reconciliation and account overlap."""
    defaults = sc.platform_default_hashes(
        zip(bots["instructions"], bots["user_id"], bots["provider_name"], strict=True),
        "workflow",
        5,
    )
    L.add(
        "cls.platform_default_texts",
        "instruction texts identified as platform placeholders",
        len(defaults),
        "texts",
        "rule: only on workflow provider and at least 5 owners",
        META,
    )
    b = bots.copy()
    b["ins_ev"] = [sc.instruction_evidence(t, defaults) for t in b["instructions"]]
    b["rag_cfg"] = [sc.rag_config_evidence(v) for v in b["corpus_ids"]]
    b["ins_fp"] = [
        sc.strict_hash(t) if e == "custom" else None
        for t, e in zip(b["instructions"], b["ins_ev"], strict=True)
    ]
    b["rag_fp"] = [sc.rag_fingerprint(v) for v in b["corpus_ids"]]
    b["ins_chars"] = b["instructions"].fillna("").str.len()
    ai = msgs[msgs["type"] == "AI"]
    agg = (
        ai.assign(
            ch=(ai["rag_n_chunks"].fillna(0) > 0),
            qo=(ai["rag_n_queries"].fillna(0) > 0)
            & (ai["rag_n_chunks"].fillna(0) == 0),
        )
        .groupby("session_id")
        .agg(
            ai_turns=("type", "size"),
            turns_chunks=("ch", "sum"),
            turns_query_only=("qo", "sum"),
        )
    )
    uturns = (
        msgs[msgs["type"] == "USER"].groupby("session_id").size().rename("user_turns")
    )
    allm = msgs.groupby("session_id").size().rename("all_msgs")
    sysm = (
        msgs[msgs["type"] == "SYSTEM"]
        .groupby("session_id")
        .size()
        .rename("system_msgs")
    )
    st = (
        sess.merge(
            b[
                [
                    "bot_id",
                    "ins_ev",
                    "rag_cfg",
                    "ins_fp",
                    "rag_fp",
                    "provider_name",
                    "provider_model",
                    "public",
                    "bot_type",
                    "ins_chars",
                ]
            ],
            on="bot_id",
            how="left",
        )
        .join(agg, on="session_id")
        .join(uturns, on="session_id")
        .join(allm, on="session_id")
        .join(sysm, on="session_id")
    )
    for col in (
        "ai_turns",
        "turns_chunks",
        "turns_query_only",
        "user_turns",
        "all_msgs",
        "system_msgs",
    ):
        st[col] = st[col].fillna(0).astype(int)
    res = [
        sc.classify_session(i, r, int(c), int(q), int(a))
        for i, r, c, q, a in zip(
            st["ins_ev"],
            st["rag_cfg"],
            st["turns_chunks"],
            st["turns_query_only"],
            st["ai_turns"],
            strict=True,
        )
    ]
    st["group"] = [x.group for x in res]
    st["subtype"] = [x.subtype for x in res]
    st["rag_positive"] = [x.rag_positive for x in res]
    st["mixed_rag"] = [x.mixed_rag for x in res]
    st["cfg_disagree"] = [x.config_observed_disagree for x in res]

    n = len(st)
    L.add(
        "cls.raw_session_rows",
        "raw rows in chat_session",
        n,
        "rows",
        "whole export",
        OBS,
    )
    L.add(
        "cls.unique_sessions",
        "unique session_id",
        st["session_id"].nunique(),
        "sessions",
        "whole export",
        OBS,
    )
    L.add(
        "cls.raw_message_rows",
        "raw rows in chat_message",
        len(msgs),
        "rows",
        "whole export",
        OBS,
    )
    L.add(
        "cls.dup_message_ids",
        "duplicate message_id removed",
        int(msgs["message_id"].duplicated().sum()),
        "rows",
        "whole export",
        OBS,
    )
    L.add(
        "cls.excluded_invalid",
        "sessions excluded as invalid",
        int(st["ins_ev"].isna().sum()),
        "sessions",
        "bot record missing",
        OBS,
    )
    classified = int((st["group"] != sc.UNKNOWN).sum())
    L.add(
        "cls.classified",
        "sessions in groups a to d",
        classified,
        "sessions",
        "all sessions",
        META,
    )
    rows = []
    for g in GROUPS:
        k = int((st["group"] == g).sum())
        ut = int(st.loc[st["group"] == g, "user_turns"].sum())
        am = int(st.loc[st["group"] == g, "all_msgs"].sum())
        rows.append(
            {
                "group": g,
                "sessions": k,
                "share_all_sessions": k / n,
                "share_classified_sessions": (
                    k / classified if g != sc.UNKNOWN and classified else None
                ),
                "user_turns": ut,
                "share_user_turns": ut / st["user_turns"].sum(),
                "all_messages": am,
                "share_all_messages": am / st["all_msgs"].sum(),
                "bots": st.loc[st["group"] == g, "bot_id"].nunique(),
                "accounts": st.loc[st["group"] == g, "user_id"].nunique(),
            }
        )
        L.ratio(
            f"cls.group.{g}",
            f"sessions in group {g}",
            k,
            n,
            "share of all sessions",
            "all sessions",
            META,
        )
        L.add(
            f"cls.group_n.{g}",
            f"sessions in group {g}",
            k,
            "sessions",
            "all sessions",
            META,
        )
        L.add(
            f"cls.turns_n.{g}",
            f"USER turns in group {g}",
            ut,
            "user turns",
            "secondary, turn-weighted",
            META,
        )
        L.ratio(
            f"cls.turns.{g}",
            f"USER turns in group {g}",
            ut,
            int(st["user_turns"].sum()),
            "share of USER turns",
            "secondary, turn-weighted",
            META,
        )
    save("session_groups", pd.DataFrame(rows))
    if sum(r["sessions"] for r in rows) != n:
        raise SystemExit("reconciliation failed: groups do not sum to sessions")
    L.add(
        "cls.reconciliation_sum",
        "sum of the five mutually exclusive groups",
        sum(r["sessions"] for r in rows),
        "sessions",
        "must equal unique sessions",
        META,
    )
    sub = (
        st.groupby(["group", "subtype"])
        .agg(
            sessions=("session_id", "size"),
            user_turns=("user_turns", "sum"),
            bots=("bot_id", "nunique"),
        )
        .reset_index()
    )
    sub["share_all_sessions"] = sub["sessions"] / n
    save("session_subtypes", sub)
    for _, r in sub.iterrows():
        L.add(
            f"cls.sub.{r['subtype']}",
            f"sessions of subtype {r['subtype']}",
            int(r["sessions"]),
            "sessions",
            "all sessions",
            META,
        )
    chat = int(st["group"].isin(sc.CHATBOT_GROUPS).sum())
    direct = int((st["group"] == sc.DIRECT).sum())
    L.add(
        "cls.chatbot_sessions",
        "inferred chatbot sessions (groups b, c, d)",
        chat,
        "sessions",
        "all sessions",
        META,
    )
    L.ratio(
        "cls.chatbot_per_direct",
        "inferred chatbot sessions per inferred direct session",
        chat,
        direct,
        "ratio",
        "classified sessions",
        META,
    )
    L.ratio(
        "cls.chatbot_share_classified",
        "inferred chatbot share of classified sessions",
        chat,
        classified,
        "share of classified sessions",
        "classified sessions",
        META,
    )
    L.ratio(
        "cls.chatbot_share_all",
        "inferred chatbot share of all sessions",
        chat,
        n,
        "share of all sessions",
        "all sessions",
        META,
    )
    wf_rag = int((st["subtype"] == "platform_default_rag_positive").sum())
    custom_unk = int((st["subtype"] == "custom_rag_unknown").sum())
    L.add(
        "cls.upper_chatbot",
        "sessions with any positive configuration evidence (b, c, d, plus RAG on workflow bots, plus custom with unknown RAG)",
        chat + wf_rag + custom_unk,
        "sessions",
        "sensitivity",
        META,
    )
    L.ratio(
        "cls.upper_chatbot_share",
        "same, share of all sessions",
        chat + wf_rag + custom_unk,
        n,
        "share of all sessions",
        "sensitivity",
        META,
    )
    L.ratio(
        "cls.mixed_rag",
        "sessions with RAG observed on some AI turns only",
        int(st["mixed_rag"].sum()),
        n,
        "share of all sessions",
        "all sessions",
        OBS,
    )
    L.add(
        "cls.mixed_rag_n",
        "sessions with RAG observed on some AI turns only",
        int(st["mixed_rag"].sum()),
        "sessions",
        "all sessions",
        OBS,
    )
    L.add(
        "cls.cfg_disagree_n",
        "sessions with retrieval observed but no configured corpus",
        int(st["cfg_disagree"].sum()),
        "sessions",
        "all sessions",
        OBS,
    )
    L.add(
        "cls.sessions_no_ai",
        "sessions with no AI message",
        int((st["ai_turns"] == 0).sum()),
        "sessions",
        "all sessions",
        OBS,
    )
    L.add(
        "cls.sessions_no_user",
        "sessions with no USER message",
        int((st["user_turns"] == 0).sum()),
        "sessions",
        "all sessions",
        OBS,
    )
    L.add(
        "cls.sessions_with_system",
        "sessions with a SYSTEM message",
        int((st["system_msgs"] > 0).sum()),
        "sessions",
        "all sessions",
        OBS,
    )
    # Sensitivity: short or cross-owner instructions may be generic defaults.
    owner_n = b[b["ins_fp"].notna()].groupby("ins_fp")["user_id"].nunique()
    cross = set(owner_n[owner_n >= 2].index)
    L.add(
        "cls.sens_cross_owner_sessions",
        "custom-instruction sessions whose exact text is on 2 or more owners",
        int(st["ins_fp"].isin(cross).sum()),
        "sessions",
        "possible templates; kept as custom",
        META,
    )
    L.add(
        "cls.sens_short_sessions",
        "custom-instruction sessions with instruction of at most 30 characters",
        int(((st["ins_ev"] == "custom") & (st["ins_chars"] <= 30)).sum()),
        "sessions",
        "possible generic text; kept as custom",
        META,
    )
    L.add(
        "cls.direct_with_system",
        "inferred direct sessions that hold a SYSTEM message",
        int(((st["group"] == sc.DIRECT) & (st["system_msgs"] > 0)).sum()),
        "sessions",
        "SYSTEM text is not read as an instruction",
        OBS,
    )
    sysg = st[st["system_msgs"] > 0]["group"].value_counts()
    for g, v in sysg.items():
        L.add(
            f"cls.system_in.{g}",
            f"sessions with a SYSTEM message in group {g}",
            int(v),
            "sessions",
            "all sessions",
            OBS,
        )
    L.add(
        "acct.bots_per_account_all",
        "bot records per account in the users table",
        len(b) / max(1, b["user_id"].nunique()),
        "bots per owning account",
        "accounts that own a bot",
        META,
    )
    L.add(
        "acct.owning_accounts",
        "accounts that own at least one bot",
        b["user_id"].nunique(),
        "accounts",
        "chat_bot table",
        META,
    )
    L.add(
        "acct.session_accounts",
        "accounts with at least one session",
        st["user_id"].nunique(),
        "accounts",
        "chat_session table",
        META,
    )
    L.add(
        "acct.used_bots_per_session_account",
        "used bots per account with sessions",
        st["bot_id"].nunique() / st["user_id"].nunique(),
        "bots per account",
        "chat_session table",
        META,
    )
    # Bot-ID cross-tabs.
    L.ratio(
        "cls.sessions_with_bot_id",
        "sessions with a bot_id",
        int(st["bot_id"].notna().sum()),
        n,
        "share of all sessions",
        "all sessions",
        OBS,
    )
    ct = (
        st.assign(workflow=st["provider_name"] == "workflow")
        .groupby(["group", "public", "bot_type", "workflow"])
        .agg(sessions=("session_id", "size"), bots=("bot_id", "nunique"))
        .reset_index()
    )
    save("group_by_bot_flags", ct)
    # Accounts: reported as owner accounts, never as people.
    pivot = st.groupby("user_id")["group"].agg(set)

    def kind(s: set) -> str:
        chat_ = bool(s & set(sc.CHATBOT_GROUPS))
        dir_ = sc.DIRECT in s
        if chat_ and dir_:
            return "both"
        if chat_:
            return "chatbot_only"
        return "direct_only" if dir_ else "unknown_only"

    ak = pivot.map(kind).value_counts()
    save(
        "account_overlap",
        ak.rename("accounts").rename_axis("account_kind").reset_index(),
    )
    for k, v in ak.items():
        L.add(
            f"acct.kind.{k}",
            f"owner accounts of kind {k}",
            int(v),
            "accounts",
            "accounts with sessions",
            META,
        )
    return b, st, defaults


def shared_configs(
    L: Ledger, b: pd.DataFrame, st: pd.DataFrame, msgs: pd.DataFrame
) -> pd.DataFrame:
    """Shared instruction and RAG configurations, among all bots and used bots."""
    sc_n = st.groupby("bot_id").size().rename("sessions")
    ut_n = st.groupby("bot_id")["user_turns"].sum().rename("user_turns")
    x = b.join(sc_n, on="bot_id").join(ut_n, on="bot_id")
    x[["sessions", "user_turns"]] = x[["sessions", "user_turns"]].fillna(0).astype(int)
    has_rag = x["rag_cfg"] == "configured"
    has_ins = x["ins_ev"] == "custom"
    known_no_rag = x["rag_cfg"] == "not_configured"
    x["kind"] = np.select(
        [
            has_ins & has_rag,
            has_ins & known_no_rag,
            x["ins_ev"].eq("absent") & has_rag,
            has_ins,
        ],
        ["both", "instruction_only", "rag_only", "instruction_rag_unknown"],
        default="excluded",
    )
    L.add(
        "cfg.bots_total",
        "chatbot records (bot_id)",
        len(x),
        "bots",
        "chat_bot table",
        OBS,
    )
    L.add(
        "cfg.bots_used",
        "bots with at least one session",
        int((x["sessions"] > 0).sum()),
        "bots",
        "chat_bot table",
        OBS,
    )
    L.add(
        "cfg.bots_in_scope",
        "bots with a custom instruction or configured RAG",
        int((x["kind"] != "excluded").sum()),
        "bots",
        "chat_bot table",
        META,
    )
    L.add(
        "cfg.bots_in_scope_used",
        "same, used in at least one session",
        int(((x["kind"] != "excluded") & (x["sessions"] > 0)).sum()),
        "bots",
        "chat_bot table",
        META,
    )
    x["cfg_key"] = (
        x["ins_fp"].fillna("-") + "|" + x["rag_fp"].fillna("-") + "|" + x["kind"]
    )
    chat_sessions = int(st["group"].isin(sc.CHATBOT_GROUPS).sum())
    scopes = {
        "all_bots": x[x["kind"] != "excluded"],
        "used_bots": x[(x["kind"] != "excluded") & (x["sessions"] > 0)],
    }
    summary = []
    tops = None
    for scope, y in scopes.items():
        g = (
            y.groupby("cfg_key")
            .agg(
                bots=("bot_id", "size"),
                owners=("user_id", "nunique"),
                sessions=("sessions", "sum"),
                user_turns=("user_turns", "sum"),
                kind=("kind", "first"),
                ins_chars=("ins_chars", "first"),
                ins_fp=("ins_fp", "first"),
                rag_fp=("rag_fp", "first"),
                models=(
                    "provider_model",
                    lambda s: ";".join(f"{k}:{v}" for k, v in s.value_counts().items()),
                ),
            )
            .reset_index()
        )
        rep = g[g["bots"] > 1]
        for kind in (
            "all",
            "instruction_only",
            "rag_only",
            "both",
            "instruction_rag_unknown",
        ):
            gk, rk = (
                (g, rep)
                if kind == "all"
                else (g[g["kind"] == kind], rep[rep["kind"] == kind])
            )
            rep_chat = int(
                rk.loc[rk["kind"] != "instruction_rag_unknown", "sessions"].sum()
            )
            summary.append(
                {
                    "scope": scope,
                    "kind": kind,
                    "unique_configurations": len(gk),
                    "bots": int(gk["bots"].sum()),
                    "repeated_groups": len(rk),
                    "bots_in_repeated_groups": int(rk["bots"].sum()),
                    "extra_bots_beyond_one_per_group": sc.extra_entities(rk["bots"]),
                    "cross_owner_groups": int((rk["owners"] > 1).sum()),
                    "same_owner_groups": int((rk["owners"] == 1).sum()),
                    "sessions_in_repeated_groups": int(rk["sessions"].sum()),
                    "share_of_chatbot_sessions": rep_chat / chat_sessions
                    if chat_sessions
                    else None,
                }
            )
            for f, v in summary[-1].items():
                if f not in ("scope", "kind") and v is not None:
                    L.add(
                        f"cfg.{scope}.{kind}.{f}",
                        f"{f} [{scope}, {kind}]",
                        float(v),
                        "count or share",
                        "bots with custom instruction or configured RAG",
                        META,
                    )
        sizes = (
            rep["bots"]
            .value_counts()
            .sort_index()
            .rename("groups")
            .rename_axis("bots_in_group")
            .reset_index()
        )
        sizes.insert(0, "scope", scope)
        save(f"shared_group_sizes_{scope}", sizes)
        if scope == "all_bots":
            tops = (
                rep.sort_values(["bots", "sessions"], ascending=False).head(25).copy()
            )
    save("shared_config_summary", pd.DataFrame(summary))
    tops["config"] = [f"G{i + 1:02d}" for i in range(len(tops))]
    tops["ins_fp"] = tops["ins_fp"].map(short)
    tops["rag_fp"] = tops["rag_fp"].map(short)
    save(
        "shared_config_top_groups",
        tops[
            [
                "config",
                "kind",
                "bots",
                "owners",
                "sessions",
                "user_turns",
                "ins_chars",
                "ins_fp",
                "rag_fp",
                "models",
            ]
        ],
    )
    # Separate, labelled comparisons.
    from metis_auto.analysis.text_features import normalize_safe

    ib = x[x["ins_fp"].notna()]
    norm = ib["instructions"].map(lambda t: sc.strict_hash(normalize_safe(t)))
    L.add(
        "cfg.strict_instruction_texts",
        "distinct custom instruction texts, exact",
        int(ib["ins_fp"].nunique()),
        "texts",
        "all bots with custom instruction",
        META,
    )
    L.add(
        "cfg.normalized_instruction_texts",
        "distinct custom instruction texts after optional Persian-aware normalisation",
        int(norm.nunique()),
        "texts",
        "separate labelled comparison, not the equality key",
        HEUR,
    )
    rb = x[x["rag_fp"].notna()]
    orderless = rb["corpus_ids"].map(
        lambda v: sc.strict_hash(sc.canonical_json(sorted(json.loads(v), key=str)))
    )
    L.add(
        "cfg.rag_refs_strict",
        "distinct configured corpus lists, order preserved",
        int(rb["rag_fp"].nunique()),
        "lists",
        "bots with configured corpus",
        META,
    )
    L.add(
        "cfg.rag_refs_orderless",
        "distinct configured corpus lists, order ignored",
        int(orderless.nunique()),
        "lists",
        "separate labelled comparison",
        META,
    )
    # Observed retrieval: a limited proxy, never knowledge-base equality.
    ch = pd.concat(
        [
            pd.read_parquet(f, columns=["message_id", "corpus_id", "h_exact"])
            for f in sorted(glob.glob(str(DER / "chunks" / "*.parquet")))
        ],
        ignore_index=True,
    )
    mm = ch.merge(msgs[["message_id", "session_id"]], on="message_id").merge(
        st[["session_id", "bot_id"]], on="session_id"
    )
    obs = (
        mm.dropna(subset=["corpus_id"])
        .groupby("bot_id")["corpus_id"]
        .apply(lambda s: set(s.astype(str)))
    )
    conf = x.set_index("bot_id")["corpus_ids"]
    rel = Counter()
    for bid, oset in obs.items():
        state, parsed = sc.json_field_state(conf.get(bid))
        if state == "null":
            rel["configured_null"] += 1
        elif state != "nonempty":
            rel["configured_empty"] += 1
        else:
            cset = {str(v) for v in parsed}
            rel[
                "subset_of_configured"
                if oset <= cset
                else ("partial_overlap" if oset & cset else "disjoint")
            ] += 1
    save(
        "observed_vs_configured_corpus",
        pd.DataFrame(sorted(rel.items()), columns=["relation", "bots"]),
    )
    for k, v in rel.items():
        L.add(
            f"cfg.obs_corpus.{k}",
            f"bots with retrieval whose observed corpus IDs are: {k}",
            v,
            "bots",
            "bots with observed chunks",
            OBS,
        )
    obs_key = obs.map(lambda s: sc.strict_hash(sc.canonical_json(sorted(s))))
    wf_ids = set(x.loc[x["provider_name"] == "workflow", "bot_id"])
    ow = obs_key[obs_key.index.isin(wf_ids)]
    L.add(
        "cfg.workflow_bots_retrieval",
        "workflow bots with observed retrieval",
        len(ow),
        "bots",
        "observed proxy only",
        OBS,
    )
    L.add(
        "cfg.workflow_distinct_obs_corpus",
        "distinct observed corpus-ID sets on those bots",
        int(ow.nunique()),
        "sets",
        "observed proxy; not knowledge-base equality",
        OBS,
    )
    payload = mm.groupby("message_id")["h_exact"].apply(
        lambda s: hashlib.blake2b(
            "|".join(sorted(map(str, s))).encode(), digest_size=12
        ).hexdigest()
    )
    L.add(
        "cfg.retrieved_payload_turns",
        "AI turns with retrieved chunks",
        len(payload),
        "AI turns",
        "observed",
        OBS,
    )
    L.add(
        "cfg.retrieved_payload_distinct",
        "distinct retrieved chunk sets",
        int(payload.nunique()),
        "sets",
        "exact payload match; limited proxy",
        OBS,
    )
    # Configuration change is not observable: one snapshot per bot.
    u = x[x["sessions"] > 0]
    L.add(
        "cfg.used_bots_updated_after_created",
        "used bots with updated_at later than created_at",
        int((u["updated_at"] > u["created_at"]).sum()),
        "bots",
        "edit content and history unobservable",
        META,
    )
    return x


def build_turns(
    st: pd.DataFrame, msgs: pd.DataFrame, b: pd.DataFrame, smoke: bool
) -> pd.DataFrame:
    """One row per USER turn: labels, context sizes and the paired AI turn."""
    um = msgs[msgs["type"].isin(["USER", "AI"])].copy()
    um["n"] = um["n_chars"].fillna(0)
    um["prior_chars"] = um.groupby("session_id")["n"].cumsum() - um["n"]
    um["next_type"] = um.groupby("session_id")["type"].shift(-1)
    for c in ("rag_chunk_chars", "rag_n_chunks", "tool_n_calls", "input_n_items"):
        um[f"next_{c}"] = (
            um.groupby("session_id")[c].shift(-1).where(um["next_type"] == "AI")
        )
    um["prev_input_items"] = um.groupby("session_id")["input_n_items"].shift(1)
    um["next_ai_id"] = (
        um.groupby("session_id")["message_id"].shift(-1).where(um["next_type"] == "AI")
    )
    u = um[um["type"] == "USER"].copy()
    u["turn"] = u.groupby("session_id").cumcount()
    u["gap_s"] = u.groupby("session_id")["timestamp"].diff().dt.total_seconds()
    u = u.merge(
        st[["session_id", "user_id", "bot_id", "group", "subtype", "ins_chars"]],
        on="session_id",
    )
    texts = {}
    files = sorted(glob.glob(str(RAW / "chat_message-*.parquet")))
    want = set(u["message_id"])
    for f in files[:1] if smoke else files:
        t = pq.read_table(f, columns=["message_id", "content"]).to_pandas()
        t = t[t["message_id"].isin(want)]
        texts.update(zip(t["message_id"], t["content"], strict=True))
    rows = [
        (m, texts.get(m), int(k))
        for m, k in zip(u["message_id"], u["turn"], strict=True)
    ]
    size = 20000
    batches = [rows[i : i + size] for i in range(0, len(rows), size)]
    with ProcessPoolExecutor(max(1, (os.cpu_count() or 2) - 1)) as ex:
        labels = [r for part in ex.map(label_batch, batches) for r in part]
    u = u.merge(pd.DataFrame(labels), on="message_id")
    u["context_chars"] = (
        u["ins_chars"].fillna(0)
        + u["prior_chars"]
        + u["n"]
        + u["next_rag_chunk_chars"].fillna(0)
    )
    p50, p90 = u["context_chars"].quantile([0.5, 0.9])
    u["context_bucket"] = np.where(
        u["context_chars"] <= p50,
        "short",
        np.where(u["context_chars"] <= p90, "medium", "long"),
    )
    u.attrs["p50"], u.attrs["p90"] = float(p50), float(p90)
    return u


def dist(s: pd.Series) -> dict[str, float]:
    return (s.value_counts(normalize=True)).to_dict()


def top_five(
    L: Ledger, u: pd.DataFrame, st: pd.DataFrame, b: pd.DataFrame, msgs: pd.DataFrame
):
    """Verify concentration, identity, and profile the five accounts."""
    total = len(u)
    c = u.groupby("user_id").size().sort_values(ascending=False)
    top = list(c.index[:5])
    alias = dict(zip(top, PSEUDO, strict=False))
    LOCAL.mkdir(parents=True, exist_ok=True)
    (LOCAL / "pseudonym_map_LOCAL_ONLY.json").write_text(json.dumps(alias, indent=1))
    u["cohort"] = u["user_id"].map(alias).fillna(REMAINING)
    st["cohort"] = st["user_id"].map(alias).fillna(REMAINING)
    L.add(
        "top.request_total",
        "requests: USER turns with text",
        total,
        "user turns",
        "all USER messages; none blank",
        OBS,
    )
    L.add(
        "top.accounts_with_requests",
        "accounts with at least one request",
        len(c),
        "accounts",
        "all",
        META,
    )
    L.add(
        "top.missing_user_ids",
        "requests with no user_id",
        int(u["user_id"].isna().sum()),
        "user turns",
        "all",
        OBS,
    )
    L.ratio(
        "top.top5_share",
        "share of requests from the 5 largest user_id",
        int(c.iloc[:5].sum()),
        total,
        "share of USER turns",
        "attribution is complete",
        META,
    )
    ai_c = (
        msgs[msgs["type"] == "AI"]
        .merge(st[["session_id", "user_id"]], on="session_id")
        .groupby("user_id")
        .size()
    )
    L.ratio(
        "top.top5_share_ai",
        "same accounts, share of AI messages (the earlier 97% basis)",
        int(ai_c.reindex(top).sum()),
        int(ai_c.sum()),
        "share of AI messages",
        "all AI messages",
        META,
    )
    own = st.merge(
        b[["bot_id", "user_id"]].rename(columns={"user_id": "owner"}), on="bot_id"
    )
    L.ratio(
        "top.session_user_is_bot_owner",
        "sessions where session user_id equals the bot's owner",
        int((own["user_id"] == own["owner"]).sum()),
        len(own),
        "share of sessions",
        "all sessions",
        OBS,
    )
    side, rows_cat, rows_bot, profiles = [], [], [], {}
    pub = b.set_index("bot_id")
    cum = 0
    for uid, name in alias.items():
        x = u[u["user_id"] == uid]
        s = st[st["user_id"] == uid]
        cum += len(x)
        gaps = x["gap_s"].dropna()
        days = x["timestamp"].dt.date.nunique()
        by_bot = (
            x.groupby("bot_id")
            .agg(requests=("message_id", "size"), sessions=("session_id", "nunique"))
            .sort_values("requests", ascending=False)
        )
        owned = b[b["user_id"] == uid]
        exact_top = x["h_exact"].value_counts()
        skel = x["skeleton"].value_counts()
        hours = x["timestamp"].dt.hour.value_counts(normalize=True)
        months = (
            x["timestamp"].dt.to_period("M").astype(str).value_counts().sort_index()
        )
        sl = s["user_turns"]
        cats = x["category"].value_counts(normalize=True)
        row = {
            "account": name,
            "requests": len(x),
            "share_requests": len(x) / total,
            "cumulative_share": cum / total,
            "sessions": len(s),
            "requests_per_session": len(x) / max(1, len(s)),
            "bots_owned": len(owned),
            "bots_used": x["bot_id"].nunique(),
            "public_bot_request_share": float(x["bot_id"].map(pub["public"]).mean()),
            "top_bot_request_share": by_bot["requests"].iloc[0] / len(x),
            "top3_bot_request_share": by_bot["requests"].iloc[:3].sum() / len(x),
            "direct_request_share": float((x["group"] == sc.DIRECT).mean()),
            "instruction_only_request_share": float(
                (x["group"] == sc.INSTRUCTION_ONLY).mean()
            ),
            "rag_only_request_share": float((x["group"] == sc.RAG_ONLY).mean()),
            "both_request_share": float((x["group"] == sc.BOTH).mean()),
            "unknown_request_share": float((x["group"] == sc.UNKNOWN).mean()),
            "direct_session_share": float((s["group"] == sc.DIRECT).mean()),
            "chatbot_session_share": float(s["group"].isin(sc.CHATBOT_GROUPS).mean()),
            "unknown_session_share": float((s["group"] == sc.UNKNOWN).mean()),
            "median_user_turns_per_session": float(sl.median()),
            "p90_user_turns_per_session": float(sl.quantile(0.9)),
            "median_context_chars": float(x["context_chars"].median()),
            "p90_context_chars": float(x["context_chars"].quantile(0.9)),
            "first_turn_share": float((x["turn"] == 0).mean()),
            "likely_history_dependent_share": float(
                (x["history_dep"] == "likely_dependent").mean()
            ),
            "fa_share": float((x["lang"] == "fa").mean()),
            "en_share": float((x["lang"] == "en").mean()),
            "mixed_share": float((x["lang"] == "fa_en_mixed").mean()),
            "short_uncertain_share": float((x["lang"] == "short_uncertain").mean()),
            "median_user_chars": float(x["n"].median()),
            "top_category": cats.index[0],
            "top_category_share": float(cats.iloc[0]),
            "coding_share": float((x["category"] == pl.CODING).mean()),
            "exact_repeat_share": float(x["h_exact"].duplicated(keep=False).mean()),
            "top10_text_share": float(exact_top.iloc[:10].sum() / len(x)),
            "top_skeleton_share": float(skel.iloc[0] / len(x)),
            "template_hint_share": float(x["template_hint"].mean()),
            "after_input_widget_share": float(
                (x["prev_input_items"].fillna(0) > 0).mean()
            ),
            "median_gap_between_user_turns_s": float(gaps.median())
            if len(gaps)
            else None,
            "gap_under_5s_share": float((gaps < 5).mean()) if len(gaps) else None,
            "peak_hour_share": float(hours.iloc[0]),
            "active_days": days,
            "requests_per_active_day": len(x) / max(1, days),
            "first_month": months.index[0],
            "last_month": months.index[-1],
            "peak_month": months.idxmax(),
            "peak_month_share": float(months.max() / len(x)),
        }
        side.append(row)
        for k, v in row.items():
            if isinstance(v, (int, float, np.integer, np.floating)) and k != "account":
                L.add(
                    f"top.{name[-1]}.{k}",
                    f"{name}: {k}",
                    float(v),
                    "see metric name",
                    "this account's requests or sessions",
                    HEUR
                    if "share" in k and k.split("_")[0] in ("coding", "top")
                    else META,
                )
        cc = x["category"].value_counts()
        for cat, n in cc.items():
            rows_cat.append(
                {
                    "account": name,
                    "category": cat,
                    "requests": int(n),
                    "share_of_account": n / len(x),
                }
            )
        topic = Counter(t for ts in x["topics"] for t in ts.split(",") if t)
        for rank, (bid, br) in enumerate(by_bot.iterrows(), start=1):
            bb = pub.loc[bid]
            tags = pl.bot_tags(
                bb["instructions"] if isinstance(bb["instructions"], str) else None
            )
            fp = (
                sc.strict_hash(bb["instructions"]) if bb["ins_ev"] == "custom" else None
            )
            shared = (
                b[(b["ins_fp"] == fp) & (b["user_id"] != uid)]["user_id"].nunique()
                if fp
                else 0
            )
            y = x[x["bot_id"] == bid]
            ycat = y["category"].value_counts(normalize=True)
            rows_bot.append(
                {
                    "account": name,
                    "rank": rank,
                    "bot": bid,
                    "requests": int(br["requests"]),
                    "sessions": int(br["sessions"]),
                    "share_of_account": br["requests"] / len(x),
                    "config_group": y["group"].iloc[0],
                    "subtype": y["subtype"].iloc[0],
                    "ins_fp": short(fp),
                    "ins_chars": int(bb["ins_chars"]),
                    "rag_fp": short(bb["rag_fp"]),
                    "model": bb["provider_model"],
                    "provider": bb["provider_name"],
                    "role_tags": ",".join(tags["roles"]),
                    "constraint_tags": ",".join(tags["constraints"]),
                    "top_request_category": ycat.index[0],
                    "top_request_category_share": float(ycat.iloc[0]),
                    "other_owners_with_same_instruction": int(shared),
                }
            )
        profiles[name] = {
            "categories": cc.head(5).to_dict(),
            "topics_in_requests": dict(topic.most_common(6)),
            "models_by_request": x["bot_id"]
            .map(pub["provider_model"])
            .value_counts()
            .head(5)
            .to_dict(),
            "months": months.to_dict(),
        }
    side_df = save("top5_side_by_side", pd.DataFrame(side))
    save("user_by_category", pd.DataFrame(rows_cat))
    save("user_by_bot", pd.DataFrame(rows_bot))
    (OUT / "top5_profiles.json").write_text(
        json.dumps(profiles, indent=1, ensure_ascii=False, default=str)
    )
    # Cohort comparison with explicit denominators.
    cmp_rows = []
    views = {
        "full_corpus": u,
        "top_five": u[u["cohort"] != REMAINING],
        "remaining": u[u["cohort"] == REMAINING],
    }
    for dim in ("category", "lang", "group", "context_bucket", "history_dep"):
        for vname, v in views.items():
            for val, share in (
                v[dim].fillna("(none)").value_counts(normalize=True).items()
            ):
                cmp_rows.append(
                    {
                        "dimension": dim,
                        "value": val,
                        "view": vname,
                        "share_of_view_requests": share,
                        "view_requests": len(v),
                    }
                )
    save("cohort_comparison", pd.DataFrame(cmp_rows))
    for vname, v in views.items():
        L.add(
            f"cohort.{vname}.requests",
            f"requests in {vname}",
            len(v),
            "user turns",
            "denominator",
            META,
        )
        L.add(
            f"cohort.{vname}.accounts",
            f"accounts in {vname}",
            v["user_id"].nunique(),
            "accounts",
            "denominator",
            META,
        )
        L.add(
            f"cohort.{vname}.bots",
            f"bots in {vname}",
            v["bot_id"].nunique(),
            "bots",
            "denominator",
            META,
        )
        L.add(
            f"cohort.{vname}.median_context",
            f"median context characters, {vname}",
            float(v["context_chars"].median()),
            "characters",
            "logged, not transmitted",
            META,
        )
        L.ratio(
            f"cohort.{vname}.rag_observed",
            f"requests answered with retrieved chunks, {vname}",
            int((v["next_rag_n_chunks"].fillna(0) > 0).sum()),
            len(v),
            "share of requests",
            "paired AI turn",
            OBS,
        )
        top_bots = v.groupby("bot_id").size().sort_values(ascending=False)
        L.ratio(
            f"cohort.{vname}.top10_bot_share",
            f"requests on the 10 largest bots, {vname}",
            int(top_bots.iloc[:10].sum()),
            len(v),
            "share of requests",
            "bots",
            META,
        )
    return alias, side_df


def categories(L: Ledger, u: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cat in (*pl.PRECEDENCE, pl.UNKNOWN):
        x = u[u["category"] == cat]
        rows.append(
            {
                "category": cat,
                "requests": len(x),
                "share_requests": len(x) / len(u),
                "sessions": x["session_id"].nunique(),
                "accounts": x["user_id"].nunique(),
                "bots": x["bot_id"].nunique(),
                "share_top_five": float((x["cohort"] != REMAINING).mean())
                if len(x)
                else None,
                "fa_share": float((x["lang"] == "fa").mean()) if len(x) else None,
                "median_chars": float(x["n"].median()) if len(x) else None,
                "first_turn_share": float((x["turn"] == 0).mean()) if len(x) else None,
                "with_other_category_match": float((x["secondary"] != "").mean())
                if len(x)
                else None,
            }
        )
        L.ratio(
            f"cat.{cat}",
            f"requests labelled {cat}",
            len(x),
            len(u),
            "share of requests",
            "all USER turns; local rules",
            HEUR,
        )
        L.add(
            f"cat_n.{cat}",
            f"requests labelled {cat}",
            len(x),
            "requests",
            "all USER turns; local rules",
            HEUR,
        )
    df = save("category_prevalence", pd.DataFrame(rows))
    unk = u[u["category"] == pl.UNKNOWN]
    no_letters = unk["n"] <= 15
    parts = {
        "after_input_widget": unk["prev_input_items"].fillna(0) > 0,
        "at_most_15_chars": no_letters,
        "later_turn": unk["turn"] > 0,
        "first_turn": unk["turn"] == 0,
        "lang_short_uncertain": unk["lang"] == "short_uncertain",
        "over_100_chars": unk["n"] > 100,
        "exact_text_repeated": unk["h_exact"].duplicated(keep=False),
    }
    save(
        "unknown_category_breakdown",
        pd.DataFrame(
            [
                {
                    "signal": k,
                    "requests": int(v.sum()),
                    "share_of_unknown": float(v.mean()),
                }
                for k, v in parts.items()
            ]
        ),
    )
    for k, v in parts.items():
        L.ratio(
            f"cat.unknown.{k}",
            f"unknown-labelled requests: {k}",
            int(v.sum()),
            len(unk),
            "share of unknown requests",
            "signals overlap",
            HEUR,
        )
    tags = []
    for dim in ("lang", "group", "history_dep", "context_bucket", "reasoning"):
        for k, v in u[dim].fillna("(none)").value_counts().items():
            tags.append(
                {"tag": dim, "value": k, "requests": int(v), "share": v / len(u)}
            )
    for name, s in (
        ("format_constraint", u["format_constraint"]),
        ("attachment", u["att_n"].fillna(0) > 0),
        ("tool_call_on_answer", u["next_tool_n_calls"].fillna(0) > 0),
        ("template_hint", u["template_hint"]),
        ("after_input_widget", u["prev_input_items"].fillna(0) > 0),
    ):
        tags.append(
            {
                "tag": name,
                "value": "true",
                "requests": int(s.sum()),
                "share": float(s.mean()),
            }
        )
    save("secondary_tag_prevalence", pd.DataFrame(tags))
    L.add(
        "ctx.p50_chars",
        "short/medium context threshold: p50 of logged context",
        u.attrs["p50"],
        "characters",
        "instruction + prior + message + retrieved",
        META,
    )
    L.add(
        "ctx.p90_chars",
        "medium/long context threshold: p90 of logged context",
        u.attrs["p90"],
        "characters",
        "same",
        META,
    )
    return df


def allocate_and_sample(
    L: Ledger,
    u: pd.DataFrame,
    b: pd.DataFrame,
    msgs: pd.DataFrame,
    seed: int,
    smoke: bool,
):
    """Exactly-300 quotas, then a proposed (not approved) candidate list."""
    # Population: one row per distinct (bot, normalised text); repeats stay in the
    # population analysis above.
    pool = u.drop_duplicates(["bot_id", "h_norm"]).copy()
    L.add(
        "gold.pool_turns",
        "distinct (bot, normalised text) USER turns",
        len(pool),
        "turns",
        "candidate pool",
        META,
    )
    cat_pop = pool["category"].value_counts().to_dict()
    non_unknown = {k: v for k, v in cat_pop.items() if k != pl.UNKNOWN}
    unk = min(UNKNOWN_QUOTA, cat_pop.get(pl.UNKNOWN, 0))
    # Prevalence from all turns, capped by supply through the pool.
    traffic = u["category"].value_counts().to_dict()
    weights = {k: traffic[k] for k in non_unknown}
    cat_q = margin_quotas(
        weights,
        TOTAL_SAMPLES - unk,
        min(CATEGORY_FLOOR, (TOTAL_SAMPLES - unk) // max(1, len(weights))),
    )
    if unk:
        cat_q[pl.UNKNOWN] = unk
    cohort_traffic = u[u["cohort"] != REMAINING]["cohort"].value_counts().to_dict()
    remaining_q = REMAINING_QUOTA if (u["cohort"] == REMAINING).any() else 0
    coh_q = margin_quotas(cohort_traffic, TOTAL_SAMPLES - remaining_q, USER_FLOOR)
    if remaining_q:
        coh_q[REMAINING] = remaining_q
    pop = pool.groupby(["category", "cohort"]).size().to_dict()
    joint = joint_quotas(pop, cat_q, coh_q)
    if (
        sum(joint.values()) != TOTAL_SAMPLES
        or sum(cat_q.values()) != TOTAL_SAMPLES
        or sum(coh_q.values()) != TOTAL_SAMPLES
    ):
        raise SystemExit("quota totals are not 300")
    tcat = u["category"].value_counts(normalize=True)
    save(
        "golden_category_quotas",
        pd.DataFrame(
            [
                {
                    "category": k,
                    "quota": v,
                    "traffic_share": float(tcat.get(k, 0)),
                    "proportional_quota": float(tcat.get(k, 0) * TOTAL_SAMPLES),
                }
                for k, v in sorted(cat_q.items(), key=lambda kv: -kv[1])
            ]
        ),
    )
    tcoh = u["cohort"].value_counts(normalize=True)
    save(
        "golden_cohort_quotas",
        pd.DataFrame(
            [
                {
                    "cohort": k,
                    "quota": v,
                    "traffic_share": float(tcoh.get(k, 0)),
                    "proportional_quota": float(tcoh.get(k, 0) * TOTAL_SAMPLES),
                }
                for k, v in sorted(coh_q.items())
            ]
        ),
    )
    cohorts = sorted(coh_q)
    tab = pd.DataFrame(
        [
            {
                "category": cat,
                **{c: joint.get((cat, c), 0) for c in cohorts},
                "total": cat_q[cat],
            }
            for cat in sorted(cat_q, key=lambda k: -cat_q[k])
        ]
    )
    tab = pd.concat(
        [
            tab,
            pd.DataFrame(
                [
                    {
                        "category": "total",
                        **{c: coh_q[c] for c in cohorts},
                        "total": TOTAL_SAMPLES,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    save("golden_joint_allocation", tab)
    L.add(
        "gold.total",
        "golden-set allocation total",
        sum(joint.values()),
        "samples",
        "category and cohort margins both exact",
        META,
    )

    # Candidate selection: round robin over language x class x history strata.
    def rank(mid: str) -> str:
        return hashlib.sha256(f"{seed}|{mid}".encode()).hexdigest()

    pool["_rank"] = pool["message_id"].map(rank)
    pool["_stratum"] = (
        pool["lang"].fillna("-") + "|" + pool["group"] + "|" + pool["history_dep"]
    )
    chosen, shortfalls = [], []
    used_sessions: set[str] = set()
    bot_count: Counter = Counter()
    # The bot cap stops one workflow filling a cohort. It is waived where a cohort has
    # at most two bots, because the cohort quota could not otherwise be met.
    cohort_bots = pool.groupby("cohort")["bot_id"].nunique()
    capped = {c for c in cohort_bots.index if cohort_bots[c] > 2}
    L.add(
        "gold.cohorts_cap_waived",
        "cohorts with at most two bots, bot cap waived",
        len(cohort_bots) - len(capped),
        "cohorts",
        "quota could not otherwise be met",
        SIM,
    )

    def take(cell_pool: pd.DataFrame, k: int) -> int:
        got = 0
        buckets = {s: g.sort_values("_rank") for s, g in cell_pool.groupby("_stratum")}
        iters = {
            s: iter(g.to_dict("records"))
            for s, g in sorted(buckets.items(), key=lambda kv: -len(kv[1]))
        }
        while got < k and iters:
            for s in list(iters):
                if got >= k:
                    break
                for rec in iters[s]:
                    over_cap = (
                        rec["cohort"] in capped and bot_count[rec["bot_id"]] >= BOT_CAP
                    )
                    if rec["session_id"] in used_sessions or over_cap:
                        continue
                    used_sessions.add(rec["session_id"])
                    bot_count[rec["bot_id"]] += 1
                    chosen.append(rec)
                    got += 1
                    break
                else:
                    del iters[s]
        return got

    for (cat, coh), k in sorted(joint.items(), key=lambda kv: kv[1]):
        got = take(pool[(pool["category"] == cat) & (pool["cohort"] == coh)], k)
        if got < k:
            shortfalls.append(
                {"category": cat, "cohort": coh, "requested": k, "achieved": got}
            )
    # Undersupplied quota: same cohort first, then any cohort; logged.
    for sf in shortfalls:
        missing = sf["requested"] - sf["achieved"]
        rest = pool[
            (pool["cohort"] == sf["cohort"])
            & (~pool["message_id"].isin([r["message_id"] for r in chosen]))
        ]
        got = take(rest, missing)
        sf["reallocated_same_cohort"] = got
        if got < missing:
            rest = pool[~pool["message_id"].isin([r["message_id"] for r in chosen])]
            sf["reallocated_any_cohort"] = take(rest, missing - got)
    save(
        "golden_shortfalls",
        pd.DataFrame(
            shortfalls,
            columns=[
                "category",
                "cohort",
                "requested",
                "achieved",
                "reallocated_same_cohort",
                "reallocated_any_cohort",
            ],
        ),
    )
    cand = pd.DataFrame(chosen)
    L.add(
        "gold.candidates",
        "proposed candidates selected",
        len(cand),
        "samples",
        "proposed, not approved",
        SIM,
    )
    L.add(
        "gold.shortfall_cells",
        "cells reallocated for lack of supply",
        len(shortfalls),
        "cells",
        "same-cohort first, logged",
        SIM,
    )
    L.add(
        "gold.candidate_sessions",
        "distinct sessions in proposed candidates",
        cand["session_id"].nunique(),
        "sessions",
        "at most one turn per session",
        SIM,
    )
    L.add(
        "gold.candidate_bots",
        "distinct bots in proposed candidates",
        cand["bot_id"].nunique(),
        "bots",
        f"cap {BOT_CAP} per bot",
        SIM,
    )
    L.add(
        "gold.candidate_max_bot",
        "largest bot count among proposed candidates",
        int(cand["bot_id"].value_counts().iloc[0]),
        "samples",
        "cap applies",
        SIM,
    )
    L.ratio(
        "gold.candidate_later_turn",
        "proposed candidates after the first turn",
        int((cand["turn"] > 0).sum()),
        len(cand),
        "share of candidates",
        "keeps history-dependent cases",
        SIM,
    )
    L.ratio(
        "gold.candidate_fa",
        "proposed candidates labelled Persian",
        int((cand["lang"] == "fa").sum()),
        len(cand),
        "share of candidates",
        "heuristic label",
        SIM,
    )
    keep = [
        "message_id",
        "session_id",
        "bot_id",
        "turn",
        "category",
        "cohort",
        "lang",
        "group",
        "history_dep",
        "context_bucket",
        "reasoning",
        "format_constraint",
    ]
    idonly = cand[keep].copy()
    idonly.insert(0, "status", "proposed_candidate")
    idonly["seed"] = seed
    save("golden_candidates_proposed_idonly", idonly)
    achieved = (
        cand.groupby(["category", "cohort"]).size().rename("achieved").reset_index()
    )
    save("golden_candidates_achieved", achieved)
    got = {
        (r["category"], r["cohort"]): int(r["achieved"]) for _, r in achieved.iterrows()
    }
    L.add(
        "gold.cells_off_quota",
        "category x cohort cells where candidates differ from the quota",
        sum(got.get(c, 0) != joint.get(c, 0) for c in set(got) | set(joint)),
        "cells",
        "0 means candidates match the allocation exactly",
        SIM,
    )

    # Local manifest with text. Nothing after the target turn enters input_messages.
    sessions = set(cand["session_id"])
    conv = msgs[
        msgs["session_id"].isin(sessions)
        & msgs["type"].isin(["USER", "AI", "SYSTEM", "TOOL"])
    ]
    text = {}
    files = sorted(glob.glob(str(RAW / "chat_message-*.parquet")))
    want = set(conv["message_id"])
    for f in files[:1] if smoke else files:
        t = pq.read_table(f, columns=["message_id", "content"]).to_pandas()
        t = t[t["message_id"].isin(want)]
        text.update(zip(t["message_id"], t["content"], strict=True))
    conv = conv.sort_values(["session_id", "order"])
    grouped = {sid: g for sid, g in conv.groupby("session_id")}
    ins = b.set_index("bot_id")["instructions"]
    LOCAL.mkdir(parents=True, exist_ok=True)
    with (LOCAL / "golden_candidates_proposed_LOCAL_ONLY.jsonl").open("w") as fh:
        for rec in chosen:
            g = grouped[rec["session_id"]]
            msgs_ = [
                {"message_id": m, "role": r, "content": text.get(m)}
                for m, r in zip(g["message_id"], g["type"], strict=True)
            ]
            e = build_manifest_entry(
                msgs_,
                rec["message_id"],
                ins.get(rec["bot_id"])
                if isinstance(ins.get(rec["bot_id"]), str)
                else None,
                {
                    "primary_category": rec["category"],
                    "cohort": rec["cohort"],
                    "rag_context_available": (
                        {
                            "state": "chunks_logged",
                            "read_rag_field_only_of_message": rec["next_ai_id"],
                        }
                        if (rec["next_rag_n_chunks"] or 0) > 0
                        else {
                            "state": "none_logged",
                            "read_rag_field_only_of_message": None,
                        }
                    ),
                    "secondary_tags": {
                        k: rec[k]
                        for k in (
                            "lang",
                            "group",
                            "history_dep",
                            "context_bucket",
                            "reasoning",
                            "format_constraint",
                        )
                    },
                },
                {
                    "seed": seed,
                    "stratum": rec["_stratum"],
                    "method": "joint quota, round robin by stratum, seeded hash",
                },
                {
                    "dataset": "poriniki/metis",
                    "revision": REVISION,
                    "session_id": rec["session_id"],
                    "bot_id": rec["bot_id"],
                },
            )
            fh.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")
    entries = [
        json.loads(line)
        for line in (LOCAL / "golden_candidates_proposed_LOCAL_ONLY.jsonl").open()
    ]
    errors = [
        e
        for entry in entries
        for e in manifest_errors(
            entry, grouped[entry["source"]["session_id"]]["message_id"].tolist()
        )
    ]
    L.add(
        "gold.manifest_leak_errors",
        "manifest entries failing the leakage check",
        len(errors),
        "errors",
        "checked against the full session order",
        OBS,
    )
    if errors:
        raise SystemExit(f"manifest leakage: {errors[:3]}")
    (OUT / "golden_manifest_schema.json").write_text(
        json.dumps(
            {
                "schema_version": MANIFEST_SCHEMA_VERSION,
                "fields": list(MANIFEST_FIELDS),
            },
            indent=1,
        )
    )
    return cand


def review_sheets(u: pd.DataFrame, seed: int) -> None:
    """Text only in runs/ (git-ignored); the committed copy holds IDs and labels."""
    parts = [
        g.sample(min(30, len(g)), random_state=seed) for _, g in u.groupby("category")
    ]
    r = pd.concat(parts)[
        ["message_id", "session_id", "category", "secondary", "cohort", "lang", "turn"]
    ]
    save(
        "category_review_idonly",
        r.assign(reviewer_category="", reviewer_confident="", notes=""),
    )
    want = set(r["message_id"])
    texts = {}
    for f in sorted(glob.glob(str(RAW / "chat_message-*.parquet"))):
        t = pq.read_table(f, columns=["message_id", "content"]).to_pandas()
        t = t[t["message_id"].isin(want)]
        texts.update(zip(t["message_id"], t["content"], strict=True))
    r = r.assign(
        text_excerpt=r["message_id"].map(lambda m: (texts.get(m) or "")[:300]),
        reviewer_category="",
        reviewer_confident="",
        notes="",
    )
    r.to_csv(LOCAL / "category_review_with_text_LOCAL_ONLY.csv", index=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seed", type=int, default=20261101)
    a = ap.parse_args()
    t0 = time.time()
    if a.smoke:
        global OUT, LOCAL
        OUT, LOCAL = (
            Path("reports/full_eda/sessions_smoke"),
            Path("runs/full_eda/sessions_smoke"),
        )
    L = Ledger()
    bots, sess, msgs = load(a.smoke)
    b, st, _ = classify(L, bots, sess, msgs)
    print("classified", round(time.time() - t0), flush=True)
    shared_configs(L, b, st, msgs)
    print("shared", round(time.time() - t0), flush=True)
    u = build_turns(st, msgs, b, a.smoke)
    print("labelled", round(time.time() - t0), flush=True)
    top_five(L, u, st, b, msgs)
    categories(L, u)
    print("profiled", round(time.time() - t0), flush=True)
    allocate_and_sample(L, u, b, msgs, a.seed, a.smoke)
    review_sheets(u, a.seed)
    LOCAL.mkdir(parents=True, exist_ok=True)
    st.drop(columns=["ins_fp", "rag_fp"]).to_parquet(
        LOCAL / "sessions_classified_LOCAL_ONLY.parquet", index=False
    )
    u.drop(columns=["skeleton"]).to_parquet(
        LOCAL / "turn_labels_LOCAL_ONLY.parquet", index=False
    )
    manifest = {
        "revision": REVISION,
        "seed": a.seed,
        "smoke": a.smoke,
        "sessions": len(st),
        "messages": len(msgs),
        "user_turns": len(u),
        "processed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_s": round(time.time() - t0),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
    L.write(
        Path("reports/full_eda/tables")
        / ("claims_ledger_smoke_d.csv" if a.smoke else "claims_ledger_d.csv")
    )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
