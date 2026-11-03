"""Paid routing benchmark P-1..P-3 (final plan "Paid branch";
ADR-0053). Thin wrapper over metis_auto.wiring.benchmark.

    python scripts/benchmark.py tenant-check              # no database, no call
    python scripts/benchmark.py plan                      # no database, no call
    python scripts/benchmark.py plan --with-db --machine <label>   # pilot machine
    python scripts/benchmark.py generate --run-id <id> --machine <label> \
        --approved-by <owner> --cap <usd> --dataset-text-approved    # PAID, gated
    python scripts/benchmark.py judge    --run-id <id> --machine <label> \
        --approved-by <owner> --cap <usd> --dataset-text-approved    # PAID, gated
    python scripts/benchmark.py spot-check --run-id <id>  # local files, no call
    python scripts/benchmark.py labels --run-id <id> --name <name>   # no call

``plan`` and ``tenant-check`` never build a client and print counts, bounds and
reasons only. ``generate`` and ``judge`` refuse, listing every reason, until the
three gates and the owner values are set; then live calls go through the spend
guard over the shared ledger (decision 7) and are recorded, so a rerun replays.
Nothing printed holds text.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from decimal import Decimal

from metis_auto.evaluation.benchmark.config import OwnerValueUnset
from metis_auto.evaluation.sampling.config import LiveApproval
from metis_auto.wiring.benchmark import Benchmark, BenchmarkRefused


def _approval(args) -> LiveApproval | None:
    if not args.approved_by or args.cap is None:
        return None
    return LiveApproval(
        approved_by=args.approved_by,
        run_id=args.run_id,
        cap_usd=Decimal(args.cap),
        sample_conversations_approved=args.dataset_text_approved,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument(
        "action",
        choices=["tenant-check", "plan", "generate", "judge", "spot-check", "labels"],
    )
    ap.add_argument(
        "--with-db", action="store_true", help="count input sizes from the database"
    )
    ap.add_argument("--machine", help="this machine's label (decision 7)")
    ap.add_argument("--run-id")
    ap.add_argument("--name", help="labels: benchmark:<name>")
    ap.add_argument("--approved-by")
    ap.add_argument("--cap", help="USD cap the owner approved for this run")
    ap.add_argument("--dataset-text-approved", action="store_true")
    args = ap.parse_args()
    bench = Benchmark()
    try:
        if args.action == "tenant-check":
            out = {
                "golden_v2": asdict(bench.tenant_check()),
                "pilot": asdict(bench.tenant_check(bench.pilot_ids())),
            }
        elif args.action == "plan":
            out = bench.plan(with_db=args.with_db, machine=args.machine)
        elif args.action in ("generate", "judge"):
            if not args.run_id or not args.machine:
                print("refused: --run-id and --machine are required", file=sys.stderr)
                return 2
            step = bench.generate if args.action == "generate" else bench.judge
            result = step(
                run_id=args.run_id, machine=args.machine, approval=_approval(args)
            )
            out = {"done": args.action, "summary": str(type(result).__name__)}
        elif args.action == "spot-check":
            out = bench.spot_check(run_id=args.run_id)
        else:
            out = bench.labels(run_id=args.run_id, name=args.name)
    except BenchmarkRefused as exc:
        print(json.dumps({"refused": list(exc.reasons)}, indent=2))
        return 1
    except OwnerValueUnset as exc:
        print(json.dumps({"refused": [str(exc)]}, indent=2))
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
