"""The Stage 7.5 follow-up live probe (owner decisions 2026-10-18: Q-32, Q-33 b,
Q-34).

    python scripts/live_probe.py              # plan only: no call
    python scripts/live_probe.py --run        # asks, then calls
    python scripts/live_probe.py --run --yes  # owner already approved

Three steps, 12 calls in one run (one per-run cap), through the real pipeline,
spend guard, persistent ledger, and recording decorator:
1. provider cache: one long SYNTHETIC prompt (> 1,024 tokens) sent twice to
   each test model, with a different short message each time, to see whether
   cached tokens are reported and discounted on the second call;
2. the one-tiny-message check for mimo-v2.5 (the new fifth test model);
3. deepseek-v4-flash once with ``thinking: {"type": "disabled"}``.
Writes content-free results to
``docs/references/metis_wrapper_live_probe_<date>.json``. Refuses if the summed
pre-call estimate is not computed or reaches 0.02 USD. Needs the same two keys
as the check (``[live] enabled = true`` in config/local.toml; METIS_API_KEY).
Thin wrapper: the logic is in metis_auto.wiring.wrapper_check.
"""

from __future__ import annotations

import argparse
import json
import sys

from metis_auto.settings import load_settings, repo_root
from metis_auto.wiring.from_settings import live_permission
from metis_auto.wiring.live import live_overrides
from metis_auto.wiring.wrapper_check import PROBE_MAX_TOTAL, probe_plan, probe_run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", action="store_true", help="make the live calls")
    parser.add_argument("--yes", action="store_true", help="do not ask again")
    args = parser.parse_args()

    def loader(overrides):
        return load_settings(overrides=overrides)

    steps, total = probe_plan(loader)
    calls = 0
    print("Pre-call estimates (counted input + framing + generation limit):")
    for step in steps:
        print(f"  {step.name}:")
        for r in step.rows:
            value = f"{r.estimate:.6f}" if r.estimate is not None else "n/c"
            print(
                f"    {r.model_id:<18} input {r.input_tokens:>5} tok, output "
                f"limit {r.output_limit:>5} tok: <= {value} {r.currency} "
                f"x {step.calls_per_model}"
            )
            calls += step.calls_per_model
    print(
        f"  total upper bound for {calls} calls: {total} USD (limit "
        f"{PROBE_MAX_TOTAL} USD)"
    )
    if total is None or total >= PROBE_MAX_TOTAL:
        print("refusing: the estimate is not computed or too high")
        return 2
    permission = live_permission(loader(live_overrides()))
    if not permission.allowed:
        print("live calls are blocked: " + "; ".join(permission.reasons))
        return 0 if not args.run else 1
    if not args.run:
        print(f"plan only; add --run to make the {calls} live calls")
        return 0
    if not args.yes and input(f"Make {calls} live calls now? Type yes: ") != "yes":
        print("not run")
        return 0

    results = probe_run(loader)
    out = (
        repo_root()
        / "docs"
        / "references"
        / (f"metis_wrapper_live_probe_{results['date']}.json")
    )
    n = 2
    while out.exists():
        out = out.with_name(f"metis_wrapper_live_probe_{results['date']}-{n}.json")
        n += 1
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
