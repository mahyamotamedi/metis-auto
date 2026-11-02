"""Checks and lever results of EXP-CTX-004 history budget, stepped window (R-C2).

Reads ``requests.parquet``, scopes it and splits it by session
(``replay_scope``). The turn-0 base per bot is fitted on the **tune** split
only (``min_n`` from ``sprint.toml``); per-turn sizes come from every logged
turn of the session. History tokens follow ADR-0044:
excess over the bot's turn-0 base less chunk tokens (characters x the ledger
coefficient ``recon.t0rag.coef_rag``). ``as_logged`` is priced at each model's
``implied_input_per_M`` and ``implied_cached_per_M``
(``reports/full_eda/tables/implied_unit_rates.csv``); repriced baselines lower
input and reprice (ADR-0038).

1. ``--checks-only``: free checks on the tune split, LLM rows only, written to
   ``reports/context/exp-ctx-004/tune_checks.json`` (aggregates).
2. Otherwise: applies every variant in ``VARIANTS`` (frozen in the README) to
   ``--split`` (default ``report``, read once) and writes one ``LeverResult``
   per variant and baseline to ``reports/levers/``. Run it on a clean tree, so
   the manifest carries the code commit.

No IDs, hashes or text are written or printed.

    .venv/bin/python scripts/history_budget_levers.py --checks-only
    .venv/bin/python scripts/history_budget_levers.py
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import math
import platform
import sys
import tomllib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from metis_auto.analysis.baselines_full import (
    BASELINE_KEYS,
    best_single_cheap_model,
    cached_reported_separately,
    token_counts,
)
from metis_auto.analysis.lever_result import build_manifest
from metis_auto.analysis.levers import ReplayContext, combine, with_blocks
from metis_auto.analysis.replay_scope import (
    period_bounds_from_config,
    scope,
    split_by_session,
)
from metis_auto.wiring.experiments import code_version

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments/context/exp-ctx-004-history-budget"
DERIVED = ROOT / "data/derived/full_eda"
TABLES = ROOT / "reports/full_eda/tables"
CHECKS = ROOT / "reports/context/exp-ctx-004/tune_checks.json"
LEDGER_ROW = "recon.t0rag.coef_rag"
RATES_VERSION = "full-eda-implied-unit-rates"
VARIANTS: Mapping[str, tuple[str, int, int]] = {
    "b2000": ("budget", 2000, 1),
    "b4000": ("budget", 4000, 1),
    "b8000": ("budget", 8000, 1),
    "half_over_8k": ("half", 8000, 1),
}
"""Name -> (kind, budget_tokens or min_input_tokens, step_turns). Frozen in the
README before any report-split run (owner decision 6, 2026-11-02)."""
TURN_BUCKETS = ((1, 1, "1"), (2, 2, "2"), (3, 4, "3-4"), (5, 9, "5-9"))
TURN_BUCKETS += ((10, 19, "10-19"), (20, None, "20+"))
REQ_COLUMNS = [
    "session_id",
    "turn",
    "a_order",
    "a_timestamp",
    "bot_id",
    "user_id",
    "u_h_norm",
    "u_n_chars",
    "a_n_chars",
    "a_rag_chunk_chars",
    "bot_provider_name",
    "bot_provider_model",
    "bot_memory_enabled",
    "bot_summarizer_mode",
    "a_billing_state",
    "a_bill_inputTokens",
    "a_bill_cachedInputTokens",
    "a_bill_outputTokens",
    "a_bill_callCount",
    "a_bill_totalCost",
    "a_n_per_call_only_items",
]


def _version():
    name = "exp_ctx_004_version"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, EXP / "version.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def make_version(spec: tuple[str, int, int], **kwargs):
    kind, size, step_turns = spec
    v = _version()
    if kind == "budget":
        return v.HistoryBudget(size, step_turns, **kwargs)
    if kind == "half":
        return v.HalfOnLong(size, step_turns, **kwargs)
    raise ValueError(f"unknown variant kind {kind}")


def assumptions(baseline: str, coef: float) -> tuple[str, ...]:
    price = (
        "as_logged: removed cached tokens at the model's implied_cached_per_M, "
        "uncached at implied_input_per_M (implied_unit_rates.csv, recorded units); "
        "a missing rate is unknown and leaves both sides, never zero."
        if baseline == "as_logged"
        else "Repriced: logged tokens less removed tokens (cached first) at the "
        "price table's tiers. Fees are not priced in price-file units (ADR-0036), "
        "so baseline_cost has no fees key."
    )
    return (
        "tokens only, quality not measured (FR-CTX-03).",
        "History tokens = effective input - bot's tune turn-0 median (net of "
        f"chunks) - chunk chars x {coef:.4f} (ledger {LEDGER_ROW}): hypothetical "
        "reconstruction and an upper bound (it holds message growth too).",
        "Per-turn sizes: history spread over earlier turns by logged characters, "
        "most recent turns assumed sent (hypothetical); oldest whole turns dropped.",
        "Removed tokens come out of cached input first, then uncached; the "
        "uncached-only rule is the upper-bound sensitivity (slice history_budget).",
        "Excluded, no saving: workflow, turn 0, memory and summarising bots, "
        "gated rows, multi-call requests, bots under min_n turn-0 rows (unknown).",
        "Dropping old turns may break the provider-cached prefix for the rest of "
        "the conversation: not measured.",
        price,
        "Fees unchanged; once per request. Metis's own history policy is unknown "
        "(EDA §2): the saving is an upper bound on what a budget could remove.",
    )


def write_levers(
    req: pd.DataFrame,
    *,
    turns: pd.DataFrame,
    turn0_base: Mapping[str, float] | pd.Series,
    ctx: ReplayContext,
    variants: Mapping[str, tuple[str, int, int]],
    tokens_per_char: float,
    input_rate_per_m: Mapping[str, float],
    cached_rate_per_m: Mapping[str, float],
    premium_model: str,
    out_dir: Path,
    code_commit: str,
    python_version: str,
    created_at: datetime,
    config_extra: Mapping[str, object] = {},
    cached_separately: frozenset[str] | None = None,
) -> list[Path]:
    """Apply every variant to ``req`` (scoped, one split, with blocks) and write
    one ``LeverResult`` per variant and baseline into ``out_dir``."""
    v = _version()
    sep = (
        cached_reported_separately(req)
        if cached_separately is None
        else cached_separately
    )
    cheap = best_single_cheap_model(req, ctx, cached_separately=sep)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, spec in variants.items():
        version = make_version(
            spec,
            turns=turns,
            turn0_base=turn0_base,
            tokens_per_char=tokens_per_char,
            input_rate_per_m=input_rate_per_m,
            cached_rate_per_m=cached_rate_per_m,
            cached_separately=sep,
        )
        out = combine(req, None, version, None, ctx)
        for key in BASELINE_KEYS:
            before, after = v.baseline_frames(
                req,
                out,
                ctx,
                baseline=key,
                premium_model=premium_model,
                cached_separately=sep,
                cheap_model=cheap,
            )
            config = {
                "version": version.name,
                "variant": name,
                "kind": spec[0],
                "size_tokens": spec[1],
                "step_turns": spec[2],
                "baseline": key,
                "tokens_per_char": tokens_per_char,
                "tokens_per_char_source": LEDGER_ROW,
                "turn0_base_fitted_on": "tune",
                "removal_rule": "cached first, then uncached",
                "premium_model": premium_model,
                "best_single_cheap": cheap,
                "cached_separately": sorted(sep),
            } | dict(config_extra)
            run_ctx = ctx
            if key == "as_logged":
                run_ctx = dataclasses.replace(
                    ctx, price_table={"version": RATES_VERSION}
                )
            manifest = build_manifest(
                config,
                run_ctx,
                code_commit=code_commit,
                python_version=python_version,
                created_at=created_at,
            )
            result = v.lever_result(
                before,
                after,
                out,
                version_id=version.name,
                baseline=key,
                manifest=manifest,
                assumptions=assumptions(key, tokens_per_char),
            )
            path = out_dir / f"{result.lever_id}.json"
            path.write_text(result.to_json())
            paths.append(path)
    return paths


def _q(values: pd.Series, q: float) -> float | None:
    return None if values.empty else float(values.quantile(q))


def _f(value: float) -> float:
    return round(float(value), 6)


def checks(
    req: pd.DataFrame,
    *,
    turns: pd.DataFrame,
    turn0_base: Mapping[str, float] | pd.Series,
    ctx: ReplayContext,
    tokens_per_char: float,
    input_rate_per_m: Mapping[str, float],
    cached_rate_per_m: Mapping[str, float],
    cached_separately: frozenset[str],
) -> dict[str, Any]:
    """Free checks on one split (aggregates): history tokens, turn buckets, the
    over-8k slice and each variant's reduction. LLM rows only in numerators."""
    v = _version()
    kwargs = dict(
        turns=turns,
        turn0_base=turn0_base,
        tokens_per_char=tokens_per_char,
        input_rate_per_m=input_rate_per_m,
        cached_rate_per_m=cached_rate_per_m,
        cached_separately=cached_separately,
    )
    llm = req["llm_request"].astype(bool)
    first = combine(req, None, make_version(VARIANTS["b2000"], **kwargs), None, ctx)
    state = first[v.HIST_STATE].where(llm)
    hist = first[v.HIST_TOKENS].where(state.eq("known"))
    eff = token_counts(req, cached_separately)["input"]
    buckets = {}
    for lo, hi, label in TURN_BUCKETS:
        in_b = req["turn"].ge(lo) & (req["turn"].le(hi) if hi else True)
        h = hist[in_b].dropna()
        buckets[label] = {
            "n_known": int(h.size),
            "median": _q(h, 0.5),
            "p90": _q(h, 0.9),
            "share_positive": _f((h > 0).mean()) if h.size else None,
        }
    over = llm & eff.gt(v.OVER_8K_TOKENS)
    over_known = over & state.eq("known")
    result: dict[str, Any] = {
        "requests_all": int(len(req)),
        "requests_llm": int(llm.sum()),
        "llm_by_state": {s: int(state.eq(s).sum()) for s in v.STATES},
        "turn0_base_bots": int(len(turn0_base)),
        "hist_positive_share_of_llm": _f((hist > 0).sum() / llm.sum()),
        "hist_positive_share_of_known": _f((hist > 0).sum() / hist.notna().sum()),
        "hist_by_turn_bucket": buckets,
        "over_8k": {
            "requests_llm": int(over.sum()),
            "requests_known": int(over_known.sum()),
            "llm_by_state": {s: int((over & state.eq(s)).sum()) for s in v.STATES},
            "input_tokens_known": _f(eff[over_known].sum()),
            "hist_tokens_known": _f(hist[over_known].sum()),
            "hist_share_of_input_known": _f(
                hist[over_known].sum() / eff[over_known].sum()
            )
            if over_known.any()
            else None,
            "hist_share_of_input_all_over_8k": _f(
                hist[over_known].sum() / eff[over].sum()
            )
            if over.any()
            else None,
        },
        "variants": {},
    }
    base_cost = math.fsum(req.loc[llm, "block_token_cost"].dropna())
    for name, spec in VARIANTS.items():
        out = combine(req, None, make_version(spec, **kwargs), None, ctx)
        known = out[v.SAVING_KNOWN].fillna(False).astype(bool) & llm
        cut = (req["block_token_cost"] - out["block_token_cost"]).where(known)
        result["variants"][name] = {
            "requests_reduced": int((llm & out[v.SAVED].gt(0)).sum()),
            "requests_reduced_over_8k": int((over & out[v.SAVED].gt(0)).sum()),
            "tokens_removed_primary": _f(out.loc[llm, v.SAVED].sum()),
            "tokens_removed_from_cached": _f(out.loc[llm, v.SAVED_CACHED].sum()),
            "tokens_removed_uncached_only": _f(
                out.loc[llm, v.SAVED_UNCACHED_ONLY].sum()
            ),
            "as_logged_saving_primary": _f(math.fsum(cut.dropna())),
            "as_logged_saving_uncached_only": _f(
                math.fsum(out.loc[known, v.CUT_UNCACHED_ONLY].dropna())
            ),
            "as_logged_saving_unknown_rows": int(
                (llm & out[v.SAVED].gt(0) & ~known).sum()
            ),
            "as_logged_token_cost_llm_known": _f(base_cost),
        } | {k: _f(x) for k, x in v.concentration(out, llm).items()}
    return result


def _load(ctx: ReplayContext) -> tuple[pd.DataFrame, frozenset[str]]:
    req = scope(pd.read_parquet(DERIVED / "requests.parquet", columns=REQ_COLUMNS), ctx)
    req["split"] = split_by_session(req, seed=ctx.seed)
    return with_blocks(req), cached_reported_separately(req)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--checks-only", action="store_true")
    ap.add_argument("--split", default="report", choices=("tune", "report"))
    ap.add_argument("--levers-dir", type=Path, default=ROOT / "reports/levers")
    ap.add_argument("--checks", type=Path, default=CHECKS)
    args = ap.parse_args()
    v = _version()
    sprint = tomllib.loads((ROOT / "config/evaluation/sprint.toml").read_text())
    base = sprint["baselines"]
    ctx = ReplayContext(
        period_bounds=period_bounds_from_config(sprint["periods"]),
        price_table=tomllib.loads((ROOT / base["price_table"]).read_text()),
        catalogue=tomllib.loads((ROOT / base["catalogue"]).read_text()),
        seed=sprint["split"]["seed"],
        min_n=sprint["sufficiency"]["min_n"],
    )
    ledger = pd.read_csv(TABLES / "claims_ledger.csv").set_index("claim_id")
    coef = float(ledger.loc[LEDGER_ROW, "value"])
    rates = pd.read_csv(TABLES / "implied_unit_rates.csv").set_index("model")
    in_rates = rates["implied_input_per_M"].dropna().astype(float).to_dict()
    cached_rates = rates["implied_cached_per_M"].dropna().astype(float).to_dict()
    turns, sep = _load(ctx)
    tune = turns[turns["split"] == "tune"]
    t0 = v.turn0_base(
        tune, tokens_per_char=coef, min_n=ctx.min_n, cached_separately=sep
    )
    common = dict(
        turns=turns,
        turn0_base=t0,
        ctx=ctx,
        tokens_per_char=coef,
        input_rate_per_m=in_rates,
        cached_rate_per_m=cached_rates,
    )
    if args.checks_only:
        summary = checks(tune, cached_separately=sep, **common)
        summary |= {"split": "tune", "tokens_per_char": coef, "min_n": ctx.min_n}
        args.checks.parent.mkdir(parents=True, exist_ok=True)
        args.checks.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n")
        print(json.dumps(summary, sort_keys=True, indent=2))
        return 0
    code = code_version(ROOT)
    split = turns[turns["split"] == args.split]
    paths = write_levers(
        split,
        variants=VARIANTS,
        premium_model=base["premium_model"],
        out_dir=args.levers_dir,
        code_commit=code.commit if code.commit and not code.dirty else "unknown",
        python_version=platform.python_version(),
        created_at=datetime.now(UTC).replace(microsecond=0),
        config_extra={
            "split": args.split,
            "turn0_base_min_n": ctx.min_n,
            "sprint": sprint["version"],
        },
        cached_separately=sep,
        **common,
    )
    print(f"wrote {len(paths)} lever results to {args.levers_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
