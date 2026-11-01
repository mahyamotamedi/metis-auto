"""Offline tests: session classes, fingerprints, labels, quotas, leakage. SYNTHETIC."""

import json

import pytest

from metis_auto.analysis import prompt_labels as pl
from metis_auto.analysis import session_config as sc
from metis_auto.evaluation.golden.allocation import joint_quotas, margin_quotas
from metis_auto.evaluation.golden.manifest import (
    MANIFEST_FIELDS,
    build_manifest_entry,
    manifest_errors,
)


@pytest.mark.parametrize(
    ("value", "state"),
    [
        (None, "null"),
        (float("nan"), "null"),
        ("", "blank"),
        (" \n\t", "blank"),
        ("x", "text"),
    ],
)
def test_text_state(value, state):
    assert sc.text_state(value) == state


@pytest.mark.parametrize(
    ("value", "state"),
    [
        (None, "null"),
        (float("nan"), "null"),
        ("", "empty"),
        ("  ", "empty"),
        ("[]", "empty"),
        ("{}", "empty"),
        ("null", "empty"),
        ([], "empty"),
        ("[1", "malformed"),
        ('["c1"]', "nonempty"),
        (["c1"], "nonempty"),
    ],
)
def test_json_field_state(value, state):
    assert sc.json_field_state(value)[0] == state


def test_rag_config_null_is_unknown_not_absent():
    assert sc.rag_config_evidence(None) == "unknown"
    assert sc.rag_config_evidence("[1") == "unknown"
    assert sc.rag_config_evidence("[]") == "not_configured"
    assert sc.rag_config_evidence('["c"]') == "configured"


def test_strict_hash_does_not_normalise():
    a = "[SYNTHETIC] Be kind"
    for other in (a + " ", a.lower(), "[SYNTHETIC]  Be kind"):
        assert sc.strict_hash(a) != sc.strict_hash(other)
    assert sc.strict_hash("كتاب") != sc.strict_hash("کتاب")  # Arabic vs Persian kaf


def test_fingerprint_deterministic_and_order_preserving():
    assert sc.rag_fingerprint('["a","b"]') == sc.rag_fingerprint(["a", "b"])
    assert sc.rag_fingerprint('["a","b"]') != sc.rag_fingerprint('["b","a"]')
    for empty in (None, "[]", "", "[1"):
        assert sc.rag_fingerprint(empty) is None
    assert sc.canonical_json({"b": 1, "a": [2, 1]}) == '{"a":[2,1],"b":1}'


def test_platform_default_needs_owners_and_provider():
    rows = [("[SYNTHETIC] ph", f"u{i}", "workflow") for i in range(5)]
    rows += [("[SYNTHETIC] shared", f"u{i}", "workflow") for i in range(4)]
    rows += [("[SYNTHETIC] mix", f"u{i}", "workflow") for i in range(5)]
    rows += [("[SYNTHETIC] mix", "u9", "google"), (None, "u1", "workflow")]
    found = sc.platform_default_hashes(rows, "workflow", 5)
    assert found == {sc.strict_hash("[SYNTHETIC] ph")}


@pytest.mark.parametrize(
    ("instr", "rag", "chunks", "query", "group", "sub"),
    [
        ("absent", "not_configured", 0, 0, sc.DIRECT, "blank_no_rag"),
        ("custom", "not_configured", 0, 0, sc.INSTRUCTION_ONLY, "custom_no_rag"),
        ("absent", "configured", 0, 0, sc.RAG_ONLY, "blank_and_rag"),
        ("absent", "not_configured", 2, 0, sc.RAG_ONLY, "blank_and_rag"),
        ("custom", "configured", 0, 0, sc.BOTH, "custom_and_rag"),
        ("custom", "unknown", 0, 1, sc.BOTH, "custom_and_rag"),
        ("custom", "unknown", 0, 0, sc.UNKNOWN, "custom_rag_unknown"),
        ("absent", "unknown", 0, 0, sc.UNKNOWN, "blank_rag_unknown"),
        ("unknown", "not_configured", 0, 0, sc.UNKNOWN, "unknown_no_rag_evidence"),
        (
            "platform_default",
            "unknown",
            3,
            0,
            sc.UNKNOWN,
            "platform_default_rag_positive",
        ),
        (
            "platform_default",
            "not_configured",
            0,
            0,
            sc.UNKNOWN,
            "platform_default_no_rag_evidence",
        ),
    ],
)
def test_classify_session(instr, rag, chunks, query, group, sub):
    c = sc.classify_session(instr, rag, chunks, query, 4)
    assert (c.group, c.subtype) == (group, sub)


def test_changing_rag_evidence_counts_and_is_flagged():
    c = sc.classify_session("custom", "not_configured", 1, 0, 5)
    assert c.group == sc.BOTH and c.mixed_rag and c.config_observed_disagree
    c = sc.classify_session("custom", "configured", 5, 0, 5)
    assert not c.mixed_rag and not c.config_observed_disagree


def test_extra_entities_differs_from_total_in_repeats():
    assert sc.extra_entities([1, 3, 2]) == 3


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("[SYNTHETIC] fix this python bug", pl.CODING),
        ("این کد رو درست کن", pl.CODING),
        ("how do I debug this", pl.CODING),
        ("لطفا این متن را ترجمه کن", pl.TRANSLATION),
        ("این مقاله را خلاصه کن", pl.SUMMARIZE),
        ("12 + 30 = ?", pl.MATH),
        ("یک شعر بنویس", pl.WRITING),
        ("برداشت من انجام نشد", pl.ACCOUNT),
        ("پایتخت فرانسه کجاست", pl.FACTUAL),
        ("سلام", pl.CONVERSATION),
        ("asdf", pl.UNKNOWN),
        ("", pl.UNKNOWN),
        (None, pl.UNKNOWN),
    ],
)
def test_primary_category(text, category):
    assert pl.primary_category(text)[0] == category


def test_coding_is_one_category_with_subtags():
    cat, others = pl.primary_category("چرا این کد خطا میده؟")
    assert cat == pl.CODING and pl.FACTUAL in others
    assert "debugging" in pl.coding_subtags("این کد خطا میده")
    assert pl.CODING == "coding_intent_debugging"
    assert not any("debug" in c and c != pl.CODING for c in pl.PRECEDENCE)


def test_precedence_keeps_secondary_tags():
    cat, others = pl.primary_category("این متن رو ترجمه کن و خلاصه کن")
    assert cat == pl.TRANSLATION and pl.SUMMARIZE in others


def test_history_dependence_needs_signal():
    assert pl.history_dependence("همون قبلی", 0) == "first_turn"
    assert pl.history_dependence("همون قبلی رو بگو", 3) == "likely_dependent"
    assert pl.history_dependence("[SYNTHETIC] " + "x" * 40, 3) == "later_turn_no_signal"


def test_skeleton_holds_no_words():
    s = pl.skeleton("Call 0912 سلام")
    assert s == "a 9 f" and "Call" not in s


def test_margin_quotas_exact_total_and_caps():
    pop = {"a": 100000, "b": 500, "c": 3, "d": 0}
    q = margin_quotas(pop, 300, 10)
    assert sum(q.values()) == 300 and q["c"] == 3 and "d" not in q and q["a"] > q["b"]
    with pytest.raises(ValueError):
        margin_quotas({"a": 5}, 300, 1)


def test_joint_quotas_match_both_margins_and_skip_empty_cells():
    pop = {
        ("cat1", "A"): 5000,
        ("cat1", "B"): 100,
        ("cat2", "A"): 30,
        ("cat2", "B"): 900,
        ("cat3", "B"): 7,
        ("cat3", "R"): 50,
        ("cat1", "R"): 40,
    }
    rows = {"cat1": 150, "cat2": 100, "cat3": 50}
    cols = {"A": 120, "B": 120, "R": 60}
    q = joint_quotas(pop, rows, cols)
    assert sum(q.values()) == 300
    for r, m in rows.items():
        assert sum(v for c, v in q.items() if c[0] == r) == m
    for k, m in cols.items():
        assert sum(v for c, v in q.items() if c[1] == k) == m
    assert all(c in pop and v <= pop[c] for c, v in q.items())


def test_joint_quotas_rejects_disagreeing_margins():
    with pytest.raises(ValueError):
        joint_quotas({("a", "b"): 5}, {"a": 2}, {"b": 3})


def _session():
    return [
        {"message_id": "m1", "role": "USER", "content": "[SYNTHETIC] first"},
        {"message_id": "m2", "role": "AI", "content": "[SYNTHETIC] old answer"},
        {"message_id": "m3", "role": "USER", "content": "[SYNTHETIC] target"},
        {"message_id": "m4", "role": "AI", "content": "[SYNTHETIC] TARGET ANSWER"},
        {"message_id": "m5", "role": "USER", "content": "[SYNTHETIC] FUTURE TURN"},
    ]


def test_manifest_has_no_target_answer_or_future_turn():
    e = build_manifest_entry(
        _session(),
        "m3",
        "[SYNTHETIC] instr",
        {"primary_category": pl.FACTUAL, "cohort": "User A"},
        {"seed": 1},
        {"session_id": "s1"},
    )
    dumped = json.dumps(e)
    assert "TARGET ANSWER" not in dumped and "FUTURE TURN" not in dumped
    assert [m["message_id"] for m in e["input_messages"]] == ["m1", "m2", "m3"]
    assert e["input_messages"][-1]["role"] == "USER"
    assert e["reference_answer"] is None and e["review"]["status"] == "not_reviewed"
    assert e["status"] == "proposed_candidate"
    assert set(e) == set(MANIFEST_FIELDS)


def test_manifest_rejects_non_user_target():
    with pytest.raises(ValueError):
        build_manifest_entry(
            _session(), "m2", None, {"primary_category": "x", "cohort": "y"}, {}, {}
        )
    with pytest.raises(ValueError):
        build_manifest_entry(
            _session(), "nope", None, {"primary_category": "x", "cohort": "y"}, {}, {}
        )


def test_manifest_errors_catches_leak():
    order = ["m1", "m2", "m3", "m4", "m5"]
    e = build_manifest_entry(
        _session(), "m3", None, {"primary_category": "x", "cohort": "y"}, {}, {}
    )
    assert manifest_errors(e, order) == []
    e["input_messages"].append(
        {"message_id": "m4", "role": "AI", "content": "[SYNTHETIC] leak"}
    )
    assert manifest_errors(e, order)
