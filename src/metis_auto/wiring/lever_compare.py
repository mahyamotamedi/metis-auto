"""Compose the lever comparison command (S-2; FR-ACCT-05, FR-EVAL-02, QA-COST).

``collect`` reads lever result files and keeps only result JSON: the command's own
output, non-JSON files, unreadable JSON and JSON of another shape (a summary such
as ``final.json``) are skipped. A result is read with the shared ``LeverResult``
(S-1, ``LeverResult.model_validate``); JSON it refuses counts as another shape.
``write_comparison`` writes the Markdown from ``analysis.compare``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from metis_auto.analysis.compare import to_markdown
from metis_auto.analysis.lever_result import LeverResult


def collect(
    paths: Sequence[Path], *, out: Path
) -> tuple[list[LeverResult], list[Path]]:
    """(results, skipped paths), results in the order given."""
    results: list[LeverResult] = []
    skipped: list[Path] = []
    target = out.resolve()
    for path in paths:
        if path.resolve() == target or path.suffix != ".json" or not path.is_file():
            skipped.append(path)
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            skipped.append(path)
            continue
        try:
            results.append(LeverResult.model_validate(data))
        except ValidationError:
            skipped.append(path)
    return results, skipped


def write_comparison(
    paths: Sequence[Path], *, out: Path, max_tenant_share: Decimal
) -> dict[str, object]:
    """Write the comparison to ``out``; return content-free counts.

    ``max_tenant_share`` is ``[sample] tenant_cap`` from ``sprint.toml`` (the
    script reads it).
    """
    results, skipped = collect(paths, out=out)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = to_markdown(results, max_tenant_share=max_tenant_share)
    out.write_text(text, encoding="utf-8")
    return {"results": len(results), "skipped": len(skipped), "out": str(out)}
