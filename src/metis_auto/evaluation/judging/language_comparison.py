"""Persian versus English judge instructions (Stage E5; framework §0.6).

Runs each supplied judge (one per instruction language) over the same pairs and
reports, **per (instruction language x answer language) cell**: n, agreement
with the human consensus, swap consistency, position bias and verbosity bias,
each with n and, if a bootstrap is given, an interval. It does not select a
winner and offers no ranking: neither prompt language is assumed better, the
choice is a recorded config decision made after reading the table, and a cell
below the configured minimum n is ``descriptive``. Judge cost is evaluation
cost, reported per judge. Pure given the injected judges. Status: provisional
(Stage E5).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from metis_auto.evaluation.comparison.types import Estimate, sufficient

from .calibration import (
    HumanLabel,
    agreement,
    position_bias,
    swap_consistency,
    verbosity_bias,
)
from .pairwise import judge_items
from .types import Bootstrap, ContentProvider, PairItem, PairwiseJudge

NOTE = (
    "no winner is selected: the instruction language is a recorded config "
    "decision made after reading these cells, and a cell with few rated items "
    "cannot distinguish the two"
)


@dataclass(frozen=True)
class InstructionLanguageCell:
    instruction_language: str
    answer_language: str
    judge_id: str
    n_items: int
    n_rated: int
    agreement: Estimate
    swap_consistency: Estimate
    position_bias: Estimate
    verbosity_bias: Estimate
    label: str
    """``rankable`` is only a sufficiency label (n meets the minimum); it never
    means a winner."""
    label_reason: str | None


@dataclass(frozen=True)
class InstructionLanguageComparison:
    cells: tuple[InstructionLanguageCell, ...]
    judge_cost_usd: Mapping[str, Decimal]
    cost_kind: str = "evaluation"
    note: str = NOTE


def compare_instruction_languages(
    judges: Mapping[str, PairwiseJudge],
    items: Sequence[PairItem],
    content: ContentProvider,
    labels: Mapping[str, HumanLabel],
    *,
    answer_languages: Sequence[str],
    statistic: str | None,
    min_n: int | None,
    bootstrap: Bootstrap | None,
    vision_candidates: frozenset[str] | None,
) -> InstructionLanguageComparison:
    for key, judge in judges.items():
        if judge.instruction_language != key:
            raise ValueError(
                f"judge for {key!r} reports {judge.instruction_language!r}"
            )
    cells = []
    costs: dict[str, Decimal] = {}
    for key, judge in judges.items():
        run = judge_items(judge, items, content, vision_candidates=vision_candidates)
        costs[key] = run.cost_usd_total
        for language in answer_languages:
            outcomes = [o for o in run.outcomes if o.item.language == language]
            rated = sum(
                1
                for o in outcomes
                if o.state == "judged"
                and (lab := labels.get(o.item.item_id)) is not None
                and lab.consensus is not None
            )
            ok, reason = sufficient(rated, min_n)
            cells.append(
                InstructionLanguageCell(
                    instruction_language=key,
                    answer_language=language,
                    judge_id=judge.judge_id,
                    n_items=sum(o.state == "judged" for o in outcomes),
                    n_rated=rated,
                    agreement=agreement(
                        outcomes, labels, statistic=statistic, bootstrap=bootstrap
                    ),
                    swap_consistency=swap_consistency(outcomes),
                    position_bias=position_bias(outcomes),
                    verbosity_bias=verbosity_bias(outcomes, labels),
                    label="rankable" if ok else "descriptive",
                    label_reason=reason,
                )
            )
    order = {lang: i for i, lang in enumerate(answer_languages)}
    cells.sort(key=lambda c: (order[c.answer_language], c.instruction_language))
    return InstructionLanguageComparison(tuple(cells), costs)
