"""P-2 spot-check agreement and the Persian gate for the benchmark's judges
(ADR-0053 amendment 1).

The filled spot-check sheet (``spot_id, language, rater, rating, note``; the
rating is ``a``, ``b`` or ``tie`` in the *blinded* order) and the local key
(``spot_id, item_id, candidate_is``) become E5's rating import
(``item_id, rater_id, preference`` with ``candidate`` / ``reference`` / ``tie``).
Agreement per judge and per language group then uses E5's ``agreement`` and the
gate is E5's ``evaluate_gate``; no new statistic and no new threshold. A pair
the judge scored swap-inconsistently has no verdict, so it is counted but is
not part of the agreement. A language group is ``validated`` only when **every**
judge passes the gate on it; with no gate values set it is ``not_configured``.

The report holds counts and statistics only: no item IDs, no model names, no
text. Pure. Traces: FR-EVAL-04, FR-EVAL-05, ADR-0053. Status: provisional.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from typing import Any

from metis_auto.evaluation.comparison.types import Estimate
from metis_auto.evaluation.judging.calibration import (
    GateConfig,
    HumanLabel,
    agreement,
    evaluate_gate,
    read_ratings,
)
from metis_auto.evaluation.judging.pairwise import PairOutcome
from metis_auto.evaluation.judging.types import Bootstrap, PairItem

FORMAT_VERSION = "benchmark-agreement-v1"
SHEET_COLUMNS = ("spot_id", "language", "rater", "rating", "note")
KEY_COLUMNS = ("spot_id", "item_id", "candidate_is")
_BLINDED = ("a", "b", "tie")
_PREFERENCE_OF_SCORE = {1.0: "candidate", 0.5: "tie", 0.0: "reference"}


def gate_configured(gate: GateConfig) -> bool:
    return any(
        v is not None
        for v in (gate.agreement_statistic, gate.min_agreement, gate.min_items)
    )


def gate_by_language(
    report: Mapping[str, Any] | None, gate: GateConfig, languages: Sequence[str]
) -> dict[str, str]:
    """Language → ``validated`` / ``unvalidated`` / ``not_configured``, for the
    label file's ``judge_gate``. Not configured wins; a configured gate with no
    report, or no result for a language, is ``unvalidated``."""
    if not gate_configured(gate):
        return dict.fromkeys(languages, "not_configured")
    results = (report or {}).get("judge_gate", {})
    return {language: results.get(language, "unvalidated") for language in languages}


def agreement_report(
    *,
    run_id: str,
    sheet_text: str,
    key_text: str,
    judge_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    gate: GateConfig,
    bootstrap: Bootstrap | None = None,
) -> dict[str, Any]:
    """``judge_rows``: judge ID → that judge's score rows (the
    ``<judge>.scores.jsonl`` lines). Refuses a malformed sheet or key, naming
    the row and never its content."""
    key = _read_key(key_text)
    ratings_csv, sheet_stats = _ratings_from_sheet(sheet_text, key)
    labels = read_ratings(ratings_csv)
    in_sheet = set(key.values_by_item)
    unrated = sum(1 for item in in_sheet if item not in labels)
    no_consensus = sum(1 for label in labels.values() if label.consensus is None)

    cells: dict[str, dict[str, dict[str, Any]]] = {}
    outcomes_by_judge = {
        judge: _outcomes(rows, in_sheet) for judge, rows in judge_rows.items()
    }
    languages = sorted(
        {o.item.language for outcomes in outcomes_by_judge.values() for o in outcomes}
    )
    configured = gate_configured(gate)
    for judge, outcomes in sorted(outcomes_by_judge.items()):
        cells[judge] = {
            language: _cell(
                [o for o in outcomes if o.item.language == language],
                labels,
                gate,
                bootstrap,
                configured,
            )
            for language in languages
        }
    judge_gate = {
        language: _language_state([cells[j][language] for j in cells], configured)
        for language in languages
    }
    return {
        "format": FORMAT_VERSION,
        "run_id": run_id,
        "gate": {
            "agreement_statistic": gate.agreement_statistic,
            "min_agreement": gate.min_agreement,
            "min_items": gate.min_items,
        },
        "gate_configured": configured,
        "sheet": {
            "items": len(in_sheet),
            "unrated_items": unrated,
            "items_without_consensus": no_consensus,
            "raters": sheet_stats["raters"],
        },
        "judges": cells,
        "judge_gate": judge_gate,
    }


# --- the sheet and the key ----------------------------------------------------


class _Key:
    def __init__(self) -> None:
        self.by_spot: dict[str, tuple[str, str]] = {}
        self.values_by_item: dict[str, str] = {}


def _read_key(text: str) -> _Key:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    missing = set(KEY_COLUMNS) - set(reader.fieldnames or ())
    if missing:
        raise ValueError(f"key is missing columns {sorted(missing)}")
    key = _Key()
    for row_number, row in enumerate(reader, start=2):
        spot, item, shown = ((row[c] or "").strip() for c in KEY_COLUMNS)
        if shown not in ("a", "b"):
            raise ValueError(f"key row {row_number}: candidate_is must be a or b")
        if spot in key.by_spot or item in key.values_by_item:
            raise ValueError(f"key row {row_number}: duplicate spot_id or item_id")
        key.by_spot[spot] = (item, shown)
        key.values_by_item[item] = spot
    return key


def _ratings_from_sheet(text: str, key: _Key) -> tuple[str, dict[str, int]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    missing = set(SHEET_COLUMNS) - set(reader.fieldnames or ())
    if missing:
        raise ValueError(f"sheet is missing columns {sorted(missing)}")
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(("item_id", "rater_id", "preference"))
    raters: set[str] = set()
    for row_number, row in enumerate(reader, start=2):
        spot = (row["spot_id"] or "").strip()
        if spot not in key.by_spot:
            raise ValueError(f"row {row_number}: unknown spot_id")
        rating = (row["rating"] or "").strip().lower()
        if not rating:
            continue
        if rating not in _BLINDED:
            raise ValueError(f"row {row_number}: rating must be one of {_BLINDED}")
        rater = (row["rater"] or "").strip()
        if not rater:
            raise ValueError(f"row {row_number}: rater is required for a rating")
        item, candidate_is = key.by_spot[spot]
        if rating == "tie":
            preference = "tie"
        else:
            preference = "candidate" if rating == candidate_is else "reference"
        raters.add(rater)
        writer.writerow((item, rater, preference))
    return out.getvalue(), {"raters": len(raters)}


# --- per judge and language ---------------------------------------------------


def _outcomes(
    rows: Sequence[Mapping[str, Any]], in_sheet: set[str]
) -> list[PairOutcome]:
    """Score rows in the sheet as E5 outcomes. The rows carry the score, not
    the verdict, so the preference is read back from it (1 / 0.5 / 0)."""
    out = []
    for r in rows:
        item = PairItem(
            case_id=r["case_id"],
            session_ref=r["case_id"],
            language=r["language"],
            candidate=(r["candidate"], None),
            reference=(r["reference"], None),
        )
        if item.item_id not in in_sheet:
            continue
        preference = None
        if r["state"] == "judged" and r["score"] is not None:
            preference = _PREFERENCE_OF_SCORE.get(float(r["score"]))
            if preference is None:
                raise ValueError("a judged score must be 0, 0.5 or 1")
        out.append(
            PairOutcome(
                item,
                r["state"],
                r.get("reason"),
                r["score"],
                preference,
                None,
                None,
                r.get("first_position_picks", 0),
                r.get("swap_consistent"),
                None,
                None,
                None,
            )
        )
    return out


def _cell(
    outcomes: Sequence[PairOutcome],
    labels: Mapping[str, HumanLabel],
    gate: GateConfig,
    bootstrap: Bootstrap | None,
    configured: bool,
) -> dict[str, Any]:
    est = agreement(
        outcomes, labels, statistic=gate.agreement_statistic, bootstrap=bootstrap
    )
    n_rated = sum(
        1
        for o in outcomes
        if o.state == "judged"
        and o.preference
        and (label := labels.get(o.item.item_id))
        and label.consensus
    )
    inconsistent = sum(1 for o in outcomes if o.state == "inconsistent")
    judged = sum(1 for o in outcomes if o.state == "judged")
    language = outcomes[0].item.language if outcomes else ""
    if not configured:
        state, reason, status = "not_configured", None, "not_configured"
    else:
        result = evaluate_gate({language: est}, gate)[language]
        state = "validated" if result.validated else "unvalidated"
        reason = result.reason
        enough = gate.min_items is not None and n_rated >= gate.min_items
        status = "sufficient" if enough else "insufficient"
    return {
        "pairs_in_sheet": len(outcomes),
        "judged_consistent": judged,
        "inconsistent": inconsistent,
        "n_rated": n_rated,
        "status": status,
        "agreement": _estimate(est),
        "gate": {"state": state, "reason": reason},
    }


def _estimate(est: Estimate) -> dict[str, Any]:
    return {
        "state": est.state,
        "value": est.value,
        "interval": list(est.interval) if est.interval else None,
        "method": est.method,
        "reason": est.reason,
        "n": est.n,
    }


def _language_state(cells: Sequence[Mapping[str, Any]], configured: bool) -> str:
    if not configured:
        return "not_configured"
    ok = all(c["gate"]["state"] == "validated" for c in cells)
    return "validated" if cells and ok else "unvalidated"
