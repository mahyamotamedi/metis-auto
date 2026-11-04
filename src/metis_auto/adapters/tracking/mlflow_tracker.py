"""MLflow ``RunTracker`` (sprint T-2; QA-REPRO, QA-PRIV; ADR-0022, ADR-0032 point 8).

Responsibility: export one finished lever result as one MLflow run, so the runs
can be compared in the MLflow UI. The result JSON stays the record.

- **Params**: the manifest (data revision, code commit, config hash, seed, price
  version, ...).
- **Metrics**: total/fee/token-cost savings, baseline cost, the interval, counts
  and overhead (``None`` is skipped, never logged as 0).
- **Tags**: ``lever_id``, step, baseline, evidence class, correctness state and
  the slice *kinds* (``lang``, ``bot_rank``, ...), not every slice.
- **Artifact**: the result restricted to the known result fields (an allow-list),
  so a stray field never leaves the process. The manifest's reproducibility pins
  are the only hashes logged; no text or ID is.

Idempotent by ``lever_id`` + ``manifest.config_hash``. This is the only module
that imports ``mlflow`` (extra ``services``, ``tests/architecture/
test_service_imports.py``). Called by: scripts/log_levers.py. Status: provisional.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path

from mlflow.tracking import MlflowClient

# The LeverResult fields (analysis.lever_result); anything else is not exported.
RESULT_FIELDS = (
    "lever_id",
    "step",
    "version",
    "baseline",
    "evidence_class",
    "correctness_state",
    "baseline_cost",
    "saving",
    "ci_low",
    "ci_high",
    "n_eligible",
    "n_requests",
    "overhead_ms_p50",
    "overhead_ms_p95",
    "assumptions",
    "slices",
    "manifest",
)
_TAG_FIELDS = ("step", "version", "baseline", "evidence_class", "correctness_state")
_SCALAR_METRICS = (
    "ci_low",
    "ci_high",
    "n_eligible",
    "n_requests",
    "overhead_ms_p50",
    "overhead_ms_p95",
)
_SAFE = re.compile(r"[^A-Za-z0-9_.\- /]")


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]  # Decimal strings and numbers
    except (TypeError, ValueError):
        return None


class MlflowRunTracker:
    """Logs lever results to the MLflow store at ``tracking_uri``."""

    def __init__(self, tracking_uri: str, experiment: str = "metis-levers") -> None:
        self.tracking_uri = tracking_uri
        if tracking_uri.startswith("file:"):
            # MLflow 3.x refuses the file store unless opted in (maintenance
            # mode upstream); the sprint plan asks for it, mlflow-skinny has no
            # SQL backend, and the result JSON stays the record (ADR-0022).
            os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
        self.experiment = experiment
        self._client = MlflowClient(tracking_uri=tracking_uri)
        found = self._client.get_experiment_by_name(experiment)
        self._experiment_id = (
            found.experiment_id
            if found is not None
            else self._client.create_experiment(experiment)
        )

    def log_result(self, result: Mapping[str, object]) -> str:
        manifest = dict(result.get("manifest") or {})  # type: ignore[call-overload]
        lever_id = str(result["lever_id"])
        config_hash = str(manifest.get("config_hash", ""))
        existing = self._client.search_runs(
            [self._experiment_id],
            filter_string=(
                f"tags.lever_id = '{lever_id}' and tags.config_hash = '{config_hash}'"
            ),
            max_results=1,
        )
        if existing:
            return existing[0].info.run_id

        run = self._client.create_run(self._experiment_id, run_name=lever_id)
        run_id = run.info.run_id
        tags = {"lever_id": lever_id, "config_hash": config_hash}
        for name in _TAG_FIELDS:
            if result.get(name) is not None:
                tags[name] = str(result[name])
        slices = result.get("slices") or {}
        kinds = sorted({str(k).split(":")[0] for k in slices})  # type: ignore[attr-defined]
        tags["slice_kinds"] = ",".join(kinds)
        for key, value in tags.items():
            self._client.set_tag(run_id, key, value)
        for key, value in manifest.items():
            self._client.log_param(run_id, key, str(value))
        for group in ("saving", "baseline_cost"):
            block = result.get(group) or {}
            for part, value in block.items():  # type: ignore[attr-defined]
                number = _number(value)
                if number is not None:
                    prefix = "saving" if group == "saving" else "baseline"
                    self._client.log_metric(
                        run_id, f"{prefix}_{_SAFE.sub('_', part)}", number
                    )
        for name in _SCALAR_METRICS:
            number = _number(result.get(name))
            if number is not None:
                self._client.log_metric(run_id, name, number)
        share = _number((slices.get("all") or {}).get("saving_share"))  # type: ignore[attr-defined]
        if share is not None:
            self._client.log_metric(run_id, "saving_share", share)

        exported = {k: result[k] for k in RESULT_FIELDS if k in result}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lever_result.json"
            path.write_text(json.dumps(exported, indent=2, sort_keys=True), "utf-8")
            self._client.log_artifact(run_id, str(path))
        self._client.set_terminated(run_id, "FINISHED")
        return run_id


__all__ = ["RESULT_FIELDS", "MlflowRunTracker"]
