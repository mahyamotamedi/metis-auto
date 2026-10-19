"""Sample loader and replay-case builder (Stage 8; contracts.md §4, A-04).

All data is SYNTHETIC, in the sample file's shape (fixtures.synthetic.sample_shaped).
"""

import json
from datetime import datetime

import pytest
from fixtures.synthetic import sample_shaped

from metis_auto.contracts import (
    ComponentName,
    ComponentState,
    LoggedMessage,
    Modality,
    PairingFlag,
    Role,
)
from metis_auto.data_access.replay_cases.builder import build_all, build_cases, case_id
from metis_auto.data_access.sample.loader import SampleDataSource, SampleFormatError


def ref(purpose, raw):  # an opaque ref stand-in (tests only; not a real key)
    return f"{purpose}-{abs(hash(raw)) % 10**8:08d}"


@pytest.fixture
def path(tmp_path):
    return sample_shaped.write(tmp_path / "sample.json")


def sessions(path, **kw):
    return list(SampleDataSource(path, ref, **kw).sessions())


def by_id(path, **kw):
    return {s.session_ref: s for s in sessions(path, **kw)}


def test_roles_refs_strata_and_naive_times(path):
    found = sessions(path)
    assert len(found) == 3
    s = found[0]
    assert s.session_ref == ref("session_ref", "syn-0001")
    assert s.stratum == ref("stratum", f"{sample_shaped.S} category A")
    assert {m.role for m in s.messages} == {Role.USER, Role.ASSISTANT}
    assert s.messages[0].logged_timestamp == datetime(2026, 5, 1, 10, 0, 0)
    assert s.messages[0].logged_timestamp.tzinfo is None
    assert s.logged_created_at == datetime(2026, 5, 1, 9, 59)


def test_nulls_are_unknown_not_in_log_and_empty_is_absent(path):
    s2 = by_id(path)[ref("session_ref", "syn-0002")]
    answer = s2.messages[3]
    for c in (answer.model_label, answer.provider_label, answer.instructions):
        assert c.state == ComponentState.UNKNOWN
        assert c.unknown_reason == "not_in_log"
    s3 = by_id(path)[ref("session_ref", "syn-0003")]
    assert s3.messages[1].instructions.state == ComponentState.ABSENT  # "" → absent


@pytest.mark.parametrize(
    "mode, state",
    [("unknown", ComponentState.UNKNOWN), ("absent", ComponentState.ABSENT)],
)
def test_missing_keys_follow_the_configured_treatment(path, mode, state):
    s1 = sessions(path, missing_key=mode)[0]
    user, answer = s1.messages[0], s1.messages[1]
    assert user.attachments.state == state  # no attachments key on the user
    assert answer.structured_input.state == state  # no input key on the answer
    if mode == "unknown":
        assert user.attachments.unknown_reason == "key_missing"
    assert answer.retrieved.state == ComponentState.PRESENT


def test_default_is_absent_and_nulls_stay_unknown(path):
    # Q-37 (2026-10-19): missing optional keys are absent by default; the
    # co-occurring nulls remain unknown, not_in_log (Q-25).
    from metis_auto.settings import DataSliceSettings

    assert DataSliceSettings().missing_key == "absent"
    found = by_id(path)
    first = found[ref("session_ref", "syn-0001")].messages[0]
    assert first.attachments.state == ComponentState.ABSENT
    nulls = found[ref("session_ref", "syn-0002")].messages[3]
    assert nulls.instructions.state == ComponentState.UNKNOWN
    assert nulls.instructions.unknown_reason == "not_in_log"


def test_attachments_structured_input_and_modality(path):
    s3 = by_id(path)[ref("session_ref", "syn-0003")]
    att = s3.messages[0].attachments.value
    assert att[0].modality == Modality.IMAGE and att[0].locator.startswith(
        sample_shaped.S
    )
    assert s3.messages[3].structured_input.state == ComponentState.PRESENT


def test_plateau_flag_is_found_in_the_data(tmp_path):
    data = sample_shaped.sessions()
    ctx = {"query": "[SYNTHETIC] q", "context": ["[SYNTHETIC] " + "x" * 50]}
    msgs = data[0]["sessions"][0]["messages"]
    for _ in range(3):  # three records at the same maximum length
        msgs += [sample_shaped.user("q"), sample_shaped.bot("a", rag=ctx)]
    path = tmp_path / "s.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    flagged = [
        m
        for s in sessions(path)
        for m in s.messages
        if any(f.flag == "possibly_truncated" for f in m.quality_flags)
    ]
    assert len(flagged) == 3
    assert all(
        f.component == ComponentName.RETRIEVED for m in flagged for f in m.quality_flags
    )
    # below the minimum count, nothing is flagged
    assert not any(
        m.quality_flags
        for s in SampleDataSource(path, ref, plateau_min_count=4).sessions()
        for m in s.messages
    )


def test_unknown_role_and_bad_shape_fail(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            [
                {
                    "category": "c",
                    "sessions": [
                        {
                            "session_id": "s",
                            "messages": [
                                {
                                    "role": "system",
                                    "content": "x",
                                    "timestamp": "2026-01-01T00:00:00",
                                }
                            ],
                        }
                    ],
                }
            ]
        )
    )
    with pytest.raises(SampleFormatError):
        sessions(bad)
    bad.write_text(json.dumps({"not": "a list"}))
    with pytest.raises(SampleFormatError):
        sessions(bad)


# --- replay-case builder -----------------------------------------------------


def test_pairing_flags_and_exclusions(path):
    cases, exclusions = build_all(sessions(path))
    flags = [c.pairing_flag for c in cases]
    assert flags == [
        PairingFlag.CLEAN,
        PairingFlag.CLEAN,  # syn-0001
        PairingFlag.SKIPPED_CONSECUTIVE_USER,
        PairingFlag.MULTIPLE_ANSWERS,
        PairingFlag.UNANSWERED,  # syn-0002
        PairingFlag.CLEAN,
        PairingFlag.CLEAN,  # syn-0003
    ]
    assert [(e.reason, e.count) for e in exclusions] == [("no_preceding_user", 1)]


def test_no_look_ahead_and_answer_side_components(path):
    s2 = by_id(path)[ref("session_ref", "syn-0002")]
    cases, _ = build_cases(s2)
    skipped, multiple, unanswered = cases
    assert skipped.references == ()
    assert skipped.request.instructions.unknown_reason == "no_paired_answer"
    # history = every earlier message, including the opening answer
    assert [t.role for t in multiple.request.history.value] == [
        Role.ASSISTANT,
        Role.USER,
    ]
    assert all("answer two" not in t.text for t in multiple.request.history.value)
    assert len(multiple.references) == 2
    assert multiple.request.instructions.unknown_reason == "not_in_log"
    assert len(unanswered.request.history.value) == 5
    first = build_cases(by_id(path)[ref("session_ref", "syn-0001")])[0][0]
    assert first.request.history.state == ComponentState.ABSENT
    assert first.request.retrieved.state == ComponentState.PRESENT
    assert first.turn_index == 0 and first.case_id == case_id(first.session_ref, 0)


def test_answers_that_disagree_are_flagged():
    from metis_auto.contracts import Component, Session

    def msg(pos, role, instr=None):
        extra = {} if role == Role.USER else {"instructions": Component.present(instr)}
        return LoggedMessage(position=pos, role=role, text="[SYNTHETIC] t", **extra)

    s = Session(
        session_ref="s1",
        dataset="synthetic_v1",
        messages=(
            msg(0, Role.USER),
            msg(1, Role.ASSISTANT, "[SYNTHETIC] a"),
            msg(2, Role.ASSISTANT, "[SYNTHETIC] b"),
        ),
    )
    (case,), _ = build_cases(s)
    assert [(f.component, f.flag) for f in case.quality_flags] == [
        (ComponentName.INSTRUCTIONS, "answers_disagree")
    ]
