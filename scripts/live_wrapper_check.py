"""The tiny live wrapper check (Stage 7.5; brief §3, TODO-12).

    python scripts/live_wrapper_check.py            # plan only: no call
    python scripts/live_wrapper_check.py --run      # asks, then calls
    python scripts/live_wrapper_check.py --run --yes  # owner already approved

Sends ONE tiny synthetic message to each of the five test models through the
real pipeline (spend guard, persistent ledger, recording decorator) and writes
the content-free comparison of reported vs locally counted tokens to
``docs/references/metis_wrapper_live_check_<date>.json``. Refuses to run if the
summed pre-call estimate is not computed or reaches 0.05 USD.

Live calls need both keys: this script asks for ``live``; you enable the
runtime with ``live.enabled = true`` in config/local.toml, and METIS_API_KEY
must be in .env. Thin wrapper: the logic is in metis_auto.wiring.wrapper_check.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from metis_auto.settings import load_settings, repo_root
from metis_auto.wiring.from_settings import live_permission
from metis_auto.wiring.live import live_overrides
from metis_auto.wiring.wrapper_check import MAX_TOTAL_ESTIMATE, plan, run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", action="store_true", help="make the live calls")
    parser.add_argument("--yes", action="store_true", help="do not ask again")
    args = parser.parse_args()

    loaded = load_settings(overrides=live_overrides())
    rows, total = plan(loaded)
    print("Pre-call estimates (counted input + framing + generation limit):")
    for r in rows:
        value = f"{r.estimate:.6f} {r.currency}" if r.estimate is not None else "n/c"
        print(
            f"  {r.model_id:<18} input {r.input_tokens:>4} tok, "
            f"output limit {r.output_limit:>5} tok: <= {value}"
        )
    print(f"  total upper bound: {total} USD (limit {MAX_TOTAL_ESTIMATE} USD)")
    if total is None or total >= MAX_TOTAL_ESTIMATE:
        print("refusing: the estimate is not computed or too high")
        return 2
    permission = live_permission(loaded)
    if not permission.allowed:
        print("live calls are blocked: " + "; ".join(permission.reasons))
        return 0 if not args.run else 1
    if not args.run:
        print("plan only; add --run to make the 5 live calls")
        return 0
    if not args.yes and input("Make 5 live calls now? Type yes: ").strip() != "yes":
        print("not run")
        return 0

    results = run(lambda o: load_settings(overrides=o))
    out = (
        repo_root()
        / "docs"
        / "references"
        / f"metis_wrapper_live_check_{results['date']}.json"
    )
    out = _free_name(out)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(results["results"], indent=2, ensure_ascii=False))
    print(f"budget after: {results['budget_after']}")
    print(f"written: {out}")
    return 0


def _free_name(path: Path) -> Path:
    n, candidate = 2, path
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
        n += 1
    return candidate


if __name__ == "__main__":
    sys.exit(main())
