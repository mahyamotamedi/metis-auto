"""Log the lever results in ``reports/levers/`` to MLflow (sprint T-2).

One run per ``LeverResult`` JSON, through the ``RunTracker`` port (idempotent by
``lever_id`` + ``config_hash``: running this twice adds no runs). Files that are
not lever results (``pipeline_b_overhead.json``, ``final.json``, which is an
aggregate over lever results, not one) are skipped and listed. The default store
is the git-ignored local file store ``runs/mlruns``; nothing hosted is started.

    python scripts/log_levers.py                      # -> runs/mlruns
    python scripts/log_levers.py --tracking-uri http://127.0.0.1:5000
    mlflow ui --backend-store-uri runs/mlruns         # then open the UI

Needs the ``services`` extra. No text, ID or hash but the manifest pins is logged
(adapters/tracking/mlflow_tracker.py). Traces: QA-REPRO, QA-PRIV.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

from metis_auto.ports.tracking import RunTracker  # noqa: E402

REQUIRED = ("lever_id", "manifest", "saving", "baseline_cost")


def lever_results(folder: Path) -> tuple[list[dict], list[str]]:
    """The lever-result files in ``folder`` and the names of those skipped."""
    found, skipped = [], []
    for path in sorted(folder.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and all(k in data for k in REQUIRED):
            found.append(data)
        else:
            skipped.append(path.name)
    return found, skipped


def log_all(tracker: RunTracker, results: list[dict]) -> list[tuple[str, str]]:
    """``(lever_id, run_id)`` per result; a lever ID may occur in several files."""
    return [(r["lever_id"], tracker.log_result(r)) for r in results]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--levers", type=Path, default=ROOT / "reports" / "levers")
    parser.add_argument(
        "--tracking-uri", default=(ROOT / "runs" / "mlruns").resolve().as_uri()
    )
    parser.add_argument("--experiment", default="metis-levers")
    args = parser.parse_args(argv)

    from metis_auto.adapters.tracking.mlflow_tracker import MlflowRunTracker

    results, skipped = lever_results(args.levers)
    tracker = MlflowRunTracker(args.tracking_uri, args.experiment)
    runs = log_all(tracker, results)
    distinct = len({run for _, run in runs})
    print(
        f"{len(runs)} lever results -> {distinct} runs "
        f"in {args.tracking_uri} (experiment {args.experiment})"
    )
    print("skipped (not lever results): " + (", ".join(skipped) or "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
