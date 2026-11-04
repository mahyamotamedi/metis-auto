"""Lever results of the rules-only decision router, EXP-ROUTE-013 (sprint final
Stage 2; ADR-0047 point 4, A-118, A-121).

    .venv/bin/python scripts/decision_router_levers.py derive      # text -> flags
    .venv/bin/python scripts/decision_router_levers.py run --split tune
    .venv/bin/python scripts/decision_router_levers.py run --split report

``router.mode = "off"``: nothing is called and nothing is spent. The script
refuses to run unless the router is off, no dataset text is approved for hosted
use, unpriced router calls are off and live calls are disabled; it loads the
settings hermetically (no ``.env``, no runtime file). Tiers come from the real
domain policy (gate, then rule-based fallback, then safe tier) over three flags
per user message that ``derive`` computes in memory from the raw user text with
the configured detectors and writes, without text, to the git-ignored
``data/derived/routing/decision_router_flags.parquet``.

``run`` computes the tiers for the whole scoped table, routes the chosen split
through ``DecisionRouterRouting`` on R-0's routing base (primary candidates,
reasoning-billed models excluded, ADR-0046 point 4) and writes one
``LeverResult`` per baseline to ``reports/levers/``, accounted per baseline
exactly as R-C3 (ADR-0046 points 5 and 6: the incumbent is the baseline's model,
a move needs a strictly cheaper target in the baseline's units). Aggregates
only: no text, ID or hash is written or printed.

Thin wrapper: tiers in ``experiments/routing/exp-route-013-decision-router/
rules_only.py``, the step version in ``version.py``, accounting from
``exp-route-012-small-classifier/version.py`` (``baseline_frames``).
"""

from __future__ import annotations

import argparse
import glob
import importlib.util
import platform
import sys
import tomllib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from metis_auto.analysis.baselines_full import (
    BASELINE_KEYS,
    best_single_cheap_model,
    cached_reported_separately,
)
from metis_auto.analysis.lever_enrich import enrich
from metis_auto.analysis.lever_result import LeverResult, Manifest, build_manifest
from metis_auto.analysis.levers import (
    BLOCKS,
    ReplayContext,
    combine,
    summarise_slices,
    with_blocks,
)
from metis_auto.analysis.replay_scope import (
    period_bounds_from_config,
    scope,
    split_by_session,
)
from metis_auto.settings import load_settings
from metis_auto.wiring.experiments import code_version
from metis_auto.wiring.from_settings import pipeline_config

ROOT = Path(__file__).resolve().parents[1]
EXP13 = ROOT / "experiments/routing/exp-route-013-decision-router"
EXP12 = ROOT / "experiments/routing/exp-route-012-small-classifier"
DERIVED = ROOT / "data/derived/full_eda"
RAW = ROOT / "data/full_data/raw/data"
TABLES = ROOT / "reports/full_eda/tables"
FLAGS = ROOT / "data/derived/routing/decision_router_flags.parquet"
VERSION_ID = "route.decision_router.rules_only"
RATES_VERSION = "full-eda-implied-unit-rates"
USER_TYPE = "USER"
REPRICED_KEYS = ("premium_gpt_5_5", "todays_models", "best_single_cheap")
REQ_COLUMNS = [
    "session_id",
    "user_message_id",
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
    "n_skipped_user",
]


def _module(name: str, path: Path) -> Any:
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


rules_only = _module("exp_route_013_rules_only", EXP13 / "rules_only.py")


def _router():
    return _module("exp_route_013_version", EXP13 / "version.py")


def _classifier():
    return _module("exp_route_012_version", EXP12 / "version.py")


# --- flags ------------------------------------------------------------------------


def derive(raw: Path, out: Path, cfg: Any) -> pd.DataFrame:
    """Flags of the ``USER`` messages of every shard under ``raw``, in memory,
    written without text to ``out`` (first row per ``message_id``)."""
    shards = sorted(glob.glob(str(raw / "chat_message-*.parquet")))
    if not shards:
        raise SystemExit(f"no message shards under {raw}")
    parts = []
    for shard in shards:
        m = pd.read_parquet(shard, columns=["message_id", "type", "content"])
        m = m[m["type"].eq(USER_TYPE)]
        parts.append(
            rules_only.derive_flags(
                m["message_id"].tolist(), m["content"].tolist(), cfg.features
            )
        )
        del m
    table = pd.concat(parts).drop_duplicates("message_id").reset_index(drop=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(out, index=False)
    return table


# --- accounting -------------------------------------------------------------------


def _accounting_frame(out: pd.DataFrame, c12: Any) -> pd.DataFrame:
    """The columns R-C3's ``baseline_frames`` reads, from the router's target:
    a row is a candidate when its tier has an eligible target."""
    acc = pd.DataFrame(index=out.index)
    acc[c12.TARGET] = out["route_target"]
    acc[c12.TARGET_COST] = out["route_target_cost"]
    acc[c12.SIMPLE] = out["route_target"].notna()
    return acc


def assumptions(baseline: str, split: str, cached_note: str) -> tuple[str, ...]:
    unit = (
        "Unit: recorded units (as_logged). Incumbent: the recorded token cost; the "
        "target at its implied recorded rates (implied_unit_rates.csv, the "
        "ADR-0038 pattern). A needed rate that is missing makes the saving "
        "unknown, never 0."
        if baseline == "as_logged"
        else f"Unit: price-file units ({baseline}). Fees are not priced, so "
        "baseline_cost has no fees key (ADR-0036). Incumbent: the baseline's model."
    )
    return (
        "quality not proven: no labels (P-1..P-3 not run); cost simulation only",
        rules_only.NO_BACKEND_NOTE + " (router.mode off, A-118)",
        "rules-only: THX-01 changed no decision on the 150-record dev slice "
        "(agreement 1.0 with the rules, A-121), so inline = the gate and rules",
        "Jev 72% tier accuracy on 100 SYNTHETIC requests is not evidence on real "
        "traffic (ADR-0047); Jev is never called here",
        "Tier -> model: the decided tier's cheapest candidate that R-0 allows "
        "(primary set, reasoning-billed models excluded, ADR-0046 point 4); a "
        "move needs a strictly cheaper target in the baseline's units; never upward",
        "Catalogue tiers are placeholders (A-48); the safe tier (1) decides every "
        "request no gate or rule marks, so most traffic goes to tier 1",
        "Flags has_code, has_coding_intent and is_greeting: a local in-memory pass "
        "with the configured detectors, no text kept; unknown text gives no tier",
        unit,
        "Fees unchanged by routing; rows not moved save exactly 0; requests with "
        "unknown cost are left out of both sides (n_cost_known).",
        "No threshold is tuned: the gate, rules and safe tier are the configured "
        f"placeholders; {split} split, timestamps naive (Q-06). {cached_note}",
    )


def lever_result(
    before: pd.DataFrame,
    after: pd.DataFrame,
    out: pd.DataFrame,
    *,
    baseline: str,
    manifest: Manifest,
    assumption_lines: Sequence[str],
    c12: Any,
    lever_id: str | None = None,
) -> LeverResult:
    """One ``LeverResult``: slices ``all``, ``llm_only`` and ``routing`` (counts
    of the apply reasons and of moved, unknown and eligible rows)."""
    slices = summarise_slices(before, after)
    llm = before["llm_request"].astype(bool)
    repriced = baseline in REPRICED_KEYS
    if repriced:
        for s in slices.values():
            del s["baseline:fees"]
    moved = after[c12.MOVED_B].astype(bool) & llm
    unknown = after[c12.SAVING_UNKNOWN].astype(bool) & llm
    routing: dict[str, Decimal] = {
        "n_moved": Decimal(int(moved.sum())),
        "n_saving_unknown": Decimal(int(unknown.sum())),
        "n_with_target": Decimal(int((llm & out["route_target"].notna()).sum())),
    }
    for reason, n in out.loc[llm, "route_reason"].value_counts().items():
        routing[f"reason:{reason}"] = Decimal(int(n))
    for model, n in (
        out.loc[moved.reindex(out.index, fill_value=False), "route_target"]
        .value_counts()
        .items()
    ):
        routing[f"moved_to:{model}"] = Decimal(int(n))
    slices["routing"] = routing
    top = slices["llm_only"]
    names = (*BLOCKS, "total")
    return LeverResult(
        lever_id=lever_id or f"{VERSION_ID}.{baseline}",
        step="routing",
        version=VERSION_ID,
        n_requests=len(before),
        n_eligible=int((llm & out["route_target"].notna()).sum()),
        baseline=baseline,
        baseline_cost={
            b: top[f"baseline:{b}"] for b in names if f"baseline:{b}" in top
        },
        saving={b: top[f"saving:{b}"] for b in names},
        slices=slices,
        evidence_class="simulation",
        correctness_state="unmeasured",
        assumptions=tuple(assumption_lines),
        manifest=manifest,
    )


def write_levers(
    req: pd.DataFrame,
    *,
    tiers: pd.Series,
    ctx: ReplayContext,
    rules: Mapping[str, Any],
    rates: Mapping[str, Mapping[str, float]],
    premium_model: str,
    out_dir: Path,
    code_commit: str,
    python_version: str,
    created_at: datetime,
    cached_separately: frozenset[str],
    split: str,
    tenant_cap: float,
    config_extra: Mapping[str, object] = {},
) -> list[Path]:
    """Route ``req`` (scoped, one split, with blocks) with the tiers and write
    one ``LeverResult`` per baseline into ``out_dir``. Returns the paths."""
    v13, c12 = _router(), _classifier()
    sep = cached_separately
    cat = ctx.catalogue
    primary = c12.candidate_sets(rules, cat)["primary"]
    tier_of = {
        str(m["model_id"]): int(m["tier"])
        for m in cat.get("models", [])
        if m.get("tier") is not None
    }
    primary_rules = {**rules, "candidates": list(primary), "candidates_jev": []}
    version = v13.DecisionRouterRouting(
        tiers=tiers,
        tier_of=tier_of,
        rules=primary_rules,
        cached_separately=sep,
        name=VERSION_ID,
    )
    out = combine(req, None, None, version, ctx)
    acc = _accounting_frame(out, c12)
    cheap = best_single_cheap_model(req, ctx, cached_separately=sep)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for key in BASELINE_KEYS:
        before, after = c12.baseline_frames(
            req,
            acc,
            ctx,
            baseline=key,
            premium_model=premium_model,
            cached_separately=sep,
            cheap_model=cheap,
            rates=rates,
        )
        run_ctx = ctx
        if key == "as_logged":
            import dataclasses

            run_ctx = dataclasses.replace(ctx, price_table={"version": RATES_VERSION})
        config = {
            "version": VERSION_ID,
            "baseline": key,
            "split": split,
            "candidates": list(primary),
            "tier_of": tier_of,
            "premium_model": premium_model,
            "best_single_cheap": cheap,
            "cached_separately": sorted(sep),
            "tenant_cap": tenant_cap,
            **dict(config_extra),
        }
        manifest = build_manifest(
            config,
            run_ctx,
            code_commit=code_commit,
            python_version=python_version,
            created_at=created_at,
        )
        result = lever_result(
            before,
            after,
            out,
            baseline=key,
            manifest=manifest,
            assumption_lines=assumptions(
                key, split, f"Candidates: {', '.join(primary)}."
            ),
            c12=c12,
            lever_id=(
                f"{VERSION_ID}.tune.{key}" if split == "tune" else f"{VERSION_ID}.{key}"
            ),
        )
        result = enrich(result, before, after, req, cached_separately=sep)
        path = out_dir / f"{result.lever_id}.json"
        path.write_text(result.to_json())
        paths.append(path)
    return paths


# --- main -------------------------------------------------------------------------


def load_rates(path: Path) -> dict[str, dict[str, float]]:
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=("derive", "run"))
    ap.add_argument("--split", default="tune", choices=("tune", "report"))
    ap.add_argument("--levers-dir", type=Path, default=ROOT / "reports/levers")
    ap.add_argument("--flags", type=Path, default=FLAGS)
    args = ap.parse_args()
    loaded = load_settings(environ={}, dotenv=None, runtime=None)  # no .env read
    rules_only.require_offline(loaded.settings)
    cfg = pipeline_config(loaded)
    if args.command == "derive":
        table = derive(RAW, args.flags, cfg)
        flagged = {
            "unknown": int(table["label_state"].ne("ok").sum()),
            "greeting": int(table["is_greeting"].sum()),
            "code": int(table["has_code"].sum()),
            "coding intent": int(table["has_coding_intent"].sum()),
        }
        summary = ", ".join(f"{k} {v}" for k, v in flagged.items())
        print(f"user messages {len(table)}, {summary}")
        return 0
    if not args.flags.exists():
        raise SystemExit(
            f"{args.flags} missing: run `decision_router_levers.py derive`"
        )
    sprint = tomllib.loads((ROOT / "config/evaluation/sprint.toml").read_text())
    base = sprint["baselines"]
    ctx = ReplayContext(
        period_bounds=period_bounds_from_config(sprint["periods"]),
        price_table=tomllib.loads((ROOT / base["price_table"]).read_text()),
        catalogue=tomllib.loads((ROOT / base["catalogue"]).read_text()),
        seed=sprint["split"]["seed"],
        min_n=sprint["sufficiency"]["min_n"],
    )
    req = scope(pd.read_parquet(DERIVED / "requests.parquet", columns=REQ_COLUMNS), ctx)
    req["split"] = split_by_session(req, seed=ctx.seed)
    req = with_blocks(req)
    sep = cached_reported_separately(req)
    tiers = rules_only.rules_only_tiers(req, pd.read_parquet(args.flags), cfg)
    rows = req[(req["split"] == args.split) & (req["period"] == args.split)]
    llm = rows["llm_request"].astype(bool)
    print(
        f"split {args.split}: requests {len(rows)}, LLM {int(llm.sum())}, "
        f"tier known {int(tiers.reindex(rows.index)[llm].notna().sum())}, "
        f"tier 0 {int(tiers.reindex(rows.index)[llm].eq(0).sum())}, "
        f"tier 1 {int(tiers.reindex(rows.index)[llm].eq(1).sum())}"
    )
    code = code_version(ROOT)
    paths = write_levers(
        rows,
        tiers=tiers,
        ctx=ctx,
        rules=sprint["routing"],
        rates=load_rates(TABLES / "implied_unit_rates.csv"),
        premium_model=base["premium_model"],
        out_dir=args.levers_dir,
        code_commit=code.commit if code.commit and not code.dirty else "unknown",
        python_version=platform.python_version(),
        created_at=datetime.now(UTC).replace(microsecond=0),
        cached_separately=sep,
        split=args.split,
        tenant_cap=sprint["sample"]["tenant_cap"],
        config_extra={"sprint": sprint["version"]},
    )
    print(f"wrote {len(paths)} lever results to {args.levers_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
