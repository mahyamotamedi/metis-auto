"""Popular-question cache, ``exp-cache-002`` (final plan R-A1; H-8, ADR-0016).

Every frame here is [SYNTHETIC]: invented labels such as ``q-1`` and ``ans-1``
stand in for grouping hashes; there is no dataset content. The candidate is
loaded from ``experiments/`` with the repository's loader
(``wiring.experiments.load_candidate``), never imported. B's ``CacheGuard`` is
replaced by a fake that satisfies ``levers.CacheGuardLike``, and C's scope step by
``llm_request`` and ``period`` columns written into the frames.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from metis_auto.analysis.cache_guard import CacheGuard
from metis_auto.analysis.lever_result import LeverResult, build_manifest
from metis_auto.analysis.levers import (
    ReplayContext,
    StepVersion,
    combine,
    summarise_slices,
)
from metis_auto.settings import StrategySettings, StrategySlot
from metis_auto.wiring.experiments import load_candidate

ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT_DIR = ROOT / "experiments" / "caching" / "exp-cache-002-popular-question"
BASE = pd.Timestamp("2026-08-01")  # naive, like the logged times (Q-06)
NEW_COLUMNS = {"pq_eligible", "pq_admitted_keys_day", "pq_answer_agrees"}


@pytest.fixture(scope="module")
def cache_class():
    spec = StrategySettings(
        slot=StrategySlot.CANDIDATE_INDEX,  # unused for a file; no lever slot yet
        file="version.py",
        object="PopularQuestionCache",
    )
    return load_candidate(spec, EXPERIMENT_DIR, ROOT / "experiments")


@pytest.fixture
def make(cache_class):
    def _make(
        variant="first_turn",
        window_days=90,
        min_count=3,
        min_sessions=2,
        key_version="pq-v1",
    ):
        return cache_class(
            window_days=window_days,
            min_count=min_count,
            min_sessions=min_sessions,
            variant=variant,
            key_version=key_version,
        )

    return _make


class FakeGuard:
    """[SYNTHETIC] stand-in for B's ``CacheGuard``: approval list and blocklist."""

    def __init__(self, approved: set[str] | None, blocked: set[str]) -> None:
        self.approved, self.blocked = approved, blocked
        self.calls: list[tuple[str, str]] = []

    def allows(self, key: str, bot: str) -> bool:
        self.calls.append((key, bot))
        if key in self.blocked:
            return False
        return self.approved is None or key in self.approved


def ctx(guard=None) -> ReplayContext:
    return ReplayContext(
        period_bounds={},
        price_table={"version": "prices-synthetic"},
        catalogue={},
        seed=7,
        guard=guard,
    )


def row(day, session, q="q-1", a="ans-1", **over) -> dict:
    """[SYNTHETIC] one eligible first-turn LLM request on day ``day``."""
    t = BASE + pd.Timedelta(days=day, hours=10, minutes=over.pop("minute", 0))
    r = {
        "llm_request": True,
        "period": "report",
        "bot_id": "bot-a",
        "session_id": session,
        "user_id": "owner-a",
        "u_timestamp": t,
        "a_timestamp": t + pd.Timedelta(seconds=30),
        "u_content_state": "text",
        "a_content_state": "text",
        "a_finish_reason": "STOP",
        "u_att_n": 0,
        "a_tool_n_calls": 0,
        "a_action_types": "",
        "bot_memory_enabled": False,
        "a_rag_state": "null",
        "a_rag_n_queries": 0,
        "n_prior_msgs": 1,  # only the request's own user message precedes it
        "u_h_norm": q,
        "a_h_norm": a,
        "bot_ins_h_exact": "ins-a",
        "block_fees": 0.002,
        "block_token_cost": 0.01,
    }
    r.update(over)
    return r


def frame(*rows: dict) -> pd.DataFrame:
    return pd.DataFrame(list(rows), index=range(100, 100 + len(rows)))


def popular(day=0, q="q-1", answers=("ans-1", "ans-1", "ans-1")) -> list[dict]:
    """[SYNTHETIC] three occurrences of one question in three sessions."""
    return [row(day, f"s-{q}-{i}", q=q, a=a) for i, a in enumerate(answers)]


def hits(cache, req, guard=None) -> list[bool]:
    return cache.apply(req, ctx(guard))["served_from_cache"].tolist()


# --- from the plan ---------------------------------------------------------------


def test_nightly_set_uses_only_previous_days(make):
    cache = make(window_days=90)
    req = frame(
        row(9, "probe-9"),  # before the occurrences: no look-ahead
        *popular(day=10),
        row(10, "probe-10", minute=30),  # same day: the set is built nightly
        row(100, "probe-100"),  # d - 90 = day 10, inside the window
    )
    assert hits(cache, req) == [False, False, False, False, False, True]
    out = cache.apply(req, ctx())
    assert out["pq_admitted_keys_day"].tolist() == [0, 0, 0, 0, 0, 1]

    late = frame(*popular(day=10), row(101, "probe-101"))  # window starts day 11
    assert hits(cache, late) == [False, False, False, False]


def test_window_over_180_days_is_rejected(make):
    make(window_days=180)
    make(window_days=1)
    for bad in (181, 0, -1):
        with pytest.raises(ValueError, match="window_days"):
            make(window_days=bad)
    with pytest.raises(ValueError, match="variant"):
        make(variant="any")


def test_requires_three_occurrences_in_two_sessions(make):
    cache = make(min_count=3, min_sessions=2)
    two = frame(row(0, "s1"), row(0, "s2"), row(5, "probe"))
    assert hits(cache, two)[-1] is False
    one_session = frame(row(0, "s1"), row(0, "s1"), row(0, "s1"), row(5, "probe"))
    assert hits(cache, one_session)[-1] is False
    enough = frame(row(0, "s1"), row(0, "s1"), row(0, "s2"), row(5, "probe"))
    assert hits(cache, enough)[-1] is True


def test_memory_and_rag_requests_ineligible(make):
    cache = make()
    req = frame(
        *popular(day=0),
        row(5, "p-ok"),
        row(5, "p-memory", bot_memory_enabled=True),
        row(5, "p-memory-unknown", bot_memory_enabled=np.nan),
        row(5, "p-rag", a_rag_state="ok", a_rag_n_queries=1),
        row(5, "p-rag-unknown", a_rag_state="malformed"),
    )
    out = cache.apply(req, ctx())
    assert out["served_from_cache"].tolist()[3:] == [True, False, False, False, False]
    assert out["pq_eligible"].tolist()[3:] == [True, False, False, False, False]


def test_guard_blocks_unapproved_and_blocked_keys(make):
    cache = make()
    req = frame(
        *popular(q="q-ok"),
        *popular(q="q-blocked"),
        *popular(q="q-unapproved"),
        row(5, "p1", q="q-ok"),
        row(5, "p2", q="q-blocked"),
        row(5, "p3", q="q-unapproved"),
    )
    keys = cache.keys(req)
    k_ok, k_blocked = keys.iloc[0], keys.iloc[3]
    guard = FakeGuard(approved={k_ok, k_blocked}, blocked={k_blocked})
    assert hits(cache, req, guard)[-3:] == [True, False, False]
    assert {bot for _, bot in guard.calls} == {"bot-a"}
    assert hits(cache, req, None)[-3:] == [True, True, True]  # no guard, no limit


def test_most_typical_answer_choice_uses_answer_hash_mode(make):
    cache = make()
    req = frame(
        *popular(answers=("ans-1", "ans-2", "ans-1")),
        row(5, "p-same", a="ans-1"),
        row(5, "p-other", a="ans-2"),
    )
    out = cache.apply(req, ctx())
    assert out["served_from_cache"].tolist()[-2:] == [True, True]
    assert out["pq_answer_agrees"].tolist()[-2:] == [True, False]
    assert out["pq_answer_agrees"].iloc[:3].isna().all()  # only hits get one

    # Tie on count: the most recently seen answer wins, whatever the row order.
    tie = frame(
        row(0, "s1", a="ans-3", minute=1),
        row(0, "s2", a="ans-1", minute=2),
        row(0, "s3", a="ans-2", minute=3),
        row(5, "probe", a="ans-2"),
    )
    shuffled = tie.iloc[[3, 1, 0, 2]]
    for f in (tie, shuffled):
        assert cache.apply(f, ctx())["pq_answer_agrees"].loc[103] is True
    # Tie on count and time: the smallest answer hash wins.
    same_time = frame(
        row(0, "s1", a="ans-c"),
        row(0, "s2", a="ans-a"),
        row(0, "s3", a="ans-b"),
        row(5, "probe", a="ans-a"),
    )
    assert cache.apply(same_time, ctx())["pq_answer_agrees"].loc[103] is True


def test_hit_labelled_candidate(make):
    cache = make()
    assert cache.evidence_class == "simulation"
    assert cache.correctness_state == "unmeasured"
    req = frame(*popular(), row(5, "probe"))
    out = cache.apply(req, ctx())
    result = LeverResult(
        lever_id=cache.lever_id,
        step=cache.step,
        version=cache.version,
        n_requests=len(req),
        n_eligible=int(out["pq_eligible"].sum()),
        baseline="as_logged",
        baseline_cost={},
        saving={},
        slices=summarise_slices(req, out),
        evidence_class=cache.evidence_class,
        correctness_state=cache.correctness_state,
        assumptions=cache.assumptions,
        manifest=build_manifest(
            {"window_days": 90},
            ctx(),
            code_commit="unknown",
            python_version="3.13.0",
            created_at=datetime(2026, 11, 2, tzinfo=UTC),
        ),
    )
    assert result.slices["llm_only"]["n_cache_hits"] == 1
    assert any("candidate" in a for a in cache.assumptions)


# --- mine ------------------------------------------------------------------------


def test_keys_carry_the_guard_key_version(make):
    """ADR-0034: a guarded key is "<key_version>|<body>", or the guard refuses it."""
    req = frame(*popular(), row(5, "probe"))
    keys = make(key_version="pq-v1").keys(req)
    assert keys.str.startswith("pq-v1|").all()
    assert make(key_version="pq-v2").keys(req).iloc[0] != keys.iloc[0]

    def guard(version: str) -> CacheGuard:
        empty: frozenset[str] = frozenset()
        return CacheGuard(
            approved=None, blocked=empty, disabled_bots=empty, key_version=version
        )

    cache = make(key_version="pq-v1")
    assert hits(cache, req, guard("pq-v1"))[-1] is True
    assert hits(cache, req, guard("pq-v2"))[-1] is False  # refused: key_version


def test_served_source_is_the_latest_window_row_with_the_stored_answer(make):
    """In memory only: which logged row supplied each served answer (K-1 sheet)."""
    cache = make()
    req = frame(
        row(0, "s1", a="ans-1", minute=1),
        row(0, "s2", a="ans-2", minute=2),
        row(0, "s3", a="ans-1", minute=3),  # latest row with the mode answer
        row(5, "probe"),
        row(5, "other", q="q-2"),
    )
    sources = cache.served_sources(req, ctx())
    assert sources.to_dict() == {103: 102}
    out = cache.apply(req, ctx())
    assert set(sources.index) == set(out.index[out["served_from_cache"]])


def test_key_version_is_validated(make):
    for bad in ("", "pq|v1"):
        with pytest.raises(ValueError, match="key_version"):
            make(key_version=bad)


def test_first_turn_variant_never_admits_or_hits_requests_with_history(make):
    later = [row(0, f"s{i}", n_prior_msgs=3) for i in range(3)]
    req = frame(*later, row(5, "probe-later", n_prior_msgs=3), row(5, "probe-first"))
    first = make("first_turn").apply(req, ctx())
    assert first["served_from_cache"].tolist() == [False] * 5  # never admitted
    assert first["pq_eligible"].tolist() == [False] * 4 + [True]

    admitted = frame(*popular(), row(5, "probe-later", n_prior_msgs=3))
    assert hits(make("first_turn"), admitted)[-1] is False
    assert hits(make("all_turns"), admitted)[-1] is True
    assert hits(make("all_turns"), req)[-2:] == [True, True]


def test_all_turns_variant_is_labelled_upper_bound_in_assumptions(make):
    upper, headline = make("all_turns"), make("first_turn")
    assert upper.lever_id == "cache.popular_question.all_turns"
    assert headline.lever_id == "cache.popular_question.first_turn"
    assert any(
        "upper bound, unsafe for follow-up questions" in a for a in upper.assumptions
    )
    assert not any("upper bound" in a for a in headline.assumptions)
    assert all(len(a) <= 300 for a in upper.assumptions + headline.assumptions)


def test_admission_counts_only_eligible_requests(make):
    cache = make()
    with_attachment = frame(
        row(0, "s1"), row(0, "s2"), row(0, "s3", u_att_n=1), row(5, "probe")
    )
    assert hits(cache, with_attachment)[-1] is False
    truncated = frame(
        row(0, "s1"), row(0, "s2"), row(0, "s3", a_finish_reason="LENGTH"), row(5, "p")
    )
    assert hits(cache, truncated)[-1] is False
    assert hits(cache, frame(*popular(), row(5, "probe")))[-1] is True


def test_funnel_reports_a_count_per_step(make):
    req = frame(
        row(0, "s1"),
        row(0, "s2", u_content_state="blank"),
        row(0, "s3", a_tool_n_calls=2),
        row(0, "s4", llm_request=False),
        row(0, "s5", bot_memory_enabled=True),
        row(0, "s6", a_rag_n_queries=2, a_rag_state="ok"),
        row(0, "s7", n_prior_msgs=5),
    )
    steps = make("first_turn").funnel(req)
    assert list(steps.columns) == ["step", "requests"]
    assert steps["step"].tolist() == [
        "all requests",
        "has_user_text",
        "answer_text_and_STOP",
        "no_attachments",
        "no_tools",
        "no_actions",
        "timestamps_valid",
        "key_known",
        "llm_request",
        "no_memory",
        "no_rag",
        "first_turn",
    ]
    assert steps["requests"].tolist() == [7, 6, 6, 6, 5, 5, 5, 5, 4, 3, 2, 1]
    assert make("all_turns").funnel(req)["step"].iloc[-1] == "no_rag"


def test_hit_rows_zero_both_cost_blocks_and_others_unchanged(make):
    req = frame(*popular(), row(5, "probe"), row(5, "other", q="q-2"))
    out = make().apply(req, ctx())
    assert out.index.equals(req.index)
    assert out["served_from_cache"].tolist() == [False, False, False, True, False]
    assert out.loc[103, ["block_fees", "block_token_cost"]].tolist() == [0.0, 0.0]
    pd.testing.assert_frame_equal(out[req.columns].drop(index=103), req.drop(103))
    unchanged = req.columns.difference(["block_fees", "block_token_cost"])
    pd.testing.assert_series_equal(
        out.loc[103, unchanged], req.loc[103, unchanged], check_names=False
    )
    assert req["block_fees"].iloc[3] == 0.002  # the input is not modified


def test_works_inside_combine_and_workflow_rows_untouched(make):
    workflow = row(5, "wf", llm_request=False, block_fees=np.nan)
    workflow["block_token_cost"] = np.nan
    req = frame(*popular(), row(5, "probe"), workflow)
    out = combine(req, make(), None, None, ctx())
    assert out["served_from_cache"].tolist() == [False, False, False, True, False]
    pd.testing.assert_series_equal(
        out.loc[104, req.columns], req.loc[104], check_names=False
    )
    slices = summarise_slices(req, out)
    assert slices["all"]["n_requests"] == 5
    assert slices["llm_only"]["n_requests"] == 4
    assert slices["llm_only"]["n_cache_hits"] == 1


def test_satisfies_step_version_protocol(make):
    for variant in ("first_turn", "all_turns"):
        cache = make(variant)
        assert isinstance(cache, StepVersion)
        assert cache.step == "cache"
        assert cache.name == cache.lever_id


def test_no_text_or_raw_key_column_in_output(make):
    req = frame(*popular(), row(5, "probe"), row(5, "other", q="q-2"))
    cache = make()
    out = cache.apply(req, ctx())
    added = set(out.columns) - set(req.columns)
    assert added <= NEW_COLUMNS | {"served_from_cache"}
    inputs = set(cache.keys(req)) | set(req["u_h_norm"]) | set(req["a_h_norm"])
    for col in added:
        assert out[col].map(lambda v: isinstance(v, str)).sum() == 0, col
        assert not set(out[col].astype(str)) & inputs, col
