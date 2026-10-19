"""The Demo A live check (owner-approved 2026-10-19, output cap 512).

    python scripts/demo_live_check.py              # plan only: no call
    python scripts/demo_live_check.py --run        # asks, then calls
    python scripts/demo_live_check.py --run --yes  # owner already approved

One scripted chat session with SYNTHETIC messages through the real pipeline,
spend guard, persistent ledger, and recording decorator: the first
substantive message, a greeting after anchoring, a code re-route, a
bot-level cache hit for another user (no call), DeepSeek with thinking
disabled over two turns, and LLMLingua-2 on a retrieved document.
Prints the exact pre-call estimate of every call first; refuses if the sum is
not computed or exceeds 0.0021 USD (the owner's approval), which is also the
run's spend cap. Writes content-free
results to ``docs/references/metis_demo_live_check_<date>.json``. Needs the
two keys (``[live] enabled = true`` in config/local.toml; METIS_API_KEY in
.env) and, for the compression step, the extra ``compress`` and the model
files.
Thin wrapper: the logic is in metis_auto.wiring.demo_check.
"""

from __future__ import annotations

import argparse
import json
import sys

from metis_auto.settings import load_settings, repo_root
from metis_auto.wiring.demo_check import MAX_TOTAL_ESTIMATE, plan, run
from metis_auto.wiring.from_settings import live_permission
from metis_auto.wiring.live import live_overrides


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", action="store_true", help="make the live calls")
    parser.add_argument("--yes", action="store_true", help="do not ask again")
    args = parser.parse_args()

    def loader(overrides):
        return load_settings(overrides=overrides)

    rows, total, worst = plan(loader)
    calls = sum(1 for r in rows if r.served_by == "model")
    print("Pre-call estimates (full request counted + framing + 512 output tokens):")
    for r in rows:
        if r.served_by != "model":
            print(f"  {r.step:<30} {r.reason_code:<44} served by {r.served_by}: 0")
            continue
        up = (
            f"  (+ {r.escalation_estimate:.6f} if it escalated to {r.escalation_model})"
            if r.escalation_model
            else ""
        )
        print(
            f"  {r.step:<30} {r.reason_code:<44} {r.model_id:<18} "
            f"<= {r.estimate:.6f}{up}"
        )
    print(f"  total upper bound for {calls} calls: {total:.6f} USD")
    print(f"  worst case if every call escalated once: {worst:.6f} USD")
    if total > MAX_TOTAL_ESTIMATE:
        print(f"refusing: above {MAX_TOTAL_ESTIMATE} USD")
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

    results = run(loader)
    out = (
        repo_root()
        / "docs"
        / "references"
        / (f"metis_demo_live_check_{results['date']}.json")
    )
    n = 2
    while out.exists():
        out = out.with_name(f"metis_demo_live_check_{results['date']}-{n}.json")
        n += 1
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
