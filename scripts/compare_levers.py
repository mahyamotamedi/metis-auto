"""Compare lever results within each step and baseline (S-2).

    python scripts/compare_levers.py reports/levers/*.json \
        --out reports/levers/comparison.md

Reads lever result JSON files (content-free aggregates), skips this command's own
output and any file that is not a lever result, and writes one Markdown table per
baseline and group. The tenant cap is ``[sample] tenant_cap`` from
``config/evaluation/sprint.toml`` (``--sprint-config``). Prints counts only. No
network, no model call, no key. Thin wrapper: all logic is in
metis_auto.wiring.lever_compare and metis_auto.analysis.compare.
"""

from __future__ import annotations

import argparse
import json
import tomllib
from decimal import Decimal
from pathlib import Path

from metis_auto.wiring.lever_compare import write_comparison

SPRINT_CONFIG = Path(__file__).resolve().parents[1] / "config/evaluation/sprint.toml"


def tenant_cap(path: Path) -> Decimal:
    """``[sample] tenant_cap``, parsed exactly (no float rounding)."""
    sprint = tomllib.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    return Decimal(sprint["sample"]["tenant_cap"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", type=Path, help="lever result JSON files")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("reports/levers/comparison.md"),
        help="Markdown output (ignored if the input glob matches it)",
    )
    parser.add_argument(
        "--sprint-config",
        type=Path,
        default=SPRINT_CONFIG,
        help="sprint settings with [sample] tenant_cap",
    )
    args = parser.parse_args()
    summary = write_comparison(
        args.paths, out=args.out, max_tenant_share=tenant_cap(args.sprint_config)
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
