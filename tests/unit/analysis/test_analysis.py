"""Offline tests for the full-EDA analysis code. All strings are SYNTHETIC."""

import json

import numpy as np
import pandas as pd

from metis_auto.analysis import (
    billing,
    cache_replay,
    ingest,
    pairing,
    stats,
)
from metis_auto.analysis import (
    text_features as tf,
)


def test_language_labels():
    assert tf.language_label("[SYNTHETIC] سلام، حال شما چطور است؟ امروز") in {
        "fa",
        "fa_en_mixed",
    }
    assert tf.language_label("سلام حال شما چطور است امروز") == "fa"
    assert tf.language_label("How can you help me with this task please") == "en"
    assert tf.language_label("salam chetori man mikham kamak") == "finglish"
    assert tf.language_label("سلام دوست من hello my friend how are") == "fa_en_mixed"
    assert tf.language_label('{"a": 1}') == "structured"
    assert tf.language_label("ok") == "short_uncertain"
    assert tf.language_label("   ") == "empty"
    # Arabic script without Persian signals is not called Persian.
    assert tf.language_label("مرحبا بكم في الموقع العربي") == "arabic_script_other"


def test_urls_do_not_make_text_mixed():
    assert tf.language_label("سلام حال شما چطور است https://example.com/path") == "fa"


def test_normalize_safe_keeps_numbers_distinct():
    assert tf.normalize_safe("كتاب ۱۲۳") == tf.normalize_safe("کتاب 123")
    assert tf.normalize_safe("کتاب ۱۲۳") != tf.normalize_safe("کتاب ۱۲۴")
    assert tf.normalize_safe("می‌روم") == tf.normalize_safe("می روم")


def test_billing_parse():
    items = [
        {
            "callCount": 1,
            "inputTokens": 100,
            "outputTokens": 10,
            "cachedInputTokens": 40,
            "totalCost": 0.5,
            "totalIncome": 0.6,
            "costBreakdown": {"input_tokens": 0.4},
        },
        {
            "callCount": 1,
            "inputTokens": 0,
            "outputTokens": 0,
            "totalCost": 0.002,
            "costBreakdown": {"per_call": 0.002},
        },
    ]
    out = billing.parse_billing(json.dumps(items))
    assert (
        out["billing_state"] == "items"
        and out["n_items"] == 2
        and out["n_token_items"] == 1
    )
    assert out["bill_inputTokens"] == 100 and out["bill_cachedInputTokens"] == 40
    assert (
        abs(out["bill_totalCost"] - 0.502) < 1e-12 and out["n_per_call_only_items"] == 1
    )
    assert billing.parse_billing(None)["billing_state"] == "null"
    assert billing.parse_billing("[]")["billing_state"] == "empty_list"
    assert billing.parse_billing("{bad")["billing_state"] == "malformed"
    assert billing.usd_per_million(1.0, 0) is None


def test_message_features_content_free():
    row = {
        "message_id": "m1",
        "session_id": "s1",
        "type": "USER",
        "timestamp": pd.Timestamp("2026-01-01"),
        "content": "[SYNTHETIC] hello there friend",
        "finish_reason": float("nan"),
        "attachments": None,
        "rag": json.dumps(
            [{"query": "q", "relevantChunks": [{"content": "abc"}, {"content": "de"}]}]
        ),
        "billing": None,
        "input": None,
        "tool_calls": None,
        "actions": "[]",
        "citations": None,
    }
    f = ingest.message_features(row)
    assert (
        f["rag_n_chunks"] == 2
        and f["rag_chunk_chars"] == 5
        and f["finish_reason"] is None
    )
    assert f["att_state"] == "null" and f["action_state"] == "empty"
    assert not any(isinstance(v, str) and "hello" in v for v in f.values())


def _msgs(spec):
    return pd.DataFrame(
        [
            {"session_id": "s", "message_id": f"m{i}", "type": t, "order": i}
            for i, t in enumerate(spec)
        ]
    )


def test_pairing_flags():
    p = pairing.pair_session_messages(
        _msgs(["USER", "AI", "USER", "USER", "AI", "AI", "SYSTEM", "USER", "AI"])
    )
    assert p["pair_flag"].tolist() == [
        "clean",
        "consecutive_user",
        "multiple_answers",
        "clean",
    ]
    assert p["n_skipped_user"].tolist() == [0, 1, 0, 0]
    p2 = pairing.pair_session_messages(_msgs(["AI", "USER", "AI"]))
    assert p2["pair_flag"].tolist() == ["no_preceding_user", "clean"]


def _req(rows):
    t0 = pd.Timestamp("2026-01-01")
    return pd.DataFrame(
        {
            "key": [r[0] for r in rows],
            "t_arrive": [t0 + pd.Timedelta(seconds=r[1]) for r in rows],
            "t_done": [t0 + pd.Timedelta(seconds=r[2]) for r in rows],
        }
    )


def test_replay_no_future_and_concurrency():
    # second request arrives before the first answer completed -> cannot hit
    r = _req([("a", 0, 10), ("a", 5, 15), ("a", 20, 25)])
    assert cache_replay.replay(r).tolist() == [False, False, True]


def test_replay_ttl_and_capacity():
    r = _req(
        [
            ("a", 0, 1),
            ("a", 100, 101),
            ("b", 200, 201),
            ("c", 300, 301),
            ("a", 400, 401),
        ]
    )
    assert cache_replay.replay(r).tolist() == [False, True, False, False, True]
    assert cache_replay.replay(r, ttl=pd.Timedelta(seconds=50)).tolist() == [
        False,
        False,
        False,
        False,
        False,
    ]
    # capacity 1: 'a' is evicted by later keys
    assert cache_replay.replay(r, capacity=1).tolist() == [
        False,
        True,
        False,
        False,
        False,
    ]


def test_replay_ineligible_never_inserts():
    r = _req([("a", 0, 1), ("a", 10, 11)])
    r["eligible"] = [False, True]
    assert cache_replay.replay(r).tolist() == [False, False]


def test_group_upper_bounds_distinct_metrics():
    out = cache_replay.group_upper_bounds(pd.Series(["a"] * 4 + ["b"] * 2 + ["c"]))
    assert (
        out["occurrences_in_dup_groups"] == 6
        and out["reusable_upper_bound"] == 4
        and out["pairs"] == 7
    )


def test_cluster_bootstrap_ratio():
    est, lo, hi = stats.cluster_bootstrap_ratio(
        np.array([1, 0, 1, 0]),
        np.array([1, 1, 1, 1]),
        np.array(["a", "a", "b", "b"]),
        n_boot=200,
    )
    assert est == 0.5 and lo <= est <= hi


def test_ledger_rejects_duplicates(tmp_path):
    led = stats.Ledger()
    led.ratio("x", "m", 1, 4, "share", "all", "observed fact")
    try:
        led.add("x", "m", 1, "u", "c", "e")
    except ValueError:
        pass
    else:
        raise AssertionError
    led.write(tmp_path / "l.csv")
    assert (tmp_path / "l.csv").read_text().count("\n") == 2
