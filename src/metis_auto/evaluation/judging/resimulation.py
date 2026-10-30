"""Full re-simulation of a conversation: a DESIGN STUB (Stage E5; framework §4).

Teacher-forced next-turn replay stays the default (the logged history, the
original later turns). A small study would instead let the candidate's own
answers drive the conversation, with a user simulator writing the next turn, to
estimate how large the teacher-forcing bias is. This module fixes the interface
and the loop and is tested with a fake simulator. **It is not a working Persian
user simulator**, makes no model call, and its output holds only counts and
lengths. Both limits must be set (no default); unset means ``not_evaluated``.
``teacher_forcing_gap`` compares per-case scores from the two methods on the
cases both have. Pure. Status: stub (Stage E5).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from metis_auto.contracts import ContractModel
from metis_auto.evaluation.comparison.types import Estimate, not_measured


class UserSimulator(Protocol):
    def next_message(self, transcript: Sequence[str]) -> str | None:
        """The next user message given the transcript so far, or None to end."""
        ...


class ResimulationConfig(ContractModel):
    max_sessions: int | None = None
    max_turns: int | None = None


@dataclass(frozen=True)
class ResimulationTrace:
    case_id: str
    turns: int
    user_chars: tuple[int, ...]
    answer_chars: tuple[int, ...]
    stopped_by: str
    """``simulator_ended`` or ``max_turns``."""


@dataclass(frozen=True)
class ResimulationResult:
    state: str
    reason: str | None
    traces: tuple[ResimulationTrace, ...]
    note: str = "design stub: not a working Persian simulator"


def resimulate(
    case_ids: Sequence[str],
    *,
    first_message: Callable[[str], str],
    answer: Callable[[str, Sequence[str]], str],
    simulator: UserSimulator,
    config: ResimulationConfig,
) -> ResimulationResult:
    if config.max_turns is None:
        return ResimulationResult("not_evaluated", "max_turns_unset", ())
    if config.max_sessions is None:
        return ResimulationResult("not_evaluated", "max_sessions_unset", ())
    traces = []
    for case_id in list(case_ids)[: config.max_sessions]:
        transcript = [first_message(case_id)]
        user_chars = [len(transcript[0])]
        answer_chars: list[int] = []
        stopped = "max_turns"
        while True:
            reply = answer(case_id, tuple(transcript))
            transcript.append(reply)
            answer_chars.append(len(reply))
            if len(answer_chars) >= config.max_turns:
                break
            follow_up = simulator.next_message(tuple(transcript))
            if follow_up is None:
                stopped = "simulator_ended"
                break
            transcript.append(follow_up)
            user_chars.append(len(follow_up))
        traces.append(
            ResimulationTrace(
                case_id,
                len(answer_chars),
                tuple(user_chars),
                tuple(answer_chars),
                stopped,
            )
        )
    return ResimulationResult("planned", None, tuple(traces))


def teacher_forcing_gap(
    forced: Mapping[str, float], resimulated: Mapping[str, float]
) -> Estimate:
    """Mean paired difference (re-simulated minus teacher-forced) over the
    cases both methods scored. A point value with n; no interval."""
    shared = sorted(set(forced) & set(resimulated))
    if not shared:
        return not_measured("not_evaluated", "no_shared_cases", 0, "estimated")
    gap = sum(resimulated[c] - forced[c] for c in shared) / len(shared)
    return Estimate(
        "measured", len(shared), "estimated", value=gap, method="paired_mean_difference"
    )
