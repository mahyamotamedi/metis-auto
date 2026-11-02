"""Build and manage an evaluation dataset: golden-v1 (ADR-0028) or golden-v2 (ADR-0029).
Thin CLI.

    python scripts/build_eval_dataset.py all     # every build step
    python scripts/build_eval_dataset.py verify  # PASS or FAIL against the team
    python scripts/build_eval_dataset.py import-labels <reviewed_labels.jsonl>
    python scripts/build_eval_dataset.py --config config/evaluation/golden_v2.toml all

Without --config the dataset is golden-v1. golden-v2 is derived from golden-v1, so
build and verify golden-v1 first.

Safe to interrupt: each step is one transaction, and re-running repeats it safely.
No model is called. Message text is written only to git-ignored folders.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from metis_auto.wiring.golden import CONFIG_PATH, Golden


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "command",
        choices=[
            "all",
            "requests",
            "select",
            "review-sheets",
            "export",
            "report",
            "fingerprint",
            "verify",
            "import-annotations",
            "import-labels",
            "export-labels",
            "carry-labels",
            "plan-swaps",
            "freeze",
        ],
    )
    ap.add_argument("file", nargs="?", help="input file for the import commands")
    ap.add_argument("--annotator", help="reviewer pseudonym for import-annotations")
    ap.add_argument("--force", action="store_true", help="rebuild existing work")
    ap.add_argument(
        "--config",
        default=CONFIG_PATH,
        help="the dataset's config file (default: golden-v1)",
    )
    args = ap.parse_args()
    g = Golden(config_path=args.config)
    if args.command in ("all", "requests"):
        g.build_requests(force=args.force)
    if args.command in ("all", "select"):
        g.build_dataset(force=args.force)
    if args.command in ("all", "review-sheets"):
        g.review_sheets()
    if args.command in ("all", "export"):
        g.export()
    if args.command in ("all", "report"):
        g.quality_report()
    if args.command == "fingerprint":
        g.write_fingerprint()
    if args.command == "verify":
        return 0 if g.verify() else 1
    if args.command == "import-annotations":
        if not (args.file and args.annotator):
            ap.error("import-annotations needs a file and --annotator")
        g.import_annotations(Path(args.file), args.annotator)
    if args.command == "import-labels":
        if not args.file:
            ap.error("import-labels needs a file")
        g.import_labels(Path(args.file))
    if args.command == "carry-labels":
        if not args.file:
            ap.error("carry-labels needs the base dataset's reviewed_labels.jsonl")
        g.carry_labels(Path(args.file))
    if args.command == "export-labels":
        g.export_labels()
    if args.command == "plan-swaps":
        swaps = g.plan_review_swaps()
        print(f"{len(swaps)} records leave their cell and have a reserve.")
        for record, reserve in swaps:
            print(f"  {record} -> {reserve}")
    if args.command == "freeze":
        g.freeze()
    return 0


if __name__ == "__main__":
    sys.exit(main())
