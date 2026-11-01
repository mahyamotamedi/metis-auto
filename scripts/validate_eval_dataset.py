"""Run validation checks V-01…V-12 and write validation.md (no content). Thin CLI."""

from __future__ import annotations

import argparse
import sys

from metis_auto.wiring.golden import Golden


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--rebuild",
        action="store_true",
        help="also redo the selection in memory and compare (V-12)",
    )
    args = ap.parse_args()
    return Golden().validate(rebuild=args.rebuild)


if __name__ == "__main__":
    sys.exit(main())
