"""Checks and lever results of EXP-ROUTE-012 small classifier, rules mode (R-C3).

Reads ``requests.parquet``, scopes it and splits it by session
(``replay_scope``). Eligibility and candidate cost come from
``analysis.routing_base`` with ``sprint.toml [routing]`` and the
``[baselines]`` catalogue and price table. ``as_logged`` prices the routed
model at its implied rates (``reports/full_eda/tables/implied_unit_rates.csv``,
recorded units).

1. ``--checks-only``: free checks on the tune split, LLM rows only, written to
   ``reports/routing/exp-route-012/tune_checks.json`` (aggregates): the
   ``max_input_tokens`` grid and its least-aggressive choice (all tune rows and
   per session-grouped fold), share marked simple, share moved and to which
   candidate, saving per baseline (primary and secondary), concentration.
2. Otherwise: applies both versions (``VERSIONS``) with the thresholds frozen
   in the README (``MAX_U_CHARS``, ``MAX_INPUT_TOKENS``) to ``--split``
   (default ``report``, read once) and writes one ``LeverResult`` per version
   and baseline to ``--levers-dir`` (default ``reports/levers/``). Run it on a
   clean tree, so the manifest carries the code commit.

No IDs, hashes or text are written or printed.

    .venv/bin/python scripts/small_classifier_levers.py --checks-only
    .venv/bin/python scripts/small_classifier_levers.py
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

import numpy as np
import pandas as pd

from metis_auto.analysis.baselines_full import (
    BASELINE_KEYS,
    best_single_cheap_model,
    cached_reported_separately,
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
EXP = ROOT / "experiments/routing/exp-route-012-small-classifier"
DERIVED = ROOT / "data/derived/full_eda"
TABLES = ROOT / "reports/full_eda/tables"
CHECKS = ROOT / "reports/routing/exp-route-012/tune_checks.json"
RATES_VERSION = "full-eda-implied-unit-rates"
MAX_U_CHARS = 200
"""EDA rule feature (``scripts/full_eda_analyze.py``, claim
``route.simple_rule_share``): ``u_n_chars <= 200``."""
MAX_INPUT_TOKENS = 16000
"""Chosen on the tune split by ``least_aggressive`` over ``TOKEN_GRID``
(tolerance ``TOLERANCE``), 2026-11-03; frozen in the README before any
report-split run (``reports/routing/exp-route-012/tune_checks.json``)."""
TOKEN_GRID = (500, 1000, 2000, 4000, 8000, 16000, 32000)
TOLERANCE = 0.01
CHECK_FOLDS = 5
VERSIONS: Mapping[str, bool] = {"primary": False, "with_reasoning_models": True}
"""Candidate set name -> include_reasoning_models. The primary drives the
decision; the secondary is a lower bound on candidate cost."""
REQ_COLUMNS = [
    "session_id",
    "turn",
    "a_order",
    "a_timestamp",
    "bot_id",
    "user_id",
    "u_h_norm",
    "u_n_chars",
    "u_lang",
    "n_prior_msgs",
    "prior_chars",
    "a_rag_n_queries",
    "u_att_n",
    "bot_n_functions",
    "bot_ins_n_chars",
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
    name = "exp_route_012_version"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, EXP / "version.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def make_versions(
    rules: Mapping[str, Any],
    catalogue: Mapping[str, Any],
    *,
    max_u_chars: float,
    max_input_tokens: float,
    cached_separately: frozenset[str],
) -> dict[str, Any]:
    v = _version()
    sets = v.candidate_sets(rules, catalogue)
    return {
        name: v.SmallClassifier(
            "rules",
            rules=rules,
            candidates=sets[name],
            cached_separately=cached_separately,
            max_u_chars=max_u_chars,
            max_input_tokens=max_input_tokens,
            include_reasoning_models=include,
        )
        for name, include in VERSIONS.items()
    }


def write_levers(
    req: pd.DataFrame,
    *,
    ctx: ReplayContext,
    rules: Mapping[str, Any],
    rates: Mapping[str, Mapping[str, float]],
    max_u_chars: float,
    max_input_tokens: float,
    premium_model: str,
    out_dir: Path,
    code_commit: str,
    python_version: str,
    created_at: datetime,
    cached_separately: frozenset[str],
    min_n: int | None,
    tenant_cap: float,
    config_extra: Mapping[str, object] = {},
) -> list[Path]:
    """Apply both versions to ``req`` (scoped, one split, with blocks) and write
    one ``LeverResult`` per version and baseline into ``out_dir``."""
    v = _version()
    sep = cached_separately
    cheap = best_single_cheap_model(req, ctx, cached_separately=sep)
    versions = make_versions(
        rules,
        ctx.catalogue,
        max_u_chars=max_u_chars,
        max_input_tokens=max_input_tokens,
        cached_separately=sep,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for set_name, version in versions.items():
        out = combine(req, None, None, version, ctx)
        for key in BASELINE_KEYS:
            before, after = v.baseline_frames(
                req,
                out,
                ctx,
                baseline=key,
                premium_model=premium_model,
                cached_separately=sep,
                cheap_model=cheap,
                rates=rates,
            )
            config = {
                "version": version.name,
                "mode": version.mode,
                "candidate_set": set_name,
                "candidates": list(version.candidates),
                "max_u_chars": max_u_chars,
                "max_input_tokens": max_input_tokens,
                "baseline": key,
                "premium_model": premium_model,
                "best_single_cheap": cheap,
                "cached_separately": sorted(sep),
                "min_n": min_n,
                "tenant_cap": tenant_cap,
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
                assumptions=v.assumptions(key, version),
                min_n=min_n,
                tenant_cap=tenant_cap,
            )
            path = out_dir / f"{result.lever_id}.json"
            path.write_text(result.to_json())
            paths.append(path)
    return paths


def _f(value: float | None) -> float | None:
    return None if value is None or not math.isfinite(value) else round(value, 6)


def _saving(v, req, out, ctx, key, *, premium, sep, cheap, rates) -> dict[str, Any]:
    """Baseline, saving and its share over LLM rows with a known cost."""
    before, after = v.baseline_frames(
        req,
        out,
        ctx,
        baseline=key,
        premium_model=premium,
        cached_separately=sep,
        cheap_model=cheap,
        rates=rates,
    )
    cols = ["block_fees", "block_token_cost"]
    known = before[cols].notna().all(axis=1) & req["llm_request"].astype(bool)
    base = before.loc[known, cols].sum(axis=1)
    save = base - after.loc[known, cols].sum(axis=1)
    total = math.fsum(base)
    res = {
        "baseline": _f(total),
        "saving": _f(math.fsum(save)),
        "saving_share": _f(math.fsum(save) / total) if total else None,
        "n_moved": int(after[v.MOVED_B].sum()),
        "n_saving_unknown": int(after[v.SAVING_UNKNOWN].sum()),
    }
    if math.fsum(save) > 0:
        by_bot = save.groupby(req.loc[known, "bot_id"]).sum().sort_values()[::-1]
        by_tenant = save.groupby(req.loc[known, "user_id"]).sum().max()
        res["saving_share_top_bot"] = _f(by_bot.iloc[:1].sum() / math.fsum(save))
        res["saving_share_top5_bots"] = _f(by_bot.iloc[:5].sum() / math.fsum(save))
        res["saving_share_top_tenant"] = _f(by_tenant / math.fsum(save))
    return res


def checks(
    req: pd.DataFrame,
    *,
    ctx: ReplayContext,
    rules: Mapping[str, Any],
    rates: Mapping[str, Mapping[str, float]],
    premium_model: str,
    cached_separately: frozenset[str],
    max_input_tokens: float | None,
) -> dict[str, Any]:
    """Free checks on one split (aggregates; LLM rows in every numerator)."""
    v = _version()
    sep = cached_separately
    llm = req["llm_request"].astype(bool)
    n_all, n_llm = len(req), int(llm.sum())
    cheap = best_single_cheap_model(req, ctx, cached_separately=sep)
    kw = dict(premium=premium_model, sep=sep, cheap=cheap, rates=rates)
    folds = v.component_folds(req, n_folds=CHECK_FOLDS, seed=ctx.seed)

    grid: dict[int, dict[str, Any]] = {}
    per_fold: dict[int, dict[int, dict[str, float]]] = {
        f: {} for f in range(CHECK_FOLDS)
    }
    for t in TOKEN_GRID:
        primary = make_versions(
            rules, ctx.catalogue, max_u_chars=MAX_U_CHARS, max_input_tokens=t,
            cached_separately=sep,
        )["primary"]  # fmt: skip
        out = combine(req, None, None, primary, ctx)
        s = _saving(v, req, out, ctx, "todays_models", **kw)
        moved = out[v.MOVED].fillna(False).astype(bool) & llm
        grid[t] = {
            "simple_share_llm": _f(out.loc[llm, v.SIMPLE].astype(bool).mean()),
            "moved_share": _f(moved.sum() / n_llm),
            "saving_share": s["saving_share"] or 0.0,
        }
        for f in range(CHECK_FOLDS):
            rows = folds.eq(f)
            sub = _saving(v, req[rows], out[rows], ctx, "todays_models", **kw)
            per_fold[f][t] = {
                "moved_share": float((moved & rows).sum() / (llm & rows).sum()),
                "saving_share": sub["saving_share"] or 0.0,
            }
    chosen = v.least_aggressive(grid, tolerance=TOLERANCE)
    fold_choice = {
        str(f): v.least_aggressive(per_fold[f], tolerance=TOLERANCE)
        for f in range(CHECK_FOLDS)
    }
    frozen = chosen if max_input_tokens is None else max_input_tokens

    versions = make_versions(
        rules, ctx.catalogue, max_u_chars=MAX_U_CHARS, max_input_tokens=frozen,
        cached_separately=sep,
    )  # fmt: skip
    rag = pd.to_numeric(req["a_rag_n_queries"], errors="coerce")
    result: dict[str, Any] = {
        "requests_all": n_all,
        "requests_llm": n_llm,
        "rule_features_unknown_share_llm": {
            c: _f(pd.to_numeric(req.loc[llm, c], errors="coerce").isna().mean())
            for c in ("u_n_chars", "a_rag_n_queries", "u_att_n", "bot_n_functions")
        },
        "rag_query_share_llm": _f((rag[llm] > 0).mean()),
        "token_grid": {str(t): g for t, g in grid.items()},
        "chosen_max_input_tokens": chosen,
        "chosen_per_fold": fold_choice,
        "frozen_max_input_tokens": frozen,
        "versions": {},
    }
    for name, version in versions.items():
        out = combine(req, None, None, version, ctx)
        simple = out[v.SIMPLE].fillna(False).astype(bool) & llm
        moved = out[v.MOVED].fillna(False).astype(bool) & llm
        result["versions"][name] = {
            "version": version.name,
            "candidates": list(version.candidates),
            "simple_share_all": _f(simple.sum() / n_all),
            "simple_share_llm": _f(simple.sum() / n_llm),
            "moved_share_all": _f(moved.sum() / n_all),
            "moved_share_llm": _f(moved.sum() / n_llm),
            "moved_to": {
                str(m): int(n)
                for m, n in out.loc[moved, v.TARGET].value_counts().sort_index().items()
            },
            "reasons_llm": {
                str(r): int(n)
                for r, n in out.loc[llm, v.REASON].value_counts().sort_index().items()
            },
            "baselines": {
                key: _saving(v, req, out, ctx, key, **kw) for key in BASELINE_KEYS
            },
        }
    return result


def load_rates(path: Path) -> dict[str, dict[str, float]]:
    """Implied recorded-unit rates per 1M tokens by logged model (NaN = none)."""
    t = pd.read_csv(path).set_index("model")
    return {
        str(m): {
            "input": float(r["implied_input_per_M"]),
            "output": float(r["implied_output_per_M"]),
            "cached": float(r["implied_cached_per_M"])
            if pd.notna(r["implied_cached_per_M"])
            else np.nan,
        }
        for m, r in t.iterrows()
    }


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
    sprint = tomllib.loads((ROOT / "config/evaluation/sprint.toml").read_text())
    base = sprint["baselines"]
    rules = sprint["routing"]
    ctx = ReplayContext(
        period_bounds=period_bounds_from_config(sprint["periods"]),
        price_table=tomllib.loads((ROOT / base["price_table"]).read_text()),
        catalogue=tomllib.loads((ROOT / base["catalogue"]).read_text()),
        seed=sprint["split"]["seed"],
        min_n=sprint["sufficiency"]["min_n"],
    )
    rates = load_rates(TABLES / "implied_unit_rates.csv")
    req, sep = _load(ctx)
    if args.checks_only:
        tune = req[(req["split"] == "tune") & (req["period"] == "tune")]
        summary = checks(
            tune,
            ctx=ctx,
            rules=rules,
            rates=rates,
            premium_model=base["premium_model"],
            cached_separately=sep,
            max_input_tokens=MAX_INPUT_TOKENS,
        )
        summary |= {
            "split": "tune (split_by_session tune rows inside the tune period)",
            "max_u_chars": MAX_U_CHARS,
            "tolerance": TOLERANCE,
            "naive_timestamps": "Q-06",
            "evidence": "simulation; quality not proven (no labels)",
        }
        args.checks.parent.mkdir(parents=True, exist_ok=True)
        args.checks.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n")
        print(json.dumps(summary, sort_keys=True, indent=2))
        return 0
    if MAX_INPUT_TOKENS is None:
        raise SystemExit("MAX_INPUT_TOKENS is not frozen yet: run --checks-only first")
    code = code_version(ROOT)
    split = req[(req["split"] == args.split) & (req["period"] == args.split)]
    paths = write_levers(
        split,
        ctx=ctx,
        rules=rules,
        rates=rates,
        max_u_chars=MAX_U_CHARS,
        max_input_tokens=MAX_INPUT_TOKENS,
        premium_model=base["premium_model"],
        out_dir=args.levers_dir,
        code_commit=code.commit if code.commit and not code.dirty else "unknown",
        python_version=platform.python_version(),
        created_at=datetime.now(UTC).replace(microsecond=0),
        cached_separately=sep,
        min_n=ctx.min_n,
        tenant_cap=sprint["sample"]["tenant_cap"],
        config_extra={"split": args.split, "sprint": sprint["version"]},
    )
    print(f"wrote {len(paths)} lever results to {args.levers_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
