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
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from metis_auto.adapters.system.resources import peak_rss_mb
from metis_auto.settings import load_settings, repo_root
from metis_auto.wiring.router_eval import BACKENDS, evaluate
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
    result = evaluate(
        lambda overrides: load_settings(overrides=overrides),
        records,
        backend=args.backend,
        profile=args.profile,
        offline=args.offline,
    )
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
