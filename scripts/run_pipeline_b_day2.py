"""Pipeline B, sprint Day 2: full-data runs of R-B1, R-B2 and F-2 (tune period).

    python scripts/run_pipeline_b_day2.py rb1
    python scripts/run_pipeline_b_day2.py f2
    python scripts/run_pipeline_b_day2.py rb2

Reads the local, git-ignored derived tables (``data/derived/full_eda/``) and the
raw export (``data/full_data/raw/``, read-only), loads the candidate code from
``experiments/`` by file path, and writes content-free aggregates to
``reports/<area>/<exp-id>/``. Prints aggregates only: no text, hash, or bot,
user, session or chunk ID. The report period (August to October 2026) is not
read: it is read once, at the end of the sprint. The split and baselines are
the interim stand-ins in exp-cache-002's ``_interim.py``. No network, no model
call, no key.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from metis_auto.analysis.cache_guard import CacheGuard

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "data" / "derived" / "full_eda"
RAW = ROOT / "data" / "full_data" / "raw" / "data"
EXPERIMENTS = ROOT / "experiments"
SEED = 20261102
SHADOW_RATE = 0.01  # plan default; interim until sprint.toml holds it (S-3)
TTL_DAYS = (1, 7, 30, 90)

REQ_COLUMNS = [
    "session_id",
    "ai_message_id",
    "u_timestamp",
    "a_timestamp",
    "u_h_norm",
    "user_id",
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


def requests_frame(interim: Any, extra: list[str] | None = None) -> pd.DataFrame:
    req = pd.read_parquet(
        DERIVED / "requests.parquet", columns=REQ_COLUMNS + (extra or [])
    )
    req["llm_request"] = interim.llm_request(req)
    return req.join(interim.assign_periods(req))


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


def passes_ttl_rule(summary: dict[str, Any]) -> bool:
    """Declared before the run (README): mean agreement on evaluable hits >= 0.9
    and at least half of the hits evaluable."""
    a = summary["agreement"]
    if not a["n_hits"] or "mean" not in a:
        return False
    return a["mean"] >= 0.9 and a["n_evaluable"] >= 0.5 * a["n_hits"]


def cmd_rb1(out_dir: Path) -> dict[str, Any]:
    run = load(RB1)
    interim = run.interim
    req = requests_frame(interim)
    n_unknown_llm = int(req["llm_request"].isna().sum())
    tune = req[req["period"] == "tune"].copy()
    if tune["llm_request"].isna().any():
        raise SystemExit("tune rows with unknown llm_request; resolve before running")
    tune["llm_request"] = tune["llm_request"].astype(bool)
    per_call = per_call_items()
    tune = run.fee_blocks(tune, per_call)
    llm = tune[tune["llm_request"]]
    rag = rag_json(set(llm["ai_message_id"]))
    lookups = run.build_lookups(llm, rag, per_call, scope="user")
    lookups_bot = run.build_lookups(llm, rag, per_call, scope="bot")
    guard = CacheGuard(
        approved=None,
        blocked=frozenset(),
        disabled_bots=frozenset(),
        key_version="rb1-v1",
    )
    ctx = type("Ctx", (), {"guard": guard, "seed": SEED})()
    fee_known = lookups["fee"].notna()
    data_facts = {
        "n_requests": len(req),
        "n_llm_unknown": n_unknown_llm,
        "n_tune_requests": len(tune),
        "n_tune_llm": int(tune["llm_request"].sum()),
        "n_tune_llm_with_rag_json": int(
            llm["ai_message_id"].isin(rag["message_id"]).sum()
        ),
        "n_lookups": len(lookups),
        "n_lookups_no_query": int(lookups["query_key"].isna().sum()),
        "n_lookups_fee_attributed": int(fee_known.sum()),
        "n_lookups_with_unknown_hash": int(
            lookups["chunks"].map(lambda c: any(h is None for _, h in c)).sum()
        ),
        "n_lookups_empty": int(lookups["chunks"].map(len).eq(0).sum()),
        "corpus_version_known": int(lookups["corpus_version"].notna().sum()),
    }
    results: dict[str, Any] = {
        "ttl_table": {
            "scope_user": run.ttl_table(lookups, TTL_DAYS),
            "scope_bot": run.ttl_table(lookups_bot, TTL_DAYS),
        },
        "churn": run.churn_summary(lookups),
        "by_ttl": {},
    }
    created = datetime.now(UTC)
    chosen = None
    for days in (None, *TTL_DAYS):
        ttl = None if days is None else pd.Timedelta(days=days)
        res = run.evaluate(tune, lookups, ttl, ctx, SHADOW_RATE)
        label = "none" if days is None else f"{days}d"
        passed = passes_ttl_rule(res["summary"])
        results["by_ttl"][label] = {
            k: res[k] for k in ("summary", "rates", "fees", "tenants")
        } | {"passes_rule": passed}
        if days is not None and passed:
            chosen = days
        if days is not None:
            text = run.lever_result_json(
                res,
                tune,
                ttl=ttl,
                seed=SEED,
                code_commit=code_commit(),
                python_version=platform.python_version(),
                created_at=created,
                shadow_rate=SHADOW_RATE,
            )
            (out_dir / "levers").mkdir(parents=True, exist_ok=True)
            name = json.loads(text)["lever_id"]
            (out_dir / "levers" / f"{name}.json").write_text(text, encoding="utf-8")
    results["chosen_ttl_days"] = chosen
    if chosen is not None:
        res = run.evaluate(
            tune, lookups_bot, pd.Timedelta(days=chosen), ctx, SHADOW_RATE
        )
        results["scope_bot_sensitivity"] = {
            k: res[k] for k in ("summary", "rates", "fees")
        }
    payload = _clean(
        {
            "lever": "R-B1 retrieval-result cache (exp-cache-002)",
            "period": "tune (2026-03-01..2026-07-31, naive timestamps, Q-06)",
            "scope": "interim split/baselines, not the shared implementation",
            "evidence": "simulation; measured potential, conditional on Metis-Auto "
            "being able to intercept retrieval; candidate reuse only",
            "shadow_rate": SHADOW_RATE,
            "data_facts": data_facts,
            **results,
            "created_at": created.isoformat(),
        }
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


F2 = "cost/exp-cost-002-cost-trace/check.py"


def _plain(obj: Any) -> Any:
    from decimal import Decimal

    if isinstance(obj, Decimal):
        return format(obj, "f")
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_plain(v) for v in obj]
    return obj


def cmd_f2(out_dir: Path) -> dict[str, Any]:
    """Cost trace over every AI message's billing JSON. Reads all periods: it
    reconciles the EDA's all-period cost split and fits nothing. The tune slice
    is reported beside it."""
    check = load(F2)
    interim = load(RB1).interim
    req = requests_frame(interim)
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
                "tune slice by interim split, not the shared implementation",
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


def cmd_rb2(out_dir: Path) -> dict[str, Any]:
    rb1 = load(RB1)
    run = load(RB2)
    interim = rb1.interim
    req = requests_frame(interim)
    tune = req[(req["period"] == "tune") & req["llm_request"].fillna(False)].copy()
    tune["llm_request"] = tune["llm_request"].astype(bool)
    tune = rb1.fee_blocks(tune, per_call_items())
    items = pd.read_parquet(
        RAW / "derived" / "chat_message_billing.parquet",
        columns=["message_id", "inputTokens", "costBreakdown.input_tokens"],
    )
    conv = pd.read_csv(
        ROOT / "reports" / "full_eda" / "tables" / "cached_token_convention.csv"
    )
    separate = frozenset(conv.loc[conv["cached_reported_separately"], "model"])
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
        "tokens_per_char": tpc,
        "s6_within_message_dedup": "not on any branch (2026-11-02); copies left out",
    }
    created = datetime.now(UTC)
    scenarios = []
    (out_dir / "levers").mkdir(parents=True, exist_ok=True)
    for window, pointer, ledger in SCENARIOS:
        res = run.evaluate(
            tune, chunks, pointer_tokens=pointer, window=window, ledger=ledger, tpc=tpc
        )
        scenarios.append({"scenario": res["scenario"], "summary": res["summary"]})
        text = run.lever_result_json(
            res,
            tune,
            seed=SEED,
            code_commit=code_commit(),
            python_version=platform.python_version(),
            created_at=created,
            period_bounds={"tune": interim.PERIODS["tune"]},
            extra_assumptions=(interim.INTERIM_LABEL,),
        )
        name = json.loads(text)["lever_id"]
        (out_dir / "levers" / f"{name}.json").write_text(text, encoding="utf-8")
    payload = _clean(
        {
            "lever": "R-B2 cross-turn chunk policy (exp-ctx-002)",
            "period": "tune (2026-03-01..2026-07-31, naive timestamps, Q-06), LLM rows",
            "scope": "interim split/baselines, not the shared implementation",
            "evidence": "tokens only, quality not measured / hypothetical "
            "reconstruction",
            "data_facts": facts,
            "scenarios": scenarios,
            "created_at": created.isoformat(),
        }
    )
    (out_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("task", choices=["rb1", "f2", "rb2"])
    args = parser.parse_args()
    if args.task == "rb1":
        payload = cmd_rb1(ROOT / "reports" / "caching" / "exp-cache-002")
    elif args.task == "f2":
        payload = cmd_f2(ROOT / "reports" / "cost" / "exp-cost-002")
    else:
        payload = cmd_rb2(ROOT / "reports" / "context" / "exp-ctx-002")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
