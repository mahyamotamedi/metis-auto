"""Pipeline B, sprint Day 2: full-data runs of R-B1, R-B2 and F-2 (tune period).

    python scripts/run_pipeline_b_day2.py rb1
    python scripts/run_pipeline_b_day2.py f2
    python scripts/run_pipeline_b_day2.py rb2
    python scripts/run_pipeline_b_day2.py rb1-report   # once, after rb1
    python scripts/run_pipeline_b_day2.py rb2-report   # once, after rb2

Reads the local, git-ignored derived tables (``data/derived/full_eda/``) and the
raw export (``data/full_data/raw/``, read-only), loads the candidate code from
``experiments/`` by file path, and writes content-free aggregates:
``LeverResult`` files to ``reports/levers/<lever_id>.json`` (one per version
per baseline, ADR-0032, read by ``compare_levers.py`` and the demo) and a
``summary.json`` to ``reports/<area>/<exp-id>/``. Prints aggregates only: no
text, hash, or bot, user, session or chunk ID.

Scope and baselines are the shared S-3 code (ADR-0036): ``replay_scope.scope``
(``period`` per row from ``a_timestamp``, ``llm_request``),
``replay_scope.split_by_session`` (the fitting split) and
``baselines_full.baseline_costs`` (the four baselines). Every setting comes from
``config/evaluation/sprint.toml`` (``--sprint-config``): periods, split seed,
shadow rate, ``min_n`` and the baseline catalogue, price table and premium
model. ``rb1``, ``f2`` and ``rb2`` read no report-period result. ``rb1`` and ``rb2``
freeze their settings in their summary (R-B1: the 1-day TTL, the stated default,
with the full grid reported; R-B2: ``k`` = 0 the default, ``k`` <= 1 the stated
scenario). ``rb1-report`` and ``rb2-report`` (owner decision 2026-11-03: one
report-split run each, like R-A1/R-A2) read those frozen settings and apply them
once to the report split (``split_by_session == "report"``); R-B1's cache history
looks back into the tune period, as R-A1's window does. No network, no model
call, no key.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from metis_auto.analysis.baselines_full import (
    baseline_costs,
    cached_reported_separately,
)
from metis_auto.analysis.cache_guard import CacheGuard
from metis_auto.analysis.levers import ReplayContext
from metis_auto.analysis.replay_scope import (
    period_bounds_from_config,
    scope,
    split_by_session,
)

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "data" / "derived" / "full_eda"
RAW = ROOT / "data" / "full_data" / "raw" / "data"
EXPERIMENTS = ROOT / "experiments"
LEVERS = ROOT / "reports" / "levers"
SPRINT_CONFIG = ROOT / "config" / "evaluation" / "sprint.toml"
TTL_DAYS = (1, 7, 30, 90)

REQ_COLUMNS = [
    "session_id",
    "ai_message_id",
    "u_timestamp",
    "a_timestamp",
    "u_h_norm",
    "user_id",
    "u_lang",
    "bot_id",
    "bot_user_id",
    "bot_provider_name",
    "bot_provider_model",
    "bot_rag_top_k",
    "bot_rag_reranking",
    "bot_n_corpora",
    "a_bill_totalCost",
    "a_bill_inputTokens",
    "a_bill_cachedInputTokens",
    "a_rag_n_queries",
    "a_rag_n_chunks",
    "turn",
    "a_order",
    "a_bill_outputTokens",
    "a_billing_state",
    "a_n_per_call_only_items",
]


def load(relative: str) -> Any:
    path = EXPERIMENTS / relative
    name = "metis_day2_" + relative.replace("/", "_").replace("-", "_")[:-3]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RB1 = "caching/exp-cache-002-retrieval-result-cache/run.py"


def code_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
        )
    except OSError:
        return "unknown"
    return out.stdout.strip() or "unknown"


def _toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def sprint_settings(path: Path) -> dict[str, Any]:
    """The ``sprint.toml`` values B's runs use, plus the replay context built
    from them (the price table and catalogue files it names)."""
    sprint = _toml(path)
    base = sprint["baselines"]
    guard = CacheGuard(
        approved=None,
        blocked=frozenset(),
        disabled_bots=frozenset(),
        key_version="rb1-v1",
    )
    seed = int(sprint["split"]["seed"])
    ctx = ReplayContext(
        period_bounds=period_bounds_from_config(sprint["periods"]),
        price_table=_toml(ROOT / base["price_table"]),
        catalogue=_toml(ROOT / base["catalogue"]),
        seed=seed,
        min_n=int(sprint["sufficiency"]["min_n"]),
        guard=guard,
    )
    return {
        "version": sprint["version"],
        "seed": seed,
        "shadow_rate": float(sprint["cache_guard"]["shadow_rate"]),
        "premium_model": str(base["premium_model"]),
        "ctx": ctx,
    }


def requests_frame(st: dict[str, Any]) -> pd.DataFrame:
    """``requests.parquet`` with ``period``, ``llm_request`` and ``split``."""
    req = pd.read_parquet(DERIVED / "requests.parquet", columns=REQ_COLUMNS)
    req = scope(req, st["ctx"])
    req["split"] = split_by_session(req, seed=st["seed"])
    return req


def split_counts(req: pd.DataFrame) -> dict[str, int]:
    """Rows per split label and the ``excluded`` rows per period (FR-EVAL-08)."""
    out = {str(k): int(v) for k, v in req["split"].value_counts().items()}
    excluded = req.loc[req["split"] == "excluded", "period"].value_counts()
    out |= {f"excluded_period:{k}": int(v) for k, v in excluded.items()}
    return dict(sorted(out.items()))


RB1_DEFAULT_TTL_DAYS = 1
RB2_DEFAULT = (0, 8, False)  # (visible window, pointer tokens, ledger)
RB2_STATED = (1, 8, False)


def report_scope(req: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(cache history, scored rows) of the report run: scored = the report split;
    history = every tune- or report-period row (and every scored row)."""
    scored = req["split"].eq("report")
    return req["period"].isin(["tune", "report"]) | scored, scored


def frozen_rb1(*, chosen_ttl_days: int | None) -> dict[str, Any]:
    """R-B1's frozen setting, written on the tune run before any report read."""
    return {
        "ttl_days": RB1_DEFAULT_TTL_DAYS,
        "role": "stated default (1 day); the full TTL grid is reported",
        "grid_ttl_days": list(TTL_DAYS),
        "ttl_rule_choice_days": chosen_ttl_days,
        "scope": "user",
    }


def _scenario(window: int | None, pointer: int, ledger: bool) -> dict[str, Any]:
    return {"visible_window": window, "pointer_tokens": pointer, "ledger": ledger}


def frozen_rb2() -> dict[str, Any]:
    """R-B2's frozen scenarios, written on the tune run before any report read."""
    return {
        "default": _scenario(*RB2_DEFAULT),
        "stated_scenario": _scenario(*RB2_STATED),
        "role": "k = 0 is the default (nothing assumed visible); k <= 1 is the "
        "stated scenario; every tune scenario is reported",
    }


def read_frozen(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "frozen" not in payload:
        raise SystemExit(f"{path}: no frozen settings; run the tune command first")
    return payload["frozen"]


def report_scenarios(frozen: Mapping[str, Any]) -> list[tuple[int, int, bool]]:
    return [
        (s["visible_window"], s["pointer_tokens"], s["ledger"])
        for s in (frozen["default"], frozen["stated_scenario"])
    ]


def write_levers(texts: dict[str, str]) -> list[str]:
    LEVERS.mkdir(parents=True, exist_ok=True)
    names = []
    for text in texts.values():
        name = json.loads(text)["lever_id"]
        (LEVERS / f"{name}.json").write_text(text, encoding="utf-8")
        names.append(name)
    return names


def _settings_record(st: dict[str, Any]) -> dict[str, Any]:
    ctx = st["ctx"]
    return {
        "sprint_config": st["version"],
        "seed": st["seed"],
        "shadow_rate": st["shadow_rate"],
        "min_n": ctx.min_n,
        "premium_model": st["premium_model"],
        "price_version": ctx.price_table["version"],
        "catalogue_version": ctx.catalogue["version"],
    }


def per_call_items() -> pd.DataFrame:
    bt = pd.read_parquet(
        RAW / "derived" / "chat_message_billing.parquet",
        columns=["message_id", "costBreakdown.per_call"],
    )
    bt = bt[bt["costBreakdown.per_call"].notna()]
    return bt.rename(columns={"costBreakdown.per_call": "amount"})


def rag_json(message_ids: set[str]) -> pd.DataFrame:
    parts = []
    for shard in sorted(RAW.glob("chat_message-*.parquet")):
        m = pd.read_parquet(shard, columns=["message_id", "rag"])
        parts.append(m[m["message_id"].isin(message_ids) & m["rag"].notna()])
    return pd.concat(parts, ignore_index=True)


def _clean(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_clean(v) for v in obj]
    if isinstance(obj, float) and obj != obj:
        return None
    return obj


def cmd_rb1(st: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    run = load(RB1)
    ctx, shadow_rate = st["ctx"], st["shadow_rate"]
    req = requests_frame(st)
    counts = split_counts(req)
    separate = cached_reported_separately(req)
    # History: every tune-period row (the report period is not read). Fitting
    # and results: the split's tune rows only (ADR-0036; owner decision 1).
    history = req[req["period"] == "tune"].copy()
    per_call = per_call_items()
    history = run.fee_blocks(history, per_call)
    scored = history["split"].eq("tune")
    everyone = pd.Series(True, index=history.index)
    tune = history.loc[scored]
    llm = history[history["llm_request"]]
    rag = rag_json(set(llm["ai_message_id"]))
    lookups = run.build_lookups(llm, rag, per_call, scope="user")
    lookups_bot = run.build_lookups(llm, rag, per_call, scope="bot")
    tune_labels = tune.index
    fee_known = lookups["fee"].notna()
    data_facts = {
        "n_requests": len(req),
        "n_tune_period": len(history),
        "n_tune_period_llm": int(history["llm_request"].sum()),
        "n_tune_split_in_tune_period": len(tune),
        "n_tune_split_llm": int(tune["llm_request"].sum()),
        "n_tune_split_in_report_period_not_read": int(
            ((req["split"] == "tune") & (req["period"] == "report")).sum()
        ),
        "n_tune_period_llm_with_rag_json": int(
            llm["ai_message_id"].isin(rag["message_id"]).sum()
        ),
        "n_lookups_tune_period": len(lookups),
        "n_lookups_tune_split": int(lookups["req"].isin(tune_labels).sum()),
        "n_lookups_no_query": int(lookups["query_key"].isna().sum()),
        "n_lookups_fee_attributed": int(fee_known.sum()),
        "n_lookups_with_unknown_hash": int(
            lookups["chunks"].map(lambda c: any(h is None for _, h in c)).sum()
        ),
        "n_lookups_empty": int(lookups["chunks"].map(len).eq(0).sum()),
        "corpus_version_known": int(lookups["corpus_version"].notna().sum()),
    }
    choice = run.choose_ttl(history, lookups, TTL_DAYS, ctx, shadow_rate, scored=scored)
    whole = run.choose_ttl(
        history, lookups, TTL_DAYS, ctx, shadow_rate, scored=everyone
    )
    chosen = choice["chosen_ttl_days"]
    results: dict[str, Any] = {
        "ttl_table": {
            "scope_user": {
                "tune_split": run.ttl_table(lookups, TTL_DAYS, tune_labels),
                "tune_period_all_rows": run.ttl_table(lookups, TTL_DAYS),
            },
            "scope_bot": {
                "tune_split": run.ttl_table(lookups_bot, TTL_DAYS, tune_labels),
            },
        },
        "frequency_bias": {
            "note": "comparison only, never used to pick the TTL (ADR-0036)",
            "chosen_ttl_days_tune_split": chosen,
            "chosen_ttl_days_tune_period_all_rows": whole["chosen_ttl_days"],
            "differs": chosen != whole["chosen_ttl_days"],
            "passes_rule_tune_period_all_rows": {
                k: v["passes_rule"] for k, v in whole["by_ttl"].items()
            },
        },
        "churn": run.churn_summary(lookups),
        "by_ttl": {"none": choice["by_ttl"]["none"]},
    }
    baselines = baseline_costs(
        tune, ctx, premium_model=st["premium_model"], cached_separately=separate
    )
    created = datetime.now(UTC)
    written: list[str] = []
    for days in TTL_DAYS:
        ttl = pd.Timedelta(days=days)
        res = run.evaluate(history, lookups, ttl, ctx, shadow_rate, scored=scored)
        label = f"{days}d"
        results["by_ttl"][label] = {
            k: res[k] for k in ("summary", "rates", "fees", "tenants")
        } | {"passes_rule": choice["by_ttl"][label]["passes_rule"]}
        texts = run.lever_results_json(
            res,
            tune,
            baselines=baselines,
            split_counts=counts,
            ttl=ttl,
            ctx=ctx,
            code_commit=code_commit(),
            python_version=platform.python_version(),
            created_at=created,
            shadow_rate=shadow_rate,
        )
        written += write_levers(texts)
    results["chosen_ttl_days"] = chosen
    if chosen is not None:
        res = run.evaluate(
            history,
            lookups_bot,
            pd.Timedelta(days=chosen),
            ctx,
            shadow_rate,
            scored=scored,
        )
        results["scope_bot_sensitivity"] = {
            k: res[k] for k in ("summary", "rates", "fees")
        }
    payload = _plain(
        _clean(
            {
                "lever": "R-B1 retrieval-result cache (exp-cache-002)",
                "period": "tune (2026-03-01..2026-07-31, naive timestamps, Q-06)",
                "scope": "shared S-3 scope (ADR-0036): results and the TTL choice "
                "on split_by_session tune rows; every tune-period row is cache "
                "history",
                "evidence": "simulation; measured potential, conditional on "
                "Metis-Auto being able to intercept retrieval; candidate reuse only",
                "settings": _settings_record(st),
                "split_counts": counts,
                "baselines": baselines,
                "baseline_units": {
                    "as_logged": "recorded units",
                    "others": "price-file units; R-B1 saving not computed (no fees)",
                },
                "lever_results": sorted(written),
                "data_facts": data_facts,
                "frozen": frozen_rb1(chosen_ttl_days=chosen),
                **results,
                "created_at": created.isoformat(),
            }
        )
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


F2 = "cost/exp-cost-002-cost-trace/check.py"


def _plain(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return format(obj, "f")
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_plain(v) for v in obj]
    return obj


def cmd_f2(st: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    """Cost trace over every AI message's billing JSON. Reads all periods: it
    reconciles the EDA's all-period cost split and fits nothing. The tune slice
    (``period`` from ``a_timestamp``, per row) is reported beside it."""
    check = load(F2)
    req = requests_frame(st)
    meta = req.set_index("ai_message_id")[
        ["period", "llm_request", "bot_provider_model"]
    ]
    traces = []
    for shard in sorted(RAW.glob("chat_message-*.parquet")):
        m = pd.read_parquet(shard, columns=["message_id", "type", "billing"])
        m = m[m["type"] == "AI"]
        for mid, raw in zip(m["message_id"], m["billing"], strict=True):
            traces.append((mid, check.trace_message(raw)))
    period = meta["period"].to_dict()
    model = meta["bot_provider_model"].to_dict()
    scopes: dict[str, Any] = {
        "all_ai_messages": check.reconcile(t for _, t in traces),
        "tune": check.reconcile(t for mid, t in traces if period.get(mid) == "tune"),
        "not_in_requests": check.reconcile(t for mid, t in traces if mid not in period),
    }
    other = [b for b in check.BLOCKS if b not in check.EDA_BLOCKS]
    by_model: dict[str, dict[str, Any]] = {}
    for mid, t in traces:
        if t["total"] is None:
            continue
        label = str(model.get(mid, "not-in-requests"))
        slot = by_model.setdefault(label, {"messages": 0, "total": 0, "other": 0})
        slot["messages"] += 1
        slot["total"] += t["total"]
        slot["other"] += sum((t["blocks"][b] for b in other), 0)
    all_other = scopes["all_ai_messages"]["other_total"]
    ranked = sorted(by_model.items(), key=lambda kv: kv[1]["other"], reverse=True)
    model_rows = [
        {
            "model_label": label,
            "messages": v["messages"],
            "other": v["other"],
            "share_of_other": float(v["other"] / all_other) if all_other else None,
            "other_share_of_model_cost": float(v["other"] / v["total"])
            if v["total"]
            else None,
        }
        for label, v in ranked
    ]
    payload = _plain(
        _clean(
            {
                "task": "F-2 cost trace (exp-cost-002)",
                "units": "recorded cost units (unstated currency), Decimal sums",
                "evidence": "observed (costBreakdown keys); metadata-derived "
                "(usage/fixed split of unbroken items, model labels)",
                "scope": "all AI messages (reconciles the EDA's all-period split); "
                "tune slice = replay_scope period tune (a_timestamp, per row)",
                "other_block": "reported inside token_cost (owner decision 3, "
                "2026-11-02: two blocks); its share is in scopes.*.blocks",
                "scopes": scopes,
                "other_by_model_label": model_rows,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


RB2 = "context/exp-ctx-002-cross-turn-chunk-policy/run.py"
SCENARIOS = (  # (visible window, pointer tokens, ledger); all hypothetical
    (0, 8, False),
    (1, 8, False),
    (1, 8, True),
    (3, 8, False),
    (3, 8, True),
    (3, 16, False),
    (None, 8, False),
    (None, 8, True),
)


def _ledger_value(claim_id: str) -> float:
    ledger = pd.read_csv(ROOT / "reports" / "full_eda" / "tables" / "claims_ledger.csv")
    return float(ledger.set_index("claim_id").at[claim_id, "value"])


def cmd_rb2(st: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    """Scenarios on ``period == "tune"`` LLM rows: R-B2 fits nothing, so it uses
    no split (owner decision 1)."""
    rb1 = load(RB1)
    run = load(RB2)
    ctx = st["ctx"]
    req = requests_frame(st)
    separate = cached_reported_separately(req)
    tune = req[(req["period"] == "tune") & req["llm_request"]].copy()
    tune = rb1.fee_blocks(tune, per_call_items())
    items = pd.read_parquet(
        RAW / "derived" / "chat_message_billing.parquet",
        columns=["message_id", "inputTokens", "costBreakdown.input_tokens"],
    )
    conv = pd.read_csv(
        ROOT / "reports" / "full_eda" / "tables" / "cached_token_convention.csv"
    )
    eda_separate = frozenset(conv.loc[conv["cached_reported_separately"], "model"])
    tune = run.request_inputs(tune, items, separate)
    shards = sorted((DERIVED / "chunks").glob("*.parquet"))
    table = pd.concat(
        [
            pd.read_parquet(f, columns=["message_id", "chunk_id", "n_chars", "h_exact"])
            for f in shards
        ],
        ignore_index=True,
    )
    chunks = run.build_chunks(tune, table)
    tpc = _ledger_value("recon.t0rag.coef_rag")
    facts = {
        "n_tune_llm": len(tune),
        "n_chunk_rows": len(chunks),
        "n_requests_with_chunks": int(chunks["req"].nunique()),
        "n_hash_unknown": int(chunks["content_hash"].isna().sum()),
        "n_input_cost_unknown": int(tune["input_cost_ordinary"].isna().sum()),
        "n_input_tokens_unknown": int(tune["input_tokens_ordinary"].isna().sum()),
        "separate_cached_models": len(separate),
        "separate_cached_models_equal_eda_table": separate == eda_separate,
        "tokens_per_char": tpc,
        "s6_within_message_dedup": "not on any branch (2026-11-02); copies left out",
    }
    created = datetime.now(UTC)
    scenarios = []
    written: list[str] = []
    for window, pointer, ledger in SCENARIOS:
        res = run.evaluate(
            tune, chunks, pointer_tokens=pointer, window=window, ledger=ledger, tpc=tpc
        )
        repriced = run.repriced_savings(
            res["after"],
            ctx,
            premium_model=st["premium_model"],
            cached_separately=separate,
        )
        scenarios.append(
            {
                "scenario": res["scenario"],
                "summary": res["summary"],
                "repriced_saving": repriced["saving"],
            }
        )
        texts = run.lever_results_json(
            res,
            tune,
            repriced=repriced,
            ctx=ctx,
            code_commit=code_commit(),
            python_version=platform.python_version(),
            created_at=created,
        )
        written += write_levers(texts)
    payload = _plain(
        _clean(
            {
                "lever": "R-B2 cross-turn chunk policy (exp-ctx-002)",
                "period": "tune (2026-03-01..2026-07-31, a_timestamp per row, "
                "naive timestamps, Q-06), LLM rows",
                "scope": "shared S-3 scope (ADR-0036): period tune, no split "
                "(no fitted parameter)",
                "evidence": "tokens only, quality not measured / hypothetical "
                "reconstruction",
                "settings": _settings_record(st),
                "baselines": repriced["before"],
                "baseline_units": {
                    "as_logged": "recorded units",
                    "others": "price-file units (before minus after)",
                },
                "lever_results": sorted(written),
                "data_facts": facts,
                "frozen": frozen_rb2(),
                "scenarios": scenarios,
                "created_at": created.isoformat(),
            }
        )
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def cmd_rb1_report(st: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    """The frozen R-B1 version once on the report split (tune rows warm it)."""
    frozen = read_frozen(out_dir / "summary.json")
    run = load(RB1)
    ctx, shadow_rate = st["ctx"], st["shadow_rate"]
    req = requests_frame(st)
    counts = split_counts(req)
    separate = cached_reported_separately(req)
    history_mask, scored_mask = report_scope(req)
    per_call = per_call_items()
    history = run.fee_blocks(req[history_mask].copy(), per_call)
    scored = scored_mask[history.index]
    report = history.loc[scored]
    llm = history[history["llm_request"]]
    lookups = run.build_lookups(
        llm, rag_json(set(llm["ai_message_id"])), per_call, scope=frozen["scope"]
    )
    ttl = pd.Timedelta(days=frozen["ttl_days"])
    res = run.evaluate(history, lookups, ttl, ctx, shadow_rate, scored=scored)
    baselines = baseline_costs(
        report, ctx, premium_model=st["premium_model"], cached_separately=separate
    )
    texts = run.lever_results_json(
        res,
        report,
        baselines=baselines,
        split_counts=counts,
        ttl=ttl,
        ctx=ctx,
        code_commit=code_commit(),
        python_version=platform.python_version(),
        created_at=datetime.now(UTC),
        shadow_rate=shadow_rate,
        period="report",
    )
    written = write_levers(texts)
    payload = _plain(
        _clean(
            {
                "lever": "R-B1 retrieval-result cache (exp-cache-002), report split",
                "approval": "owner (Kimia, Pipeline B), 2026-11-03: one report-split "
                "run, like R-A1/R-A2",
                "frozen": frozen,
                "scope": "scored: split_by_session report; cache history: every "
                "tune- and report-period row (tune rows may warm the cache)",
                "baselines": baselines,
                "summary": res["summary"],
                "rates": res["rates"],
                "fees": res["fees"],
                "data_facts": {
                    "n_report": len(report),
                    "n_report_llm": int(report["llm_request"].sum()),
                    "n_history": len(history),
                    "n_lookups_history": len(lookups),
                },
                "lever_results": sorted(written),
            }
        )
    )
    (out_dir / "report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def cmd_rb2_report(st: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    """The frozen R-B2 scenarios once on the report split (whole sessions)."""
    frozen = read_frozen(out_dir / "summary.json")
    rb1, run = load(RB1), load(RB2)
    ctx = st["ctx"]
    req = requests_frame(st)
    separate = cached_reported_separately(req)
    _, scored = report_scope(req)
    rows = rb1.fee_blocks(req[scored].copy(), per_call_items())
    items = pd.read_parquet(
        RAW / "derived" / "chat_message_billing.parquet",
        columns=["message_id", "inputTokens", "costBreakdown.input_tokens"],
    )
    rows = run.request_inputs(rows, items, separate)
    llm = rows[rows["llm_request"].astype(bool)]
    ids = set(llm["ai_message_id"])
    parts = []
    for f in sorted((DERIVED / "chunks").glob("*.parquet")):
        part = pd.read_parquet(
            f, columns=["message_id", "chunk_id", "n_chars", "h_exact"]
        )
        parts.append(part[part["message_id"].isin(ids)])
    chunks = run.build_chunks(llm, pd.concat(parts, ignore_index=True))
    tpc = _ledger_value("recon.t0rag.coef_rag")
    created = datetime.now(UTC)
    written: list[str] = []
    scenarios = []
    for window, pointer, ledger in report_scenarios(frozen):
        res = run.evaluate(
            rows, chunks, pointer_tokens=pointer, window=window, ledger=ledger, tpc=tpc
        )
        repriced = run.repriced_savings(
            res["after"],
            ctx,
            premium_model=st["premium_model"],
            cached_separately=separate,
        )
        scenarios.append(
            {
                "scenario": res["scenario"],
                "summary": res["summary"],
                "repriced_saving": repriced["saving"],
            }
        )
        texts = run.lever_results_json(
            res,
            rows,
            repriced=repriced,
            ctx=ctx,
            code_commit=code_commit(),
            python_version=platform.python_version(),
            created_at=created,
            split="report",
        )
        written += write_levers(texts)
    payload = _plain(
        _clean(
            {
                "lever": "R-B2 cross-turn chunk policy (exp-ctx-002), report split",
                "approval": "owner (Kimia, Pipeline B), 2026-11-03: one report-split "
                "run, like R-A1/R-A2",
                "frozen": frozen,
                "scope": "split_by_session report rows (whole sessions); LLM rows act",
                "data_facts": {
                    "n_report": len(rows),
                    "n_report_llm": len(llm),
                    "n_chunk_rows": len(chunks),
                    "tokens_per_char": tpc,
                },
                "scenarios": scenarios,
                "lever_results": sorted(written),
                "created_at": created.isoformat(),
            }
        )
    )
    (out_dir / "report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "task", choices=["rb1", "f2", "rb2", "rb1-report", "rb2-report"]
    )
    parser.add_argument(
        "--sprint-config",
        type=Path,
        default=SPRINT_CONFIG,
        help="sprint settings (periods, split seed, shadow rate, baselines)",
    )
    args = parser.parse_args()
    st = sprint_settings(args.sprint_config)
    if args.task == "rb1":
        payload = cmd_rb1(st, ROOT / "reports" / "caching" / "exp-cache-002")
    elif args.task == "rb1-report":
        payload = cmd_rb1_report(st, ROOT / "reports" / "caching" / "exp-cache-002")
    elif args.task == "rb2-report":
        payload = cmd_rb2_report(st, ROOT / "reports" / "context" / "exp-ctx-002")
    elif args.task == "f2":
        payload = cmd_f2(st, ROOT / "reports" / "cost" / "exp-cost-002")
    else:
        payload = cmd_rb2(st, ROOT / "reports" / "context" / "exp-ctx-002")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
