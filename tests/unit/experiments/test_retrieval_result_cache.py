"""R-B1 retrieval-result cache (exp-cache-002). Every fixture here is SYNTHETIC:
labels such as ``tenant-01`` and ``bot-01`` and made-up query strings."""

from types import SimpleNamespace

import pandas as pd
import pytest

from metis_auto.analysis.cache_guard import CacheGuard, versioned_key

VERSION = "caching/exp-cache-002-retrieval-result-cache/version.py"
T0 = pd.Timestamp("2026-04-01 10:00")


@pytest.fixture(scope="module")
def rb1(load_experiment):
    return load_experiment(VERSION)


def _guard(**kw):
    base = dict(
        approved=None, blocked=frozenset(), disabled_bots=frozenset(), key_version="r1"
    )
    base.update(kw)
    return CacheGuard(**base)


def _ctx(guard=None):
    return SimpleNamespace(guard=guard or _guard(), seed=7)


def _lookup(rb1, req, minutes, query="synthetic question one", **kw):
    row = dict(
        req=req,
        pos=0,
        t_arrive=T0 + pd.Timedelta(minutes=minutes),
        t_done=T0 + pd.Timedelta(minutes=minutes, seconds=30),
        tenant="tenant-01",
        bot="bot-01",
        corpus_version="cv-1",
        settings="top_k=5;rerank=off",
        query_key=rb1.query_key(query),
        chunks=(("chunk-a", "h-a"), ("chunk-b", "h-b")),
        fee=0.002,
    )
    row.update(kw)
    return row


def _frame(rows):
    return pd.DataFrame(rows)


def _req(n, **cols):
    data = {
        "llm_request": [True] * n,
        "block_fees": [0.01] * n,
        "block_token_cost": [0.5] * n,
    }
    data.update(cols)
    return pd.DataFrame(data, index=[f"r{i}" for i in range(n)])


WEEK = pd.Timedelta(days=7)


def _cache(rb1, rows, ttl=WEEK, shadow_rate=0.0):
    return rb1.RetrievalResultCache(ttl, lookups=_frame(rows), shadow_rate=shadow_rate)


# --- key ---------------------------------------------------------------------


def test_key_is_bot_corpus_version_settings_and_normalised_query(rb1):
    q = rb1.query_key("Synthetic   QUESTION ي")
    assert q == rb1.query_key("synthetic question ی")  # normalize_safe only
    key = rb1.lookup_key("tenant-01", "bot-01", "cv-1", "top_k=5", q)
    for other in (
        rb1.lookup_key("tenant-02", "bot-01", "cv-1", "top_k=5", q),
        rb1.lookup_key("tenant-01", "bot-02", "cv-1", "top_k=5", q),
        rb1.lookup_key("tenant-01", "bot-01", "cv-2", "top_k=5", q),
        rb1.lookup_key("tenant-01", "bot-01", "cv-1", "top_k=8", q),
        rb1.lookup_key("tenant-01", "bot-01", "cv-1", "top_k=5", rb1.query_key("x")),
    ):
        assert other != key
    assert rb1.query_key("  ") is None and rb1.query_key(None) is None
    assert rb1.lookup_key("tenant-01", "bot-01", "cv-1", "top_k=5", None) is None
    assert rb1.lookup_key("tenant-01", "bot-01", "cv-1", None, q) is None
    # the key never holds the query text itself
    assert "synthetic" not in key


def test_no_cross_tenant_reuse_from_equal_text(rb1):
    rows = [
        _lookup(rb1, "r0", 0),
        _lookup(rb1, "r1", 5, tenant="tenant-02"),
    ]
    out = _cache(rb1, rows).replay(_ctx())
    assert out["status"].tolist() == ["miss", "miss"]


# --- fees ----------------------------------------------------------------------


def test_fee_avoided_equals_recorded_fee_of_skipped_lookups(rb1):
    rows = [
        _lookup(rb1, "r0", 0, fee=0.002),
        _lookup(rb1, "r1", 5, fee=0.0025),  # recorded amount, not a constant
    ]
    out = _cache(rb1, rows).replay(_ctx())
    assert out["status"].tolist() == ["miss", "hit"]
    assert out["fee_avoided"].tolist() == [0.0, 0.0025]


def test_multi_query_fee_attribution_has_no_double_count(rb1):
    assert rb1.attribute_fees(2, [0.002, 0.002]) == (0.002, 0.002)
    assert rb1.attribute_fees(3, [0.002, 0.002]) is None  # count mismatch
    assert rb1.attribute_fees(2, [0.002, 0.004]) is None  # mapping unknown
    assert rb1.attribute_fees(0, []) == ()
    rows = [
        _lookup(rb1, "r0", 0, pos=0, query="q one"),
        _lookup(rb1, "r0", 0, pos=1, query="q two"),
        _lookup(rb1, "r1", 5, pos=0, query="q one"),
        _lookup(rb1, "r1", 5, pos=1, query="q two"),
        _lookup(rb1, "r1", 5, pos=2, query="q three"),
    ]
    cache = _cache(rb1, rows)
    out = cache.apply(_req(2), _ctx())
    assert out.loc["r1", "retrieval_lookups_skipped"] == 2
    assert out.loc["r1", "retrieval_fee_avoided"] == pytest.approx(0.004)
    assert out.loc["r1", "block_fees"] == pytest.approx(0.006)
    assert out.loc["r0", "retrieval_fee_avoided"] == 0.0


def test_unsupported_fee_is_never_skipped(rb1):
    rows = [_lookup(rb1, "r0", 0), _lookup(rb1, "r1", 5, fee=float("nan"))]
    out = _cache(rb1, rows).replay(_ctx())
    assert out.loc[1, "status"] == "ineligible"
    assert out.loc[1, "reason"] == "fee_unattributed"
    assert out.loc[1, "fee_avoided"] == 0.0


def test_llm_cost_blocks_unchanged(rb1):
    rows = [_lookup(rb1, "r0", 0), _lookup(rb1, "r1", 5)]
    req = _req(2)
    out = _cache(rb1, rows).apply(req, _ctx())
    assert out.index.equals(req.index)
    assert out["block_token_cost"].equals(req["block_token_cost"])
    assert "served_from_cache" not in out  # a retrieval cache is not an answer cache
    assert out["retrieval_reused"].tolist() == [False, True]
    assert req["block_fees"].tolist() == [0.01, 0.01]  # input not mutated


def test_fee_avoided_above_fee_block_is_refused(rb1):
    rows = [_lookup(rb1, "r0", 0), _lookup(rb1, "r1", 5, fee=0.05)]
    with pytest.raises(ValueError, match="fee block"):
        _cache(rb1, rows).apply(_req(2), _ctx())


# --- agreement -------------------------------------------------------------------


def test_agreement_is_overlap_with_later_real_chunk_ids(rb1):
    a, b, c = ("chunk-a", "h-a"), ("chunk-b", "h-b"), ("chunk-c", "h-c")
    assert rb1.agreement((a, b), (b, a)) == 1.0  # order ignored
    assert rb1.agreement((a, b), (a, c)) == pytest.approx(1 / 3)  # Jaccard
    assert rb1.agreement((a,), ()) == 0.0
    assert rb1.agreement((), ()) is None  # both empty: not evaluable
    rows = [
        _lookup(rb1, "r0", 0, chunks=(a, b)),
        _lookup(rb1, "r1", 5, chunks=(a, c)),  # the later real lookup
    ]
    out = _cache(rb1, rows).replay(_ctx())
    assert out.loc[1, "agreement"] == pytest.approx(1 / 3)


def test_changed_chunk_hash_is_disagreement(rb1):
    old, new = ("chunk-a", "h-a"), ("chunk-a", "h-a2")
    assert rb1.agreement((old,), (new,)) == 0.0
    assert rb1.agreement((old,), (("chunk-a", None),)) is None  # unknown, not 1
    rows = [
        _lookup(rb1, "r0", 0, chunks=(old,)),
        _lookup(rb1, "r1", 5, chunks=(new,)),
    ]
    out = _cache(rb1, rows).replay(_ctx())
    assert out.loc[1, "status"] == "hit"  # candidate reuse...
    assert out.loc[1, "agreement"] == 0.0  # ...that disagrees


# --- time --------------------------------------------------------------------------


def test_backstop_ttl_expires(rb1):
    rows = [
        _lookup(rb1, "r0", 0),
        _lookup(rb1, "r1", 60 * 24 * 3),  # 3 days later: within 7 days
        _lookup(rb1, "r2", 60 * 24 * 9),  # 9 days after the insert: expired
    ]
    out = _cache(rb1, rows, ttl=pd.Timedelta(days=7)).replay(_ctx())
    assert out["status"].tolist() == ["miss", "hit", "miss"]
    assert out.loc[2, "reason"] == "expired"


def test_no_future_lookup_populates_earlier_state(rb1):
    rows = [
        _lookup(rb1, "r1", 10),  # listed first but later in time
        _lookup(rb1, "r0", 0, t_done=T0 + pd.Timedelta(minutes=20)),
    ]
    out = _cache(rb1, rows).replay(_ctx())
    # r0 completes at minute 20, after r1 arrives at 10: no hit for either
    assert out["status"].tolist() == ["miss", "miss"]
    same = [_lookup(rb1, "r0", 0, pos=0), _lookup(rb1, "r0", 0, pos=1)]
    assert _cache(rb1, same).replay(_ctx())["status"].tolist() == ["miss", "miss"]


def test_missing_freshness_evidence_is_not_a_safe_hit(rb1):
    rows = [
        _lookup(rb1, "r0", 0, corpus_version=None),
        _lookup(rb1, "r1", 5, corpus_version=None),
    ]
    no_ttl = _cache(rb1, rows, ttl=None).replay(_ctx())
    assert no_ttl["status"].tolist() == ["ineligible", "ineligible"]
    assert no_ttl.loc[1, "reason"] == "no_freshness_evidence"
    with_ttl = _cache(rb1, rows, ttl=pd.Timedelta(days=1)).replay(_ctx())
    assert with_ttl.loc[1, "status"] == "hit"
    assert with_ttl.loc[1, "basis"] == "ttl_only"  # never "version"
    known = _cache(rb1, [_lookup(rb1, "r0", 0), _lookup(rb1, "r1", 5)], ttl=None)
    assert known.replay(_ctx()).loc[1, "basis"] == "version"


# --- guard, shadow, scope ----------------------------------------------------------


def test_guard_is_called_before_a_hit_counts(rb1):
    rows = [_lookup(rb1, "r0", 0), _lookup(rb1, "r1", 5)]
    key = rb1.lookup_key(
        "tenant-01", "bot-01", "cv-1", "top_k=5;rerank=off", rows[0]["query_key"]
    )
    guard = _guard(blocked=frozenset({versioned_key("r1", key)}))
    out = _cache(rb1, rows).replay(_ctx(guard))
    assert out.loc[1, "status"] == "guard_block"
    assert out.loc[1, "reason"] == "blocked"
    assert out.loc[1, "fee_avoided"] == 0.0
    off = _cache(rb1, rows).replay(_ctx(_guard(disabled_bots=frozenset({"bot-01"}))))
    assert off.loc[1, "reason"] == "disabled_bot"
    with pytest.raises(ValueError, match="guard"):
        _cache(rb1, rows).replay(SimpleNamespace(guard=None, seed=7))


def test_shadow_check_reported(rb1):
    a, b = ("chunk-a", "h-a"), ("chunk-b", "h-b")
    rows = [
        _lookup(rb1, "r0", 0, chunks=(a, b)),
        _lookup(rb1, "r1", 5, chunks=(a, b)),  # agrees
        _lookup(rb1, "r2", 6, chunks=(("chunk-a", None),)),  # no hash: unknown
    ]
    out = _cache(rb1, rows, shadow_rate=1.0).replay(_ctx())
    assert out["shadow"].tolist() == [False, True, True]  # hits only
    assert out["shadow_result"].tolist() == [None, "agree", "unknown"]
    summary = rb1.summarise(out)
    assert summary["shadow"] == {"sampled": 2, "agree": 1, "disagree": 0, "unknown": 1}
    none = _cache(rb1, rows, shadow_rate=0.0).replay(_ctx())
    assert not none["shadow"].any()


def test_shadow_rate_has_no_default(rb1):
    with pytest.raises(TypeError):
        rb1.RetrievalResultCache(pd.Timedelta(days=1), lookups=_frame([]))


def test_workflow_rows_never_counted(rb1):
    rows = [
        _lookup(rb1, "r0", 0),
        _lookup(rb1, "r1", 5),  # a workflow row: never looks up, never hits
        _lookup(rb1, "r2", 6),
    ]
    req = _req(3, llm_request=[True, False, True])
    out = _cache(rb1, rows).apply(req, _ctx())
    assert out.loc["r1", "retrieval_reused"] == False  # noqa: E712
    assert out.loc["r1", "retrieval_fee_avoided"] == 0.0
    assert out.loc["r1", "block_fees"] == 0.01
    assert out.loc["r2", "retrieval_reused"] == True  # noqa: E712
    with pytest.raises(ValueError, match="llm_request"):
        _cache(rb1, rows).apply(req.drop(columns="llm_request"), _ctx())


def test_summary_counts_hits_and_coverage(rb1):
    rows = [
        _lookup(rb1, "r0", 0),
        _lookup(rb1, "r1", 5),
        _lookup(rb1, "r2", 6, query=""),  # no query: unsupported
    ]
    rows[2]["query_key"] = None
    out = _cache(rb1, rows).replay(_ctx())
    s = rb1.summarise(out)
    assert s["n_lookups"] == 3
    assert s["status"] == {"hit": 1, "miss": 1, "ineligible": 1}
    assert s["reasons"]["no_query"] == 1
    assert s["fee_avoided"] == pytest.approx(0.002)
    assert s["agreement"]["n_evaluable"] == 1
    assert s["agreement"]["mean"] == 1.0
    assert s["agreement"]["share_at_least_0_9"] == 1.0


# --- free checks ---------------------------------------------------------------------


def test_repeat_rate_windows_use_only_earlier_lookups(rb1):
    rows = [
        _lookup(rb1, "r0", 0),
        _lookup(rb1, "r1", 60 * 24 * 2),  # 2 days later
        _lookup(rb1, "r2", 60 * 24 * 40, query="another"),
    ]
    rates = rb1.repeat_rates(_frame(rows), windows_days=(1, 7, 30))
    assert rates == {1: 0.0, 7: pytest.approx(1 / 3), 30: pytest.approx(1 / 3)}


def test_chunk_churn_counts_ids_with_changed_hash(rb1):
    rows = [
        _lookup(rb1, "r0", 0, chunks=(("chunk-a", "h-a"), ("chunk-b", "h-b"))),
        _lookup(rb1, "r1", 5, chunks=(("chunk-a", "h-a2"),)),
        _lookup(rb1, "r2", 6, bot="bot-02", chunks=(("chunk-z", None),)),
    ]
    churn = rb1.chunk_churn(_frame(rows)).set_index("bot")
    assert churn.loc["bot-01", "n_chunk_ids"] == 2
    assert churn.loc["bot-01", "n_changed"] == 1
    assert churn.loc["bot-02", "n_hash_unknown"] == 1
    assert churn.loc["bot-02", "n_changed"] == 0


# --- the real contract (runs once analysis/levers.py is on this branch) ---


def test_combine_carries_retrieval_columns_and_keeps_rows_eligible(rb1):
    levers = pytest.importorskip("metis_auto.analysis.levers")
    rows = [_lookup(rb1, "r0", 0), _lookup(rb1, "r1", 5)]
    ctx = levers.ReplayContext(
        period_bounds={}, price_table={}, catalogue={}, seed=7, guard=_guard()
    )
    cache = _cache(rb1, rows)
    assert isinstance(cache, levers.StepVersion)
    out = levers.combine(_req(2), cache, None, None, ctx)
    assert out["served_from_cache"].tolist() == [False, False]
    assert out["retrieval_reused"].tolist() == [False, True]
    assert out.loc["r1", "block_fees"] == pytest.approx(0.008)


# --- loader --------------------------------------------------------------------------


def test_lookups_from_rag_keeps_only_fingerprints(rb1):
    import json

    from metis_auto.analysis.text_features import fingerprint

    raw = json.dumps(
        [
            {
                "query": "Synthetic Query",
                "relevantChunks": [
                    {"id": "chunk-a", "content": " synthetic text a "},
                    {"id": "chunk-b", "content": None},
                    {"content": "no id"},
                ],
            },
            {"query": "", "relevantChunks": []},
            "not a dict",
        ]
    )
    out = rb1.lookups_from_rag(raw)
    assert [o[0] for o in out] == [0, 1]
    pos, qkey, chunks = out[0]
    assert qkey == rb1.query_key("synthetic query")
    assert chunks == (
        ("chunk-a", fingerprint("synthetic text a")),
        ("chunk-b", None),
        (rb1.NO_CHUNK_ID, None),
    )
    assert out[1] == (1, None, ())
    for bad in (None, "", "{not json", json.dumps({"query": "x"})):
        assert rb1.lookups_from_rag(bad) == []
