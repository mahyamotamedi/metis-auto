"""The System-One wire shape, shared by the local backends
(ADR-0047; R5).

One format serves THX-01 in process and a ``/v1/systemone`` server (Mizan on
llama-server, THX-01's own server): ``state`` (a string or JSON), and
``questions`` keyed by question ID, each ``{type, instructions, criteria}``
(``criteria``: an object of option → description for ``choice``, a list of
level labels for ``score``, absent for ``noul``). Answers come back keyed by
question ID: ``choice`` → ``choice, probabilities, confidence``; ``score`` →
``score, probabilities, confidence``; ``noul`` → ``noul`` (P(yes)) and,
from THX-01, ``confidence``. Sources: THX-01 1.0.0 ``agent.py``/``server.py``
and the Mizan card (R0 findings §3, §5). Fields we do not use (``legend``,
``action``) are ignored.

The state rendering never includes instructions or retrieved text: the
``DecisionState`` does not hold them (QA-PRIV). Content stays in memory.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from metis_auto.contracts import (
    ComponentState,
    DecisionAnswer,
    DecisionQuestionSet,
    DecisionQuestionType,
    DecisionState,
)

StateFormat = Literal["text", "json"]


class WireError(ValueError):
    """The backend's answers do not fit the asked questions."""


def render_state(state: DecisionState, fmt: StateFormat = "text") -> str | dict:
    """The state as the backend sees it. ``text`` (default) is compact, so the
    sequence budget goes to the message; ``json`` is the same fields keyed."""
    previous = (
        state.previous_user_turn.value
        if state.previous_user_turn.state == ComponentState.PRESENT
        else None
    )
    labels = {
        "language": state.language.value,
        "turn": state.turn_depth,
        "last_assistant_turn": state.last_assistant_turn_kind.value,
        "attachments": [m.value for m in state.attachment_modalities] or None,
        "retrieved_context": state.retrieved_state.value,
    }
    if fmt == "json":
        data: dict[str, Any] = {"message": state.message}
        if previous:
            data["previous_user_message"] = previous
        data.update({k: v for k, v in labels.items() if v is not None})
        return data
    parts = []
    if previous:
        parts.append(f"Previous user message: {previous}")
    parts.append(f"Message: {state.message}")
    tags = ", ".join(
        f"{k}={','.join(v) if isinstance(v, list) else v}"
        for k, v in labels.items()
        if v is not None
    )
    parts.append(f"[{tags}]")
    return "\n".join(parts)


def render_questions(questions: DecisionQuestionSet) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for q in questions.questions:
        item: dict[str, Any] = {"type": q.type.value, "instructions": q.instructions}
        if q.type == DecisionQuestionType.CHOICE:
            item["criteria"] = {o.name: o.description for o in q.options}
        elif q.type == DecisionQuestionType.SCORE:
            item["criteria"] = list(q.levels)
        out[q.id] = item
    return out


def _probabilities(raw: Any) -> dict[str, float]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise WireError("probabilities is not an object")
    return {str(k): float(v) for k, v in raw.items()}


def parse_answers(
    raw: Any, questions: DecisionQuestionSet
) -> tuple[DecisionAnswer, ...]:
    """Typed answers for the asked questions; anything malformed raises
    ``WireError`` (the caller reports ``invalid_response``). Answers to
    questions not asked are ignored; a missing required one is an error."""
    if not isinstance(raw, Mapping):
        raise WireError("answers is not an object keyed by question ID")
    answers = []
    for q in questions.questions:
        item = raw.get(q.id)
        if item is None:
            if q.required:
                raise WireError(f"no answer for {q.id!r}")
            continue
        if not isinstance(item, Mapping):
            raise WireError(f"answer {q.id!r} is not an object")
        kind = item.get("type", q.type.value)
        if kind != q.type.value:
            raise WireError(f"answer {q.id!r} has type {kind!r}")
        confidence = item.get("confidence")
        try:
            if q.type == DecisionQuestionType.CHOICE:
                answer = DecisionAnswer(
                    question_id=q.id,
                    type=q.type,
                    choice=item.get("choice"),
                    probabilities=_probabilities(item.get("probabilities")),
                    confidence=None if confidence is None else float(confidence),
                )
            elif q.type == DecisionQuestionType.SCORE:
                answer = DecisionAnswer(
                    question_id=q.id,
                    type=q.type,
                    score=float(item["score"]),
                    probabilities=_probabilities(item.get("probabilities")),
                    confidence=None if confidence is None else float(confidence),
                )
            else:
                answer = DecisionAnswer(
                    question_id=q.id,
                    type=q.type,
                    p_yes=float(item["noul"]),
                    confidence=None if confidence is None else float(confidence),
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise WireError(f"answer {q.id!r} is malformed") from exc
        answers.append(answer)
    return tuple(answers)
