"""Lever results of EXP-CTX-001 within-message chunk dedup (S-6b).

Reads ``requests.parquet`` and the chunk table, keeps one fitting split
(``replay_scope.split_by_session``; default ``report``, read once), applies the
version through ``levers.combine`` with the owner's conversion (tokens per
character from the claims ledger row ``recon.t0rag.coef_rag``; ``as_logged``
priced at each model's ``implied_input_per_M`` from
``reports/full_eda/tables/implied_unit_rates.csv``) and writes one
``LeverResult`` per baseline to ``reports/levers/`` plus an aggregate table to
``reports/context/exp-ctx-001/saving.csv``. No IDs, hashes or text are written
or printed. Rule: ADR-0038.

    .venv/bin/python scripts/context_dedup_levers.py
"""

from __future__ import annotations

import argparse
import dataclasses
import glob
import importlib.util
import platform
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from metis_auto.analysis.baselines_full import (
    BASELINE_KEYS,
    baseline_costs,
    best_single_cheap_model,
    cached_reported_separately,
)
from metis_auto.analysis.lever_enrich import enrich
from metis_auto.analysis.lever_result import build_manifest
from metis_auto.analysis.levers import ReplayContext, combine, with_blocks
from metis_auto.analysis.replay_scope import (
    period_bounds_from_config,
    scope,
    split_by_session,
)
from metis_auto.wiring.experiments import code_version

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments/context/exp-ctx-001-within-message-dedup"
DERIVED = ROOT / "data/derived/full_eda"
TABLES = ROOT / "reports/full_eda/tables"
LEDGER_ROW = "recon.t0rag.coef_rag"
RATES_VERSION = "full-eda-implied-unit-rates"
REQ_COLUMNS = [
    "ai_message_id",
    "session_id",
    "bot_id",
    "user_id",
    "u_lang",
    "u_h_norm",
    "a_timestamp",
    "a_order",
    "bot_provider_name",
    "bot_provider_model",
    "a_billing_state",
    "a_bill_inputTokens",
    "a_bill_cachedInputTokens",
    "a_bill_outputTokens",
    "a_bill_totalCost",
    "a_n_per_call_only_items",
]


def _version():
    name = "exp_ctx_001_version"
    spec = importlib.util.spec_from_file_location(name, EXP / "version.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _assumptions(coef: float, baseline: str) -> tuple[str, ...]:
    price = (
        "as_logged: saving = saved tokens x the logged model's implied_input_per_M"
        " / 1e6 (reports/full_eda/tables/implied_unit_rates.csv, recorded units);"
        " a model with no rate is unknown and leaves both sides, never zero."
        if baseline == "as_logged"
        else "Repriced: logged tokens less saved tokens at the price table's tiers;"
        " a lower input can move a request to a cheaper tier. Fees are not priced"
        " in price-file units (ADR-0036), so baseline_cost has no fees key."
    )
    return (
        f"Tokens = duplicate characters x {coef:.4f} (claims ledger {LEDGER_ROW},"
        " OLS over turn-0 single-call billed RAG requests): a hypothetical"
        " reconstruction, not a tokenizer count.",
        "Saved tokens come out of uncached input only (chunks follow the target"
        " message, A-84, outside the cacheable prefix), capped at the row's"
        " uncached input.",
        "A multi-call request saves once, not once per call.",
        price,
        "Fees unchanged: a context version never changes fees.",
        "Whether Metis actually sent the duplicate copies is unknown (U-04); the"
        " quality of dropping a copy is unmeasured (FR-CTX-03).",
        "Report split only (replay_scope.split_by_session); workflow rows are in"
        " no numerator.",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--split", default="report", choices=("tune", "report"))
    ap.add_argument("--levers-dir", type=Path, default=ROOT / "reports/levers")
    ap.add_argument(
        "--table", type=Path, default=ROOT / "reports/context/exp-ctx-001/saving.csv"
    )
    args = ap.parse_args()
    version = _version()
    sprint = tomllib.loads((ROOT / "config/evaluation/sprint.toml").read_text())
    base = sprint["baselines"]
    prices = tomllib.loads((ROOT / base["price_table"]).read_text())
    catalogue = tomllib.loads((ROOT / base["catalogue"]).read_text())
    ctx = ReplayContext(
        period_bounds=period_bounds_from_config(sprint["periods"]),
        price_table=prices,
        catalogue=catalogue,
        seed=sprint["split"]["seed"],
        min_n=sprint["sufficiency"]["min_n"],
    )
    ledger = pd.read_csv(TABLES / "claims_ledger.csv").set_index("claim_id")
    coef = float(ledger.loc[LEDGER_ROW, "value"])
    rate_table = pd.read_csv(TABLES / "implied_unit_rates.csv")
    rates = rate_table.dropna(subset=["implied_input_per_M"]).set_index("model")
    rates = rates["implied_input_per_M"].astype(float).to_dict()

    req = scope(pd.read_parquet(DERIVED / "requests.parquet", columns=REQ_COLUMNS), ctx)
    req["split"] = split_by_session(req, seed=ctx.seed)
    sep = cached_reported_separately(req)
    req = with_blocks(req[req["split"] == args.split])
    files = sorted(glob.glob(str(DERIVED / "chunks" / "*.parquet")))
    cols = ["message_id", "h_exact", "n_chars"]
    chunks = pd.concat([pd.read_parquet(f, columns=cols) for f in files])
    chunks = chunks[chunks["message_id"].isin(req["ai_message_id"])]
    chunks = chunks.reset_index(drop=True)

    dedup = version.WithinMessageDedup(
        chunks, tokens_per_char=coef, input_rate_per_m=rates, cached_separately=sep
    )
    out = combine(req, None, dedup, None, ctx)
    premium = base["premium_model"]
    cheap = best_single_cheap_model(req, ctx, cached_separately=sep)
    full = baseline_costs(req, ctx, premium_model=premium, cached_separately=sep)
    code = code_version(ROOT)
    commit = code.commit if code.commit and not code.dirty else "unknown"
    created = datetime.now(UTC).replace(microsecond=0)
    llm = req["llm_request"].astype(bool)
    print(
        f"split {args.split}: requests {len(req)}, LLM {int(llm.sum())}; "
        f"tokens per char {coef:.4f}; LLM rows with an implied rate "
        f"{int(req.loc[llm, 'bot_provider_model'].isin(rates).sum())}; "
        f"cached reported separately: {len(sep)} models; best single cheap {cheap}"
    )

    rows = []
    args.levers_dir.mkdir(parents=True, exist_ok=True)
    for key in BASELINE_KEYS:
        before, after = version.baseline_frames(
            req,
            out,
            ctx,
            baseline=key,
            premium_model=premium,
            cached_separately=sep,
            cheap_model=cheap,
        )
        config = {
            "version": version.VERSION_ID,
            "baseline": key,
            "split": args.split,
            "tokens_per_char": coef,
            "tokens_per_char_source": LEDGER_ROW,
            "premium_model": premium,
            "best_single_cheap": cheap,
            "cached_separately": sorted(sep),
            "sprint": sprint["version"],
        }
        run_ctx = ctx
        if key == "as_logged":
            run_ctx = dataclasses.replace(ctx, price_table={"version": RATES_VERSION})
        manifest = build_manifest(
            config,
            run_ctx,
            code_commit=commit,
            python_version=platform.python_version(),
            created_at=created,
        )
        result = version.lever_result(
            before,
            after,
            baseline=key,
            manifest=manifest,
            assumptions=_assumptions(coef, key),
        )
        result = enrich(result, before, after, out, cached_separately=sep)
        path = args.levers_dir / f"{result.lever_id}.json"
        path.write_text(result.to_json())
        for name in ("all", "llm_only"):
            s = result.slices[name]
            rows.append(
                {
                    "split": args.split,
                    "baseline": key,
                    "unit": "recorded" if key == "as_logged" else "price-file",
                    "slice": name,
                    "n_requests": s["n_requests"],
                    "n_cost_known": s["n_cost_known"],
                    "n_saving_unknown": s["n_saving_unknown"],
                    "n_baseline_unknown": full[key]["n_unknown"],
                    "n_eligible": result.n_eligible,
                    "saved_input_tokens": s["saved_input_tokens"],
                    "baseline_total_known": s["baseline:total"],
                    "saving_token_cost": s["saving:token_cost"],
                    "saving_fees": s["saving:fees"],
                    "saving_share": s.get("saving_share"),
                    "baseline_total_all_known_cost": full[key]["total"],
                }
            )
    table = pd.DataFrame(rows)
    money = table.columns[table.columns.get_loc("saved_input_tokens") :]
    table[money] = table[money].astype(float)
    args.table.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.table, index=False, float_format="%.6f")
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(table.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
