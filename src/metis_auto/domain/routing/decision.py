"""Decision-router gate, state builder and answer view (pure;
ADR-XXXX (system-one-decision-router)).

- ``needs_decision``: the fast path. Configured gate rules decide from cheap
  features alone (0 ms): greeting or small talk, code or coding intent, an
  attachment, a long message. An unknown feature never fires a rule (P-6).
  Anything else asks the decision model.
- ``build_state``: the minimised ``DecisionState`` sent to a backend: the
  message (truncated), optionally the previous user turn (truncated), and
  derived labels. **Never instructions or retrieved text** (QA-PRIV).
- ``Answers``: a typed view of a ``DecisionResult`` by configured question IDs;
  a missing answer is None, never a default.
- ``check_result``: does a backend's result answer the asked question set
  (every required question, the right types, known options, levels in range)?
- ``result_confidence``: the lowest confidence a backend reported (None when
  it reported none), for the cascade's confidence gate.
- ``cache_material``: the state, with its text folded, as the router-cache
  fingerprint's payload (never stored).

Called by: application.routing (cascade, R4), domain.routing.decision_policy.
Config: ``GateConfig``, ``StateConfig``, ``QuestionIds`` (placeholders, A-43
style). Traces: FR-FEAT-02, FR-ROUTE-01/04, P-6, QA-PRIV.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from metis_auto.contracts import (
    Component,
    ComponentState,
    ContractModel,
    DecisionQuestionSet,
    DecisionQuestionType,
    DecisionResult,
    DecisionState,
    LastAssistantTurnKind,
    Name,
    Request,
    RequestFeatures,
    Role,
)

from ..caching import ALL_TREATMENTS, normalise


class GateConfig(ContractModel):
    """Fast-path rules, first match wins. A rule whose tier is None is off."""

    greeting_tier: int | None = Field(default=0, ge=0)
    """Greeting or small talk (configured phrase list) → this tier."""
    code_tier: int | None = Field(default=1, ge=0)
    """Code present, or a coding intent without code → this tier."""
    attachment_tier: int | None = Field(default=1, ge=0)
    """An attachment is present (eligibility keeps verified-modality models)."""
    long_message_chars: int = Field(default=2000, gt=0)
    long_message_tier: int | None = Field(default=1, ge=0)
    """A message of at least ``long_message_chars`` characters → this tier."""


@dataclass(frozen=True)
class GateDecision:
    rule_id: str
    """``gate.greeting``, ``gate.code``, ``gate.coding_intent``,
    ``gate.attachment`` or ``gate.long_message``."""
    tier: int
    features_used: tuple[str, ...]


def needs_decision(
    features: RequestFeatures, config: GateConfig
) -> GateDecision | None:
    """A decisive gate rule, or None when the decision model should be asked."""
    if config.greeting_tier is not None and features.is_greeting is True:
        return GateDecision("gate.greeting", config.greeting_tier, ("is_greeting",))
    if config.code_tier is not None:
        if features.has_code is True:
            return GateDecision("gate.code", config.code_tier, ("has_code",))
        if features.has_coding_intent is True:
            return GateDecision(
                "gate.coding_intent", config.code_tier, ("has_coding_intent",)
            )
    if (
        config.attachment_tier is not None
        and features.attachment_count is not None
        and features.attachment_count > 0
    ):
        return GateDecision(
            "gate.attachment", config.attachment_tier, ("attachment_count",)
        )
    if (
        config.long_message_tier is not None
        and features.message_chars >= config.long_message_chars
    ):
        return GateDecision(
            "gate.long_message", config.long_message_tier, ("message_chars",)
        )
    return None


WIDGET_NOT_LOADED = "widget_definition_not_loaded"
"""``unknown_reason`` of a structured input known to have been shown but not
loaded (the dev slice: the previous AI message carried an input widget)."""


class StateConfig(ContractModel):
    max_message_chars: int = Field(default=1000, gt=0)
    max_previous_turn_chars: int = Field(default=300, ge=0)
    """0 = never send the previous user turn (it is then absent)."""
    fold: Name | None = None
    """An ADR-0025 treatment applied to the state's text, or None (the text as
    written). The router cache folds separately for its key."""


def _cut(text: str, limit: int) -> tuple[str, bool]:
    text = text.strip()
    return (text, False) if len(text) <= limit else (text[:limit].rstrip(), True)


def build_state(
    request: Request,
    features: RequestFeatures,
    config: StateConfig,
    *,
    dataset_derived: bool,
    bot_role_class: str | None = None,
) -> DecisionState | None:
    """The minimised state, or None when no state can be built (an
    attachment-only message: there is no text to ask about)."""
    if config.fold is not None and config.fold not in ALL_TREATMENTS:
        raise ValueError(f"unknown text treatment {config.fold!r}")

    def prepared(text: str) -> str:
        return normalise(text, config.fold) if config.fold else text

    if not request.message.strip():
        return None
    message, message_cut = _cut(prepared(request.message), config.max_message_chars)
    if not message:
        return None

    history = request.history
    previous: Component[str]
    previous_cut = False
    if history.state == ComponentState.UNKNOWN:
        previous = Component[str].unknown("history_unknown")
        kind = LastAssistantTurnKind.UNKNOWN
    else:
        turns = history.value or ()
        user_turns = [t for t in turns if t.role == Role.USER]
        previous = Component[str].absent()
        if user_turns and config.max_previous_turn_chars:
            text, previous_cut = _cut(
                prepared(user_turns[-1].text), config.max_previous_turn_chars
            )
            if text:
                previous = Component.present(text)
        if not turns or turns[-1].role != Role.ASSISTANT:
            kind = LastAssistantTurnKind.NONE
        elif request.structured_input.state == ComponentState.PRESENT or (
            request.structured_input.unknown_reason == WIDGET_NOT_LOADED
        ):
            # A widget was shown (A-16 proxy); an unknown structured input with
            # no such reason says nothing, so the turn counts as an answer.
            kind = LastAssistantTurnKind.STRUCTURED_INPUT
        else:
            kind = LastAssistantTurnKind.ANSWER
    turn_depth = features.turn_depth
    if turn_depth == 0:
        previous, previous_cut = Component[str].absent(), False
    return DecisionState(
        message=message,
        message_truncated=message_cut,
        previous_user_turn=previous,
        previous_user_turn_truncated=previous_cut,
        last_assistant_turn_kind=kind,
        retrieved_state=features.retrieved_state,
        attachment_modalities=features.attachment_modalities,
        language=features.language,
        turn_depth=turn_depth,
        bot_role_class=bot_role_class,
        dataset_derived=dataset_derived,
    )


class QuestionIds(ContractModel):
    """Which question of the set plays which role (renamable by config)."""

    complexity: Name = "complexity"
    needs_reasoning: Name = "needs_reasoning"
    cheap_model_ok: Name = "cheap_model_ok"
    intent: Name = "intent"
    depends_on_history: Name = "depends_on_history"


@dataclass(frozen=True)
class Answers:
    """Typed answers; None means the backend gave no answer (unknown)."""

    complexity: float | None
    complexity_confidence: float | None
    needs_reasoning: float | None
    cheap_model_ok: float | None
    intent: str | None
    intent_confidence: float | None
    depends_on_history: float | None

    @classmethod
    def of(cls, result: DecisionResult, ids: QuestionIds) -> Answers:
        def get(qid: str):
            return result.answer(qid)

        c, i = get(ids.complexity), get(ids.intent)
        r, ok, h = (
            get(ids.needs_reasoning),
            get(ids.cheap_model_ok),
            get(ids.depends_on_history),
        )
        return cls(
            complexity=c.score if c else None,
            complexity_confidence=c.confidence if c else None,
            needs_reasoning=r.p_yes if r else None,
            cheap_model_ok=ok.p_yes if ok else None,
            intent=i.choice if i else None,
            intent_confidence=i.confidence if i else None,
            depends_on_history=h.p_yes if h else None,
        )


def check_result(result: DecisionResult, questions: DecisionQuestionSet) -> str | None:
    """Why ``result`` does not answer ``questions``, or None when it does. A
    backend's answers are validated against what was asked, not trusted."""
    if result.question_set_version != questions.version:
        return "question_set_version"
    asked = {q.id: q for q in questions.questions}
    for answer in result.answers:
        question = asked.get(answer.question_id)
        if question is None:
            return "unknown_question"
        if answer.type != question.type:
            return "wrong_type"
        if (
            question.type == DecisionQuestionType.CHOICE
            and answer.choice not in question.option_names
        ):
            return "unknown_option"
        if question.type == DecisionQuestionType.CHOICE and any(
            name not in question.option_names for name in answer.probabilities
        ):
            return "unknown_option"
        if (
            question.type == DecisionQuestionType.SCORE
            and answer.score is not None
            and answer.score > len(question.levels) - 1
        ):
            return "score_out_of_range"
    answered = {a.question_id for a in result.answers}
    if any(q.required and q.id not in answered for q in questions.questions):
        return "missing_answer"
    return None


GateStatistic = Literal["reported", "probability"]


def answer_strength(answer, statistic: GateStatistic = "reported") -> float | None:
    """How sure one answer is. ``reported``: the backend's own ``confidence``
    (THX-01: normalised entropy). ``probability``: the probability the answer
    itself carries, i.e. the top option's or level's probability for choice
    and score, and ``max(p, 1 - p)`` for a yes/no question. None when the
    backend gave nothing to read (no number is invented)."""
    if statistic == "reported":
        return answer.confidence
    if answer.p_yes is not None:
        return max(answer.p_yes, 1.0 - answer.p_yes)
    if answer.probabilities:
        return max(answer.probabilities.values())
    return None


def result_confidence(
    result: DecisionResult,
    question_ids: Collection[str] | None = None,
    statistic: GateStatistic = "reported",
) -> float | None:
    """The lowest strength (``answer_strength``) over the answers to
    ``question_ids`` (None: every answer); None when none of them has one (the
    gate then does not apply: no number is invented). Q-61 (owner,
    2026-11-03): the cascade passes the mapping questions by default."""
    reported = [
        value
        for a in result.answers
        if (question_ids is None or a.question_id in question_ids)
        and (value := answer_strength(a, statistic)) is not None
    ]
    return min(reported) if reported else None


def mapping_question_ids(ids: QuestionIds) -> tuple[str, ...]:
    """The questions the tier mapping reads (Q-61): complexity,
    needs_reasoning, cheap_model_ok. Intent and history dependence only
    adjust or explain, so their confidence does not gate."""
    return (ids.complexity, ids.needs_reasoning, ids.cheap_model_ok)


def cache_material(state: DecisionState, fold: str | None) -> dict[str, object]:
    """The state as the router-cache fingerprint's payload: every field, the
    text folded by ``fold`` (an ADR-0025 treatment) so trivial variants share
    an entry. Content: hashed with a keyed fingerprint, never stored."""
    if fold is not None and fold not in ALL_TREATMENTS:
        raise ValueError(f"unknown text treatment {fold!r}")

    def folded(text: str) -> str:
        return normalise(text, fold) if fold else text

    data = state.model_dump(mode="json")
    data["message"] = folded(state.message)
    previous = state.previous_user_turn
    if previous.state == ComponentState.PRESENT and previous.value is not None:
        data["previous_user_turn"] = {
            "state": "present",
            "value": folded(previous.value),
        }
    return data
