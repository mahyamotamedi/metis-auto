"""Eligibility and free candidate cost replay of the routing base (R-0) on the
tune split.

Reads ``requests.parquet``, scopes it and splits it by session
(``replay_scope``); keeps ``split_by_session == "tune"`` rows inside the tune
period, LLM rows only (the rows R-B3 scores). Applies
``analysis.routing_base`` with ``sprint.toml [routing]`` and the
``[baselines]`` catalogue and price table, and writes aggregates to
``reports/routing/routing-base/tune_eligibility.json``:

- share of LLM rows with at least one eligible candidate;
- per candidate: eligible rows and share, its first failing reasons, and its
  total price-file cost (USD) on its eligible rows;
- the requests' first failing reasons;
- the comparison with Pipeline B's interim rules (EXP-ROUTE-011), whose one
  difference in meaning is an unknown attachment count (B: no attachment).

Cost is a *simulation* (logged tokens, assumed model-independent). Timestamps
are naive (Q-06). The report period is not read. No IDs, hashes or text are
written or printed.

    .venv/bin/python scripts/routing_base_report.py
"""

from __future__ import annotations

import json
import math
import time
import tomllib
from pathlib import Path

import pandas as pd

from metis_auto.analysis.baselines_full import cached_reported_separately
from metis_auto.analysis.levers import ReplayContext
from metis_auto.analysis.replay_scope import (
    period_bounds_from_config,
    scope,
    split_by_session,
)
from metis_auto.analysis.routing_base import (
    REASON_COLUMN,
    candidate_costs,
    candidate_list,
    eligibility_frame,
)

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "data/derived/full_eda"
OUT = ROOT / "reports/routing/routing-base/tune_eligibility.json"
REQ_COLUMNS = [
    "session_id",
    "a_order",
    "a_timestamp",
    "bot_id",
    "user_id",
    "u_h_norm",
    "bot_provider_name",
    "bot_provider_model",
    "a_billing_state",
    "a_bill_inputTokens",
    "a_bill_cachedInputTokens",
    "a_bill_outputTokens",
    "u_att_n",
    "bot_n_functions",
]
# EXP-ROUTE-011 README and reports/routing/exp-route-011/summary.json
# (code_commit 5a68fb6, 2026-11-02), tune split, LLM rows.
B_README = {"n_scored_llm": 209_331, "unknown_tokens": 506}


def _share(n: int, d: int) -> float | None:
    return round(n / d, 6) if d else None


def main() -> int:
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
    req = scope(pd.read_parquet(DERIVED / "requests.parquet", columns=REQ_COLUMNS), ctx)
    sep = cached_reported_separately(req)
    req["split"] = split_by_session(req, seed=ctx.seed)
    req = req[(req["split"] == "tune") & (req["period"] == "tune") & req["llm_request"]]
    n = len(req)
    cands = candidate_list(rules)

    t0 = time.perf_counter()
    elig = eligibility_frame(req, ctx, rules=rules, cached_separately=sep, reasons=True)
    seconds = time.perf_counter() - t0
    costs = candidate_costs(req, ctx, cands, rules=rules, cached_separately=sep)

    any_elig = elig[list(cands)].any(axis=1)
    reasons = elig.loc[~any_elig, REASON_COLUMN].value_counts()
    per_candidate = {}
    for m in cands:
        k = int(elig[m].sum())
        per_candidate[m] = {
            "eligible": k,
            "eligible_share": _share(k, n),
            "first_failing_reasons": {
                str(r): int(c)
                for r, c in elig.loc[~elig[m], f"reason:{m}"].value_counts().items()
            },
            "cost_usd_on_eligible_rows": round(math.fsum(costs[m].dropna()), 6),
            "n_costed": int(costs[m].notna().sum()),
        }

    # B's interim meaning: an unknown attachment count is no attachment.
    b_like = req.assign(u_att_n=req["u_att_n"].fillna(0))
    b_elig = eligibility_frame(b_like, ctx, rules=rules, cached_separately=sep)
    b_any = b_elig[list(cands)].any(axis=1)

    out = {
        "what": "routing base (R-0) eligibility and free candidate cost replay",
        "scope": "split_by_session tune rows inside the tune period, LLM rows; "
        "report period not read; naive timestamps (Q-06)",
        "evidence": "simulation: logged tokens assumed model-independent; "
        "price-file USD; quality not measured",
        "settings": {
            "sprint_config": sprint["version"],
            "catalogue_version": ctx.catalogue["version"],
            "price_version": ctx.price_table["version"],
            "candidates": list(cands),
            "retiring": [r["model_id"] for r in rules["retiring"]],
            "avoid_long_context_tier": rules["avoid_long_context_tier"],
            "separate_cached_models": len(sep),
        },
        "n_llm_rows": n,
        "any_eligible": int(any_elig.sum()),
        "any_eligible_share": _share(int(any_elig.sum()), n),
        "request_first_failing_reasons": {str(r): int(c) for r, c in reasons.items()},
        "per_candidate": per_candidate,
        "compare_b_interim": {
            "b_readme": B_README,
            "unknown_tokens_here": int((elig[REASON_COLUMN] == "unknown_tokens").sum()),
            "any_eligible_with_b_meaning": int(b_any.sum()),
            "rows_only_b_allows": int((b_any & ~any_elig).sum()),
            "rows_only_here": int((any_elig & ~b_any).sum()),
            "per_candidate_with_b_meaning": {m: int(b_elig[m].sum()) for m in cands},
        },
        "eligibility_frame_seconds": round(seconds, 2),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
