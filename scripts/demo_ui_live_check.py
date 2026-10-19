"""Live smoke test of the Demo B UI (owner-approved 2026-10-19, output cap 512).

    python scripts/demo_ui_live_check.py              # plan only: no call
    python scripts/demo_ui_live_check.py --run        # asks, then calls
    python scripts/demo_ui_live_check.py --run --yes  # owner already approved

Drives the real page (scripts/demo_ui.py) with Streamlit's offline test
runner in **live** mode: the SYNTHETIC English FAQ preset, bot-level cache on,
a greeting, a first question, a similar follow-up, a coding request, then a
second user's greeting (a cache hit, no call). Every call goes through the
page's live switch, the real pipeline, spend guard, persistent ledger, and
recording decorator. Prints the exact pre-call estimate of every call first;
refuses if the sum is not computed or exceeds 0.02 USD (the owner's
approval), which is also the run's spend cap. Writes content-free results
(no answer text) to ``docs/references/metis_demo_ui_live_check_<date>.json``.
Needs both keys ([live] enabled = true in config/local.toml; METIS_API_KEY
in .env) and the extra ``ui``.
Thin wrapper: the steps and limits are in metis_auto.wiring.demo_ui_check.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime

from streamlit.testing.v1 import AppTest

from metis_auto.settings import load_settings, repo_root
from metis_auto.wiring.demo_ui import live_check
from metis_auto.wiring.demo_ui_check import (
    APPROVED_TOTAL,
    OUTPUT_CAP,
    PRESET,
    STEPS,
    loader,
    plan,
    result_row,
)

PAGE = repo_root() / "scripts" / "demo_ui.py"
LIVE = "Live (real models, budgeted)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", action="store_true", help="make the live calls")
    parser.add_argument("--yes", action="store_true", help="do not ask again")
    args = parser.parse_args()

    def base(overrides):
        return load_settings(overrides=overrides)

    rows, total, worst = plan(base)
    calls = sum(1 for r in rows if r.served_by == "model")
    print(
        f"Pre-call estimates (full request counted + framing + {OUTPUT_CAP} "
        "output tokens):"
    )
    for r in rows:
        if r.served_by != "model":
            print(f"  {r.step:<22} {r.reason_code:<52} served by {r.served_by}: 0")
            continue
        up = (
            f"  (+ {r.escalation_estimate:.6f} if escalated to {r.escalation_model})"
            if r.escalation_model
            else ""
        )
        print(
            f"  {r.step:<22} {r.reason_code:<52} {r.model_id:<14} "
            f"<= {r.estimate:.6f}{up}"
        )
    print(f"  total upper bound for {calls} calls: {total:.6f} USD")
    print(f"  worst case if every call escalated once: {worst:.6f} USD")
    if worst > APPROVED_TOTAL:
        print(f"refusing: the worst case is above {APPROVED_TOTAL} USD")
        return 2
    allowed, reasons = live_check(base)
    if not allowed:
        print("live calls are blocked: " + "; ".join(reasons))
        return 0 if not args.run else 1
    if not args.run:
        print(f"plan only; add --run to make the {calls} live calls")
        return 0
    if not args.yes and input(f"Make {calls} live calls now? Type yes: ") != "yes":
        print("not run")
        return 0

    stamp = datetime.now(UTC)
    at = AppTest.from_file(str(PAGE), default_timeout=180)
    at.session_state["_test_settings_loader"] = loader(base)
    at.run()
    at.radio(key="mode").set_value(LIVE).run()
    chat = at.session_state["chat"]
    if not chat.live:
        print("the page refused live mode: " + str(at.session_state["blocked"]))
        return 1
    at.button(key=f"preset_{PRESET}").click().run()
    at.toggle(key="bot_cache").set_value(True).run()
    results = []
    for step, message in STEPS:
        if step == "new_user":
            at.button(key="new_user").click().run()
            continue
        at.chat_input[0].set_value(message).run()
        if at.exception:
            print(f"page error at {step}: {at.exception}")
            return 1
        report = at.session_state["messages"][-1]["report"]
        results.append(result_row(step, report))
        print(
            f"  {step:<22} {results[-1]['badge']:<12} {report.served_by:<6} "
            f"{report.model_id or '-':<14} {report.cost}"
        )
        if report.live_stopped or report.failure:
            break
    last = at.session_state["messages"][-1]["report"]
    out = {
        "check": "metis-demo-b-ui-live-check",
        "date": stamp.date().isoformat(),
        "time_utc": stamp.isoformat(timespec="seconds"),
        "run_id": chat.run_id,
        "output_cap": OUTPUT_CAP,
        "run_cap": str(APPROVED_TOTAL),
        "plan": {
            "calls": calls,
            "total_upper_bound": str(total),
            "worst_case_with_escalation": str(worst),
            "rows": [
                {
                    "step": r.step,
                    "model_id": r.model_id,
                    "estimate": str(r.estimate),
                }
                for r in rows
            ],
        },
        "synthetic_input": {
            "note": "All messages SYNTHETIC: the preset's suggested messages.",
            "preset": PRESET,
            "steps": [list(s) for s in STEPS],
        },
        "config": chat.loaded.reference.versions(),
        "results": results,
        "session_decomposition": dict(last.session_decomposition),
        "budget_after": chat.budget(),
    }
    path = (
        repo_root()
        / "docs"
        / "references"
        / f"metis_demo_ui_live_check_{out['date']}.json"
    )
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"results: {path.relative_to(repo_root())}")
    print(f"budget after: {out['budget_after']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
