"""Replay the frozen routing dev slice through the pipeline
(ADR-0047, R4). Thin CLI.

    python scripts/replay_router_slice.py                     # all scenarios
    python scripts/replay_router_slice.py --scenario local    # one scenario
    python scripts/replay_router_slice.py --scenario thx01    # the real THX-01 (R5)
    python scripts/replay_router_slice.py --profile complex   # fake answers

Fakes only: the fake answering client and fake decision backends. No network,
no model weights, no keys, no spend; the spend ledger is never touched.
Scenarios: ``off`` (router off), ``local`` (fake local backend, two passes:
the second shows the router cache), ``hosted_refused`` (a fake hosted backend
first: every dataset state is refused before it, because
``router.real_data_approved`` is false).

Reads the local slice records only after checking they are the committed,
frozen slice (``fingerprint.json`` and ``ids.csv``); never rebuilds them.
Prints counts, timings and peak memory only: never message text.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from metis_auto.adapters.system.resources import peak_rss_mb
from metis_auto.settings import load_settings, repo_root
from metis_auto.wiring.router_replay import (
    OFFLINE_SCENARIOS,
    SCENARIOS,
    run_scenario,
)
from metis_auto.wiring.router_slice import DEFAULT_CONFIG, RouterSlice, SliceRefused


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--scenario", choices=["all", *SCENARIOS], default="all")
    ap.add_argument(
        "--profile", choices=["neutral", "cheap", "complex"], default="cheap"
    )
    ap.add_argument("--passes", type=int, default=2, choices=[1, 2, 3])
    ap.add_argument(
        "--config", default=DEFAULT_CONFIG, help="slice config (repo-relative)"
    )
    ap.add_argument("--out", type=Path, help="also write the JSON here")
    args = ap.parse_args()

    root = repo_root()
    settings = load_settings().settings
    started = time.perf_counter()
    try:
        sl = RouterSlice(root, settings.data.full_data_root, root / Path(args.config))
        records = sl.frozen_records()
    except SliceRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    scenarios = OFFLINE_SCENARIOS if args.scenario == "all" else (args.scenario,)
    results = [
        run_scenario(
            lambda overrides: load_settings(overrides=overrides),
            records,
            name,
            profile=args.profile,
            passes=args.passes,
        )
        for name in scenarios
    ]
    text = json.dumps(
        {
            "slice_records": len(records),
            "profile": args.profile,
            "scenarios": results,
            "total_s": round(time.perf_counter() - started, 1),
            "peak_rss_mb": peak_rss_mb(),
        },
        indent=2,
    )
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
