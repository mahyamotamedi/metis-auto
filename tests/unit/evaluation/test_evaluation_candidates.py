"""Candidate indexes and variants (Stage 8). SYNTHETIC fingerprints."""

import pytest

from metis_auto.contracts import ComponentName, ComponentState, KeyComponent, Request
from metis_auto.evaluation.cache_candidates import (
    CandidateItem,
    ExactKeyIndex,
    WildcardIndex,
    variants,
)
from metis_auto.evaluation.metrics import wilson

FP = {k: "fp1:" + k * 64 for k in "abc"}


def comp(name, state, fp=None):
    return KeyComponent(component=name, state=state, fingerprint=fp, treatment="full")


def item(
    case,
    session,
    instr_state,
    instr_fp=None,
    key=None,
    model=(ComponentState.ABSENT, None),
):
    return CandidateItem(
        case_id=case,
        session_ref=session,
        components=(
            comp(ComponentName.MESSAGE, ComponentState.PRESENT, FP["a"]),
            comp(ComponentName.INSTRUCTIONS, instr_state, instr_fp),
        ),
        model=model,
        key=key,
        request=Request(message="[SYNTHETIC] m"),
    )


def test_wildcard_matches_unknown_either_side_but_not_a_different_value():
    index = WildcardIndex()
    index.add(item("c1", "s1", ComponentState.PRESENT, FP["b"]))
    assert (
        index.lookup(item("c2", "s2", ComponentState.UNKNOWN), session_ref=None) == "c1"
    )
    assert (
        index.lookup(
            item("c2", "s2", ComponentState.PRESENT, FP["c"]), session_ref=None
        )
        is None
    )
    assert (
        index.lookup(item("c2", "s2", ComponentState.UNKNOWN), session_ref="s2") is None
    )
    index.add(item("c3", "s1", ComponentState.UNKNOWN))
    assert (
        index.lookup(
            item("c4", "s1", ComponentState.PRESENT, FP["c"]), session_ref="s1"
        )
        == "c3"
    )


def test_wildcard_model_label():
    index = WildcardIndex()
    index.add(
        item("c1", "s1", ComponentState.ABSENT, model=(ComponentState.PRESENT, "m-1"))
    )
    other = item(
        "c2", "s1", ComponentState.ABSENT, model=(ComponentState.PRESENT, "m-2")
    )
    unknown = item(
        "c3", "s1", ComponentState.ABSENT, model=(ComponentState.UNKNOWN, None)
    )
    assert index.lookup(other, session_ref=None) is None
    assert index.lookup(unknown, session_ref=None) == "c1"


def test_exact_index_by_sealed_key_and_scope():
    index = ExactKeyIndex()
    index.add(item("c1", "s1", ComponentState.ABSENT, key=FP["a"]))
    assert (
        index.lookup(
            item("c2", "s2", ComponentState.ABSENT, key=FP["a"]), session_ref=None
        )
        == "c1"
    )
    assert (
        index.lookup(
            item("c2", "s2", ComponentState.ABSENT, key=FP["a"]), session_ref="s2"
        )
        is None
    )


def test_variants_from_params():
    assert len(variants({})) == 5 * 3 * 2
    names = [
        v.name
        for v in variants({"bases": ["msg_only"], "message_treatments": ["literal"]})
    ]
    assert names == ["msg_only.lit.strict", "msg_only.lit.wildcard"]
    with pytest.raises(ValueError):
        variants({"bases": ["nope"]})


def test_wilson_interval():
    assert wilson(0, 0) is None
    iv = wilson(10, 465)
    assert 0 < iv.low < 10 / 465 < iv.high < 0.05
