"""R8 shadow evaluation of the decision router on the frozen dev slice
(exp-route-013). Local only; prints counts, shares and timings, never text.

    python scripts/evaluate_router_slice.py                    # THX-01 vs the rules
    python scripts/evaluate_router_slice.py --backend fake     # the harness, no weights
    python scripts/evaluate_router_slice.py --out runs/finish_router/shadow_eval.json
    python scripts/evaluate_router_slice.py --offline              # real answers (R8)

Rules only versus the decision router on every record (fake answering client):
tier mix, agreement with the rules, confidence (gate questions, Q-61), gate share,
path mix and the decision step's p95, for all records, the tune split and the check
split, each balanced and traffic-weighted, and per language group (Persian first).
There are no labels yet, so agreement is not accuracy. THX-01 needs the
router-local extra and the pinned files (scripts/fetch_router_assets.py check).

``--offline`` (the evaluation mode): no inline deadline (60 s per request), no
router cache, the confidence gate off, so every row holds THX-01's real answer;
it adds each question's confidence and probability distribution and the
provisional gate proposal (threshold from the tune split, effect on check).
Without it, the inline settings apply (60 ms deadline, gate 0.6).

``--backend jev`` (owner 2026-11-03, after Metis's written OK, Q-55) sends each
record's state to Jev through Metis: **live and paid**. ``--plan`` prints the
upper-bound cost and every reason the run may not start, with no call. The run
needs ``--yes``, live calls allowed (``live.enabled``, ``METIS_API_KEY``, caps)
and ``router.real_data_approved`` set in the runtime (config/local.toml or
``METIS__ROUTER__REAL_DATA_APPROVED=true`` for the run); every call goes
through the spend guard over the persistent ledger, capped at ``--run-cap``
(at most 0.05 USD). Models Metis no longer serves (gpt-4.1-nano, mimo-v2.5)
are disabled for the run, in memory. The output adds ``costs``: the same
logged tokens priced on today's model, the rules' model and the router's model
with the team's replay pricing (ADR-0041; a cost simulation).

    python scripts/evaluate_router_slice.py --backend jev --offline --plan
    python scripts/evaluate_router_slice.py --backend jev --offline --yes \
        --out runs/jev_slice/shadow_jev.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from decimal import Decimal
from pathlib import Path

from metis_auto.adapters.system.resources import peak_rss_mb
from metis_auto.evaluation.router_eval import DIFFERENCE_COLUMNS, differences
from metis_auto.settings import load_settings, repo_root
from metis_auto.wiring.live import live_overrides
from metis_auto.wiring.router_eval import (
    BACKENDS,
    HOSTED_BACKENDS,
    JEV_RUN_CAP,
    evaluate,
    hosted_ledger,
    hosted_plan,
)
from metis_auto.wiring.router_slice import DEFAULT_CONFIG, RouterSlice, SliceRefused


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--backend", choices=BACKENDS, default="thx01")
    ap.add_argument(
        "--profile", choices=["neutral", "cheap", "complex"], default="cheap"
    )
    ap.add_argument("--config", default=DEFAULT_CONFIG, help="slice config")
    ap.add_argument("--offline", action="store_true", help="evaluation mode")
    ap.add_argument("--out", type=Path, help="also write the JSON here")
    ap.add_argument(
        "--differences-out",
        type=Path,
        help="CSV of only the requests where the router and the rules differ "
        "(IDs, tiers, model IDs; no text)",
    )
    ap.add_argument("--plan", action="store_true", help="hosted: cost bound, no call")
    ap.add_argument("--yes", action="store_true", help="hosted: the owner approved")
    ap.add_argument("--run-cap", default=str(JEV_RUN_CAP), help="hosted: USD cap")
    ap.add_argument(
        "--exclude-gone-models",
        action="store_true",
        help="disable gpt-4.1-nano and mimo-v2.5 for this run (always for jev)",
    )
    args = ap.parse_args()
    root = repo_root()
    settings = load_settings().settings
    started = time.perf_counter()
    try:
        records = RouterSlice(
            root, settings.data.full_data_root, root / Path(args.config)
        ).frozen_records()
    except SliceRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    hosted = args.backend in HOSTED_BACKENDS
    ledger = None
    extra: dict = live_overrides() if hosted else {}
    if hosted:
        cap = min(Decimal(args.run_cap), JEV_RUN_CAP)
        loaded = load_settings(overrides=extra)
        plan = hosted_plan(loaded, records, run_cap=cap)
        print(json.dumps({"plan": plan}, indent=2))
        if args.plan:
            return 0
        if not plan["allowed"] or not args.yes:
            reason = (
                "add --yes (the owner's approval)" if plan["allowed"] else "blocked"
            )
            print(f"refused: {reason}; no call was made", file=sys.stderr)
            return 1
        ledger = hosted_ledger(loaded, Decimal(plan["run_cap_usd"]), "router-jev-slice")
    rows: list = []
    result = evaluate(
        lambda overrides: load_settings(overrides={**overrides, **extra}),
        records,
        backend=args.backend,
        profile=args.profile,
        offline=args.offline,
        spend_ledger=ledger,
        exclude_gone_models=hosted or args.exclude_gone_models,
        rows_sink=rows,
    )
    if args.differences_out is not None:
        args.differences_out.parent.mkdir(parents=True, exist_ok=True)
        with args.differences_out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=DIFFERENCE_COLUMNS, lineterminator="\n")
            w.writeheader()
            w.writerows(differences(rows))
    if ledger is not None:
        left = ledger.remaining()
        result["ledger_remaining_usd"] = str(left.amount) if left else None
    result["total_s"] = round(time.perf_counter() - started, 1)
    result["peak_rss_mb"] = peak_rss_mb()
    text = json.dumps(result, indent=2)
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
