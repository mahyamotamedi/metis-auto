"""Compose the framework's evaluation of the pipelines' lever results.

``collect`` reads lever result JSON files (the same files ``lever_compare``
reads) and keeps only result JSON; the command's own output and anything of
another shape are skipped. ``write_evaluation`` applies the framework's rules
(``evaluation.reporting.lever_verdicts``, pure) and writes a JSON and a Markdown
report. Content-free (counts, savings, reasons); no network, no model call.
Traces: FR-EVAL-04, FR-EVAL-05. Status: provisional.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from metis_auto.evaluation.reporting import lever_verdicts as lv
from metis_auto.wiring._interim_lever_json import is_result

OUTPUT_NAMES = ("lever_evaluation.json", "lever_evaluation.md")


def collect(paths: Sequence[Path]) -> tuple[list[dict[str, Any]], list[Path]]:
    """(result mappings in the order given, skipped paths)."""
    results: list[dict[str, Any]] = []
    skipped: list[Path] = []
    for path in paths:
        if path.suffix != ".json" or not path.is_file() or path.name in OUTPUT_NAMES:
            skipped.append(path)
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            skipped.append(path)
            continue
        if not is_result(data):
            skipped.append(path)
            continue
        results.append(data)
    return results, skipped


def write_evaluation(
    paths: Sequence[Path],
    *,
    out_dir: Path,
    min_reviewed: int = lv.DEFAULT_MIN_REVIEWED,
) -> dict[str, Any]:
    """Write ``lever_evaluation.json`` and ``.md`` under ``out_dir``; return
    content-free counts."""
    results, skipped = collect(paths)
    report = lv.evaluate_levers(results, min_reviewed=min_reviewed)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / OUTPUT_NAMES[0]).write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / OUTPUT_NAMES[1]).write_text(lv.to_markdown(report), encoding="utf-8")
    return {
        "results": len(results),
        "skipped": len(skipped),
        "pickable": {s: b["pickable"] for s, b in report["steps"].items()},
        "out_dir": str(out_dir),
    }
