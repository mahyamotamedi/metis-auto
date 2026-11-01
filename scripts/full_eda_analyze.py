"""Phases 2-6: profile the full dataset and write tables, figures, claims ledger.

    python scripts/full_eda_analyze.py [--smoke]

Inputs: data/derived/full_eda[_smoke]/ (from full_eda_ingest.py and
full_eda_requests.py). Outputs: reports/full_eda/tables/*.csv (feature-only; no
message content, no content hashes, no bot or user IDs), claims_ledger.csv, and
local-only extras under runs/full_eda/. Every number reported in the write-up is a
row of the claims ledger.
"""

from __future__ import annotations

import argparse
import glob
import tomllib
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

from metis_auto.analysis.cache_replay import group_upper_bounds, replay
from metis_auto.analysis.stats import (
    Ledger,
    cluster_bootstrap_ratio,
    describe,
    spearman,
)

RAW = Path("data/full_data/raw/data")
OUT = Path("reports/full_eda")
OBS, META, HEUR, HYP, SIM = (
    "observed fact",
    "metadata-derived",
    "heuristic label",
    "hypothetical reconstruction",
    "simulation",
)


class Ctx:
    def __init__(self, smoke: bool) -> None:
        self.d = Path("data/derived/full_eda" + ("_smoke" if smoke else ""))
        self.tab = OUT / ("tables_smoke" if smoke else "tables")
        self.tab.mkdir(parents=True, exist_ok=True)
        self.led = Ledger()
        self.r = pd.read_parquet(self.d / "requests.parquet")
        self.msgs = pd.concat(
            [
                pd.read_parquet(f)
                for f in sorted(glob.glob(str(self.d / "messages_*.parquet")))
            ],
            ignore_index=True,
        )
        self.bots = pd.read_parquet(self.d / "bots.parquet")
        self.sess = pd.read_parquet(self.d / "sessions.parquet")
        self.smoke = smoke
        self._cached_convention()

    def _cached_convention(self) -> None:
        """Detect models whose records report cached tokens *outside* inputTokens.

        If cachedInputTokens > inputTokens on most billed rows of a model, inputTokens
        is read as the uncached part and effective input = input + cached. The rule
        and its per-model evidence are written to tables/cached_token_convention.csv.
        """
        r = self.r
        b = r[(r["a_billing_state"] == "items") & (r["a_bill_inputTokens"] > 0)]
        share = (
            (b["a_bill_cachedInputTokens"].fillna(0) > b["a_bill_inputTokens"])
            .groupby(b["bot_provider_model"])
            .mean()
        )
        self.additive = set(share[share > 0.5].index)
        r["a_raw_inputTokens"] = r["a_bill_inputTokens"]
        add = r["bot_provider_model"].isin(self.additive)
        r["a_bill_inputTokens"] = r["a_raw_inputTokens"] + np.where(
            add, r["a_bill_cachedInputTokens"].fillna(0), 0
        )
        self.save(
            "cached_token_convention",
            pd.DataFrame(
                {
                    "model": share.index,
                    "share_rows_cached_gt_input": share.values,
                    "cached_reported_separately": [
                        m in self.additive for m in share.index
                    ],
                }
            ),
        )

    def save(self, name: str, df: pd.DataFrame) -> pd.DataFrame:
        df.to_csv(self.tab / f"{name}.csv", index=False)
        return df


def scope(c: Ctx) -> None:
    L, m, r = c.led, c.msgs, c.r
    L.add(
        "scope.sessions",
        "sessions in export",
        c.sess.session_id.nunique(),
        "sessions",
        "all",
        OBS,
    )
    L.add("scope.messages", "messages in export", len(m), "messages", "all", OBS)
    for t, n in m["type"].value_counts().items():
        L.ratio(
            f"scope.msg_type.{t}",
            f"share of messages of type {t}",
            n,
            len(m),
            "share of messages",
            "all",
            OBS,
        )
        L.add(f"scope.msg_n.{t}", f"messages of type {t}", n, "messages", "all", OBS)
    L.add(
        "scope.users",
        "distinct user_id in sessions",
        c.sess.user_id.nunique(),
        "users",
        "all sessions",
        META,
    )
    L.add(
        "scope.bots_in_sessions",
        "distinct bots used by sessions",
        c.sess.bot_id.nunique(),
        "bots",
        "all sessions",
        META,
    )
    L.add("scope.bots_total", "bots in chat_bot", len(c.bots), "bots", "all", OBS)
    L.add(
        "scope.requests",
        "candidate request-response pairs (AI messages)",
        len(r),
        "pairs",
        "all AI messages",
        HEUR,
    )
    ts = m["timestamp"].dropna()
    L.add(
        "scope.msg_first_ts_year",
        "first message year",
        ts.min().year,
        "year",
        "naive timestamp",
        OBS,
    )
    L.add(
        "scope.null_timestamps",
        "messages with null timestamp",
        int(m["timestamp"].isna().sum()),
        "messages",
        "all",
        OBS,
    )
    L.add(
        "scope.dup_message_ids",
        "duplicate message_id",
        int(m["message_id"].duplicated().sum()),
        "messages",
        "all",
        OBS,
    )
    # Sessions per creation year vs message date range (C-01 analogue).
    c.save(
        "monthly_messages",
        m.groupby(m["timestamp"].dt.to_period("M").astype(str))
        .size()
        .rename("messages")
        .reset_index(),
    )
    sy = (
        c.sess.groupby(c.sess["created_at"].dt.to_period("M").astype(str))
        .size()
        .rename("sessions")
        .reset_index()
    )
    c.save("monthly_sessions_by_created_at", sy)
    L.ratio(
        "scope.sessions_created_before_msgs",
        "sessions with created_at earlier than first message month 2026-03",
        (c.sess["created_at"] < "2026-03-01").sum(),
        len(c.sess),
        "share of sessions",
        "all",
        OBS,
    )
    # dialogue_length vs observed
    obs = m.groupby("session_id").size()
    dl = c.sess.set_index("session_id")["dialogue_length"]
    L.ratio(
        "integrity.dialogue_len_match",
        "sessions with dialogue_length == observed messages",
        (dl == obs.reindex(dl.index)).sum(),
        len(dl),
        "share of sessions",
        "all",
        OBS,
    )
    # Pairing quality.
    for fl, n in r["pair_flag"].value_counts().items():
        L.ratio(
            f"pairing.{fl}",
            f"AI messages with pair flag {fl}",
            n,
            len(r),
            "share of AI messages",
            "all",
            HEUR,
        )
    users = m[m["type"] == "USER"]
    paired_users = r["user_message_id"].dropna().nunique()
    L.ratio(
        "pairing.unanswered_user",
        "USER messages not paired with any AI message",
        len(users) - paired_users,
        len(users),
        "share of USER messages",
        "all",
        HEUR,
    )
    L.ratio(
        "pairing.user_multi_answer",
        "USER messages paired with >1 AI message",
        int((r["user_message_id"].value_counts() > 1).sum()),
        paired_users,
        "share of paired USER messages",
        "all",
        HEUR,
    )
    # Session depth.
    ut = users.groupby("session_id").size()
    L.add(
        "session.user_turns_median",
        "median user messages per session",
        float(ut.median()),
        "messages",
        "sessions with >=1 USER",
        OBS,
    )
    L.ratio(
        "session.single_turn",
        "sessions with exactly one USER message",
        (ut == 1).sum(),
        len(ut),
        "share of sessions",
        "sessions with >=1 USER",
        OBS,
    )
    c.save("session_user_turns", pd.DataFrame([describe(ut)]))


def language(c: Ctx) -> None:
    L, r, m = c.led, c.r, c.msgs
    cov = r["u_lang"].notna()
    n = int(cov.sum())
    L.ratio(
        "lang.user_coverage",
        "paired requests with a USER message and text feature",
        n,
        len(r),
        "share of requests",
        "all AI messages",
        HEUR,
    )
    dist = r.loc[cov, "u_lang"].value_counts()
    tab = []
    for lg, k in dist.items():
        v = L.ratio(
            f"lang.user.{lg}",
            f"requests whose USER message is labelled {lg}",
            k,
            n,
            "share of requests",
            "requests with USER text",
            HEUR,
        )
        tab.append({"lang": lg, "requests": k, "request_share": v})
    # Token-weighted: billed input tokens of the paired request.
    b = r[cov & (r["a_billing_state"] == "items")]
    tot = b["a_bill_inputTokens"].sum()
    tw = b.groupby("u_lang")["a_bill_inputTokens"].sum()
    for t in tab:
        t["billed_input_token_share"] = tw.get(t["lang"], 0) / tot if tot else np.nan
        L.add(
            f"lang.tokw.{t['lang']}",
            f"billed-input-token share of requests labelled {t['lang']}",
            t["billed_input_token_share"],
            "share of billed input tokens",
            "requests with billing items",
            HEUR,
            tw.get(t["lang"], 0),
            tot,
        )
    c.save("language_user_requests", pd.DataFrame(tab))
    # Session-level: share of sessions by set of languages among text-labelled messages.
    um = m[
        (m["type"] == "USER")
        & (
            m["lang"].isin(
                ["fa", "en", "fa_en_mixed", "finglish", "arabic_script_other", "other"]
            )
        )
    ]
    langs = um.groupby("session_id")["lang"].agg(lambda s: tuple(sorted(set(s))))
    sess_n = len(langs)
    single = langs.str.len() == 1
    L.ratio(
        "lang.sess_single",
        "sessions with one language label across labelled USER messages",
        single.sum(),
        sess_n,
        "share of sessions",
        "sessions with >=1 labelled USER message",
        HEUR,
    )
    L.ratio(
        "lang.sess_switch",
        "sessions with >1 language label across USER messages",
        (~single).sum(),
        sess_n,
        "share of sessions",
        "sessions with >=1 labelled USER message",
        HEUR,
    )
    # Digit and character-variant shapes in USER text.
    us = m[(m["type"] == "USER") & (m["content_state"] == "text")]
    d_fa, d_ar, d_la = (
        (us["n_digit_fa"] > 0),
        (us["n_digit_ar"] > 0),
        (us["n_digit_latin"] > 0),
    )
    for nm, s in (
        ("persian_digits", d_fa),
        ("arabic_indic_digits", d_ar),
        ("latin_digits", d_la),
    ):
        L.ratio(
            f"text.user_has_{nm}",
            f"USER messages containing {nm}",
            s.sum(),
            len(us),
            "share of USER text messages",
            "USER messages with text",
            OBS,
        )
    L.ratio(
        "text.user_has_zwnj",
        "USER messages containing ZWNJ",
        (us["n_zwnj"] > 0).sum(),
        len(us),
        "share of USER text messages",
        "USER messages with text",
        OBS,
    )
    L.ratio(
        "text.user_has_arabic_variants",
        "USER messages containing Arabic yeh/kaf",
        (us["n_ar_variant"] > 0).sum(),
        len(us),
        "share of USER text messages",
        "USER messages with text",
        OBS,
    )
    # Instruction language by bot and by request.
    bi = c.bots[c.bots["ins_content_state"] == "text"]
    il = bi["ins_lang"].value_counts()
    for lg, k in il.items():
        L.ratio(
            f"lang.instr_bots.{lg}",
            f"bots whose instructions are labelled {lg}",
            k,
            len(bi),
            "share of bots with instruction text",
            "bots with instruction text",
            HEUR,
        )
    ri = r[r["bot_ins_content_state"] == "text"]
    for lg, k in ri["bot_ins_lang"].value_counts().items():
        L.ratio(
            f"lang.instr_reqs.{lg}",
            f"requests whose bot instructions are labelled {lg}",
            k,
            len(ri),
            "share of requests",
            "requests with instruction text",
            HEUR,
        )
    # Answer language vs request language (agreement).
    pair = r[(r["a_lang"].notna()) & (r["u_lang"].isin(["fa", "en"]))]
    ct = pd.crosstab(pair["u_lang"], pair["a_lang"], normalize="index").round(4)
    c.save("lang_request_vs_answer", ct.reset_index())
    # Cross-tab with stratum (provider).
    c.save(
        "lang_by_provider",
        pd.crosstab(
            r["bot_provider_name"].fillna("(unknown)"),
            r["u_lang"].fillna("(no user text)"),
        ).reset_index(),
    )


def tokens_cost(c: Ctx) -> None:
    L, r = c.led, c.r
    n = len(r)
    for st, k in r["a_billing_state"].value_counts(dropna=False).items():
        L.ratio(
            f"bill.state.{st}",
            f"AI messages with billing state {st}",
            k,
            n,
            "share of AI messages",
            "all AI messages",
            OBS,
        )
    b = r[r["a_billing_state"] == "items"]
    tin, tout, tca = (
        b["a_bill_inputTokens"].sum(),
        b["a_bill_outputTokens"].sum(),
        b["a_bill_cachedInputTokens"].sum(),
    )
    cost, inc = b["a_bill_totalCost"].sum(), b["a_bill_totalIncome"].sum()
    cv = "AI messages with billing items"
    L.add(
        "tok.input_total",
        "input tokens, effective (inputTokens + cachedInputTokens for models that report cached separately)",
        tin,
        "tokens",
        cv,
        OBS,
    )
    L.add(
        "tok.input_raw_total",
        "recorded inputTokens field, raw sum",
        b["a_raw_inputTokens"].sum(),
        "tokens",
        cv,
        OBS,
    )
    L.add("tok.output_total", "recorded output tokens (sum)", tout, "tokens", cv, OBS)
    L.add(
        "tok.cached_total", "recorded cached input tokens (sum)", tca, "tokens", cv, OBS
    )
    L.ratio(
        "tok.cached_share",
        "cached share of effective input tokens",
        tca,
        tin,
        "share of input tokens",
        cv,
        OBS,
    )
    L.add(
        "tok.models_cached_separate",
        "models whose cached tokens are reported outside inputTokens",
        len(c.additive),
        "models",
        "models with billed rows",
        OBS,
    )
    L.add(
        "cost.recorded_total",
        "recorded total cost (Metis field totalCost, currency unstated)",
        cost,
        "recorded cost units",
        cv,
        OBS,
    )
    L.add(
        "cost.income_total",
        "recorded total income (totalIncome)",
        inc,
        "recorded cost units",
        cv,
        OBS,
    )
    L.ratio(
        "cost.income_over_cost", "totalIncome / totalCost", inc, cost, "ratio", cv, OBS
    )
    for col, nm in (
        ("a_bill_inputTokens", "input_tokens"),
        ("a_bill_outputTokens", "output_tokens"),
        ("a_bill_totalCost", "cost"),
    ):
        d = describe(b[col])
        for k, v in d.items():
            L.add(
                f"dist.{nm}.{k}",
                f"{nm} per AI message: {k}",
                v,
                "tokens" if "token" in nm else "recorded cost units",
                cv,
                OBS,
            )
    # Cost components from the billing table (input/output/per_call split).
    bt = (
        pd.read_parquet(
            RAW / "derived" / "chat_message_billing.parquet",
            columns=[
                "message_id",
                "totalCost",
                "costBreakdown.input_tokens",
                "costBreakdown.output_tokens",
                "costBreakdown.per_call",
                "costBreakdown.cached_input_tokens",
                "webSearchCalls",
            ],
        )
        if not c.smoke
        else None
    )
    if bt is not None:
        tot = bt["totalCost"].sum()
        for col, nm in (
            ("costBreakdown.input_tokens", "input"),
            ("costBreakdown.output_tokens", "output"),
            ("costBreakdown.cached_input_tokens", "cached_input"),
            ("costBreakdown.per_call", "per_call"),
        ):
            L.ratio(
                f"cost.split.{nm}",
                f"{nm} share of recorded cost",
                bt[col].fillna(0).sum(),
                tot,
                "share of recorded cost",
                "all billing items",
                OBS,
            )
    pcs = (
        pd.read_parquet(
            RAW / "derived" / "chat_message_billing.parquet",
            columns=["message_id", "totalCost", "costBreakdown.per_call"],
        )
        if not c.smoke
        else None
    )
    if pcs is not None:
        pr = pcs[pcs["costBreakdown.per_call"].notna()]
        vc = pr["costBreakdown.per_call"].round(5).value_counts()
        L.add(
            "fee.per_call_rows",
            "billing items charged per call (no token usage)",
            len(pr),
            "items",
            "all billing items",
            OBS,
        )
        L.add(
            "fee.per_call_modal_amount",
            "most common per-call charge (recorded cost units)",
            float(vc.index[0]),
            "recorded cost units",
            "per-call items",
            OBS,
        )
        L.ratio(
            "fee.per_call_modal_share",
            "per-call items at the modal amount",
            vc.iloc[0],
            len(pr),
            "share of per-call items",
            "per-call items",
            OBS,
        )
    rg = b[b["a_n_per_call_only_items"] > 0]
    L.ratio(
        "fee.percall_msgs_with_rag_queries",
        "messages with per-call items that also log RAG queries",
        (rg["a_rag_n_queries"] > 0).sum(),
        len(rg),
        "share of messages with per-call items",
        "billed messages with per-call items",
        OBS,
    )
    L.add(
        "fee.corr_percall_items_rag_queries",
        "Pearson correlation: per-call items vs logged RAG queries (messages with per-call items)",
        float(
            np.corrcoef(rg["a_rag_n_queries"].fillna(0), rg["a_n_per_call_only_items"])[
                0, 1
            ]
        ),
        "correlation",
        f"{len(rg)} messages",
        OBS,
    )
    L.ratio(
        "fee.messages_with_percall",
        "billed messages with >=1 per-call item",
        len(rg),
        len(b),
        "share of billed messages",
        cv,
        OBS,
    )
    if bt is not None:
        full = pd.read_parquet(RAW / "derived" / "chat_message_billing.parquet")
        full = full.merge(
            r[["ai_message_id", "bot_provider_model"]],
            left_on="message_id",
            right_on="ai_message_id",
            how="inner",
        )
        full = full[full["inputTokens"] > 0]
        rows = []
        for mdl, x in full.groupby("bot_provider_model"):
            i, o, ca = (
                x["inputTokens"].sum(),
                x["outputTokens"].sum(),
                x["cachedInputTokens"].fillna(0).sum(),
            )
            rows.append(
                {
                    "model": mdl,
                    "items": len(x),
                    "input_tokens": i,
                    "output_tokens": o,
                    "cached_tokens": ca,
                    "implied_input_per_M": x["costBreakdown.input_tokens"]
                    .fillna(0)
                    .sum()
                    / i
                    * 1e6
                    if i
                    else np.nan,
                    "implied_output_per_M": x["costBreakdown.output_tokens"]
                    .fillna(0)
                    .sum()
                    / o
                    * 1e6
                    if o
                    else np.nan,
                    "implied_cached_per_M": x["costBreakdown.cached_input_tokens"]
                    .fillna(0)
                    .sum()
                    / ca
                    * 1e6
                    if ca
                    else np.nan,
                    "income_over_cost": x["totalIncome"].sum() / x["totalCost"].sum(),
                }
            )
        c.save(
            "implied_unit_rates",
            pd.DataFrame(rows).sort_values("items", ascending=False),
        )
    # Concentration: by bot, session, user.
    for key, nm in (("bot_id", "bot"), ("session_id", "session"), ("user_id", "user")):
        g = b.groupby(key)["a_bill_totalCost"].sum().sort_values(ascending=False)
        for frac in (0.01, 0.10):
            k = max(1, int(np.ceil(frac * len(g))))
            L.ratio(
                f"cost.top{int(frac * 100)}pct_{nm}",
                f"share of recorded cost from top {int(frac * 100)}% of {nm}s",
                g.iloc[:k].sum(),
                g.sum(),
                "share of recorded cost",
                cv,
                OBS,
            )
    # Provider/model usage (bot-level configured label; NOT proven per-message).
    g = r.assign(
        model=r["bot_provider_model"].fillna("(unknown)"),
        prov=r["bot_provider_name"].fillna("(unknown)"),
    ).groupby(["prov", "model"], dropna=False)
    mt = g.agg(
        requests=("ai_message_id", "size"),
        sessions=("session_id", "nunique"),
        bots=("bot_id", "nunique"),
    ).reset_index()
    bb = (
        b.assign(
            model=b["bot_provider_model"].fillna("(unknown)"),
            prov=b["bot_provider_name"].fillna("(unknown)"),
        )
        .groupby(["prov", "model"])
        .agg(
            billed_requests=("ai_message_id", "size"),
            in_tokens=("a_bill_inputTokens", "sum"),
            out_tokens=("a_bill_outputTokens", "sum"),
            cached_tokens=("a_bill_cachedInputTokens", "sum"),
            cost=("a_bill_totalCost", "sum"),
        )
        .reset_index()
    )
    mt = mt.merge(bb, on=["prov", "model"], how="left")
    mt["request_share"] = mt["requests"] / len(r)
    mt["cost_share"] = mt["cost"] / cost
    mt["cached_share"] = mt["cached_tokens"] / mt["in_tokens"]
    mt["cost_per_billed_request"] = mt["cost"] / mt["billed_requests"]
    c.save("model_usage", mt.sort_values("requests", ascending=False))
    wf = r["bot_provider_name"].eq("workflow")
    L.ratio(
        "model.workflow_share",
        "requests whose bot provider is 'workflow'/'default'",
        wf.sum(),
        n,
        "share of requests",
        "all AI messages",
        META,
    )
    L.ratio(
        "model.workflow_billing_empty",
        "workflow requests with empty billing list",
        ((r["a_billing_state"] == "empty_list") & wf).sum(),
        wf.sum(),
        "share of workflow requests",
        "workflow requests",
        OBS,
    )
    L.ratio(
        "model.nonworkflow_billing_items",
        "non-workflow requests with billing items",
        ((r["a_billing_state"] == "items") & ~wf).sum(),
        (~wf).sum(),
        "share of non-workflow requests",
        "non-workflow requests",
        OBS,
    )
    L.add(
        "model.n_labels",
        "distinct provider_model labels on bots used",
        r["bot_provider_model"].nunique(),
        "labels",
        "requests",
        META,
    )
    L.add(
        "model.n_providers",
        "distinct provider_name labels on bots used",
        r["bot_provider_name"].nunique(),
        "labels",
        "requests",
        META,
    )
    # Model switching: bots that changed model cannot be seen (snapshot). Report bot updated_at presence.
    ub = c.bots[c.bots["bot_id"].isin(r["bot_id"].unique())]
    L.ratio(
        "model.bots_updated_after_created",
        "used bots with updated_at later than created_at",
        (ub["updated_at"] > ub["created_at"]).sum(),
        len(ub),
        "share of used bots",
        "bots used in sessions",
        META,
        note="bot configuration is a single snapshot; not proof of what was used per message",
    )
    # Per-provider cached share.
    c.save(
        "cached_by_provider",
        b.groupby(b["bot_provider_name"].fillna("(unknown)"))
        .apply(
            lambda x: pd.Series(
                {
                    "billed_requests": len(x),
                    "in_tokens": x["a_bill_inputTokens"].sum(),
                    "cached_tokens": x["a_bill_cachedInputTokens"].sum(),
                    "cached_share": x["a_bill_cachedInputTokens"].sum()
                    / max(1, x["a_bill_inputTokens"].sum()),
                }
            ),
            include_groups=False,
        )
        .reset_index(),
    )
    # Hours and finish reasons.
    for fr, k in r["a_finish_reason"].value_counts(dropna=False).items():
        L.ratio(
            f"finish.{fr}",
            f"AI messages with finish_reason {fr}",
            k,
            n,
            "share of AI messages",
            "all AI messages",
            OBS,
        )
    L.ratio(
        "ans.blank",
        "AI messages with blank content",
        (r["a_content_state"] == "blank").sum(),
        n,
        "share of AI messages",
        "all AI messages",
        OBS,
    )
    L.ratio(
        "ans.json_like",
        "AI messages whose content parses as JSON",
        r["a_is_json"].fillna(False).astype(bool).sum(),
        n,
        "share of AI messages",
        "all AI messages",
        OBS,
    )


def history_instructions(c: Ctx) -> None:
    L, r = c.led, c.r
    b = r[
        (r["a_billing_state"] == "items")
        & (r["a_n_token_items"] == 1)
        & (r["a_bill_inputTokens"] > 0)
    ].copy()
    b["tb"] = pd.cut(
        b["turn"],
        [-1, 0, 1, 2, 4, 9, 19, 10**6],
        labels=["0", "1", "2", "3-4", "5-9", "10-19", "20+"],
    )
    h = (
        b.groupby("tb", observed=True)
        .agg(
            requests=("turn", "size"),
            median_input_tokens=("a_bill_inputTokens", "median"),
            p90_input_tokens=("a_bill_inputTokens", lambda s: s.quantile(0.9)),
            median_logged_prior_chars=("prior_chars", "median"),
            median_instr_chars=("bot_ins_n_chars", "median"),
        )
        .reset_index()
    )
    c.save("history_growth", h)
    first = b[b["turn"] == 0]
    late = b[b["turn"] >= 20]
    L.add(
        "hist.median_input_turn0",
        "median recorded input tokens at turn 0",
        first["a_bill_inputTokens"].median(),
        "tokens",
        "single-call billed requests, turn 0",
        OBS,
    )
    L.add(
        "hist.median_input_turn20p",
        "median recorded input tokens at turn 20+",
        late["a_bill_inputTokens"].median(),
        "tokens",
        "single-call billed requests, turn 20+",
        OBS,
    )
    L.add(
        "hist.median_prior_chars_turn20p",
        "median logged prior chars at turn 20+",
        late["prior_chars"].median(),
        "characters",
        "single-call billed requests, turn 20+",
        OBS,
    )
    # Is input within-bot correlated with available history? (Spearman, per bot with >=200 requests)
    cors = []
    for _bid, g in b.groupby("bot_id"):
        if len(g) >= 200 and g["prior_chars"].nunique() > 5:
            cors.append(spearman(g["a_bill_inputTokens"], g["prior_chars"]))
    cors = pd.Series(cors).dropna()
    L.add(
        "hist.within_bot_spearman_median",
        "median within-bot Spearman(input tokens, logged prior chars)",
        cors.median(),
        "correlation",
        f"{len(cors)} bots with >=200 single-call billed requests",
        OBS,
    )
    # Turn-0 fits by instruction language (no RAG, no memory, trimmed top 1%): are instructions sent?
    t0 = first[
        (first["a_rag_n_chunks"].fillna(0) == 0)
        & (~first["bot_memory_enabled"].fillna(False))
        & first["bot_ins_n_chars"].notna()
    ]
    t0 = t0[t0["a_bill_inputTokens"] <= t0["a_bill_inputTokens"].quantile(0.99)]
    for lab, g in (
        ("all", t0),
        ("en", t0[t0["bot_ins_lang"] == "en"]),
        ("fa", t0[t0["bot_ins_lang"] == "fa"]),
    ):
        X = np.c_[np.ones(len(g)), g["bot_ins_n_chars"], g["u_n_chars"].fillna(0)]
        y = g["a_bill_inputTokens"].to_numpy(float)
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        r2 = 1 - ((y - X @ coef) ** 2).sum() / ((y - y.mean()) ** 2).sum()
        cv = f"{len(g)} turn-0 single-call billed requests, no RAG, no memory, instruction labelled {lab}"
        L.add(
            f"recon.t0.{lab}.coef_instr",
            f"OLS tokens per instruction character at turn 0 [{lab}]",
            float(coef[1]),
            "tokens per char",
            cv,
            HYP,
            note="~0.3 would mean instructions are sent in full",
        )
        L.add(
            f"tok.chars_per_token_slope.{lab}",
            f"instruction characters per billed input token implied by the turn-0 slope [{lab}]",
            float(1 / coef[1]) if coef[1] > 0 else float("nan"),
            "chars per token",
            cv,
            HYP,
            note="slope-based; intercept absorbs fixed overhead",
        )
        L.add(
            f"recon.t0.{lab}.coef_user",
            f"OLS tokens per user character at turn 0 [{lab}]",
            float(coef[2]),
            "tokens per char",
            cv,
            HYP,
        )
        L.add(
            f"recon.t0.{lab}.intercept",
            f"OLS intercept (tokens) at turn 0 [{lab}]",
            float(coef[0]),
            "tokens",
            cv,
            HYP,
        )
        L.add(
            f"recon.t0.{lab}.r2",
            f"R^2 of turn-0 fit [{lab}]",
            float(r2),
            "R^2",
            cv,
            HYP,
        )
    # Turn-0 fit with RAG, then a rough composition of billed input (HYPOTHETICAL reconstruction).
    t0r = first[
        (first["a_rag_n_chunks"].fillna(0) > 0)
        & (~first["bot_memory_enabled"].fillna(False))
        & first["bot_ins_n_chars"].notna()
    ]
    t0r = t0r[t0r["a_bill_inputTokens"] <= t0r["a_bill_inputTokens"].quantile(0.99)]
    Xr = np.c_[
        np.ones(len(t0r)),
        t0r["bot_ins_n_chars"],
        t0r["u_n_chars"].fillna(0),
        t0r["a_rag_chunk_chars"].fillna(0),
    ]
    yr = t0r["a_bill_inputTokens"].to_numpy(float)
    cr, *_ = np.linalg.lstsq(Xr, yr, rcond=None)
    L.add(
        "recon.t0rag.coef_rag",
        "OLS tokens per retrieved-chunk character at turn 0 with RAG",
        float(cr[3]),
        "tokens per char",
        f"{len(t0r)} turn-0 single-call billed requests with RAG, no memory",
        HYP,
    )
    L.add(
        "recon.t0rag.r2",
        "R^2 of turn-0 RAG fit",
        float(1 - ((yr - Xr @ cr) ** 2).sum() / ((yr - yr.mean()) ** 2).sum()),
        "R^2",
        f"{len(t0r)} requests",
        HYP,
    )
    tot_in = b["a_bill_inputTokens"].sum()
    comp = {
        "instr": float(
            next(x.value for x in L.claims if x.claim_id == "recon.t0.all.coef_instr")
            * b["bot_ins_n_chars"].fillna(0).sum()
        ),
        "rag": float(cr[3] * b["a_rag_chunk_chars"].fillna(0).sum()),
        "user": float(
            next(x.value for x in L.claims if x.claim_id == "recon.t0.all.coef_user")
            * b["u_n_chars"].fillna(0).sum()
        ),
    }
    for k, v in comp.items():
        L.ratio(
            f"comp.{k}_share",
            f"model-attributed share of billed input tokens: {k}",
            v,
            tot_in,
            "share of input tokens",
            "single-call billed requests; fits from turn-0 requests applied to every request",
            HYP,
            note="rough reconstruction; assumes instructions and retrieved chunks are sent on every call",
        )
    L.ratio(
        "comp.remainder_share",
        "billed input tokens not attributed to instructions, RAG or the current user message (history, memory, summaries, formatting, error)",
        tot_in - sum(comp.values()),
        tot_in,
        "share of input tokens",
        "single-call billed requests",
        HYP,
    )
    # Observed growth of input relative to the same bot's turn-0 median (no RAG).
    nr = b[b["a_rag_n_chunks"].fillna(0) == 0]
    base = (
        nr[nr["turn"] == 0]
        .groupby("bot_id")["a_bill_inputTokens"]
        .median()
        .rename("t0")
    )
    nr = nr.join(base, on="bot_id").dropna(subset=["t0"])
    nr["ratio"] = nr["a_bill_inputTokens"] / nr["t0"]
    rows = []
    for lab, g in nr.groupby("tb", observed=True):
        rows.append(
            {
                "turn_bucket": lab,
                "requests": len(g),
                "median_ratio_to_bot_turn0": g["ratio"].median(),
                "p90_ratio": g["ratio"].quantile(0.9),
            }
        )
        L.add(
            f"hist.ratio_to_t0.{lab}",
            f"median billed input / same bot's turn-0 median, turn {lab} (no RAG)",
            float(g["ratio"].median()),
            "ratio",
            f"{len(g)} single-call billed requests",
            OBS,
        )
    c.save("history_ratio_to_turn0", pd.DataFrame(rows))
    exc = (
        nr.loc[nr["turn"] >= 1, "a_bill_inputTokens"] - nr.loc[nr["turn"] >= 1, "t0"]
    ).clip(lower=0)
    L.ratio(
        "hist.excess_over_t0_share",
        "input tokens above the bot's turn-0 median, as share of all input tokens, turn >=1 no-RAG requests",
        exc.sum(),
        nr.loc[nr["turn"] >= 1, "a_bill_inputTokens"].sum(),
        "share of input tokens",
        "single-call billed no-RAG requests at turn >=1",
        HYP,
        note="upper-bound proxy for history/memory/summary tokens; includes longer user messages",
    )
    L.ratio(
        "hist.excess_over_t0_all",
        "same excess as share of ALL billed input tokens (single-call, no-RAG)",
        exc.sum(),
        nr["a_bill_inputTokens"].sum(),
        "share of input tokens",
        "single-call billed no-RAG requests",
        HYP,
    )
    # Instruction presence/size vs billed input at turn 0 without RAG (is the instruction sent?).
    f0 = first[
        (first["a_rag_n_chunks"].fillna(0) == 0)
        & (~first["bot_memory_enabled"].fillna(False))
    ]
    L.add(
        "recon.turn0_spearman_instr",
        "Spearman(instruction chars, billed input tokens) at turn 0, no RAG, no memory",
        spearman(f0["bot_ins_n_chars"], f0["a_bill_inputTokens"]),
        "correlation",
        f"{len(f0)} requests",
        OBS,
    )
    L.add(
        "recon.turn0_spearman_user",
        "Spearman(user chars, billed input tokens) at turn 0, no RAG, no memory",
        spearman(f0["u_n_chars"], f0["a_bill_inputTokens"]),
        "correlation",
        f"{len(f0)} requests",
        OBS,
    )
    L.ratio(
        "recon.turn0_input_below_instr_chars",
        "turn-0 no-RAG requests whose billed input tokens are below the bot's instruction character count / 6",
        (f0["a_bill_inputTokens"] < f0["bot_ins_n_chars"] / 6).sum(),
        len(f0),
        "share of requests",
        "turn 0, no RAG, no memory, billed",
        HYP,
        note="a screen for 'instructions not fully sent'; chars/6 is a deliberately low tokens-per-char bound",
    )
    # Chars per token among turn-0 requests where instruction dominates.
    f1 = f0[(f0["bot_ins_n_chars"] > 500)]
    cpt = (f1["bot_ins_n_chars"] + f1["u_n_chars"].fillna(0)) / f1["a_bill_inputTokens"]
    for lg in ("fa", "en"):
        s = cpt[f1["bot_ins_lang"] == lg]
        L.add(
            f"tok.chars_per_input_token_{lg}",
            f"median (instruction+user chars)/billed input tokens, instruction labelled {lg}",
            s.median(),
            "chars per token",
            f"{len(s)} turn-0 requests",
            HYP,
            note="upper-bound-biased: other components excluded",
        )
    # Instruction groups.
    bi = (
        r.groupby("bot_id")
        .agg(
            ins_hash=("bot_ins_h_norm", "first"),
            chars=("bot_ins_n_chars", "first"),
            requests=("ai_message_id", "size"),
        )
        .reset_index()
    )
    bi = bi[bi["chars"] > 0]
    gsz = (
        bi.groupby("ins_hash")
        .agg(
            bots=("bot_id", "size"),
            requests=("requests", "sum"),
            chars=("chars", "first"),
        )
        .reset_index()
    )
    L.add(
        "instr.n_bots_with_text",
        "used bots with instruction text",
        len(bi),
        "bots",
        "bots with requests",
        META,
    )
    L.add(
        "instr.n_groups",
        "distinct normalised instruction texts among used bots",
        len(gsz),
        "groups",
        "bots with instruction text",
        META,
    )
    L.ratio(
        "instr.bots_in_shared_group",
        "used bots whose instruction text is shared with another bot",
        gsz.loc[gsz["bots"] > 1, "bots"].sum(),
        len(bi),
        "share of bots",
        "bots with instruction text",
        META,
    )
    ri = r[r["bot_ins_n_chars"] > 0]
    d = describe(ri["bot_ins_n_chars"])
    for k, v in d.items():
        L.add(
            f"instr.chars.{k}",
            f"instruction characters per request: {k}",
            v,
            "characters",
            "requests whose bot has instruction text",
            META,
        )
    top = gsz.sort_values("requests", ascending=False)
    top["rank"] = range(1, len(top) + 1)
    top["request_share"] = top["requests"] / top["requests"].sum()
    c.save(
        "instruction_groups_top",
        top.head(25)[["rank", "bots", "requests", "request_share", "chars"]],
    )
    L.add(
        "instr.top10_group_request_share",
        "request share of the 10 largest instruction groups",
        float(top["request_share"].head(10).sum()),
        "share of requests",
        "requests with instruction text",
        META,
    )
    # Repeated transmission opportunity: same instruction text on consecutive requests in a session.
    L.ratio(
        "instr.hist_chars_vs_instr",
        "logged prior-history chars summed / (history + instruction + user chars summed)",
        r["prior_chars"].sum(),
        (
            r["prior_chars"] + r["bot_ins_n_chars"].fillna(0) + r["u_n_chars"].fillna(0)
        ).sum(),
        "share of logged chars",
        "all requests",
        HYP,
        note="hypothetical full-resend scenario; billing shows history is not fully resent",
    )


def rag_att(c: Ctx) -> None:
    L, r = c.led, c.r
    n = len(r)
    L.ratio(
        "rag.requests_with_chunks",
        "AI messages with >=1 logged retrieved chunk",
        (r["a_rag_n_chunks"] > 0).sum(),
        n,
        "share of AI messages",
        "all AI messages",
        OBS,
    )
    for st, k in r["a_rag_state"].value_counts(dropna=False).items():
        L.ratio(
            f"rag.state.{st}",
            f"AI messages with rag column state {st}",
            k,
            n,
            "share of AI messages",
            "all AI messages",
            OBS,
        )
    cfg = r["bot_rag_top_k"].notna() | (r["bot_n_corpora"] > 0)
    L.ratio(
        "rag.bot_configured",
        "requests whose bot has rag_top_k or corpus ids configured",
        cfg.sum(),
        n,
        "share of requests",
        "all AI messages",
        META,
    )
    L.ratio(
        "rag.configured_with_chunks",
        "RAG-configured requests with >=1 logged chunk",
        (cfg & (r["a_rag_n_chunks"] > 0)).sum(),
        cfg.sum(),
        "share of RAG-configured requests",
        "RAG-configured requests",
        OBS,
    )
    L.ratio(
        "rag.unconfigured_with_chunks",
        "requests with chunks although the bot has no RAG config",
        (~cfg & (r["a_rag_n_chunks"] > 0)).sum(),
        (~cfg).sum(),
        "share of non-configured requests",
        "requests without RAG config",
        OBS,
    )
    rr = r[r["a_rag_n_chunks"] > 0]
    for k, v in describe(rr["a_rag_n_chunks"]).items():
        L.add(
            f"rag.chunks_per_req.{k}",
            f"retrieved chunks per RAG request: {k}",
            v,
            "chunks",
            "requests with chunks",
            OBS,
        )
    for k, v in describe(rr["a_rag_chunk_chars"]).items():
        L.add(
            f"rag.chars_per_req.{k}",
            f"retrieved chunk characters per RAG request: {k}",
            v,
            "characters",
            "requests with chunks",
            OBS,
        )
    # Chunk-level table.
    ch = pd.concat(
        [
            pd.read_parquet(f)
            for f in sorted(glob.glob(str(c.d / "chunks" / "*.parquet")))
        ],
        ignore_index=True,
    )
    L.add("rag.chunk_rows", "logged chunk rows", len(ch), "chunks", "all", OBS)
    cl = ch["n_chars"]
    for k, v in describe(cl).items():
        L.add(
            f"rag.chunk_chars.{k}",
            f"chunk characters: {k}",
            v,
            "characters",
            "all chunk rows",
            OBS,
        )
    vc = cl.value_counts()
    L.add(
        "rag.chunk_mode_len",
        "most frequent chunk length (characters)",
        float(vc.index[0]),
        "characters",
        "all chunk rows",
        OBS,
    )
    L.ratio(
        "rag.chunk_at_mode_len",
        "chunk rows at the most frequent length",
        vc.iloc[0],
        len(cl),
        "share of chunk rows",
        "all chunk rows",
        OBS,
    )
    L.ratio(
        "rag.chunk_dup_rows",
        "chunk rows whose text hash appeared in an earlier chunk row",
        ch["h_exact"].duplicated().sum() - ch["h_exact"].isna().sum() * 0,
        ch["h_exact"].notna().sum(),
        "share of chunk rows",
        "chunk rows with text",
        OBS,
    )
    L.add(
        "rag.distinct_chunks",
        "distinct chunk texts",
        ch["h_exact"].nunique(),
        "chunks",
        "chunk rows with text",
        OBS,
    )
    # Same chunk text reused across consecutive requests of the same session.
    cm = ch.merge(
        r[["ai_message_id", "session_id", "a_order"]],
        left_on="message_id",
        right_on="ai_message_id",
        how="inner",
    )
    cm = cm.sort_values(["session_id", "a_order"])
    cm["seen_in_session"] = cm.duplicated(["session_id", "h_exact"])
    L.ratio(
        "rag.chunk_repeat_in_session",
        "chunk rows repeating a chunk already supplied earlier in the same session",
        cm["seen_in_session"].sum(),
        len(cm),
        "share of chunk rows",
        "chunk rows joined to requests",
        OBS,
    )
    c.save(
        "rag_chunk_top_lengths",
        vc.head(10).rename("rows").reset_index().rename(columns={"n_chars": "chars"}),
    )
    # Attachments, tools, actions, input widgets.
    L.ratio(
        "att.requests_user_attachments",
        "paired USER messages with attachments",
        (r["u_att_n"].fillna(0) > 0).sum(),
        r["u_att_n"].notna().sum(),
        "share of paired USER messages",
        "requests with a paired USER message",
        OBS,
    )
    am = c.msgs[c.msgs["att_n"] > 0]
    types: dict[str, int] = {}
    for s in am["att_types"]:
        for part in s.split(","):
            if part:
                k, v = part.rsplit(":", 1)
                types[k] = types.get(k, 0) + int(v)
    for k, v in types.items():
        L.add(
            f"att.type.{k}",
            f"attachment items of type {k}",
            v,
            "attachment items",
            "all messages",
            OBS,
        )
    L.add(
        "att.messages_with_attachments",
        "messages with >=1 attachment item",
        len(am),
        "messages",
        "all messages",
        OBS,
    )
    L.ratio(
        "tool.requests",
        "AI messages with >=1 logged tool call",
        (r["a_tool_n_calls"] > 0).sum(),
        len(r),
        "share of AI messages",
        "all AI messages",
        OBS,
    )
    L.add(
        "tool.n_messages_type_TOOL",
        "messages of role TOOL",
        int((c.msgs["type"] == "TOOL").sum()),
        "messages",
        "all",
        OBS,
    )
    L.ratio(
        "input.requests_with_items",
        "AI messages with an input (widget) object",
        (r["a_input_n_items"] > 0).sum(),
        len(r),
        "share of AI messages",
        "all AI messages",
        OBS,
    )
    L.ratio(
        "actions.requests",
        "AI messages with moderation/action records",
        (r["a_action_types"].fillna("") != "").sum(),
        len(r),
        "share of AI messages",
        "all AI messages",
        OBS,
    )
    L.add(
        "cit.requests_with_citations",
        "AI messages with >=1 citation",
        int((r["a_citation_n"] > 0).sum()),
        "messages",
        "all AI messages",
        OBS,
    )
    L.ratio(
        "sys.system_messages",
        "SYSTEM messages (share of all messages)",
        (c.msgs["type"] == "SYSTEM").sum(),
        len(c.msgs),
        "share of messages",
        "all",
        OBS,
    )
    L.add(
        "bot.memory_enabled_requests",
        "requests whose bot has memory_enabled",
        int(r["bot_memory_enabled"].fillna(False).sum()),
        "requests",
        "all",
        META,
    )
    L.add(
        "bot.summarizer_requests",
        "requests whose bot has summarizer_mode AI_SUMMARIZE",
        int((r["bot_summarizer_mode"] == "AI_SUMMARIZE").sum()),
        "requests",
        "all",
        META,
    )
    L.add(
        "bot.google_search_requests",
        "requests whose bot has google_search_enabled",
        int(r["bot_google_search_enabled"].fillna(False).sum()),
        "requests",
        "all",
        META,
    )
    L.add(
        "bot.functions_requests",
        "requests whose bot defines functions",
        int((r["bot_n_functions"] > 0).sum()),
        "requests",
        "all",
        META,
    )


def exact_cache(c: Ctx) -> None:
    L, r = c.led, c.r
    n_all = len(r)
    r = r.copy()
    r["t_arrive"] = r["u_timestamp"]
    r["t_done"] = r["a_timestamp"]
    elig_steps = [
        ("has_user_text", r["u_content_state"] == "text"),
        (
            "answer_text_and_STOP",
            (r["a_content_state"] == "text") & (r["a_finish_reason"] == "STOP"),
        ),
        ("no_attachments", r["u_att_n"].fillna(0) == 0),
        ("no_tools", r["a_tool_n_calls"].fillna(0) == 0),
        ("no_actions", r["a_action_types"].fillna("") == ""),
        (
            "timestamps_valid",
            r["t_arrive"].notna()
            & r["t_done"].notna()
            & (r["t_done"] >= r["t_arrive"]),
        ),
    ]
    el = pd.Series(True, index=r.index)
    funnel = [{"step": "all AI messages", "requests": n_all}]
    for nm, s in elig_steps:
        el &= s
        funnel.append({"step": nm, "requests": int(el.sum())})
        L.ratio(
            f"cache.elig.{nm}",
            f"requests still eligible after: {nm}",
            el.sum(),
            n_all,
            "share of all AI messages",
            "all AI messages",
            HEUR,
        )
    r["eligible"] = el
    e = r[el].copy()
    # Key variants (candidate keys): which components the key includes.
    e["k_text"] = e["u_h_norm"]
    e["k_bot_text"] = e["bot_id"] + "|" + e["u_h_norm"]
    e["k_bot_hist"] = (
        e["bot_id"] + "|" + e["hist_hash"]
    )  # hist_hash at AI includes this user message and all earlier turns
    e["k_bot_hist_rag"] = e["k_bot_hist"] + "|" + e["a_rag_set_hash"].fillna("-")
    variants = {
        "text_only": "k_text",
        "bot+text": "k_bot_text",
        "bot+full_history": "k_bot_hist",
        "bot+full_history+rag_set": "k_bot_hist_rag",
    }
    scopes = {"global": None, "same_user_id": "user_id", "session": "session_id"}
    rows = []
    billed = e["a_billing_state"] == "items"
    e["tok_in"] = e["a_bill_inputTokens"].where(billed)
    e["tok_out"] = e["a_bill_outputTokens"].where(billed)
    e["cost"] = e["a_bill_totalCost"].where(billed)
    tot_cost, tot_in = (
        r.loc[r["a_billing_state"] == "items", "a_bill_totalCost"].sum(),
        r.loc[r["a_billing_state"] == "items", "a_bill_inputTokens"].sum(),
    )
    for vn, vc in variants.items():
        for sn, sc in scopes.items():
            ek = e[vc] if sc is None else e[vc] + "|" + e[sc].astype(str)
            tmp = e.assign(key=ek)
            ub = group_upper_bounds(tmp["key"])
            hits = replay(tmp[["key", "t_arrive", "t_done"]])
            row = {
                "variant": vn,
                "scope": sn,
                "eligible_requests": len(tmp),
                "dup_group_occurrences": ub["occurrences_in_dup_groups"],
                "reusable_upper_bound": ub["reusable_upper_bound"],
                "pairs": ub["pairs"],
                "candidate_hits_cold": int(hits.sum()),
            }
            for ttl_name, ttl in (
                ("1h", pd.Timedelta(hours=1)),
                ("24h", pd.Timedelta(hours=24)),
                ("7d", pd.Timedelta(days=7)),
            ):
                row[f"candidate_hits_ttl_{ttl_name}"] = int(
                    replay(tmp[["key", "t_arrive", "t_done"]], ttl=ttl).sum()
                )
            row["candidate_hits_cap10k"] = int(
                replay(tmp[["key", "t_arrive", "t_done"]], capacity=10000).sum()
            )
            h = hits.to_numpy()
            row["avoided_cost_candidate"] = float(
                tmp["cost"].fillna(0).to_numpy()[h].sum()
            )
            row["avoided_input_tokens_candidate"] = float(
                tmp["tok_in"].fillna(0).to_numpy()[h].sum()
            )
            row["avoided_output_tokens_candidate"] = float(
                tmp["tok_out"].fillna(0).to_numpy()[h].sum()
            )
            row["hit_rate_all_requests"] = row["candidate_hits_cold"] / n_all
            row["hit_rate_eligible"] = row["candidate_hits_cold"] / len(tmp)
            row["avoided_cost_share"] = row["avoided_cost_candidate"] / tot_cost
            row["avoided_input_token_share"] = (
                row["avoided_input_tokens_candidate"] / tot_in
            )
            if (vn, sn) in {
                ("bot+text", "global"),
                ("bot+full_history", "session"),
                ("bot+full_history", "global"),
                ("text_only", "global"),
                ("bot+text", "session"),
            }:
                est, lo, hi = cluster_bootstrap_ratio(
                    h.astype(float),
                    np.ones(len(tmp)),
                    tmp["session_id"].to_numpy(),
                    n_boot=200,
                )
                row["hit_rate_eligible_ci_lo"], row["hit_rate_eligible_ci_hi"] = lo, hi
            rows.append(row)
            cid = f"cache.{vn}.{sn}"
            L.ratio(
                f"{cid}.hit_all",
                f"candidate exact hits / all AI messages [{vn}, scope {sn}, cold, no TTL]",
                row["candidate_hits_cold"],
                n_all,
                "share of all AI messages",
                "chronological replay over eligible requests",
                SIM,
                ci=(
                    row.get("hit_rate_eligible_ci_lo", np.nan) * len(tmp) / n_all,
                    row.get("hit_rate_eligible_ci_hi", np.nan) * len(tmp) / n_all,
                )
                if "hit_rate_eligible_ci_lo" in row
                else None,
                note="candidate hits; validity unchecked; completion time = logged AI timestamp (assumption)",
            )
            L.ratio(
                f"{cid}.hit_elig",
                f"candidate exact hits / eligible requests [{vn}, scope {sn}]",
                row["candidate_hits_cold"],
                len(tmp),
                "share of eligible requests",
                "eligible requests",
                SIM,
            )
            L.ratio(
                f"{cid}.avoided_cost",
                f"recorded cost of candidate-hit requests / total recorded cost [{vn}, scope {sn}]",
                row["avoided_cost_candidate"],
                tot_cost,
                "share of recorded cost",
                "billed AI messages",
                SIM,
                note="as-logged cost of the avoided calls; excludes lookup/storage overhead",
            )
            L.add(
                f"{cid}.reusable_ub",
                f"n-1 upper bound over duplicate groups [{vn}, scope {sn}]",
                row["reusable_upper_bound"],
                "requests",
                "eligible requests",
                HEUR,
            )
            L.add(
                f"{cid}.pairs",
                f"pairs in duplicate groups [{vn}, scope {sn}] (not a hit count)",
                row["pairs"],
                "pairs",
                "eligible requests",
                HEUR,
            )
    res = pd.DataFrame(rows)
    c.save("exact_cache_variants", res)
    c.save("exact_cache_funnel", pd.DataFrame(funnel))
    # Cross-user: do keys occur under more than one user_id / bot? (shared-scope evidence)
    g = e.groupby("k_bot_text").agg(
        n=("session_id", "size"),
        sessions=("session_id", "nunique"),
        users=("user_id", "nunique"),
    )
    dup = g[g["n"] > 1]
    L.ratio(
        "cache.bot_text_dup_cross_session",
        "duplicate (bot,text) groups spanning >1 session",
        (dup["sessions"] > 1).sum(),
        len(dup),
        "share of duplicate groups",
        "eligible requests",
        HEUR,
    )
    # first-turn popularity (curated cache H-8).
    f = e[e["turn"] == 0]
    gf = f.groupby("k_bot_text").size().sort_values(ascending=False)
    L.ratio(
        "cache.firstturn_top100_share",
        "share of eligible first-turn requests covered by the 100 most frequent (bot,text) keys",
        gf.head(100).sum(),
        gf.sum(),
        "share of first-turn requests",
        "eligible turn-0 requests",
        HEUR,
    )
    L.ratio(
        "cache.firstturn_repeat_share",
        "eligible first-turn requests whose (bot,text) key occurs >1 time",
        gf[gf > 1].sum(),
        gf.sum(),
        "share of first-turn requests",
        "eligible turn-0 requests",
        HEUR,
    )
    # Reuse interval for candidate hits (bot+text, global).
    tmp = e.assign(key=e["k_bot_text"])
    hits = replay(tmp[["key", "t_arrive", "t_done"]])
    first_seen = tmp.groupby("key")["t_done"].transform("min")
    gap = (tmp.loc[hits, "t_arrive"] - first_seen[hits]).dt.total_seconds() / 3600
    for k, v in describe(gap).items():
        L.add(
            f"cache.reuse_gap_h.{k}",
            f"hours between first answer and candidate hit [bot+text, global]: {k}",
            v,
            "hours",
            "candidate hits",
            SIM,
        )
    # Personalisation/time sensitivity proxies on hit rows.
    L.ratio(
        "cache.hits_memory_bot",
        "candidate hits [bot+text, global] on bots with memory enabled",
        hits[tmp["bot_memory_enabled"].fillna(False).to_numpy()].sum(),
        hits.sum(),
        "share of candidate hits",
        "candidate hits",
        SIM,
    )
    L.ratio(
        "cache.hits_rag_bot",
        "candidate hits [bot+text, global] with logged RAG chunks",
        hits[(tmp["a_rag_n_chunks"] > 0).to_numpy()].sum(),
        hits.sum(),
        "share of candidate hits",
        "candidate hits",
        SIM,
    )
    L.ratio(
        "cache.hits_first_turn",
        "candidate hits [bot+text, global] at turn 0",
        hits[(tmp["turn"] == 0).to_numpy()].sum(),
        hits.sum(),
        "share of candidate hits",
        "candidate hits",
        SIM,
    )
    # Provider prefix-cache evidence: observed cached input tokens.
    # (reported in tokens_cost)


def _price_table() -> pd.DataFrame:
    d = tomllib.loads(Path("config/reference/prices-metis-2026-10-18.toml").read_text())
    return pd.DataFrame(d["prices"])


def reprice(b: pd.DataFrame, ref: str, pt: pd.DataFrame) -> pd.Series:
    """Per-request cost of the recorded tokens at catalogue price ``ref`` (USD, decimal)."""
    rows = pt[pt["price_ref"] == ref]
    cost = pd.Series(0.0, index=b.index)
    inp = b["a_bill_inputTokens"].fillna(0)
    cached = np.minimum(b["a_bill_cachedInputTokens"].fillna(0), inp)
    out = b["a_bill_outputTokens"].fillna(0)
    for _, p in rows.iterrows():
        lo = (
            float(p["min_input_tokens"]) if pd.notna(p.get("min_input_tokens")) else 0.0
        )
        hi = (
            float(p["max_input_tokens"])
            if pd.notna(p.get("max_input_tokens"))
            else np.inf
        )
        m = (inp >= lo) & (inp <= hi)
        cost[m] = (
            (inp - cached)[m] * float(p["input"])
            + cached[m] * float(p["cached_input"])
            + out[m] * float(p["output"])
        ) / 1e6
    return cost


def routing_finance(c: Ctx) -> None:
    L, r = c.led, c.r
    pt = _price_table()
    b = r[(r["a_billing_state"] == "items") & (r["a_n_token_items"] >= 1)].copy()
    cv = "billed AI messages with >=1 token item"
    rec = b["a_bill_totalCost"].sum()
    L.add(
        "fin.recorded_cost",
        "recorded totalCost over billed token requests",
        rec,
        "recorded cost units",
        cv,
        OBS,
    )
    rows = []
    prem = reprice(b, "metis-gpt-5.4", pt).sum()
    for ref in sorted(pt["price_ref"].unique()):
        rp = reprice(b, ref, pt)
        rows.append(
            {
                "price_ref": ref,
                "repriced_cost": rp.sum(),
                "ratio_to_premium_gpt_5_4": rp.sum() / prem,
            }
        )
        L.ratio(
            f"fin.reprice_vs_premium.{ref}",
            f"cost at {ref} / cost at premium baseline gpt-5.4 (same tokens, price file basis)",
            rp.sum(),
            prem,
            "ratio",
            cv,
            SIM,
            note="tokens assumed model-independent; recorded costs are on a different basis (see implied_unit_rates)",
        )
        L.add(
            f"fin.reprice.{ref}",
            f"cost of all recorded tokens at {ref} prices (Metis price file 2026-10-18)",
            rp.sum(),
            "USD (price-file basis)",
            cv,
            SIM,
            note="same token counts assumed for every model (tokenizers differ); quality, capability and availability not checked",
        )
    c.save("repricing_all_traffic", pd.DataFrame(rows))
    # Rule-based routing-proxy: requests a transparent rule would call 'simple'.
    ru = b["u_n_chars"].fillna(0)
    simple = (
        (ru <= 200)
        & (b["a_rag_n_chunks"].fillna(0) == 0)
        & (b["u_att_n"].fillna(0) == 0)
        & (b["a_tool_n_calls"].fillna(0) == 0)
        & (b["a_input_n_items"].fillna(0) == 0)
        & (~b["a_is_json"].fillna(False).astype(bool))
    )
    L.ratio(
        "route.simple_rule_share",
        "billed requests matching the 'short, no RAG, no attachments, no tools, no JSON' rule",
        simple.sum(),
        len(b),
        "share of billed requests",
        cv,
        HEUR,
        note="a screen, not a difficulty label",
    )
    L.ratio(
        "route.simple_rule_cost_share",
        "recorded cost share of requests matching that rule",
        b.loc[simple, "a_bill_totalCost"].sum(),
        rec,
        "share of recorded cost",
        cv,
        HEUR,
    )
    # Same-basis routing simulation: recorded-basis implied rates of the cheapest high-volume model.
    ir = (
        pd.read_csv(c.tab / "implied_unit_rates.csv")
        if (c.tab / "implied_unit_rates.csv").exists()
        else None
    )
    if ir is not None:
        big = ir[ir["items"] >= 10000].copy()
        big["blend"] = (
            big["implied_input_per_M"] * 0.9 + big["implied_output_per_M"] * 0.1
        )  # nominal 90/10 mix, only to rank models
        tgt = big.sort_values("blend").iloc[0]
        inp = b["a_bill_inputTokens"].fillna(0)
        ca = np.minimum(b["a_bill_cachedInputTokens"].fillna(0), inp)
        new = (
            (inp - ca) * tgt["implied_input_per_M"]
            + ca
            * (
                tgt["implied_cached_per_M"]
                if pd.notna(tgt["implied_cached_per_M"])
                else tgt["implied_input_per_M"]
            )
            + b["a_bill_outputTokens"].fillna(0) * tgt["implied_output_per_M"]
        ) / 1e6
        token_cost = (
            b["a_bill_totalCost"] - 0.002 * b["a_n_per_call_only_items"].fillna(0)
        ).clip(lower=0)
        save = (token_cost - new).clip(lower=0)  # never route to a pricier model
        for nm, mask in (
            ("simple_rule", simple),
            ("all_billed_requests", pd.Series(True, index=b.index)),
        ):
            L.ratio(
                f"route.sim_save.{nm}",
                f"simulated saving if {nm} requests were served at the recorded-basis rates of {tgt['model']}, share of recorded cost",
                save[mask].sum(),
                rec,
                "share of recorded cost",
                cv,
                SIM,
                note="hypothetical upper bound: assumes acceptable quality, same tokens, no capacity or capability limits; excludes per-call fees",
            )
        L.add(
            "route.sim_target_model",
            "cheapest high-volume model by recorded-basis rate used as simulation target (index into model_usage)",
            float(tgt["items"]),
            "billed items",
            f"model {tgt['model']}",
            SIM,
        )
        L.ratio(
            "route.simple_rule_already_on_target",
            "rule-matching requests already on the target model",
            (b.loc[simple, "bot_provider_model"] == tgt["model"]).sum(),
            simple.sum(),
            "share of rule-matching requests",
            cv,
            OBS,
        )
    # Spend by language and history depth (routing context).
    c.save(
        "cost_by_turn_bucket",
        b.assign(
            tb=pd.cut(
                b["turn"], [-1, 0, 2, 9, 10**6], labels=["0", "1-2", "3-9", "10+"]
            )
        )
        .groupby("tb", observed=True)
        .agg(
            requests=("turn", "size"),
            cost=("a_bill_totalCost", "sum"),
            in_tokens=("a_bill_inputTokens", "sum"),
        )
        .reset_index(),
    )
    # Output-limit hits as an escalation signal source.
    L.ratio(
        "route.finish_length",
        "AI messages ending with finish_reason LENGTH",
        (r["a_finish_reason"] == "LENGTH").sum(),
        len(r),
        "share of AI messages",
        "all AI messages",
        OBS,
    )
    L.ratio(
        "route.json_answers",
        "AI messages whose content parses as JSON (structured-output proxy)",
        r["a_is_json"].fillna(False).astype(bool).sum(),
        len(r),
        "share of AI messages",
        "all AI messages",
        HEUR,
    )


def reduction(c: Ctx) -> None:
    L, r = c.led, c.r
    b = r[
        (r["a_billing_state"] == "items")
        & (r["a_n_token_items"] == 1)
        & (r["a_bill_inputTokens"] > 0)
    ]
    tin = b["a_bill_inputTokens"].sum()
    # Share of tokens in requests with large inputs (where reduction matters).
    for th in (2000, 8000, 32000):
        s = b["a_bill_inputTokens"] > th
        L.ratio(
            f"red.input_over_{th}.reqs",
            f"single-call billed requests with input > {th} tokens",
            s.sum(),
            len(b),
            "share of requests",
            "single-call billed requests",
            OBS,
        )
        L.ratio(
            f"red.input_over_{th}.tokens",
            f"share of input tokens in requests with input > {th}",
            b.loc[s, "a_bill_inputTokens"].sum(),
            tin,
            "share of input tokens",
            "single-call billed requests",
            OBS,
        )
    # Scenario table: shorten the instruction share by x% (uses global OLS attribution).
    # Cached input already realised.
    L.ratio(
        "red.cached_share_single",
        "cached share of input tokens (single-call billed requests)",
        b["a_bill_cachedInputTokens"].sum(),
        tin,
        "share of input tokens",
        "single-call billed requests",
        OBS,
    )
    # Provider prefix caching: instruction-heavy requests (>=1500 chars) and their cached share.
    h = b[b["bot_ins_n_chars"] >= 1500]
    L.ratio(
        "red.cached_share_instr_heavy",
        "cached share of input tokens where bot instruction >= 1500 chars",
        h["a_bill_cachedInputTokens"].sum(),
        h["a_bill_inputTokens"].sum(),
        "share of input tokens",
        "single-call billed, instruction >= 1500 chars",
        OBS,
    )
    # Chunk duplicates inside one message.
    ch = pd.concat(
        [
            pd.read_parquet(f)
            for f in sorted(glob.glob(str(c.d / "chunks" / "*.parquet")))
        ],
        ignore_index=True,
    )
    ch = ch.dropna(subset=["h_exact"])
    dup_in_msg = ch.duplicated(["message_id", "h_exact"])
    L.ratio(
        "red.rag_dup_within_message",
        "chunk rows duplicating another chunk in the same message",
        dup_in_msg.sum(),
        len(ch),
        "share of chunk rows",
        "chunk rows with text",
        OBS,
    )
    L.ratio(
        "red.rag_dup_chars",
        "characters in within-message duplicate chunks / all chunk characters",
        ch.loc[dup_in_msg, "n_chars"].sum(),
        ch["n_chars"].sum(),
        "share of chunk characters",
        "chunk rows with text",
        OBS,
    )
    # Chunk cap: relevancy distribution.
    L.add(
        "red.rag_relevancy_median",
        "median chunk relevancy score",
        float(ch["relevancy"].median()),
        "score (unit unspecified)",
        "chunk rows",
        OBS,
    )
    # Summaries and memory: bots.
    L.ratio(
        "red.summarizer_bot_requests",
        "requests on bots with AI_SUMMARIZE",
        (r["bot_summarizer_mode"] == "AI_SUMMARIZE").sum(),
        len(r),
        "share of requests",
        "all",
        META,
    )
    # Multi-call messages (summary/rewrites): extra billing items per AI message.
    mc = r[r["a_n_token_items"] > 1]
    L.ratio(
        "red.multi_call_messages",
        "AI messages with >1 billed token item (extra internal calls)",
        len(mc),
        (r["a_n_token_items"] >= 1).sum(),
        "share of billed messages",
        "AI messages with >=1 token item",
        OBS,
    )
    L.ratio(
        "red.multi_call_cost",
        "recorded cost share of messages with >1 token item",
        mc["a_bill_totalCost"].sum(),
        r.loc[r["a_billing_state"] == "items", "a_bill_totalCost"].sum(),
        "share of recorded cost",
        "billed AI messages",
        OBS,
    )


def semantic_lexical(c: Ctx, n_sample: int = 60000, seed: int = 20261030) -> None:
    """Sampled lexical near-duplicate opportunity (a floor for semantic caching).

    Embeds nothing and calls no service. Reads message text in memory only and
    writes counts. Word-bigram MinHash with banding; pairs restricted to the same
    bot. Similarity is not correctness: these are candidate pairs only.
    """
    L, r = c.led, c.r
    import pyarrow.parquet as pq

    e = r[
        (r["u_content_state"] == "text")
        & (r["turn"] == 0)
        & (r["u_att_n"].fillna(0) == 0)
    ]
    e = e.drop_duplicates(["bot_id", "u_h_norm"], keep="first")
    samp = e.sample(min(n_sample, len(e)), random_state=seed)
    want = set(samp["user_message_id"])
    texts: dict[str, str] = {}
    for f in sorted(glob.glob(str(RAW / "chat_message-*.parquet"))):
        t = pq.read_table(f, columns=["message_id", "content"]).to_pandas()
        t = t[t["message_id"].isin(want)]
        texts.update(zip(t["message_id"], t["content"], strict=False))
    rng = np.random.default_rng(seed)
    a = [int(x) for x in rng.integers(1, 2**31, 64)]
    b_ = [int(x) for x in rng.integers(0, 2**31, 64)]
    import re

    from metis_auto.analysis.text_features import normalize_safe

    sigs, ids, bots = [], [], []
    for mid, bid in zip(samp["user_message_id"], samp["bot_id"], strict=False):
        words = re.findall(r"\w+", normalize_safe(texts.get(mid) or ""))
        if len(words) < 4:
            continue
        sh = {
            zlib.crc32(" ".join(words[i : i + 2]).encode())
            for i in range(len(words) - 1)
        }
        sigs.append(
            [
                min(((x * a_ + b0) % 2147483647) for x in sh)
                for a_, b0 in zip(a, b_, strict=False)
            ]
        )
        ids.append(mid)
        bots.append(bid)
    S = np.array(sigs)
    bands = {}
    for i, (sg, bid) in enumerate(zip(S, bots, strict=False)):
        for k in range(16):
            bands.setdefault((bid, k, tuple(sg[k * 4 : (k + 1) * 4])), []).append(i)
    cand = set()
    for v in bands.values():
        if 1 < len(v) <= 50:
            for x in range(len(v)):
                for y in range(x + 1, len(v)):
                    cand.add((v[x], v[y]))
    sims = np.array([(S[i] == S[j]).mean() for i, j in cand]) if cand else np.array([])
    near = set()
    pairs_out = [
        (ids[i], ids[j], float(sv))
        for (i, j), sv in zip(cand, sims, strict=False)
        if sv >= 0.6
    ]
    Path("runs/full_eda").mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        pairs_out, columns=["message_id_a", "message_id_b", "est_jaccard"]
    ).to_parquet("runs/full_eda/semantic_candidate_pairs.parquet", index=False)
    for (i, j), sv in zip(cand, sims, strict=False):
        if sv >= 0.8:
            near.add(i)
            near.add(j)
    L.add(
        "sem.sample_size",
        "sampled distinct first-turn (bot,text) requests with >=4 words",
        len(ids),
        "requests",
        f"seeded sample (seed {seed}) from {len(e)} eligible distinct first-turn requests",
        HEUR,
    )
    L.add(
        "sem.candidate_pairs",
        "same-bot candidate pairs with estimated word-bigram Jaccard >= 0.8 (non-identical texts)",
        int((sims >= 0.8).sum()),
        "pairs",
        "sample",
        HEUR,
        note="lexical candidates; not validated as safe reuse",
    )
    L.ratio(
        "sem.requests_in_near_pairs",
        "sampled distinct requests with a same-bot lexical near-duplicate partner",
        len(near),
        len(ids),
        "share of sampled distinct requests",
        "sample",
        HEUR,
        note="sampled; validity and recall unmeasured; embedding-based semantic matching not run",
    )


def extras(c: Ctx) -> None:
    L, r, m = c.led, c.r, c.msgs
    ts = m["timestamp"].dropna()
    L.add(
        "scope.first_ym",
        "month of the first message timestamp (YYYYMM)",
        ts.min().year * 100 + ts.min().month,
        "YYYYMM",
        "naive message timestamps",
        OBS,
    )
    L.add(
        "scope.last_ym",
        "month of the last message timestamp (YYYYMM)",
        ts.max().year * 100 + ts.max().month,
        "YYYYMM",
        "naive message timestamps",
        OBS,
    )
    L.add(
        "scope.session_first_ym",
        "month of the earliest session created_at (YYYYMM)",
        c.sess["created_at"].min().year * 100 + c.sess["created_at"].min().month,
        "YYYYMM",
        "session created_at",
        OBS,
    )
    bb = r[r["a_billing_state"] == "items"]
    tc = bb["a_bill_totalCost"].sum()
    for mdl, g in r.groupby("bot_provider_model"):
        rs, cs = (
            len(g) / len(r),
            bb.loc[bb["bot_provider_model"] == mdl, "a_bill_totalCost"].sum() / tc,
        )
        if rs >= 0.005 or cs >= 0.02:
            L.add(
                f"model.req_share.{mdl}",
                f"request share of bots labelled {mdl}",
                rs,
                "share of requests",
                "all AI messages",
                META,
            )
            L.add(
                f"model.cost_share.{mdl}",
                f"recorded-cost share of bots labelled {mdl}",
                cs,
                "share of recorded cost",
                "billed AI messages",
                OBS,
            )
    L.add(
        "model.cost_per_request_ratio_top",
        "recorded cost per billed request: highest-cost label over all-billed mean",
        float(
            bb.groupby("bot_provider_model")["a_bill_totalCost"].mean().max()
            / bb["a_bill_totalCost"].mean()
        ),
        "ratio",
        "billed AI messages",
        OBS,
    )
    um = m[(m["type"] == "USER") & (m["content_state"] == "text")]
    for k, v in describe(um["n_chars"]).items():
        L.add(
            f"user.chars.{k}",
            f"USER message characters: {k}",
            v,
            "characters",
            "USER messages with text",
            OBS,
        )
    L.ratio(
        "user.chars_le_100",
        "USER messages with <= 100 characters",
        (um["n_chars"] <= 100).sum(),
        len(um),
        "share of USER text messages",
        "USER messages with text",
        OBS,
    )
    am = m[(m["type"] == "AI") & (m["content_state"] == "text")]
    for k, v in describe(am["n_chars"]).items():
        L.add(
            f"ai.chars.{k}",
            f"AI message characters: {k}",
            v,
            "characters",
            "AI messages with text",
            OBS,
        )
    L.ratio(
        "ai.repeat_occurrences",
        "AI answers whose normalised text occurs more than once in the export",
        int(am["h_norm"].duplicated(keep=False).sum()),
        len(am),
        "share of AI text messages",
        "AI messages with text",
        OBS,
    )
    L.ratio(
        "user.repeat_occurrences",
        "USER messages whose normalised text occurs more than once in the export",
        int(um["h_norm"].duplicated(keep=False).sum()),
        len(um),
        "share of USER text messages",
        "USER messages with text",
        OBS,
    )
    gap = (r["a_timestamp"] - r["u_timestamp"]).dt.total_seconds().dropna()
    gap = gap[gap >= 0]
    for k in ("median", "p90", "p99"):
        L.add(
            f"gap.user_to_ai_s.{k}",
            f"seconds from paired USER timestamp to AI timestamp: {k}",
            describe(gap)[k],
            "seconds",
            f"{len(gap)} pairs with valid timestamps",
            OBS,
            note="not API latency",
        )
    # Tenants / traffic-source proxies.
    ur = r.groupby("user_id").size().sort_values(ascending=False)
    L.ratio(
        "tenant.top1_user_requests",
        "request share of the largest user_id",
        ur.iloc[0],
        ur.sum(),
        "share of requests",
        "AI messages",
        META,
    )
    L.ratio(
        "tenant.top5_user_requests",
        "request share of the 5 largest user_ids",
        ur.iloc[:5].sum(),
        ur.sum(),
        "share of requests",
        "AI messages",
        META,
    )
    us = pd.read_parquet(c.d / "users.parquet")
    L.add("tenant.users_table", "rows in users table", len(us), "users", "all", OBS)
    L.ratio(
        "tenant.users_with_owner",
        "users with owner_user_id set",
        us["owner_user_id"].notna().sum(),
        len(us),
        "share of users",
        "users table",
        OBS,
    )
    L.ratio(
        "tenant.users_with_sessions",
        "users table rows that appear in sessions",
        us["user_id"].isin(c.sess["user_id"]).sum(),
        len(us),
        "share of users",
        "users table",
        OBS,
    )
    ub = c.bots[c.bots["bot_id"].isin(r["bot_id"].unique())]
    L.ratio(
        "tenant.public_bots",
        "used bots flagged public",
        ub["public"].fillna(False).sum(),
        len(ub),
        "share of used bots",
        "used bots",
        META,
    )
    bpu = ub.groupby("user_id").size()
    L.add(
        "tenant.bots_per_user_median",
        "median used bots per user_id",
        float(bpu.median()),
        "bots",
        "users with used bots",
        META,
    )
    sb = r.groupby("bot_id").size().sort_values(ascending=False)
    L.ratio(
        "tenant.top10_bot_requests",
        "request share of the 10 largest bots",
        sb.iloc[:10].sum(),
        sb.sum(),
        "share of requests",
        "AI messages",
        META,
    )
    # Monthly drift.
    r2 = r.assign(month=r["a_timestamp"].dt.to_period("M").astype(str))
    mo = (
        r2.groupby("month")
        .agg(
            requests=("ai_message_id", "size"),
            fa_share=("u_lang", lambda s: (s == "fa").sum() / max(1, s.notna().sum())),
            mean_input_tokens=("a_bill_inputTokens", "mean"),
            rag_share=("a_rag_n_chunks", lambda s: (s > 0).mean()),
            workflow_share=("bot_provider_name", lambda s: (s == "workflow").mean()),
            cost=("a_bill_totalCost", "sum"),
        )
        .reset_index()
    )
    c.save("monthly_profile", mo)
    # Field missingness.
    rows = []
    for col in (
        "att_state",
        "rag_state",
        "billing_state",
        "input_state",
        "tool_state",
        "action_state",
        "content_state",
    ):
        vc = m[col].value_counts(dropna=False, normalize=True)
        for k, v in vc.items():
            rows.append(
                {
                    "table": "chat_message",
                    "field": col.replace("_state", ""),
                    "state": k,
                    "share": v,
                }
            )
    for col in (
        "ins_content_state",
        "corpus_ids_state",
        "functions_state",
        "provider_args_state",
        "async_webhook_state",
        "description_state",
    ):
        for k, v in c.bots[col].value_counts(dropna=False, normalize=True).items():
            rows.append(
                {
                    "table": "chat_bot",
                    "field": col.replace("_state", ""),
                    "state": k,
                    "share": v,
                }
            )
    c.save("field_states", pd.DataFrame(rows))
    L.ratio(
        "bots.instr_blank_or_null",
        "bots with blank or null instructions",
        (c.bots["ins_content_state"] != "text").sum(),
        len(c.bots),
        "share of bots",
        "all bots",
        OBS,
    )
    L.ratio(
        "bots.deleted",
        "bots with deleted_at set",
        c.bots["deleted_at"].notna().sum(),
        len(c.bots),
        "share of bots",
        "all bots",
        OBS,
    )
    L.ratio(
        "bots.enabled",
        "bots with enabled = true",
        c.bots["enabled"].fillna(False).sum(),
        len(c.bots),
        "share of bots",
        "all bots",
        META,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--phases", default="scope,language,tokens,history,rag,cache")
    ap.add_argument("--tag", default="a")
    a = ap.parse_args()
    c = Ctx(a.smoke)
    fns = {
        "scope": scope,
        "language": language,
        "tokens": tokens_cost,
        "history": history_instructions,
        "rag": rag_att,
        "cache": exact_cache,
        "routing": routing_finance,
        "reduction": reduction,
        "semantic": semantic_lexical,
        "extras": extras,
    }
    for ph in a.phases.split(","):
        print("phase", ph, flush=True)
        fns[ph](c)
    c.led.write(
        OUT / ("tables_smoke" if a.smoke else "tables") / f"claims_ledger_{a.tag}.csv"
    )
    print("claims", len(c.led.claims))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
