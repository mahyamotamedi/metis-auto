"""The tiny live Gemini check through the Metis wrapper (ADR-XXXX
(gemini-native-adapter), ADR-XXXX (gemini-live-calls)).

    python scripts/live_gemini_check.py --thinking-budget 0        # plan only
    python scripts/live_gemini_check.py --thinking-budget 0 --run  # asks, calls
    python scripts/live_gemini_check.py --thinking-budget 0 --run --yes

NOT RUN YET. Before the first ``--run`` it needs, all from the owner:
  1. the ADR-0018 amendment, ADR-XXXX (gemini-live-calls), accepted;
  2. a raised Metis dashboard limit (Q-29) that covers this check;
  3. the enabling step: a catalogue row for the model (with a price and a
     tokenizer row), and the ``gemini`` endpoint row's status ``enabled``;
  4. per-run approval (typed ``yes``, or ``--yes`` after a written approval).

Sends ONE tiny SYNTHETIC message (the wrapper check's instructions and
message) to one Gemini model through the real pipeline: spend guard,
persistent ledger (data/spend/ledger.jsonl), recording decorator, one attempt,
output cap ``OUTPUT_CAP`` tokens, run cap ``MAX_TOTAL_ESTIMATE`` USD. The
thinking budget is explicit (``--thinking-budget``, required): thinking
tokens bill as output, so the printed estimate adds the budget to the output
limit. Prints the pre-call estimate first and refuses if any check fails or
the estimate is not computed or reaches the run cap. Writes the content-free
results to ``docs/references/metis_gemini_live_check_<date>.json``; they
verify the request and usage field names marked UNVERIFIED in
``adapters/providers/gemini_native.py``.

Live calls need both keys: this script asks for ``live``; you enable the
runtime with ``live.enabled = true`` in config/local.toml, and METIS_API_KEY
must be in .env. Thin wrapper: the logic is in metis_auto.wiring.gemini_check
and metis_auto.wiring.wrapper_check.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from metis_auto.settings import load_settings, repo_root
from metis_auto.wiring import gemini_check
from metis_auto.wiring.from_settings import live_permission
from metis_auto.wiring.wrapper_check import run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=gemini_check.DEFAULT_MODEL)
    parser.add_argument(
        "--thinking-budget",
        type=int,
        required=True,
        help="explicit thinking budget in tokens (>= 0); never the provider default",
    )
    parser.add_argument("--run", action="store_true", help="make the live call")
    parser.add_argument("--yes", action="store_true", help="do not ask again")
    args = parser.parse_args()

    overrides = gemini_check.overrides(args.model, args.thinking_budget)
    loaded = load_settings(overrides=overrides)
    result = gemini_check.plan(loaded, args.model)
    print("Pre-call estimate (counted input + output limit + thinking budget):")
    value = (
        f"{result.estimate:.6f} {result.currency}"
        if result.estimate is not None
        else "n/c"
    )
    print(
        f"  {result.model_id:<18} input {result.input_tokens} tok, output limit "
        f"{result.output_limit} tok + thinking {result.thinking_budget} tok: "
        f"<= {value} (run cap {gemini_check.MAX_TOTAL_ESTIMATE} USD)"
    )
    if result.reasons:
        print("refusing: " + "; ".join(result.reasons))
        return 2
    permission = live_permission(loaded)
    if not permission.allowed:
        print("live calls are blocked: " + "; ".join(permission.reasons))
        return 0 if not args.run else 1
    if not args.run:
        print("plan only; add --run to make the 1 live call")
        return 0
    if not args.yes and input("Make 1 live call now? Type yes: ").strip() != "yes":
        print("not run")
        return 0

    results = run(
        lambda o: load_settings(overrides={**o, **overrides}),
        models=(args.model,),
    )
    results["check"] = "metis-gemini-live-check"
    results["thinking_budget"] = args.thinking_budget
    out = (
        repo_root()
        / "docs"
        / "references"
        / f"metis_gemini_live_check_{results['date']}.json"
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
