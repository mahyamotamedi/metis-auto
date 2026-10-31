"""A deterministic fake pairwise judge, for tests only (Stage E5).

It decides from answer lengths and a mode, never from meaning, so tests can
build exact biases: ``longer`` (verbosity-biased), ``shorter``, ``first`` and
``second`` (position-biased), ``tie``, or ``scripted`` (a callable). It is not
a quality judge and says nothing about Persian ability. Never used outside
tests and the offline harness checks. Status: test double.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from .types import JudgeRequestView, PairwiseVerdict

MODES = ("longer", "shorter", "first", "second", "tie", "scripted")


class FakePairwiseJudge:
    def __init__(
        self,
        mode: str = "longer",
        *,
        judge_id: str = "fake-pairwise@0",
        instruction_language: str = "en",
        supports_images: bool = False,
        cost_per_call_usd: Decimal | None = None,
        scripted: Callable[[JudgeRequestView, str, str], str] | None = None,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if mode == "scripted" and scripted is None:
            raise ValueError("scripted mode needs a callable")
        self._mode = mode
        self._id = judge_id
        self._language = instruction_language
        self._images = supports_images
        self._cost = cost_per_call_usd
        self._scripted = scripted
        self.calls = 0
        self.views: list[JudgeRequestView] = []

    @property
    def judge_id(self) -> str:
        return self._id

    @property
    def instruction_language(self) -> str:
        return self._language

    @property
    def supports_images(self) -> bool:
        return self._images

    def compare(
        self, view: JudgeRequestView, first: str, second: str
    ) -> PairwiseVerdict:
        self.calls += 1
        self.views.append(view)
        if self._mode == "scripted":
            assert self._scripted is not None
            choice = self._scripted(view, first, second)
        elif self._mode in ("first", "second", "tie"):
            choice = self._mode
        elif len(first) == len(second):
            choice = "tie"
        elif self._mode == "longer":
            choice = "first" if len(first) > len(second) else "second"
        else:
            choice = "first" if len(first) < len(second) else "second"
        return PairwiseVerdict(choice, self._cost)
