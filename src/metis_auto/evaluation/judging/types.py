"""Types for pairwise judging (Stage E5; framework §0.4, §0.6, §4).

A pairwise judge sees a request view and two answers in a given order and picks
``first``, ``second`` or ``tie``. It is a plug-in: nothing here chooses a judge
model, and the only implementation shipped is a deterministic fake for tests.
Text travels only through ``ContentProvider`` at judging time (from the
recorded store); every result held here is content-free: IDs, scores, lengths
and counts. The existing pointwise ``ports.Judge`` is unchanged; moving this
protocol into ``ports`` is a later decision (E6), made with a real judge in view.
Pure. Status: provisional (Stage E5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

CHOICES = ("first", "second", "tie")
PREFERENCES = ("candidate", "reference", "tie")
Variant = tuple[str, "str | None"]
"""(model_id, effort)"""


@dataclass(frozen=True)
class JudgeRequestView:
    """What the judge may see of the request: text pieces, transient."""

    message: str
    instructions: str | None = None
    history: tuple[str, ...] = ()
    retrieved: str | None = None
    """The logged retrieved context, shown so grounding is judged against what
    the answering model was given (§4)."""
    has_attachments: bool = False


@dataclass(frozen=True)
class PairwiseVerdict:
    choice: str
    cost_usd: Decimal | None = None
    """Evaluation cost of this judge call; never a request cost."""

    def __post_init__(self) -> None:
        if self.choice not in CHOICES:
            raise ValueError(f"choice must be one of {CHOICES}")


class PairwiseJudge(Protocol):
    @property
    def judge_id(self) -> str:
        """``ID@version``, recorded with every result."""
        ...

    @property
    def instruction_language(self) -> str:
        """Language of the judge's instructions (``fa`` or ``en``)."""
        ...

    @property
    def supports_images(self) -> bool: ...

    def compare(
        self, view: JudgeRequestView, first: str, second: str
    ) -> PairwiseVerdict: ...


class ContentProvider(Protocol):
    """Gives the judge text at judging time (from the recorded store)."""

    def request(self, case_id: str) -> JudgeRequestView: ...

    def answer(self, case_id: str, variant: Variant) -> str | None: ...


@dataclass(frozen=True)
class PairItem:
    """One comparison: a candidate variant against the reference variant."""

    case_id: str
    session_ref: str
    language: str
    candidate: Variant
    reference: Variant
    has_attachments: bool = False

    @property
    def item_id(self) -> str:
        c, r = self.candidate, self.reference
        return f"{self.case_id}~{c[0]}@{c[1] or '-'}~{r[0]}@{r[1] or '-'}"


@dataclass(frozen=True)
class Bootstrap:
    n_boot: int
    seed: int | str
    level: float


@dataclass(frozen=True)
class Counts:
    """Content-free tallies."""

    by_reason: dict[str, int] = field(default_factory=dict)
