"""Compare lever results within each step and baseline (S-2).

    python scripts/compare_levers.py reports/levers/*.json \
        --out reports/levers/comparison.md

Reads lever result JSON files (content-free aggregates), skips this command's own
output and any file that is not a lever result, and writes one Markdown table per
baseline and group. Prints counts only. No network, no model call, no key. Thin
wrapper: all logic is in metis_auto.wiring.lever_compare and
metis_auto.analysis.compare.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from metis_auto.wiring.lever_compare import write_comparison


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", type=Path, help="lever result JSON files")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("reports/levers/comparison.md"),
        help="Markdown output (ignored if the input glob matches it)",
    )
    args = parser.parse_args()
    print(json.dumps(write_comparison(args.paths, out=args.out), indent=2))


if __name__ == "__main__":
    main()
