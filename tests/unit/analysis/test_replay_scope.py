"""Replay scope, split and tenant cap (final plan S-3; Review Focus 2 and 5).

Every frame here is [SYNTHETIC]: invented labels and numbers, no dataset content.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from metis_auto.analysis.levers import ReplayContext
from metis_auto.analysis.replay_scope import (
    bot_sufficiency,
    cap_tenant_share,
    period_bounds_from_config,
    scope,
    split_by_session,
)

SPRINT_TOML = Path(__file__).resolve().parents[3] / "config/evaluation/sprint.toml"
TS = pd.Timestamp


def ctx(min_n: int | None = None) -> ReplayContext:
    return ReplayContext(
        period_bounds={
            "tune": (TS("2026-03-01"), TS("2026-07-31 23:59:59.999999")),
            "report": (TS("2026-08-01"), TS("2026-10-31 23:59:59.999999")),
        },
        price_table={"version": "prices-synthetic"},
        catalogue={},
        seed=7,
        min_n=min_n,
    )


def frame(**cols) -> pd.DataFrame:
    n = len(next(iter(cols.values())))
    base = {
        "a_timestamp": [TS("2026-05-01")] * n,
        "bot_provider_name": ["synthetic-provider"] * n,
    }
    return pd.DataFrame(base | cols)


# --- period ---


def test_period_unknown_when_timestamp_missing():
    req = frame(a_timestamp=[TS("2026-05-01"), pd.NaT, TS("2026-09-01")])
    out = scope(req, ctx())
    assert out["period"].tolist() == ["tune", "unknown", "report"]
    assert "period" not in req  # a copy, not an edit


def test_boundaries_inclusive():
    stamps = [
        TS("2026-03-01 00:00:00"),  # tune start
        TS("2026-07-31 23:59:59.999999"),  # tune end
        TS("2026-08-01 00:00:00"),  # report start
        TS("2026-10-31 23:59:59.999999"),  # report end
        TS("2026-02-28 23:59:59.999999"),  # before both
        TS("2026-11-01 00:00:00"),  # after both
    ]
    out = scope(frame(a_timestamp=stamps), ctx())
    assert out["period"].tolist() == [
        "tune",
        "tune",
        "report",
        "report",
        "unknown",
        "unknown",
    ]


def test_config_dates_cover_whole_days():
    bounds = period_bounds_from_config(
        {"tune": {"start": "2026-03-01", "end": "2026-07-31"}}
    )
    start, end = bounds["tune"]
    assert start == TS("2026-03-01")
    assert end == TS("2026-07-31 23:59:59.999999")


def test_overlapping_periods_are_refused():
    with pytest.raises(ValueError, match="overlap"):
        period_bounds_from_config(
            {
                "tune": {"start": "2026-03-01", "end": "2026-08-01"},
                "report": {"start": "2026-08-01", "end": "2026-10-31"},
            }
        )


def test_sprint_toml_periods_load_and_do_not_overlap():
    cfg = tomllib.loads(SPRINT_TOML.read_text(encoding="utf-8"))
    bounds = period_bounds_from_config(cfg["periods"])
    assert set(bounds) == {"tune", "report"}
    assert bounds["tune"][1] < bounds["report"][0]
    assert cfg["sample"]["tenant_cap"] == 0.35
    assert cfg["cache_guard"]["shadow_rate"] == 0.01


# --- llm_request ---


def test_workflow_rows_are_not_llm_requests():
    req = frame(bot_provider_name=["workflow", "google", "openai_chat_completion"])
    out = scope(req, ctx())
    assert out["llm_request"].dtype == bool
    assert out["llm_request"].tolist() == [False, True, True]


def test_unknown_provider_is_not_false():
    req = frame(bot_provider_name=["google", None])
    with pytest.raises(ValueError, match="unknown"):
        scope(req, ctx())


# --- split ---


def split_frame() -> pd.DataFrame:
    """[SYNTHETIC] Session s1 starts in tune and runs over the boundary. Family
    (b1, f-greet) has rows in both periods: 3 in tune, 1 in report. Family
    (b2, f-tie) has 1 row on each side (a tie). Row 9 has no user text."""
    return pd.DataFrame(
        {
            "session_id": ["s1", "s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9"],
            "bot_id": ["b1", "b1", "b1", "b1", "b1", "b2", "b2", "b3", "b3", "b3"],
            "u_h_norm": [
                "f-a",
                "f-b",
                "f-greet",
                "f-greet",
                "f-greet",
                "f-tie",
                "f-tie",
                "f-c",
                "f-greet",
                None,
            ],
            "a_order": [0, 1, 0, 0, 0, 0, 0, 0, 0, 0],
            "a_timestamp": [
                TS("2026-07-31 23:50"),
                TS("2026-08-01 00:10"),  # same session, next period
                TS("2026-04-01"),
                TS("2026-05-01"),
                TS("2026-08-15"),
                TS("2026-06-01"),
                TS("2026-09-01"),
                TS("2026-09-02"),
                TS("2026-03-02"),
                pd.NaT,
            ],
            "bot_provider_name": ["google"] * 10,
        },
        index=range(100, 110),
    )


def test_no_session_or_duplicate_family_straddles_the_split():
    req = scope(split_frame(), ctx())
    split = split_by_session(req, seed=7)
    assert split.index.equals(req.index)
    assert set(split.unique()) <= {"tune", "report", "unknown", "excluded"}
    sides = split.isin(["tune", "report"])
    by_session = split[sides].groupby(req.loc[sides, "session_id"]).nunique()
    assert (by_session == 1).all()
    has_text = sides & req["u_h_norm"].notna()
    family = req.loc[has_text, "bot_id"] + "\x1f" + req.loc[has_text, "u_h_norm"]
    assert (split[has_text].groupby(family).nunique() == 1).all()
    # A whole session takes the period of its first request.
    assert split.loc[[100, 101]].tolist() == ["tune", "tune"]
    # A family goes to the side holding most of its rows; the rest is excluded.
    assert split.loc[[102, 103]].tolist() == ["tune", "tune"]
    assert split.loc[104] == "excluded"
    # A family is per bot: the same text under bot b3 is its own family.
    assert split.loc[108] == "tune"
    # No timestamp in the session: unknown, never silently tune.
    assert split.loc[109] == "unknown"


def test_seed_only_breaks_ties():
    req = scope(split_frame(), ctx())
    splits = [split_by_session(req, seed=s) for s in range(20)]
    tie = [105, 106]
    others = req.index.difference(tie)
    for s in splits:
        assert s.loc[others].equals(splits[0].loc[others])
        assert sorted(s.loc[tie]) in (["excluded", "tune"], ["excluded", "report"])
    assert len({tuple(s.loc[tie]) for s in splits}) == 2
    assert split_by_session(req, seed=3).equals(split_by_session(req, seed=3))


# --- sufficiency ---


def test_bot_with_one_request_is_insufficient():
    req = pd.DataFrame({"bot_id": ["b1", "b2", "b2", "b3", "b3", "b3"]})
    for min_n in (None, 0, 1):
        status = bot_sufficiency(req, min_n)
        assert status["b1"] == "insufficient"
        assert status["b2"] == "sufficient"
    status = bot_sufficiency(req, 3)
    assert status.to_dict() == {
        "b1": "insufficient",
        "b2": "insufficient",
        "b3": "sufficient",
    }


# --- tenant cap ---


def tenant_frame() -> pd.DataFrame:
    """[SYNTHETIC] One tenant has 60% of rows, like the real top user's 41.6%."""
    counts = {"u1": 60, "u2": 15, "u3": 10, "u4": 8, "u5": 5, "u6": 2}
    users = [u for u, n in counts.items() for _ in range(n)]
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "user_id": users,
            "session_id": [f"{u}-s{i % 7}" for i, u in enumerate(users)],
            "a_order": rng.integers(0, 5, len(users)),
        }
    )


def test_sample_caps_any_tenant_at_35_percent():
    req = tenant_frame()
    out = cap_tenant_share(req, 0.35, seed=7)
    shares = out["user_id"].value_counts(normalize=True)
    assert shares.max() <= 0.35
    assert out.index.isin(req.index).all()
    # Only the over-cap tenant loses rows; the others keep all of theirs.
    kept = out["user_id"].value_counts()
    full = req["user_id"].value_counts()
    assert (kept.drop("u1") == full.drop("u1")).all()
    assert kept["u1"] < full["u1"]
    # Deterministic for a seed.
    assert out.index.equals(cap_tenant_share(req, 0.35, seed=7).index)


def test_cap_impossible_with_too_few_tenants():
    req = pd.DataFrame({"user_id": ["u1", "u2"], "session_id": ["a", "b"]})
    with pytest.raises(ValueError, match="cannot"):
        cap_tenant_share(req, 0.35, seed=7)
