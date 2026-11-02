"""EXP-CACHE-004 session memo + greeting skip gate (sprint task R-C1; FR-REQ-06,
FR-XCACHE-01, FR-ACCT-02, H-3, X1; ADR-0036, ADR-0037, ADR-0038,
ADR-0039).

Every frame, word, fingerprint, fee, rate and price here is SYNTHETIC: invented
values, no dataset content, no real price. The version lives in
``experiments/``, so it is loaded by file path.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from metis_auto.analysis.cache_guard import CacheGuard
from metis_auto.analysis.lever_result import LeverResult
from metis_auto.analysis.levers import ReplayContext, combine
from metis_auto.analysis.text_features import fingerprint, normalize_safe

ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/caching/exp-cache-004-session-memo-gate"
NAN = np.nan
WORDS = frozenset({"syn-hello", "سلام-آزمایشی"})  # SYNTHETIC phatic list
COEF = 0.5  # SYNTHETIC tokens per character
RATES = {"syn-small": 2.0}  # SYNTHETIC implied input per 1M
PRICES = {
    "version": "prices-synthetic",
    "per_tokens": 1,
    "prices": [
        {"price_ref": "p-small", "input": "1", "output": "2", "cached_input": "0.5"},
        {"price_ref": "p-premium", "input": "10", "output": "20", "cached_input": "5"},
    ],
}
CATALOGUE = {
    "models": [
        {"model_id": "syn-small", "price_ref": "p-small", "enabled": True},
        {"model_id": "syn-premium", "price_ref": "p-premium", "enabled": False},
    ]
}
CTX = ReplayContext(period_bounds={}, price_table=PRICES, catalogue=CATALOGUE, seed=0)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def v():
    yield _load("exp_cache_004_under_test", EXP / "version.py")
    sys.modules.pop("exp_cache_004_under_test", None)


@pytest.fixture(scope="module")
def derive():
    yield _load(
        "derive_rag_query_fps_under_test",
        ROOT / "scripts/derive_rag_query_fingerprints.py",
    )
    sys.modules.pop("derive_rag_query_fps_under_test", None)


@pytest.fixture(scope="module")
def script():
    yield _load(
        "session_memo_levers_under_test", ROOT / "scripts/session_memo_levers.py"
    )
    sys.modules.pop("session_memo_levers_under_test", None)


def text_key(text: str) -> str:
    """The ``u_h_norm`` rule of the ingest, on SYNTHETIC text."""
    return fingerprint(normalize_safe(text))


# A SYNTHETIC turn: (session, turn, message, user text or None, attachments,
# queries (None = no lookup), chunks [(chunk_id, h_exact, n_chars)], fees, llm)
def frames(turns: list[tuple]) -> dict[str, pd.DataFrame]:
    req_rows, fp_rows, chunk_rows, fee_rows = [], [], [], []
    for i, (sess, turn, msg, text, att, queries, chunks, fees, llm) in enumerate(turns):
        n_q = 0 if queries is None else len(queries)
        req_rows.append(
            {
                "session_id": sess,
                "turn": turn,
                "a_order": i,
                "ai_message_id": msg,
                "bot_id": "bot-syn",
                "u_h_norm": None if text is None else text_key(text),
                "u_att_n": att,
                "a_rag_n_queries": n_q,
                "a_citation_n": 1 if n_q else 0,
                "llm_request": llm,
                "bot_provider_name": "syn-provider" if llm else "workflow",
                "bot_provider_model": "syn-small" if llm else None,
                "a_billing_state": "items" if llm else None,
                "a_bill_inputTokens": 1000.0 if llm else NAN,
                "a_bill_cachedInputTokens": 100.0 if llm else NAN,
                "a_bill_outputTokens": 50.0 if llm else NAN,
                "a_bill_totalCost": 0.01 if llm else NAN,
                "a_n_per_call_only_items": len(fees),
            }
        )
        if queries:
            fp_rows.append(
                {"message_id": msg, "query_fps": sorted(text_key(q) for q in queries)}
            )
        for cid, h, n in chunks:
            chunk_rows.append(
                {"message_id": msg, "chunk_id": cid, "h_exact": h, "n_chars": n}
            )
        for amount in fees:
            fee_rows.append({"message_id": msg, "amount": amount})
    return {
        "req": pd.DataFrame(req_rows),
        "query_fps": pd.DataFrame(fp_rows, columns=["message_id", "query_fps"]),
        "chunks": pd.DataFrame(
            chunk_rows, columns=["message_id", "chunk_id", "h_exact", "n_chars"]
        ),
        "per_call": pd.DataFrame(fee_rows, columns=["message_id", "amount"]),
    }


CH_A = [("c1", "h1", 100), ("c2", "h2", 100)]
CH_B = [("c3", "h3", 100)]
FEES = [0.002, 0.002]


def prepared(v, turns):
    f = frames(turns)
    req = v.fee_blocks(f["req"], f["per_call"])
    lookups = v.build_lookups(req, f["query_fps"], f["chunks"], f["per_call"])
    return req, lookups


def memo(v, lookups, threshold=0.5, **kw):
    return v.SessionMemo(threshold, WORDS, lookups=lookups, **kw)


def test_reuse_only_inside_one_session(v):
    req, lookups = prepared(
        v,
        [
            ("s1", 0, "m1", "q", 0, ["alpha", "beta"], CH_A, FEES, True),
            ("s2", 0, "m2", "q", 0, ["gamma", "delta"], CH_B, FEES, True),
            ("s2", 1, "m3", "q", 0, ["alpha", "beta"], CH_A, FEES, True),
            ("s1", 1, "m4", "q", 0, ["alpha", "beta"], CH_A, FEES, True),
        ],
    )
    out = memo(v, lookups).apply(req, CTX)
    status = dict(zip(out["ai_message_id"], out["memo_status"], strict=True))
    assert status["m3"] == "performed"  # same queries, other session: no reuse
    assert status["m4"] == "reused"


def test_phatic_message_skips_retrieval(v):
    req, lookups = prepared(
        v,
        [
            ("s1", 0, "m1", "q", 0, ["alpha"], CH_A, [0.002], True),
            ("s1", 1, "m2", "syn-hello!", 0, ["beta"], CH_B, [0.002], True),
            ("s1", 2, "m3", "سلام-آزمایشی؟", 0, ["gamma"], CH_B, [0.002], True),
            ("s1", 3, "m4", "SYN-HELLO", 0, ["delta"], CH_B, [0.002], True),
            ("s1", 4, "m5", "syn-hello!!", 0, ["eps"], CH_B, [0.002], True),
            ("s1", 5, "m6", "syn-hello there", 0, ["zeta"], CH_B, [0.002], True),
        ],
    )
    out = memo(v, lookups, threshold=1.0).apply(req, CTX)
    status = dict(zip(out["ai_message_id"], out["memo_status"], strict=True))
    assert status["m2"] == status["m3"] == status["m4"] == "skipped_phatic"
    assert status["m5"] == status["m6"] == "performed"  # exact match only
    skipped = out[out["memo_status"] == "skipped_phatic"]
    assert (skipped["memo_lookups_skipped"] == 1).all()
    assert skipped["memo_fee_avoided"].tolist() == pytest.approx([0.002] * 3)


def test_overlap_threshold_has_no_default(v):
    param = inspect.signature(v.SessionMemo).parameters["overlap_threshold"]
    assert param.default is inspect.Parameter.empty
    req, lookups = prepared(
        v, [("s1", 0, "m1", "q", 0, ["alpha"], CH_A, [0.002], True)]
    )
    with pytest.raises(ValueError, match="overlap_threshold"):
        v.SessionMemo(None, WORDS, lookups=lookups).apply(req, CTX)
    for bad in (0.0, 1.5, NAN):
        with pytest.raises(ValueError, match="overlap_threshold"):
            v.SessionMemo(bad, WORDS, lookups=lookups)


def test_turn_zero_never_skipped(v):
    req, lookups = prepared(
        v,
        [
            ("s1", 0, "m1", "syn-hello", 0, ["alpha"], CH_A, [0.002], True),
            ("s2", 0, "m2", "q", 0, ["alpha"], CH_A, [0.002], True),
            ("s2", 1, "m3", "syn-hello", 2, ["beta"], CH_B, [0.002], True),
            ("s2", 2, "m4", "syn-hello", NAN, ["gamma"], CH_B, [0.002], True),
            ("s3", 0, "m5", "q", 0, ["alpha"], CH_A, [0.002], False),
            ("s3", 1, "m6", "syn-hello", 0, ["beta"], CH_B, [0.002], False),
        ],
    )
    out = combine(req, memo(v, lookups, threshold=1.0), None, None, CTX)
    status = dict(zip(out["ai_message_id"], out["memo_status"], strict=True))
    assert status["m1"] == "performed"  # turn 0
    assert status["m3"] == "performed"  # attachments
    assert status["m4"] == "performed"  # attachments unknown
    assert pd.isna(status["m6"])  # workflow: the version never sees it
    wf = out["ai_message_id"].isin(["m5", "m6"])
    assert out.loc[wf, "block_fees"].equals(req.loc[wf, "block_fees"])


def test_reuse_decision_uses_no_current_turn_chunks(v):
    base = [
        ("s1", 0, "m1", "q", 0, ["alpha", "beta"], CH_A, FEES, True),
        ("s1", 1, "m2", "q", 0, ["alpha", "beta"], CH_A, FEES, True),
        ("s1", 2, "m3", "q", 0, ["omega"], CH_B, [0.002], True),
    ]
    changed = [*base[:1], (*base[1][:6], CH_B, FEES, True), base[2]]
    outs = [
        memo(v, prepared(v, t)[1]).apply(prepared(v, t)[0], CTX)
        for t in (base, changed)
    ]
    cols = ["memo_status", "memo_overlap", "memo_lookups_skipped", "memo_fee_avoided"]
    pd.testing.assert_frame_equal(outs[0][cols], outs[1][cols])
    assert outs[0].loc[1, "memo_agreement"] == 1.0
    assert outs[1].loc[1, "memo_agreement"] == 0.0  # only the score sees them


def test_memo_reuse_lowers_fees_only(v):
    req, lookups = prepared(
        v,
        [
            ("s1", 0, "m1", "q", 0, ["alpha", "beta"], CH_A, FEES, True),
            ("s1", 1, "m2", "q", 0, ["alpha", "beta"], CH_A, FEES, True),
        ],
    )
    version = memo(v, lookups, tokens_per_char=COEF, input_rate_per_m=RATES)
    out = combine(req, version, None, None, CTX)
    row = out.loc[1]
    assert row["memo_status"] == "reused"
    assert row["block_fees"] == pytest.approx(req.loc[1, "block_fees"] - 0.004)
    assert row["block_token_cost"] == req.loc[1, "block_token_cost"]
    assert row["memo_saved_input_tokens"] == 0
    assert not out["served_from_cache"].any()


def test_skip_saves_fees_and_chunk_tokens(v):
    req, lookups = prepared(
        v,
        [
            ("s1", 0, "m1", "q", 0, ["alpha"], CH_A, [0.002], True),
            ("s1", 1, "m2", "syn-hello", 0, ["beta"], CH_A, [0.002], True),
        ],
    )
    version = memo(v, lookups, tokens_per_char=COEF, input_rate_per_m=RATES)
    out = combine(req, version, None, None, CTX)
    row = out.loc[1]
    assert row["memo_status"] == "skipped_phatic"
    assert row["block_fees"] == pytest.approx(req.loc[1, "block_fees"] - 0.002)
    tokens = 200 * COEF  # two chunks x 100 chars, below input - cached (900)
    assert row["memo_saved_input_tokens"] == pytest.approx(tokens)
    cut = tokens * RATES["syn-small"] / 1e6
    assert row["block_token_cost"] == pytest.approx(
        req.loc[1, "block_token_cost"] - cut
    )
    assert bool(row["memo_saving_known"])
    assert not out["served_from_cache"].any()
    unpriced = memo(v, lookups, tokens_per_char=COEF, input_rate_per_m={})
    out = unpriced.apply(req, CTX)
    assert not bool(out.loc[1, "memo_saving_known"])  # unknown, never zero
    assert out.loc[1, "block_token_cost"] == req.loc[1, "block_token_cost"]


def test_unattributable_fee_is_not_skippable(v):
    req, lookups = prepared(
        v,
        [
            ("s1", 0, "m1", "q", 0, ["alpha", "beta"], CH_A, FEES, True),
            ("s1", 1, "m2", "q", 0, ["alpha", "beta"], CH_A, [0.002, 0.003], True),
            ("s1", 2, "m3", "syn-hello", 0, ["gamma"], CH_B, [], True),
        ],
    )
    out = memo(v, lookups).apply(req, CTX)
    assert out["memo_status"].tolist() == [
        "performed",
        "fee_unattributed",
        "fee_unattributed",
    ]
    assert (out["memo_fee_avoided"] == 0).all()


def test_memo_holds_the_last_real_lookup(v):
    req, lookups = prepared(
        v,
        [
            ("s1", 0, "m1", "q", 0, ["a", "b"], CH_A, FEES, True),
            ("s1", 1, "m2", "q", 0, ["a", "b", "c"], CH_A, [0.002] * 3, True),
            ("s1", 2, "m3", "q", 0, ["b", "c", "d"], CH_B, [0.002] * 3, True),
        ],
    )
    out = memo(v, lookups, threshold=0.5).apply(req, CTX)
    # m2 vs m1: 2/3 -> reused. m3 vs the memo (m1, not the reused m2): 1/4.
    assert out["memo_status"].tolist() == ["performed", "reused", "performed"]
    assert out.loc[2, "memo_overlap"] == pytest.approx(0.25)


def test_agreement_is_jaccard_over_chunk_id_and_hash(v):
    assert v.agreement([("c1", "h1")], [("c1", "h1")]) == 1.0
    assert v.agreement([("c1", "h1")], [("c1", "h9")]) == 0.0  # changed text
    assert v.agreement([("c1", None)], [("c1", "h1")]) is None
    assert v.agreement([], []) is None


def test_guard_refusal_blocks_reuse(v):
    req, lookups = prepared(
        v,
        [
            ("s1", 0, "m1", "q", 0, ["alpha"], CH_A, [0.002], True),
            ("s1", 1, "m2", "q", 0, ["alpha"], CH_A, [0.002], True),
        ],
    )
    guard = CacheGuard(
        approved=None,
        blocked=frozenset(),
        disabled_bots=frozenset({"bot-syn"}),
        key_version="syn-v1",
    )
    ctx = ReplayContext(
        period_bounds={}, price_table={}, catalogue={}, seed=0, guard=guard
    )
    out = memo(v, lookups).apply(req, ctx)
    assert out["memo_status"].tolist() == ["performed", "guard_block"]


def test_threshold_choice_is_lowest_passing_on_tune(v):
    def s(n, evaluable, mean):
        return {"n_reused": n, "n_evaluable": evaluable, "agreement_mean": mean}

    assert (
        v.choose_threshold({0.5: s(10, 9, 0.7), 0.8: s(6, 4, 0.95), 1.0: s(3, 3, 1)})
        == 0.8
    )
    assert (
        v.choose_threshold(
            {0.5: s(10, 4, 0.99), 0.8: s(0, 0, None), 1.0: s(2, 2, 0.95)}
        )
        == 1.0
    )
    assert v.choose_threshold({0.5: s(0, 0, None), 1.0: s(2, 2, 0.5)}) is None


def test_query_fingerprints_keep_no_text(derive):
    rag = '[{"query": " Syn Query "}, {"query": "a"}, {"query": ""}, 7]'
    fps = derive.query_fingerprints(rag)
    assert fps == sorted([text_key("syn query"), text_key("a")])
    assert all(len(f) == 24 and "syn" not in f for f in fps)
    assert derive.query_fingerprints(None) is None
    assert derive.query_fingerprints("not json") is None


def test_levers_script_writes_one_result_per_baseline(v, script, tmp_path):
    f = frames(
        [
            ("s1", 0, "m1", "q", 0, ["alpha"], CH_A, [0.002], True),
            ("s1", 1, "m2", "q", 0, ["alpha"], CH_A, [0.002], True),
            ("s1", 2, "m3", "syn-hello", 0, ["beta"], CH_B, [0.002], True),
            ("s2", 0, "m4", "q", 0, None, [], [], False),
        ]
    )
    paths = script.write_levers(
        f["req"],
        query_fps=f["query_fps"],
        chunks=f["chunks"],
        per_call=f["per_call"],
        ctx=CTX,
        overlap_threshold=0.5,
        phatic_words=WORDS,
        tokens_per_char=COEF,
        input_rate_per_m=RATES,
        premium_model="syn-premium",
        out_dir=tmp_path,
        code_commit="unknown",
        python_version="3.13.0",
        created_at=datetime(2026, 11, 2, tzinfo=UTC),
        config_extra={"split": "synthetic"},
    )
    results = {
        r.baseline: r for r in (LeverResult.from_json(p.read_text()) for p in paths)
    }
    assert set(results) == {
        "as_logged",
        "premium_gpt_5_5",
        "todays_models",
        "best_single_cheap",
    }
    logged = results["as_logged"]
    assert logged.lever_id == "cache.session_memo_gate.as_logged"
    assert logged.step == "cache"
    assert set(logged.saving) == {"fees", "token_cost", "total"}
    assert logged.saving["fees"] > 0 and logged.saving["token_cost"] > 0
    memo_slice = logged.slices["session_memo"]
    assert memo_slice["n_reused"] == 1 and memo_slice["n_skipped_phatic"] == 1
    for key in ("premium_gpt_5_5", "todays_models", "best_single_cheap"):
        r = results[key]
        assert r.saving == {}  # fee part not priced: unknown, never ranked
        assert "fees" not in r.baseline_cost
        assert r.slices["session_memo"]["token_saving_lower_bound"] > 0
        assert "fee_avoided" not in r.slices["session_memo"]
    text = "".join(p.read_text() for p in paths)
    for secret in ("m1", "s1", "alpha", text_key("alpha"), "bot-syn"):
        assert secret not in text
