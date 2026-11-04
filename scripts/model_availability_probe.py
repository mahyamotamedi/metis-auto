"""Which models does the Metis wrapper serve today? (ADR-0053 amendment 5)

    python scripts/model_availability_probe.py              # plan only: no call
    python scripts/model_availability_probe.py --run        # asks, then calls
    python scripts/model_availability_probe.py --run --yes  # owner already approved

The wrapper documents no model-list endpoint (docs/references/metis_wrapper_api.md),
so this sends ONE tiny SYNTHETIC message per model (the live wrapper check's
message), through the spend guard, the persistent ledger and the recording
decorator, and records status, provider-reported model and usage. No text.
Uses the benchmark's catalogue and price files (``benchmark.toml [reference]``).
Writes ``docs/references/metis_model_availability_<date>.json``. Thin wrapper:
the logic is ``metis_auto.wiring.wrapper_check``.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib

from metis_auto.settings import load_settings, repo_root
from metis_auto.wiring.from_settings import live_permission
from metis_auto.wiring.live import live_overrides
from metis_auto.wiring.wrapper_check import MAX_TOTAL_ESTIMATE, plan, run

MODELS = (
    "deepseek-v4.1-flash",
    "deepseek-v4-flash",
    "gpt-5-nano",
    "gpt-4o-mini",
    "gpt-4.1-nano",
    "mimo-v2.5",
)


def _reference() -> dict[str, str]:
    raw = tomllib.loads(
        (repo_root() / "config/evaluation/benchmark.toml").read_text("utf-8")
    )
    ref = raw.get("reference", {})
    return {f"reference.{k}": v for k, v in ref.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--models", nargs="+", default=list(MODELS))
    parser.add_argument("--suffix", default="")
    parser.add_argument(
        "--catalogue",
        default=None,
        help="a catalogue file with every probed model enabled (a temporary copy; "
        "the repository's file keeps its enabled flags)",
    )
    args = parser.parse_args()
    ref = _reference()
    if args.catalogue:
        ref["reference.catalogue"] = args.catalogue

    def loader(overrides):
        return load_settings(overrides=overrides | ref)

    loaded = loader(live_overrides(allow_unknown_window=True))
    rows, total = plan(loaded, args.models)
    for r in rows:
        value = f"{r.estimate:.6f} {r.currency}" if r.estimate is not None else "n/c"
        print(
            f"  {r.model_id:<20} input {r.input_tokens:>4} tok, "
            f"output limit {r.output_limit:>6} tok: <= {value}"
        )
    print(f"  total upper bound: {total} USD (limit {MAX_TOTAL_ESTIMATE} USD)")
    if total is None or total >= MAX_TOTAL_ESTIMATE:
        print("refusing: the estimate is not computed or too high")
        return 2
    permission = live_permission(loaded)
    if not permission.allowed:
        print("live calls are blocked: " + "; ".join(permission.reasons))
        return 1 if args.run else 0
    if not args.run:
        print(f"plan only; add --run to make the {len(args.models)} live calls")
        return 0
    if (
        not args.yes
        and input(f"Make {len(args.models)} live calls? Type yes: ") != "yes"
    ):
        print("not run")
        return 0
    results = run(loader, models=args.models)
    out = (
        repo_root()
        / "docs"
        / "references"
        / f"metis_model_availability_{results['date']}{args.suffix}.json"
    )
    out.write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(results["results"], indent=2, ensure_ascii=True))
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
