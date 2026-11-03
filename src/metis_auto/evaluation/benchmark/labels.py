"""P-3: judged results → routing labels for R-B3 (kNN) and R-C3 (classifier).

Per record and answering arm, each judge's pairwise score against the
reference (gpt-5.5; E5: 1 win, 0.5 tie, 0 loss, averaged over both orders) is
**acceptable** when it is at least ``acceptable_score`` (an owner decision; unset
refuses). An arm is acceptable when **both** judges say so, not acceptable when
both say not, and unknown when they disagree or one did not judge it (never
resolved by guessing). From that:

- ``cheap_ok``: some ``cheap_arms`` arm (owner decision) is acceptable → True;
  every cheap arm is not acceptable → False; else None. This is R-C3's boolean
  label (``fit_logistic(labels=...)``: True = a small model is enough).
- ``min_adequate_tier``: the lowest catalogue tier among acceptable arms (L2,
  routing plan §2); None when no arm is known acceptable.

``labels_source`` is ``benchmark:<name>``, the form R-C3 accepts
(``LABEL_SOURCE``). Rows carry the record ID and the join key
``user_message_id`` (= golden-v2 ``target_message_id`` = the requests frame's
``user_message_id``); the label file stays local (git-ignored ``runs/``), and
only the content-free summary may be committed. Format:
docs/evaluation/benchmark_labels.md. Pure apart from pandas.
Traces: FR-ROUTE-03, routing plan §2 (L1, L2), ADR-0053.
Status: provisional.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import pandas as pd

from metis_auto.evaluation.judging.pairwise import JudgeRun

from .config import require

SOURCE = re.compile(r"^benchmark:[a-z0-9][a-z0-9_.\-]*$")
FORMAT_VERSION = "benchmark-labels-v1"
COLUMNS = (
    "format",
    "record_id",
    "user_message_id",
    "labels_source",
    "state",
    "cheap_ok",
    "min_adequate_tier",
    "judges",
    "arms_judged",
)


@dataclass(frozen=True)
class LabelRow:
    record_id: str
    user_message_id: str
    labels_source: str
    state: str
    """``labelled`` or ``not_labelled:<reason>``."""
    cheap_ok: bool | None
    min_adequate_tier: int | None
    judges: int
    arms_judged: int
    arm_acceptable: Mapping[str, bool | None] = field(default_factory=dict)


def scores_of(run: JudgeRun) -> dict[tuple[str, str], float]:
    """``(record ID, candidate model) → pairwise score`` of one judge."""
    return {
        (o.item.case_id, o.item.candidate[0]): o.score
        for o in run.judged
        if o.score is not None
    }


def make_labels(
    scores: Sequence[Mapping[tuple[str, str], float]],
    *,
    records: Mapping[str, str],
    arms: Sequence[str],
    tiers: Mapping[str, int],
    acceptable_score: float | None,
    cheap_arms: Sequence[str] | None,
    name: str,
) -> tuple[LabelRow, ...]:
    """``records``: record ID → user message ID. ``scores``: one table per
    judge (plan P-2: two), from ``scores_of`` or the judging files."""
    threshold = require(acceptable_score, "labels.acceptable_score")
    cheap = tuple(require(cheap_arms, "labels.cheap_arms"))
    source = f"benchmark:{name}"
    if not SOURCE.match(source):
        raise ValueError(
            f"labels source {source!r} is not of the form benchmark:<name>"
        )
    if len(scores) != 2:
        raise ValueError("labels need the two judges' scores (plan P-2)")
    unknown = [a for a in cheap if a not in arms]
    if unknown:
        raise ValueError(f"cheap arms not among the arms: {unknown}")
    by_judge = list(scores)
    out = []
    for record_id, message_id in records.items():
        verdicts: dict[str, bool | None] = {}
        judged = 0
        for arm in arms:
            scores = [s.get((record_id, arm)) for s in by_judge]
            if any(x is None for x in scores):
                verdicts[arm] = None
                continue
            judged += 1
            ok = [x >= threshold for x in scores]  # type: ignore[operator]
            verdicts[arm] = ok[0] if ok[0] == ok[1] else None
        cheap_values = [verdicts.get(a) for a in cheap]
        if any(v is True for v in cheap_values):
            cheap_ok: bool | None = True
        elif cheap_values and all(v is False for v in cheap_values):
            cheap_ok = False
        else:
            cheap_ok = None
        acceptable = [tiers[a] for a, v in verdicts.items() if v is True]
        min_tier = min(acceptable) if acceptable else None
        if judged == 0:
            state = "not_labelled:not_judged"
        elif cheap_ok is None and min_tier is None:
            state = "not_labelled:judges_disagree_or_incomplete"
        else:
            state = "labelled"
        out.append(
            LabelRow(
                record_id=record_id,
                user_message_id=message_id,
                labels_source=source,
                state=state,
                cheap_ok=cheap_ok,
                min_adequate_tier=min_tier,
                judges=len(scores),
                arms_judged=judged,
                arm_acceptable=verdicts,
            )
        )
    return tuple(out)


def to_frame(rows: Sequence[LabelRow], arms: Sequence[str]) -> pd.DataFrame:
    """The label file's table (format ``benchmark-labels-v1``)."""
    data = []
    for r in rows:
        row = {
            "format": FORMAT_VERSION,
            "record_id": r.record_id,
            "user_message_id": r.user_message_id,
            "labels_source": r.labels_source,
            "state": r.state,
            "cheap_ok": r.cheap_ok,
            "min_adequate_tier": r.min_adequate_tier,
            "judges": r.judges,
            "arms_judged": r.arms_judged,
        }
        for arm in arms:
            row[f"acceptable:{arm}"] = r.arm_acceptable.get(arm)
        data.append(row)
    frame = pd.DataFrame(data, columns=[*COLUMNS, *(f"acceptable:{a}" for a in arms)])
    frame["cheap_ok"] = frame["cheap_ok"].astype("boolean")
    frame["min_adequate_tier"] = frame["min_adequate_tier"].astype("Int64")
    for arm in arms:
        frame[f"acceptable:{arm}"] = frame[f"acceptable:{arm}"].astype("boolean")
    return frame


def summary(rows: Sequence[LabelRow]) -> dict[str, object]:
    """Content-free counts, safe to commit."""
    states = Counter(r.state for r in rows)
    cheap = Counter(
        "unknown" if r.cheap_ok is None else str(r.cheap_ok).lower() for r in rows
    )
    tiers = Counter(
        "none" if r.min_adequate_tier is None else str(r.min_adequate_tier)
        for r in rows
    )
    return {
        "format": FORMAT_VERSION,
        "records": len(rows),
        "labels_source": rows[0].labels_source if rows else None,
        "states": dict(sorted(states.items())),
        "cheap_ok": dict(sorted(cheap.items())),
        "min_adequate_tier": dict(sorted(tiers.items())),
    }


def labels_for_requests(labels: pd.DataFrame, requests: pd.DataFrame) -> pd.Series:
    """R-C3's input: a boolean ``cheap_ok`` Series on ``requests``' index
    (joined on ``user_message_id``; unlabelled rows are NA, which
    ``fit_logistic`` drops). Refuses a label file of another format or with
    mixed sources."""
    if set(labels["format"]) != {FORMAT_VERSION}:
        raise ValueError("not a benchmark-labels-v1 file")
    if labels["labels_source"].nunique() != 1:
        raise ValueError("one label file must have one labels_source")
    if labels["user_message_id"].duplicated().any():
        raise ValueError("duplicate user_message_id in the label file")
    keyed = labels.set_index("user_message_id")["cheap_ok"].astype("boolean")
    out = requests["user_message_id"].map(keyed)
    return out.astype("boolean").rename("cheap_ok")
