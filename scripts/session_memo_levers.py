"""Checks and lever results of EXP-CACHE-004 session memo + greeting skip gate
(R-C1).

Reads ``requests.parquet``, the chunk table, the recorded per-call billing items
and the local query fingerprints (``scripts/derive_rag_query_fingerprints.py``).
Fees are the recorded per-call amounts (ADR-0037 items 2 and 3); a skipped
phatic turn's chunk tokens follow ADR-0038 (characters x the ledger coefficient
``recon.t0rag.coef_rag``, uncached input only, ``as_logged`` at each model's
``implied_input_per_M``).

1. On the **tune** split only, replays ``overlap_threshold`` in {0.5, 0.8, 1.0}
   and picks the lowest whose reuses have mean agreement >= 0.9 with at least
   half evaluable. Sessions replay whole; only tune rows are scored.
2. Free checks by split, LLM rows only (aggregates).
3. Unless ``--checks-only``: applies the chosen threshold to the **report**
   split (read once) and writes one ``LeverResult`` per baseline to
   ``reports/levers/cache.session_memo_gate.<baseline>.json``. Run it on a clean
   tree, so the manifest carries the code commit.

No IDs, hashes or text are written or printed. ADR-0039.

    .venv/bin/python scripts/session_memo_levers.py --checks-only
    .venv/bin/python scripts/session_memo_levers.py
"""

from __future__ import annotations

import argparse
import dataclasses
import glob
import importlib.util
import json
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
)
from metis_auto.analysis.cache_guard import CacheGuard
from metis_auto.analysis.lever_result import build_manifest
from metis_auto.analysis.levers import ReplayContext, combine
from metis_auto.analysis.replay_scope import (
    period_bounds_from_config,
    scope,
    split_by_session,
)
from metis_auto.wiring.experiments import code_version

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments/caching/exp-cache-004-session-memo-gate"
DERIVED = ROOT / "data/derived/full_eda"
QUERY_FPS = ROOT / "data/derived/cache/rag_query_fingerprints.parquet"
BILLING = ROOT / "data/full_data/raw/data/derived/chat_message_billing.parquet"
TABLES = ROOT / "reports/full_eda/tables"
SUMMARY = ROOT / "reports/caching/exp-cache-004/summary.json"
LEDGER_ROW = "recon.t0rag.coef_rag"
RATES_VERSION = "full-eda-implied-unit-rates"
GUARD_KEY_VERSION = "session-memo-v1"
REQ_COLUMNS = [
    "session_id",
    "turn",
    "a_order",
    "a_timestamp",
    "ai_message_id",
    "bot_id",
    "user_id",
    "u_h_norm",
    "u_att_n",
    "a_rag_n_queries",
    "a_citation_n",
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
    name = "exp_cache_004_version"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, EXP / "version.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def assumptions(
    baseline: str, coef: float, threshold: float, review_state: str
) -> tuple[str, ...]:
    price = (
        "as_logged: fees avoided are the recorded per-call amounts of skipped "
        "lookups (ADR-0037 items 2-3); a skipped turn's tokens are priced at the "
        "model's implied_input_per_M; no rate = unknown, never zero."
        if baseline == "as_logged"
        else "Repriced: saving not computed. The fee part is not priced in "
        "price-file units (ADR-0036, ADR-0037 item 7), so the total is unknown; "
        "the known token part is session_memo.token_saving_lower_bound."
    )
    return (
        "Candidate reuse and candidate skip: simulation on logged requests; "
        "production correctness not measured.",
        f"Memo: reuse the session's last real lookup when the Jaccard of normalised "
        f"query fingerprints is >= {threshold:g} (chosen on the tune split). "
        "Reused chunks are still sent: fees only, never served_from_cache.",
        "Gate: exact match of u_h_norm against the phatic list plus one trailing "
        f"mark (heuristic); list state {review_state}. Never turn 0, attachments "
        "or workflow.",
        f"Skipped turn tokens = all its chunk characters x {coef:.4f} (ledger "
        f"{LEDGER_ROW}): hypothetical reconstruction, uncached input only.",
        price,
        "Agreement = Jaccard over (chunk_id, h_exact) with the turn's logged "
        "chunks (slice session_memo); the gate has no agreement, n_skipped_cited "
        "is a proxy risk indicator.",
        "Combined with a context version, a skipped turn's dropped chunks must "
        "not be counted again (Review Focus 1); not enforced by combine.",
        "Measured potential, conditional on Metis-Auto being able to intercept "
        "retrieval. Timestamps naive (Q-06).",
    )


def write_levers(
    req: pd.DataFrame,
    *,
    query_fps: pd.DataFrame,
    chunks: pd.DataFrame,
    per_call: pd.DataFrame,
    ctx: ReplayContext,
    overlap_threshold: float,
    phatic_words: frozenset[str],
    tokens_per_char: float,
    input_rate_per_m: Mapping[str, float],
    premium_model: str,
    out_dir: Path,
    code_commit: str,
    python_version: str,
    created_at: datetime,
    config_extra: Mapping[str, object] = {},
    review_state: str = "[PLACEHOLDER: Persian review]",
) -> list[Path]:
    """Apply the version to ``req`` (scoped, one split) and write one
    ``LeverResult`` per baseline into ``out_dir``. Returns the paths."""
    v = _version()
    req = v.fee_blocks(req, per_call)
    lookups = v.build_lookups(req, query_fps, chunks, per_call)
    sep = cached_reported_separately(req)
    memo = v.SessionMemo(
        overlap_threshold,
        phatic_words,
        lookups=lookups,
        tokens_per_char=tokens_per_char,
        input_rate_per_m=input_rate_per_m,
        cached_separately=sep,
    )
    out = combine(req, memo, None, None, ctx)
    cheap = best_single_cheap_model(req, ctx, cached_separately=sep)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
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
            "version": v.VERSION_ID,
            "baseline": key,
            "overlap_threshold": overlap_threshold,
            "phatic_words": sorted(phatic_words),
            "phatic_marks": list(v.PHATIC_MARKS),
            "tokens_per_char": tokens_per_char,
            "tokens_per_char_source": LEDGER_ROW,
            "premium_model": premium_model,
            "best_single_cheap": cheap,
            "cached_separately": sorted(sep),
            "fees": "recorded per-call (ADR-0037 items 2-3)",
        } | dict(config_extra)
        run_ctx = ctx
        if key == "as_logged":
            run_ctx = dataclasses.replace(ctx, price_table={"version": RATES_VERSION})
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
            baseline=key,
            manifest=manifest,
            assumptions=assumptions(
                key, tokens_per_char, overlap_threshold, review_state
            ),
        )
        path = out_dir / f"{result.lever_id}.json"
        path.write_text(result.to_json())
        paths.append(path)
    return paths


def _load_inputs(sprint: dict[str, Any], ctx: ReplayContext):
    req = scope(pd.read_parquet(DERIVED / "requests.parquet", columns=REQ_COLUMNS), ctx)
    req["split"] = split_by_session(req, seed=ctx.seed)
    bt = pd.read_parquet(BILLING, columns=["message_id", "costBreakdown.per_call"])
    per_call = bt[bt["costBreakdown.per_call"].notna()].rename(
        columns={"costBreakdown.per_call": "amount"}
    )
    rag_ids = set(req.loc[req["a_rag_n_queries"] > 0, "ai_message_id"])
    per_call = per_call[per_call["message_id"].isin(set(req["ai_message_id"]))]
    files = sorted(glob.glob(str(DERIVED / "chunks" / "*.parquet")))
    cols = ["message_id", "chunk_id", "h_exact", "n_chars"]
    chunks = pd.concat([pd.read_parquet(f, columns=cols) for f in files])
    chunks = chunks[chunks["message_id"].isin(rag_ids)].reset_index(drop=True)
    query_fps = pd.read_parquet(QUERY_FPS)
    query_fps = query_fps[query_fps["message_id"].isin(rag_ids)]
    return req, per_call, chunks, query_fps


def checks(
    req: pd.DataFrame,
    *,
    query_fps: pd.DataFrame,
    chunks: pd.DataFrame,
    per_call: pd.DataFrame,
    ctx: ReplayContext,
    phatic_words: frozenset[str],
) -> dict[str, Any]:
    """The threshold table (tune rows scored, whole sessions replayed), the
    chosen threshold and the free checks per split. Aggregates only."""
    v = _version()
    req = v.fee_blocks(req, per_call)
    lookups = v.build_lookups(req, query_fps, chunks, per_call)
    by_split = {s: req["split"].eq(s) for s in ("tune", "report")}
    table = {}
    for t in v.THRESHOLDS:
        memo = v.SessionMemo(t, phatic_words, lookups=lookups)
        out = combine(req, memo, None, None, ctx)
        table[t] = v.summarise(out, by_split["tune"])
    chosen = v.choose_threshold(table)
    free = {
        s: {
            "requests_all": int(mask.sum()),
            "requests_llm": int((mask & req["llm_request"]).sum()),
            "chunk_overlap_previous_turn": v.chunk_overlap_shares(
                req, lookups, v.THRESHOLDS, mask
            ),
            "phatic": v.phatic_share(req, lookups, phatic_words, mask),
        }
        for s, mask in by_split.items()
    }
    known_q = lookups["query_fps"].notna()
    return {
        "thresholds_tune": {f"{t:g}": s for t, s in table.items()},
        "chosen_threshold": chosen,
        "free_checks": free,
        "lookups": {
            "n_requests_with_lookup": len(lookups),
            "n_query_set_known": int(known_q.sum()),
            "n_fee_attributable": int(lookups["fees"].notna().sum()),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--checks-only", action="store_true")
    ap.add_argument("--levers-dir", type=Path, default=ROOT / "reports/levers")
    ap.add_argument("--summary", type=Path, default=SUMMARY)
    args = ap.parse_args()
    sprint = tomllib.loads((ROOT / "config/evaluation/sprint.toml").read_text())
    base = sprint["baselines"]
    guard = CacheGuard(
        approved=None,
        blocked=frozenset(),
        disabled_bots=frozenset(),
        key_version=GUARD_KEY_VERSION,
    )
    ctx = ReplayContext(
        period_bounds=period_bounds_from_config(sprint["periods"]),
        price_table=tomllib.loads((ROOT / base["price_table"]).read_text()),
        catalogue=tomllib.loads((ROOT / base["catalogue"]).read_text()),
        seed=sprint["split"]["seed"],
        min_n=sprint["sufficiency"]["min_n"],
        guard=guard,
    )
    words = frozenset(sprint["phatic"]["words"])
    review_state = sprint["phatic"]["review_state"]
    req, per_call, chunks, query_fps = _load_inputs(sprint, ctx)
    inputs = dict(query_fps=query_fps, chunks=chunks, per_call=per_call, ctx=ctx)
    summary = checks(req, phatic_words=words, **inputs)
    summary["phatic_review_state"] = review_state
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n")
    print(json.dumps(summary, sort_keys=True, indent=2))
    if args.checks_only:
        return 0
    chosen = summary["chosen_threshold"]
    if chosen is None:
        print("no threshold passes the agreement rule on tune; no LeverResult written")
        return 1
    ledger = pd.read_csv(TABLES / "claims_ledger.csv").set_index("claim_id")
    coef = float(ledger.loc[LEDGER_ROW, "value"])
    rates = pd.read_csv(TABLES / "implied_unit_rates.csv")
    rates = rates.dropna(subset=["implied_input_per_M"]).set_index("model")
    code = code_version(ROOT)
    report = req[req["split"] == "report"].drop(columns="split")
    paths = write_levers(
        report,
        overlap_threshold=chosen,
        phatic_words=words,
        tokens_per_char=coef,
        input_rate_per_m=rates["implied_input_per_M"].astype(float).to_dict(),
        premium_model=base["premium_model"],
        out_dir=args.levers_dir,
        code_commit=code.commit if code.commit and not code.dirty else "unknown",
        python_version=platform.python_version(),
        created_at=datetime.now(UTC).replace(microsecond=0),
        config_extra={
            "split": "report",
            "threshold_chosen_on": "tune",
            "sprint": sprint["version"],
        },
        review_state=review_state,
        **inputs,
    )
    print(f"wrote {len(paths)} lever results to {args.levers_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
