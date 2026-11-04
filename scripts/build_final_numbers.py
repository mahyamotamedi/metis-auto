"""Build ``reports/levers/final.json`` (sprint plan I-2; format ``final-v1``).

    .venv/bin/python scripts/build_final_numbers.py

Reads the combined run's ``reports/pipelines/sprint-final/summary.json``, the
lever results of the pipelines' versions, F-2's cost trace and the baseline totals
of the report split (``baselines_full.baseline_costs`` on the same frame the
combined run used), and writes the content-free ``final.json`` through
``analysis.final_numbers.build_final``. Aggregates only: no text, ID or hash.
Refuses a summary from a smoke (sampled) run. No network, no model call, no key.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

from metis_auto.analysis.baselines_full import baseline_costs
from metis_auto.analysis.final_numbers import build_final
from metis_auto.analysis.lever_result import LeverResult

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "reports/pipelines/sprint-final/summary.json"
F2 = ROOT / "reports/cost/exp-cost-002/summary.json"
LEVERS = ROOT / "reports/levers"
CONFIG = ROOT / "experiments/pipelines/sprint-final.toml"
OUT = LEVERS / "final.json"


def _runner() -> Any:
    name = "build_final_run_sprint_final"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, ROOT / "scripts/run_sprint_final.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def named_versions(config: dict[str, Any]) -> set[str]:
    """Every version id the config names for a pipeline, winner or runner-up."""
    ids = set()
    for name, spec in config.items():
        if name.startswith("pipeline_") or name in ("parham", "winners", "runners_up"):
            ids |= {
                str(v) for k, v in spec.items() if k in ("cache", "context", "routing")
            }
    return ids


def pick_results(ids: set[str], populations: set[int]) -> list[LeverResult]:
    """The report-split results of the named versions (tune results and other
    populations are not part of the final numbers)."""
    picked = []
    for path in sorted(LEVERS.glob("*.json")):
        try:
            result = LeverResult.from_json(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        keys = {result.version, result.lever_id}
        named = any(k == i or k.startswith(i + ".") for k in keys for i in ids)
        if (
            named
            and ".tune" not in result.lever_id
            and result.n_requests in populations
        ):
            picked.append(result)
    return picked


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--summary", type=Path, default=SUMMARY)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    if summary["population"].get("sample") is not None:
        raise SystemExit("refused: the summary is from a sampled (smoke) run")
    config = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    runner = _runner()
    p = runner.Prep(None)
    scored = p.frame[p.scored]
    totals = baseline_costs(
        scored, p.ctx, premium_model=p.st["premium_model"], cached_separately=p.sep
    )
    baseline_totals = {
        k: {
            m: format(v, "f")
            for m, v in t.items()
            if m in ("total", "fees", "token_cost")
        }
        for k, t in totals.items()
    }
    expected = int(config["population"]["expected_requests"])
    results = pick_results(named_versions(config), {expected, expected - 1, 77774})
    f2 = json.loads(F2.read_text(encoding="utf-8"))
    final = build_final(summary, results, f2, baseline_totals, config)
    args.out.write_text(
        json.dumps(final, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    n = sum(len(b["pipelines"]) for b in final["baselines"].values())
    print(
        f"wrote {args.out}: {len(final['baselines'])} baselines, {n} pipeline cells, "
        f"{len(final['versions'])} version rows, skipped {sorted(final['skipped'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
