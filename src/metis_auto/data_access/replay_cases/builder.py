"""Replay-case builder (CMP-18; evaluation.md §3, FR-REQ-03, FR-REQ-06).

Responsibility: turn a ``Session`` into ``ReplayCase``s, one per user turn,
holding only what came before that turn (no look-ahead), with 0…n paired
answers, the pairing method and flag, and exclusion counts.

Pairing heuristic (A-04; re-implemented and tested, never taken from the
EDA helpers): each answer is paired with the **latest preceding user
message in log order**. Then, per user message:
- one answer → ``clean``;
- several answers → ``multiple_answers``;
- none, and the next message is a user message → ``skipped_consecutive_user``;
- none, and nothing follows (the log ends) → ``unanswered``.
An answer with no preceding user message never becomes a case: it is counted
as the exclusion ``no_preceding_user`` (it still appears in later history).

The request at a turn: the user message and its attachments; history = every
earlier message in log order (absent on the first message); instructions,
retrieved context, and structured input from the **first paired answer**,
because the sample logs them on the answer side (contracts.md §4). Without a
paired answer they are unknown (``no_paired_answer``). When several answers
disagree on one of them, the case gets a ``answers_disagree`` quality flag
for that component. ``traffic_source`` stays unknown (reserved, ADR-0016).
Loader flags of the first answer (e.g. ``possibly_truncated``) are copied.

Called by: wiring-built data pipelines for evaluation (``wiring.experiments``).
Status: implemented (pulled forward from Stage 9 into Stage 8).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from metis_auto.contracts import (
    Component,
    ComponentName,
    DataQualityFlag,
    ExclusionCount,
    Identifier,
    LoggedMessage,
    PairingFlag,
    PairingMethod,
    Reference,
    ReplayCase,
    Request,
    Role,
    Session,
    Turn,
)

NO_PAIRED_ANSWER = "no_paired_answer"
EMPTY_MESSAGE = "empty_message"
"""Exclusion: an empty user message without attachments (A-39)."""


def case_id(session_ref: str, turn_index: int) -> Identifier:
    """Deterministic per run: 16 hex characters of the (keyed) session ref."""
    tail = session_ref.split(":", 1)[-1][:16]
    return f"case:{tail}:{turn_index:04d}"


def pair(session: Session) -> tuple[dict[int, list[LoggedMessage]], int]:
    """User position → paired answers, and the number of unpaired answers."""
    paired: dict[int, list[LoggedMessage]] = {}
    last_user: int | None = None
    unpaired = 0
    for m in session.messages:
        if m.role == Role.USER:
            last_user = m.position
            paired.setdefault(m.position, [])
        elif last_user is None:
            unpaired += 1
        else:
            paired[last_user].append(m)
    return paired, unpaired


def build_cases(
    session: Session,
) -> tuple[tuple[ReplayCase, ...], tuple[ExclusionCount, ...]]:
    paired, unpaired = pair(session)
    messages = session.messages
    exclusions: Counter[str] = Counter()
    if unpaired:
        exclusions[PairingFlag.NO_PRECEDING_USER.value] = unpaired
    cases: list[ReplayCase] = []
    turn = 0
    for index, m in enumerate(messages):
        if m.role != Role.USER:
            continue
        answers = paired[m.position]
        following = messages[index + 1] if index + 1 < len(messages) else None
        flag = _flag(answers, following)
        history = tuple(Turn(role=p.role, text=p.text) for p in messages[:index])
        first = answers[0] if answers else None
        missing = Component.unknown(NO_PAIRED_ANSWER)
        if not m.text.strip() and m.attachments.value is None:
            exclusions[EMPTY_MESSAGE] += 1
            turn += 1
            continue
        request = Request(
            message=m.text,
            history=Component.present(history) if history else Component.absent(),
            instructions=first.instructions if first else missing,
            retrieved=first.retrieved if first else missing,
            structured_input=first.structured_input if first else missing,
            attachments=m.attachments,
            session_ref=session.session_ref,
        )
        cases.append(
            ReplayCase(
                case_id=case_id(session.session_ref, turn),
                session_ref=session.session_ref,
                turn_index=turn,
                request=request,
                references=tuple(_reference(a) for a in answers),
                pairing_method=PairingMethod.HEURISTIC_ARRAY_ORDER,
                pairing_flag=flag,
                logged_timestamp=m.logged_timestamp,
                stratum=session.stratum,
                quality_flags=_quality(answers),
            )
        )
        turn += 1
    return tuple(cases), tuple(
        ExclusionCount(reason=r, count=n) for r, n in sorted(exclusions.items())
    )


def build_all(
    sessions: Iterable[Session],
) -> tuple[tuple[ReplayCase, ...], tuple[ExclusionCount, ...]]:
    """Every session's cases in session order, and summed exclusions."""
    cases: list[ReplayCase] = []
    totals: Counter[str] = Counter()
    for session in sessions:
        built, excluded = build_cases(session)
        cases.extend(built)
        for e in excluded:
            totals[e.reason] += e.count
    return tuple(cases), tuple(
        ExclusionCount(reason=r, count=n) for r, n in sorted(totals.items())
    )


def _flag(answers: list[LoggedMessage], following: LoggedMessage | None) -> PairingFlag:
    if len(answers) > 1:
        return PairingFlag.MULTIPLE_ANSWERS
    if answers:
        return PairingFlag.CLEAN
    if following is not None and following.role == Role.USER:
        return PairingFlag.SKIPPED_CONSECUTIVE_USER
    return PairingFlag.UNANSWERED


def _reference(m: LoggedMessage) -> Reference:
    return Reference(
        position=m.position,
        text=m.text,
        model_label=m.model_label,
        provider_label=m.provider_label,
        logged_timestamp=m.logged_timestamp,
    )


def _quality(answers: list[LoggedMessage]) -> tuple[DataQualityFlag, ...]:
    if not answers:
        return ()
    flags = list(answers[0].quality_flags)
    for name, attr in (
        (ComponentName.INSTRUCTIONS, "instructions"),
        (ComponentName.RETRIEVED, "retrieved"),
        (ComponentName.STRUCTURED_INPUT, "structured_input"),
    ):
        if len({getattr(a, attr).model_dump_json() for a in answers}) > 1:
            flags.append(DataQualityFlag(component=name, flag="answers_disagree"))
    return tuple(flags)
