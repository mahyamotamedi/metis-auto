"""Pairwise judging with position swapping (Stage E5; framework §0.4, §4, §6).

Each pair is judged twice, candidate first and then reference first, so a
judge that prefers a position cannot decide the outcome. Per ordering the
choice is mapped back to ``candidate``, ``reference`` or ``tie``; the pair's
score is the mean of the two orderings (candidate win 1, tie 0.5, loss 0), and
``swap_consistent`` says whether both orderings agreed. A pairwise score is
quality **relative to the reference** (the reference scores 0.5 against itself
by definition), not an absolute rating.

Exclusions are stated, not silent (FR-EVAL-08): a turn with attachments is not
judged unless the judge can see images **and** the candidate is a known vision
model (the set is config; unset means no model is assumed to see images). A
missing answer is ``not_evaluated``. Judge cost is **evaluation cost**
(``cost_kind``), never added to request costs. Results hold no text. Pure
given the injected judge and content provider. Status: provisional (Stage E5).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from .types import ContentProvider, PairItem, PairwiseJudge, Variant


@dataclass(frozen=True)
class PairOutcome:
    item: PairItem
    state: str
    """``judged``, ``excluded`` or ``not_evaluated``."""
    reason: str | None
    score: float | None
    """0, 0.5 or 1: the candidate's score against the reference."""
    preference: str | None
    """``candidate``, ``reference`` or ``tie``."""
    candidate_first: str | None
    """Mapped verdict when the candidate was shown first."""
    reference_first: str | None
    """Mapped verdict when the reference was shown first."""
    first_position_picks: int
    """How many of the two orderings picked the first position (0 to 2)."""
    swap_consistent: bool | None
    candidate_chars: int | None
    reference_chars: int | None
    cost_usd: Decimal | None


@dataclass(frozen=True)
class JudgeRun:
    judge_id: str
    instruction_language: str
    outcomes: tuple[PairOutcome, ...]
    cost_usd_total: Decimal
    cost_kind: str
    """Always ``evaluation``: never part of request cost."""
    excluded_by_reason: Mapping[str, int]

    @property
    def judged(self) -> tuple[PairOutcome, ...]:
        return tuple(o for o in self.outcomes if o.state == "judged")


def _map(choice: str, candidate_first: bool) -> str:
    if choice == "tie":
        return "tie"
    picked_first = choice == "first"
    return "candidate" if picked_first == candidate_first else "reference"


_VALUE = {"candidate": 1.0, "tie": 0.5, "reference": 0.0}


def _not_judged(item: PairItem, state: str, reason: str) -> PairOutcome:
    return PairOutcome(
        item, state, reason, None, None, None, None, 0, None, None, None, None
    )


def judge_items(
    judge: PairwiseJudge,
    items: Sequence[PairItem],
    content: ContentProvider,
    *,
    vision_candidates: frozenset[str] | None,
) -> JudgeRun:
    outcomes: list[PairOutcome] = []
    total = Decimal(0)
    for item in items:
        if item.has_attachments:
            if vision_candidates is None:
                outcomes.append(
                    _not_judged(item, "excluded", "vision_capability_unset")
                )
                continue
            if item.candidate[0] not in vision_candidates:
                outcomes.append(_not_judged(item, "excluded", "candidate_not_vision"))
                continue
            if not judge.supports_images:
                outcomes.append(
                    _not_judged(item, "excluded", "judge_cannot_see_images")
                )
                continue
        cand: str | None = content.answer(item.case_id, item.candidate)
        ref: str | None = content.answer(item.case_id, item.reference)
        if cand is None or ref is None:
            outcomes.append(_not_judged(item, "not_evaluated", "answer_missing"))
            continue
        view = content.request(item.case_id)
        a = judge.compare(view, cand, ref)
        b = judge.compare(view, ref, cand)
        cost = None
        if a.cost_usd is not None or b.cost_usd is not None:
            cost = (a.cost_usd or Decimal(0)) + (b.cost_usd or Decimal(0))
            total += cost
        mapped_a = _map(a.choice, candidate_first=True)
        mapped_b = _map(b.choice, candidate_first=False)
        score = (_VALUE[mapped_a] + _VALUE[mapped_b]) / 2
        preference = (
            "candidate" if score > 0.5 else "reference" if score < 0.5 else "tie"
        )
        outcomes.append(
            PairOutcome(
                item=item,
                state="judged",
                reason=None,
                score=score,
                preference=preference,
                candidate_first=mapped_a,
                reference_first=mapped_b,
                first_position_picks=(a.choice == "first") + (b.choice == "first"),
                swap_consistent=mapped_a == mapped_b,
                candidate_chars=len(cand),
                reference_chars=len(ref),
                cost_usd=cost,
            )
        )
    excluded = Counter(o.reason for o in outcomes if o.state != "judged" and o.reason)
    return JudgeRun(
        judge_id=judge.judge_id,
        instruction_language=judge.instruction_language,
        outcomes=tuple(outcomes),
        cost_usd_total=total,
        cost_kind="evaluation",
        excluded_by_reason=dict(excluded),
    )


def pairwise_quality(
    run: JudgeRun, reference: Variant
) -> dict[tuple[str, str, str | None], float]:
    """Scores keyed ``(case_id, model_id, effort)`` for the E4 tables: each
    candidate's pairwise score, and 0.5 for the reference itself."""
    scores: dict[tuple[str, str, str | None], float] = {}
    for o in run.judged:
        assert o.score is not None
        scores[(o.item.case_id, o.item.candidate[0], o.item.candidate[1])] = o.score
        scores[(o.item.case_id, reference[0], reference[1])] = 0.5
    return scores
