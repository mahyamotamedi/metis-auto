"""Calibration set, human ratings, agreement, bias diagnostics and the Persian
gate (Stage E5; framework §0.4, §6; TODO-05).

**Export** a calibration set as IDs, language and derived lengths only (no
text): predominantly Persian by a configured share (the size and share have no
default), selected deterministically by a seeded hash. A Persian target the
data cannot meet is reported ``persian_unmet``; it is never filled with other
languages silently. **Import** human ratings from CSV text (item, rater,
preference); several raters give a consensus only by strict majority.
**Agreement** (accuracy or Cohen's kappa, chosen in config, no default) compares
the judge's pair preference with the consensus. **Diagnostics**: first-position
pick rate (a position-unbiased judge picks the first slot about half the time
once orderings are swapped), swap consistency, and a verbosity-bias estimate
(how much more often the judge, than the humans, prefers the longer answer).

**Gate.** Judge scores are ``validated`` for a language slice only if
``min_agreement`` and ``min_items`` are both configured, the slice has at
least ``min_items`` rated items, and agreement (its interval's lower bound when
there is one, else the point value) reaches ``min_agreement``. Anything else,
including every unset value, leaves the slice ``unvalidated`` with the reason.
``gated_tables`` sets the E1 table's ``quality_validated`` flag per language
from the gate, so unvalidated scores cannot reach a non-inferiority claim or an
oracle label. Pure; no I/O (the caller reads and writes files). Calibration
files hold item IDs: keep them out of git. Status: provisional (Stage E5).
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import model_validator

from metis_auto.contracts import ContractModel
from metis_auto.evaluation.comparison.stats import cluster_bootstrap
from metis_auto.evaluation.comparison.types import (
    PRIMARY_LANGUAGE,
    Estimate,
    OutcomeTable,
    not_measured,
)

from .pairwise import PairOutcome
from .types import PREFERENCES, Bootstrap

PROVENANCE = "estimated"


class CalibrationConfig(ContractModel):
    size: int | None = None
    persian_share: float | None = None
    seed: str | None = None

    @model_validator(mode="after")
    def _check(self) -> CalibrationConfig:
        if self.size is not None and self.size < 1:
            raise ValueError("size must be at least 1")
        if self.persian_share is not None and not 0 <= self.persian_share <= 1:
            raise ValueError("persian_share must be between 0 and 1")
        return self


class GateConfig(ContractModel):
    agreement_statistic: Literal["accuracy", "cohen_kappa"] | None = None
    min_agreement: float | None = None
    min_items: int | None = None

    @model_validator(mode="after")
    def _check(self) -> GateConfig:
        if self.min_agreement is not None and not -1 <= self.min_agreement <= 1:
            raise ValueError("min_agreement must be between -1 and 1")
        if self.min_items is not None and self.min_items < 1:
            raise ValueError("min_items must be at least 1")
        return self


# --- export and import ---------------------------------------------------------


@dataclass(frozen=True)
class CalibrationItem:
    item_id: str
    session_ref: str
    language: str
    candidate: str
    reference: str
    candidate_chars: int
    reference_chars: int


@dataclass(frozen=True)
class CalibrationExport:
    state: str
    """``planned`` or ``not_evaluated``."""
    reason: str | None
    items: tuple[CalibrationItem, ...]
    persian_target: int | None
    persian_achieved: int
    other_achieved: int
    persian_unmet: bool
    notes: tuple[str, ...] = field(default_factory=tuple)


def export_calibration(
    outcomes: Sequence[PairOutcome], config: CalibrationConfig
) -> CalibrationExport:
    if config.size is None:
        return CalibrationExport("not_evaluated", "size_unset", (), None, 0, 0, False)
    if config.persian_share is None:
        return CalibrationExport(
            "not_evaluated", "persian_share_unset", (), None, 0, 0, False
        )
    if not config.seed:
        return CalibrationExport("not_evaluated", "seed_unset", (), None, 0, 0, False)

    def key(o: PairOutcome) -> str:
        digest = hashlib.sha256(f"{config.seed}\x1f{o.item.item_id}".encode())
        return digest.hexdigest()

    judged = [o for o in outcomes if o.state == "judged"]
    persian = sorted(
        (o for o in judged if o.item.language == PRIMARY_LANGUAGE), key=key
    )
    others = sorted((o for o in judged if o.item.language != PRIMARY_LANGUAGE), key=key)
    target = round(config.size * config.persian_share)
    take_persian = persian[:target]
    take_others = others[: config.size - target]
    chosen = take_persian + take_others
    items = tuple(
        CalibrationItem(
            o.item.item_id,
            o.item.session_ref,
            o.item.language,
            f"{o.item.candidate[0]}@{o.item.candidate[1] or '-'}",
            f"{o.item.reference[0]}@{o.item.reference[1] or '-'}",
            o.candidate_chars or 0,
            o.reference_chars or 0,
        )
        for o in chosen
    )
    notes = []
    if len(take_persian) < target:
        notes.append("persian_items_fewer_than_target")
    if len(take_others) < config.size - target:
        notes.append("other_items_fewer_than_requested")
    return CalibrationExport(
        "planned",
        None,
        items,
        target,
        len(take_persian),
        len(take_others),
        len(take_persian) < target,
        tuple(notes),
    )


CSV_COLUMNS = (
    "item_id",
    "language",
    "candidate",
    "reference",
    "candidate_chars",
    "reference_chars",
    "rater_id",
    "preference",
)


def to_csv(export: CalibrationExport) -> str:
    """The rating sheet: IDs, language and lengths only; ``rater_id`` and
    ``preference`` are left empty for the human to fill (one row per rater)."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for item in export.items:
        writer.writerow(
            [
                item.item_id,
                item.language,
                item.candidate,
                item.reference,
                item.candidate_chars,
                item.reference_chars,
                "",
                "",
            ]
        )
    return out.getvalue()


@dataclass(frozen=True)
class HumanLabel:
    item_id: str
    n_raters: int
    consensus: str | None
    """The strict-majority preference, or None (no consensus)."""


def read_ratings(csv_text: str) -> dict[str, HumanLabel]:
    reader = csv.DictReader(io.StringIO(csv_text))
    missing = {"item_id", "rater_id", "preference"} - set(reader.fieldnames or ())
    if missing:
        raise ValueError(f"missing columns {sorted(missing)}")
    votes: dict[str, list[str]] = {}
    for row_number, row in enumerate(reader, start=2):
        preference = (row["preference"] or "").strip().lower()
        if not preference:
            continue
        if preference not in PREFERENCES:
            raise ValueError(
                f"row {row_number}: preference must be one of {PREFERENCES}"
            )
        if not (row["rater_id"] or "").strip():
            raise ValueError(f"row {row_number}: rater_id is required")
        votes.setdefault(row["item_id"], []).append(preference)
    labels = {}
    for item_id, cast in votes.items():
        top, count = Counter(cast).most_common(1)[0]
        labels[item_id] = HumanLabel(
            item_id, len(cast), top if count * 2 > len(cast) else None
        )
    return labels


# --- agreement and diagnostics --------------------------------------------------


def _pairs(
    outcomes: Sequence[PairOutcome], labels: Mapping[str, HumanLabel]
) -> list[tuple[str, str, str]]:
    out = []
    for o in outcomes:
        label = labels.get(o.item.item_id)
        if o.state == "judged" and o.preference and label and label.consensus:
            out.append((o.preference, label.consensus, o.item.session_ref))
    return out


def _accuracy(rows: Sequence[tuple[str, str, str]]) -> float | None:
    return sum(j == h for j, h, _ in rows) / len(rows) if rows else None


def _kappa(rows: Sequence[tuple[str, str, str]]) -> float | None:
    if not rows:
        return None
    n = len(rows)
    observed = sum(j == h for j, h, _ in rows) / n
    judge = Counter(j for j, _, _ in rows)
    human = Counter(h for _, h, _ in rows)
    expected = sum((judge[c] / n) * (human[c] / n) for c in PREFERENCES)
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


def agreement(
    outcomes: Sequence[PairOutcome],
    labels: Mapping[str, HumanLabel],
    *,
    statistic: str | None,
    bootstrap: Bootstrap | None,
) -> Estimate:
    if statistic is None:
        return not_measured("not_evaluated", "agreement_statistic_unset", 0, PROVENANCE)
    if statistic not in ("accuracy", "cohen_kappa"):
        raise ValueError("statistic must be accuracy or cohen_kappa")
    rows = _pairs(outcomes, labels)
    if not rows:
        return not_measured("not_evaluated", "no_rated_items", 0, PROVENANCE)
    function = _accuracy if statistic == "accuracy" else _kappa
    point = function(rows)
    if point is None:
        return not_measured("undefined", "statistic_undefined", len(rows), PROVENANCE)
    interval = None
    if bootstrap is not None:
        result = cluster_bootstrap(
            rows,
            lambda r: r[2],
            function,
            n_boot=bootstrap.n_boot,
            seed=bootstrap.seed,
            level=bootstrap.level,
        )
        if result.low is not None and result.high is not None:
            interval = (result.low, result.high)
    return Estimate(
        "measured",
        len(rows),
        PROVENANCE,
        value=point,
        interval=interval,
        level=bootstrap.level if interval and bootstrap else None,
        method=statistic,
    )


def position_bias(outcomes: Sequence[PairOutcome]) -> Estimate:
    """Share of non-tie orderings that picked the first slot. With orderings
    swapped, an unbiased judge sits near one half; 1 is always-first, 0 is
    always-second. Needs no human labels."""
    judged = [o for o in outcomes if o.state == "judged"]
    non_tie = sum(
        (o.candidate_first != "tie") + (o.reference_first != "tie") for o in judged
    )
    if not non_tie:
        return not_measured("not_evaluated", "no_non_tie_verdicts", 0, PROVENANCE)
    picks = sum(o.first_position_picks for o in judged)
    return Estimate(
        "measured",
        non_tie,
        PROVENANCE,
        value=picks / non_tie,
        method="first_position_rate",
    )


def swap_consistency(outcomes: Sequence[PairOutcome]) -> Estimate:
    """Share of pairs on which both orderings gave the same verdict."""
    judged = [o for o in outcomes if o.state == "judged"]
    if not judged:
        return not_measured("not_evaluated", "no_judged_items", 0, PROVENANCE)
    return Estimate(
        "measured",
        len(judged),
        PROVENANCE,
        value=sum(bool(o.swap_consistent) for o in judged) / len(judged),
        method="swap_consistency",
    )


def verbosity_bias(
    outcomes: Sequence[PairOutcome], labels: Mapping[str, HumanLabel]
) -> Estimate:
    """On items where judge and humans both pick a side and the answers differ
    in length: judge's longer-wins share minus the humans'. Positive means the
    judge favours length more than the humans do."""
    judge_longer = human_longer = n = 0
    for o in outcomes:
        label = labels.get(o.item.item_id)
        if (
            o.state != "judged"
            or o.preference in (None, "tie")
            or not label
            or label.consensus in (None, "tie")
            or o.candidate_chars == o.reference_chars
        ):
            continue
        candidate_longer = (o.candidate_chars or 0) > (o.reference_chars or 0)
        n += 1
        judge_longer += (o.preference == "candidate") == candidate_longer
        human_longer += (label.consensus == "candidate") == candidate_longer
    if not n:
        return not_measured("not_evaluated", "no_comparable_items", 0, PROVENANCE)
    return Estimate(
        "measured",
        n,
        PROVENANCE,
        value=judge_longer / n - human_longer / n,
        method="longer_wins_difference",
        extra={
            "judge_longer_share": judge_longer / n,
            "human_longer_share": human_longer / n,
        },
    )


# --- the gate ------------------------------------------------------------------


@dataclass(frozen=True)
class GateResult:
    language: str
    validated: bool
    reason: str | None
    agreement: float | None
    lower_bound: float | None
    n_items: int


def evaluate_gate(
    agreements: Mapping[str, Estimate], gate: GateConfig
) -> dict[str, GateResult]:
    """One result per language in ``agreements`` (language → agreement)."""
    results = {}
    for language, est in agreements.items():
        lower = est.interval[0] if est.interval else None
        validated, reason = _gate_decision(est, lower, gate)
        results[language] = GateResult(
            language, validated, reason, est.value, lower, est.n
        )
    return results


def _gate_decision(
    est: Estimate, lower: float | None, gate: GateConfig
) -> tuple[bool, str | None]:
    if gate.agreement_statistic is None:
        return False, "agreement_statistic_unset"
    if gate.min_agreement is None:
        return False, "min_agreement_unset"
    if gate.min_items is None:
        return False, "min_items_unset"
    if not est.measured or est.value is None:
        return False, f"agreement_{est.state}"
    if est.n < gate.min_items:
        return False, "n_below_min_items"
    worst = lower if lower is not None else est.value
    if worst >= gate.min_agreement:
        return True, None
    return False, "agreement_below_threshold"


def gated_tables(
    table: OutcomeTable, gate_results: Mapping[str, GateResult]
) -> dict[str, OutcomeTable]:
    """One E1 table per language with ``quality_validated`` set from that
    language's gate (False when it has no gate result), plus ``all``, validated
    only if every language present is."""
    languages = sorted({r.language for r in table.requests})
    out = {}
    flags = {}
    for language in languages:
        flags[language] = bool(
            gate_results.get(language) and gate_results[language].validated
        )
        subset = table.language(language)
        out[language] = OutcomeTable(
            subset.requests,
            subset.cost_provenance,
            subset.quality_provenance,
            flags[language],
        )
    out["all"] = OutcomeTable(
        table.requests,
        table.cost_provenance,
        table.quality_provenance,
        bool(flags) and all(flags.values()),
    )
    return out
