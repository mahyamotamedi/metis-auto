"""Offline tests for request features and the per-session pairing. [SYNTHETIC] text."""

import tomllib
from pathlib import Path

from metis_auto.analysis.pairing import pair_ordered
from metis_auto.analysis.request_features import (
    BotContext,
    Vocabulary,
    bigrams,
    family_ids,
    jaccard,
    session_requests,
)

RAW = tomllib.loads(
    (
        Path(__file__).resolve().parents[3] / "config/evaluation/golden_v1.toml"
    ).read_text(encoding="utf-8")
)
VOCAB = Vocabulary(RAW["rules"])
THRESHOLDS = {
    "complex_chars": 1000,
    "average_chars": 50,
    "complex_history": 8000,
    "distant_history_min_turn": 6,
}
BOT = BotContext("b1", "custom", "not_configured", 10)


def msg(mid, typ, content, finish=None, **kw):
    return {
        "message_id": mid,
        "session_id": "s1",
        "type": typ,
        "content": content,
        "finish_reason": finish,
        "timestamp_is_null": False,
        "input_state": "null",
        "attachment_types": [],
        **kw,
    }


def rows(messages, bot=BOT):
    return session_requests(
        messages,
        bot=bot,
        cohort="User A",
        vocab=VOCAB,
        groups=RAW["language_groups"],
        intent_map=RAW["intent_map"],
        thresholds=THRESHOLDS,
        feature_version="t",
    )


def test_pair_ordered_flags():
    pairs = pair_ordered(["USER", "AI", "AI", "USER", "USER", "AI"], list("abcdef"))
    assert [p.pair_flag for p in pairs] == [
        "clean",
        "multiple_answers",
        "consecutive_user",
    ]
    assert pair_ordered(["AI"], ["a"])[0].pair_flag == "no_preceding_user"


def test_clean_pair_is_eligible_and_counts_history():
    out = rows(
        [
            msg("u1", "USER", "[SYNTHETIC] what is the capital?"),
            msg("a1", "AI", "[SYNTHETIC] answer one", "STOP"),
            msg("u2", "USER", "[SYNTHETIC] and the river there?"),
            msg("a2", "AI", "[SYNTHETIC] answer two", "STOP"),
        ]
    )
    assert [r["eligible"] for r in out] == [True, True]
    assert out[0]["turn_index"] == 1 and out[0]["n_prior_messages"] == 0
    assert out[1]["turn_index"] == 2 and out[1]["n_prior_messages"] == 2
    assert out[1]["answer_message_id"] == "a2"
    assert out[1]["history_chars"] > 0


def test_exclusion_reasons():
    out = rows(
        [
            msg("u1", "USER", "[SYNTHETIC] first"),
            msg("u2", "USER", "[SYNTHETIC] second"),
            msg("a2", "AI", "[SYNTHETIC] answer", "STOP"),
            msg("u3", "USER", "   "),
            msg("a3", "AI", "[SYNTHETIC] answer", "STOP"),
            msg("u4", "USER", "[SYNTHETIC] cut off"),
            msg("a4", "AI", "[SYNTHETIC] answer", "LENGTH"),
            msg("u5", "USER", "[SYNTHETIC] blank answer"),
            msg("a5", "AI", "  ", "STOP"),
            msg("u6", "USER", "[SYNTHETIC] no answer yet"),
        ]
    )
    assert [r["exclusion_reason"] for r in out] == [
        "pair_unanswered",
        "pair_consecutive_user",
        "blank_target",
        "answer_not_stop",
        "blank_answer",
        "pair_unanswered",
    ]
    assert not any(r["eligible"] for r in out)


def test_null_target_timestamp_is_excluded():
    out = rows(
        [
            msg("u1", "USER", "[SYNTHETIC] x", timestamp_is_null=True),
            msg("a1", "AI", "[SYNTHETIC] y", "STOP"),
        ]
    )
    assert out[0]["exclusion_reason"] == "null_target_timestamp"


def test_system_and_tool_do_not_count_as_turns():
    out = rows(
        [
            msg("s", "SYSTEM", "[SYNTHETIC] sys"),
            msg("u1", "USER", "[SYNTHETIC] q"),
            msg("t", "TOOL", "[SYNTHETIC] tool"),
            msg("a1", "AI", "[SYNTHETIC] a", "STOP"),
        ]
    )
    assert out[0]["turn_index"] == 1 and out[0]["pair_flag"] == "clean"
    assert out[0]["n_prior_messages"] == 0


def test_greeting_rule_and_widget_and_attachment_flags():
    out = rows(
        [
            msg("u1", "USER", "hello!", attachment_types=["IMAGE"]),
            msg("a1", "AI", "[SYNTHETIC] a", "STOP", input_state="ok"),
            msg("u2", "USER", "[SYNTHETIC] picked an option"),
            msg("a2", "AI", "[SYNTHETIC] b", "STOP"),
        ]
    )
    assert out[0]["rule_tags"]["pure_greeting"] is True
    assert out[0]["rule_intent"] == "conversational_smalltalk"
    assert out[0]["attachment_count"] == 1
    assert out[0]["rule_tags"]["attachment_dependent"] is True
    assert out[1]["after_widget"] is True


def test_length_alone_does_not_make_a_label_only_a_proxy():
    out = rows(
        [
            msg("u1", "USER", "[SYNTHETIC] " + "word " * 400),
            msg("a1", "AI", "[SYNTHETIC] a", "STOP"),
        ]
    )
    assert out[0]["complexity_proxy"] == "complex"
    assert "complexity" not in out[0]


def test_no_text_in_the_row():
    secret = "[SYNTHETIC] a private sentence"
    out = rows([msg("u1", "USER", secret), msg("a1", "AI", "[SYNTHETIC] a", "STOP")])
    assert secret not in repr(out)


def test_rag_observed_comes_from_the_answer():
    out = rows(
        [
            msg("u1", "USER", "[SYNTHETIC] q"),
            msg("a1", "AI", "[SYNTHETIC] a", "STOP", rag_n_chunks=3, rag_n_queries=1),
        ],
        BotContext("b1", "custom", "configured", 10),
    )
    assert out[0]["rag_observed_on_answer"] is True
    assert out[0]["bot_class"] == "instruction_rag"


def test_family_ids_group_folded_text_within_one_bot():
    assert family_ids("b", "ي a")[0] == family_ids("b", "ی a")[0]
    assert family_ids("b", "x y")[0] != family_ids("c", "x y")[0]
    assert family_ids("b", "x y")[1] == family_ids("b", "y x")[1]
    assert family_ids("b", "  ") == (None, None)


def test_near_duplicate_measure():
    a = bigrams("[SYNTHETIC] one two three four five")
    assert jaccard(a, a) == 1.0
    assert jaccard(a, bigrams("completely other words here now")) == 0.0
    assert jaccard(frozenset(), frozenset()) == 0.0
