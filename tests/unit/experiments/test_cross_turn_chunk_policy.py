"""R-B2 cross-turn chunk policy (exp-ctx-002). SYNTHETIC fixtures only: labels
such as ``s1``, ``scope-01``, ``chunk-a`` and made-up hashes."""

from types import SimpleNamespace

import pandas as pd
import pytest

VERSION = "context/exp-ctx-002-cross-turn-chunk-policy/version.py"
CTX = SimpleNamespace(seed=1)


@pytest.fixture(scope="module")
def rb2(load_experiment):
    return load_experiment(VERSION)


def chunk(
    req, turn, cid="chunk-a", h="h-a", chars=1000, session="s1", scope="scope-01"
):
    return dict(
        req=req,
        session=session,
        scope=scope,
        turn=turn,
        chunk_id=cid,
        content_hash=h,
        n_chars=chars,
    )


def requests(n, **cols):
    data = {
        "llm_request": [True] * n,
        "input_tokens_ordinary": [10_000.0] * n,
        "input_cost_ordinary": [0.01] * n,  # 1e-6 per ordinary input token
        "block_fees": [0.004] * n,
        "block_token_cost": [0.02] * n,
    }
    data.update(cols)
    return pd.DataFrame(data, index=[f"r{i}" for i in range(n)])


def policy(rb2, rows, pointer=10, visible=lambda k: k <= 1, ledger=False):
    return rb2.CrossTurnChunkPolicy(
        pointer,
        visible,
        ledger,
        chunks=pd.DataFrame(rows),
        tokens_per_char=0.5,
    )


def test_repeat_in_session_dropped_with_pointer_cost(rb2):
    out = policy(rb2, [chunk("r0", 0), chunk("r1", 1)]).apply(requests(2), CTX)
    assert out.loc["r1", "ctx_chunks_dropped"] == 1
    assert out.loc["r1", "ctx_tokens_removed"] == 500
    assert out.loc["r1", "ctx_tokens_added"] == 10
    assert out.loc["r1", "ctx_tokens_saved"] == 490
    assert out.loc["r1", "block_token_cost"] == pytest.approx(0.02 - 490e-6)
    assert out.loc["r1", "input_tokens_after"] == 10_000 - 490
    assert out.loc["r0", "ctx_tokens_saved"] == 0


def test_not_visible_chunk_kept(rb2):
    rows = [chunk("r0", 0), chunk("r1", 2)]  # two turns back
    p = policy(rb2, rows, visible=lambda k: k <= 1)
    decisions = p.decide(requests(2))
    assert decisions.loc[1, "reason"] == "kept_not_visible"
    never = policy(rb2, [chunk("r0", 0), chunk("r1", 1)], visible=lambda k: False)
    assert never.apply(requests(2), CTX)["ctx_tokens_saved"].sum() == 0


def test_visibility_counts_from_the_last_full_supply(rb2):
    rows = [chunk("r0", 0), chunk("r1", 1), chunk("r2", 2)]
    d = policy(rb2, rows, visible=lambda k: k <= 1).decide(requests(3))
    # r1 drops it (k=1); r2 is k=2 from the last full supply at turn 0: kept
    assert d["reason"].tolist() == ["kept_first_seen", "dropped", "kept_not_visible"]


def test_changed_hash_kept(rb2):
    rows = [chunk("r0", 0, h="h-a"), chunk("r1", 1, h="h-a2")]
    d = policy(rb2, rows).decide(requests(2))
    assert d.loc[1, "reason"] == "kept_changed_hash"
    unknown = [chunk("r0", 0, h=None), chunk("r1", 1, h=None)]
    d = policy(rb2, unknown).decide(requests(2))
    assert d.loc[1, "reason"] == "kept_hash_unknown"


def test_optional_session_ledger_counts_append_only_block(rb2):
    rows = [
        chunk("r0", 0, "chunk-a", "h-a"),
        chunk("r0", 0, "chunk-b", "h-b"),
        chunk("r1", 1, "chunk-a", "h-a"),
        chunk("r1", 1, "chunk-b", "h-b"),
        chunk("r1", 1, "chunk-c", "h-c"),
        chunk("r2", 2, "chunk-a", "h-a"),
    ]
    p = policy(rb2, rows, pointer=10, visible=lambda k: True, ledger=True)
    out = p.apply(requests(3), CTX)
    # turn 1: ledger holds {a, b} -> 20 tokens; turn 2: {a, b, c} -> 30
    assert out.loc["r1", "ctx_tokens_added"] == 20
    assert out.loc["r2", "ctx_tokens_added"] == 30
    assert out.loc["r1", "ctx_tokens_removed"] == 1000
    no_ledger = policy(rb2, rows, pointer=10, visible=lambda k: True).apply(
        requests(3), CTX
    )
    assert no_ledger.loc["r1", "ctx_tokens_added"] == 20  # one pointer per drop
    assert no_ledger.loc["r2", "ctx_tokens_added"] == 10


def test_sessions_and_scopes_are_isolated(rb2):
    rows = [
        chunk("r0", 0, session="s1"),
        chunk("r1", 1, session="s2"),
        chunk("r2", 2, session="s1", scope="scope-02"),
    ]
    d = policy(rb2, rows, visible=lambda k: True).decide(requests(3))
    assert d["reason"].tolist() == ["kept_first_seen"] * 3


def test_no_negative_savings(rb2):
    rows = [chunk("r0", 0, chars=10), chunk("r1", 1, chars=10)]  # 5 tokens
    p = policy(rb2, rows, pointer=10)
    out = p.apply(requests(2), CTX)
    assert out.loc["r1", "ctx_tokens_saved"] == 0
    assert out.loc["r1", "block_token_cost"] == 0.02
    assert p.decide(requests(2)).loc[1, "reason"] == "kept_net_nonpositive"


def test_never_below_supported_input_tokens(rb2):
    req = requests(2, input_tokens_ordinary=[10_000.0, 100.0])
    out = policy(rb2, [chunk("r0", 0), chunk("r1", 1)]).apply(req, CTX)
    assert out.loc["r1", "ctx_tokens_saved"] == 100
    assert out.loc["r1", "input_tokens_after"] == 0
    assert out.loc["r1", "block_token_cost"] >= 0


def test_within_message_duplicates_are_not_counted(rb2):
    rows = [chunk("r0", 0), chunk("r1", 1), chunk("r1", 1)]  # S-6 owns the copy
    p = policy(rb2, rows)
    d = p.decide(requests(2))
    assert d["reason"].tolist() == ["kept_first_seen", "dropped", "within_message"]
    assert p.apply(requests(2), CTX).loc["r1", "ctx_tokens_removed"] == 500


def test_answer_cache_rows_skipped_retrieval_reuse_rows_eligible(rb2):
    rows = [chunk("r0", 0), chunk("r1", 1), chunk("r2", 2)]
    req = requests(
        3,
        served_from_cache=[False, True, False],
        retrieval_reused=[False, False, True],
    )
    out = policy(rb2, rows, visible=lambda k: True).apply(req, CTX)
    assert out.loc["r1", "ctx_tokens_saved"] == 0  # answer cache: no context step
    assert out.loc["r1", "block_token_cost"] == 0.02
    assert out.loc["r2", "ctx_tokens_saved"] == 490  # R-B1 reuse stays eligible


def test_fees_output_and_workflow_rows_unchanged(rb2):
    rows = [chunk("r0", 0), chunk("r1", 1), chunk("r2", 2)]
    req = requests(3, llm_request=[True, False, True])
    out = policy(rb2, rows, visible=lambda k: True).apply(req, CTX)
    assert out["block_fees"].equals(req["block_fees"])
    assert out.loc["r1", "block_token_cost"] == 0.02
    assert out.loc["r1", "ctx_tokens_saved"] == 0
    assert out.index.equals(req.index)


def test_unknown_input_cost_is_not_applied(rb2):
    req = requests(2, input_cost_ordinary=[0.01, float("nan")])
    p = policy(rb2, [chunk("r0", 0), chunk("r1", 1)])
    out = p.apply(req, CTX)
    assert out.loc["r1", "ctx_tokens_saved"] == 0
    assert out.loc["r1", "block_token_cost"] == 0.02
    assert p.decide(req).loc[1, "reason"] == "kept_cost_unknown"


def test_ordinary_input_follows_the_cached_token_convention(rb2):
    separate = frozenset({"model-sep"})
    f = rb2.ordinary_input_tokens
    assert f(100.0, 30.0, "model-sep", separate) == 100.0  # excludes cached
    assert f(100.0, 30.0, "model-incl", separate) == 70.0  # includes cached
    assert f(100.0, float("nan"), "model-incl", separate) == 100.0
    assert f(20.0, 30.0, "model-incl", separate) == 0.0
    assert pd.isna(f(float("nan"), 3.0, "model-incl", separate))


def test_summary_reports_reasons_and_shares(rb2):
    rows = [chunk("r0", 0), chunk("r1", 1), chunk("r1", 1, "chunk-z", "h-z")]
    p = policy(rb2, rows)
    s = rb2.summarise(p.decide(requests(2)), p.apply(requests(2), CTX), requests(2))
    assert s["reasons"] == {"kept_first_seen": 2, "dropped": 1}
    assert s["tokens"]["saved"] == 490
    assert s["tokens"]["supported_input"] == 20_000
    assert s["cost"]["saving_share_of_token_cost"] == pytest.approx(490e-6 / 0.04)
    assert s["repeat_reference"]["share_rows_repeating_in_session"] == pytest.approx(
        1 / 3
    )


def test_combine_applies_context_after_retrieval_cache(rb2):
    levers = pytest.importorskip("metis_auto.analysis.levers")
    ctx = levers.ReplayContext(period_bounds={}, price_table={}, catalogue={}, seed=1)
    p = policy(rb2, [chunk("r0", 0), chunk("r1", 1)])
    assert isinstance(p, levers.StepVersion)
    out = levers.combine(requests(2), None, p, None, ctx)
    assert out.loc["r1", "block_token_cost"] == pytest.approx(0.02 - 490e-6)
    assert out["served_from_cache"].tolist() == [False, False]
