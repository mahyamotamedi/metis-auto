"""One shared spend total across the team's machines (decision 7).

    python scripts/spend_share.py export --machine <label>   # this machine's summary
    python scripts/spend_share.py merge                       # the team total

``export`` reads this machine's ledger (``paths.spend_ledger``) read-only and
writes a content-free summary (totals per run, no prompt, no key) to
``reports/spend/ledgers/<label>.json``, to commit or share. ``merge`` sums the
newest summary per machine. A paid benchmark run counts the other machines'
summaries through ``SharedSpendLedger`` (refuses if one is missing or too old).
No ledger is ever edited or deleted. No network, no model call.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from metis_auto.adapters.system.shared_spend import LedgerSummary, merge_summaries
from metis_auto.wiring.benchmark import Benchmark

LABEL = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("action", choices=["export", "merge"])
    ap.add_argument("--machine", help="lower-case label, e.g. parham-laptop")
    args = ap.parse_args()
    bench = Benchmark()
    folder = bench.root / bench.config.spend_share.summaries_dir
    if args.action == "export":
        if not args.machine or not LABEL.match(args.machine):
            print("refused: --machine <lower-case label> is required", file=sys.stderr)
            return 2
        summary = bench.ledger_summary(args.machine)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{args.machine}.json"
        path.write_text(
            json.dumps(summary.to_json(), indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "wrote": str(Path(path).relative_to(bench.root)),
                    "total": str(summary.total),
                    "charges": summary.charges,
                }
            )
        )
        return 0
    summaries = (
        [
            LedgerSummary.from_json(json.loads(p.read_text(encoding="utf-8")))
            for p in sorted(folder.glob("*.json"))
        ]
        if folder.exists()
        else []
    )
    out = merge_summaries(summaries)
    status = bench.summary_status()
    out["summary_status"] = status
    if not status["folder_exists"] or status["missing"]:
        print(
            f"warning: ledger summaries missing: {status['missing']}", file=sys.stderr
        )
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
