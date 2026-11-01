"""Reference answers of a strong model for a dataset's records (ADR-0030). Thin CLI.

    python scripts/golden_answers.py plan                     # no call; counts, IDs
    python scripts/golden_answers.py pilot --run-id R --live  # the pilot records
    python scripts/golden_answers.py run --run-id R --live    # the records not done
    python scripts/golden_answers.py summary --run-id R       # content-free summary
    python scripts/golden_answers.py runs                     # stored runs and counts

A live command needs ``--live`` AND ``golden_answers.real_data_approved = true``,
the live keys and both budget caps in ``config/local.toml``; otherwise it refuses
before any call. Prompts and answers stay in the local database and ``runs/``;
nothing printed here contains message text.
"""

from __future__ import annotations

import argparse
import json
import sys

from metis_auto.data_access.postgres import golden_answers as db
from metis_auto.wiring.golden_answers import CONFIG_PATH, GoldenAnswers, RunRefused


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=["plan", "pilot", "run", "summary", "runs"])
    ap.add_argument("--run-id", help="the run to create, continue or summarise")
    ap.add_argument("--config", default=CONFIG_PATH)
    ap.add_argument("--live", action="store_true", help="allow real provider calls")
    args = ap.parse_args()
    g = GoldenAnswers(config_path=args.config)

    if args.command == "plan":
        print(json.dumps(g.plan(), indent=1, sort_keys=True))
        return 0
    if args.command == "runs":
        with g.engine.connect() as conn:
            for run_id, n in db.runs(conn):
                print(f"{run_id}: {n} stored records")
        return 0
    if not args.run_id:
        ap.error(f"{args.command} needs --run-id")
    if args.command == "summary":
        g.summary(args.run_id)
        return 0
    if not args.live:
        print("Refused: this would make live provider calls. Pass --live to allow it.")
        return 2
    try:
        report = g.run(args.run_id, scope=args.command)
    except RunRefused as exc:
        print(exc)
        return 2
    print(
        f"answered {report.answered}, failed {report.failed}, "
        f"skipped (already stored) {report.skipped}, calls {report.calls}"
    )
    for halt in report.halts:
        print(f"halt: {halt.reason} (record {halt.record_id})")
    return 1 if report.halts else 0


if __name__ == "__main__":
    sys.exit(main())
