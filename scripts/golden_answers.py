"""Reference answers of a strong model for a dataset's records (ADR-0030). Thin CLI.

    python scripts/golden_answers.py plan [--run-id R]        # no call; counts, IDs
    python scripts/golden_answers.py pilot --run-id R --live  # the pilot records
    python scripts/golden_answers.py run --run-id R --live    # the records not done
    python scripts/golden_answers.py summary --run-id R       # content-free summary
    python scripts/golden_answers.py runs                     # stored runs and counts
    python scripts/golden_answers.py review-language R        # language mismatches
    python scripts/golden_answers.py export R                 # folder to upload (lead)
    python scripts/golden_answers.py import FOLDER            # load a teammate's export
    python scripts/golden_answers.py verify-answers R         # PASS or FAIL
    python scripts/golden_answers.py fingerprint-answers R    # the lead, once

``export`` writes answer text under ``runs/`` (git-ignored): upload that folder only
to the team's private dataset, never to the raw-data dataset. ``import`` and
``verify-answers`` make no call: never run the answers again against the provider.

``review-language`` writes a local file WITH message text under ``runs/`` (git-ignored,
never share or commit it) and a content-free sheet to fill in; it makes no call.

A live command needs ``--live`` AND ``golden_answers.real_data_approved = true``,
the live keys and both budget caps in ``config/local.toml``; otherwise it refuses
before any call. Prompts and answers stay in the local database and ``runs/``;
nothing printed here contains message text.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from metis_auto.data_access.postgres import golden_answers as db
from metis_auto.evaluation.golden_answers.share import ShareRefused
from metis_auto.wiring.golden_answers import (
    CONFIG_PATH,
    SCOPES,
    GoldenAnswers,
    RunRefused,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "command",
        choices=[
            "plan",
            "pilot",
            "run",
            "summary",
            "runs",
            "review-language",
            "export",
            "import",
            "verify-answers",
            "fingerprint-answers",
        ],
    )
    ap.add_argument(
        "run", nargs="?", help="the run (or, for import, the export folder)"
    )
    ap.add_argument("--run-id", help="the run to create, continue or summarise")
    ap.add_argument("--config", default=CONFIG_PATH)
    ap.add_argument("--live", action="store_true", help="allow real provider calls")
    ap.add_argument(
        "--retry-failed",
        default="",
        metavar="CLASSES",
        help="comma-separated error classes of stored failures to try again, "
        "e.g. auth after the provider refused calls for lack of credit",
    )
    args = ap.parse_args()
    g = GoldenAnswers(config_path=args.config)

    if args.command == "plan":
        print(json.dumps(g.plan(args.run_id), indent=1, sort_keys=True))
        return 0
    if args.command == "runs":
        with g.engine.connect() as conn:
            for run_id, n in db.runs(conn):
                print(f"{run_id}: {n} stored records")
        return 0
    if args.command == "import":
        if not args.run:
            ap.error("import needs the export folder")
        try:
            result = g.import_answers(Path(args.run))
        except ShareRefused as exc:
            print(exc)
            return 2
        print(json.dumps(result, indent=1, sort_keys=True))
        return 0
    args.run_id = args.run_id or args.run
    if not args.run_id:
        ap.error(f"{args.command} needs a run ID")
    if args.command == "export":
        try:
            result = g.export_answers(args.run_id)
        except ShareRefused as exc:
            print(exc)
            return 2
        print(json.dumps(result, indent=1, sort_keys=True))
        return 0
    if args.command == "fingerprint-answers":
        g.fingerprint_answers(args.run_id)
        return 0
    if args.command == "verify-answers":
        return 0 if g.verify_answers(args.run_id) else 1
    if args.command == "review-language":
        result = g.review_language(args.run_id)
        print(json.dumps(result, indent=1, sort_keys=True, ensure_ascii=False))
        return 1 if result["verdict_problems"] else 0
    if args.command == "summary":
        g.summary(args.run_id)
        return 0
    if not args.live:
        print("Refused: this would make live provider calls. Pass --live to allow it.")
        return 2
    try:
        report = g.run(
            args.run_id,
            scope=SCOPES[args.command],
            retry_failed=frozenset(c for c in args.retry_failed.split(",") if c),
        )
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
