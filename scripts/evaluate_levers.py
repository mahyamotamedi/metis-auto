"""Apply the evaluation framework's rules to the pipelines' lever results.

    python scripts/evaluate_levers.py reports/levers/*.json

Reads lever result JSON files (content-free aggregates; anything else is
skipped) and writes ``lever_evaluation.json`` and ``lever_evaluation.md`` under
``--out-dir`` (default ``runs/lever_evaluation``, git-ignored): per step and
baseline the saving with its interval and provenance, the Persian slice, the
quality side (measured or not) and the plan's decision rule with the reason when
its evidence is not in the file. Prints counts only. No network, no model call,
no key. Thin wrapper: all logic is in metis_auto.wiring.lever_evaluation and
metis_auto.evaluation.reporting.lever_verdicts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from metis_auto.evaluation.reporting.lever_verdicts import DEFAULT_MIN_REVIEWED
from metis_auto.wiring.lever_evaluation import write_evaluation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", type=Path, help="lever result JSON files")
    parser.add_argument("--out-dir", type=Path, default=Path("runs/lever_evaluation"))
    parser.add_argument(
        "--min-reviewed",
        type=int,
        default=DEFAULT_MIN_REVIEWED,
        help="reviewed hits an answer cache needs (the plan: about 300)",
    )
    args = parser.parse_args()
    summary = write_evaluation(
        args.paths, out_dir=args.out_dir, min_reviewed=args.min_reviewed
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
