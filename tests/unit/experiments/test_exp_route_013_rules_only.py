"""exp-route-013, rules-only mode (sprint final Stage 2; ADR-0047 point 4,
A-118, A-121). With ``router.mode = "off"`` the decision router calls nothing:
its tier comes from the gate and the rule-based fallback of the real domain
policy. Every frame and text here is [SYNTHETIC]; no dataset content.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from metis_auto.settings import load_settings
from metis_auto.wiring.from_settings import pipeline_config

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "experiments/routing/exp-route-013-decision-router" / "rules_only.py"


@pytest.fixture(scope="module")
def ro():
    spec = importlib.util.spec_from_file_location("exp_route_013_rules_only", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cfg():
    loaded = load_settings(environ={}, dotenv=None, runtime=None)
    return pipeline_config(loaded)


def frame(**rows) -> pd.DataFrame:
    n = len(next(iter(rows.values())))
    base = {
        "user_message_id": [f"m{i}" for i in range(n)],
        "u_lang": ["fa"] * n,
        "u_n_chars": [30] * n,
        "u_att_n": [0] * n,
        "turn": [0] * n,
    }
    return pd.DataFrame(base | rows)


def flags(**rows) -> pd.DataFrame:
    n = len(next(iter(rows.values())))
    base = {
        "message_id": [f"m{i}" for i in range(n)],
        "has_code": [False] * n,
        "has_coding_intent": [False] * n,
        "is_greeting": [False] * n,
    }
    return pd.DataFrame(base | rows)


# --- flags: text read in memory, none kept ------------------------------------------


def test_flags_table_has_no_text_column(ro, cfg):
    out = ro.derive_flags(
        ["a", "b", "c"],
        ["hello", "def f():\n    return 1\n", "how do I fix this python error"],
        cfg.features,
    )
    assert list(out.columns) == [
        "message_id",
        "has_code",
        "has_coding_intent",
        "is_greeting",
        "label_state",
    ]
    assert out["is_greeting"].tolist() == [True, False, False]
    assert bool(out["has_code"].iloc[1])
    assert bool(out["has_coding_intent"].iloc[2])
    for col in ("has_code", "has_coding_intent", "is_greeting"):
        assert out[col].dtype == bool


def test_empty_or_missing_text_is_unknown_not_false(ro, cfg):
    out = ro.derive_flags(["a", "b"], [None, ""], cfg.features)
    assert out["label_state"].tolist() == ["unknown", "unknown"]
    ok = ro.derive_flags(["a"], ["hello"], cfg.features)
    assert ok["label_state"].tolist() == ["ok"]


# --- tiers: the real domain policy, row by row --------------------------------------


def test_gate_and_rules_give_the_documented_tiers(ro, cfg):
    req = frame(
        u_n_chars=[10, 10, 10, 10, 3000, 10, 10],
        u_att_n=[0, 0, 0, 1, 0, 0, 0],
        turn=[0, 0, 0, 0, 0, 0, 9],
    )
    fl = flags(
        is_greeting=[True, False, False, False, False, False, False],
        has_code=[False, True, False, False, False, False, False],
        has_coding_intent=[False, False, True, False, False, False, False],
    )
    fl["label_state"] = "ok"
    tiers = ro.rules_only_tiers(req, fl, cfg)
    # greeting 0, code 1, coding intent 1, attachment 1, long message 1,
    # plain short message: the safe tier (1); deep session: rule tier 1
    assert tiers.tolist() == [0, 1, 1, 1, 1, 1, 1]


def test_plain_message_without_a_matching_rule_takes_the_safe_tier(ro, cfg):
    tiers = ro.rules_only_tiers(
        frame(u_n_chars=[30]), _ok(flags(has_code=[False])), cfg
    )
    assert tiers.tolist() == [cfg.routing.decision_router.safe_tier]


def test_unknown_flags_give_no_tier(ro, cfg):
    fl = flags(has_code=[False, False])
    fl["label_state"] = ["ok", "unknown"]
    tiers = ro.rules_only_tiers(frame(u_n_chars=[30, 30]), fl, cfg)
    assert tiers.iloc[0] == 1 and np.isnan(tiers.iloc[1])


def test_message_without_a_flags_row_has_no_tier(ro, cfg):
    fl = _ok(flags(has_code=[False]))
    tiers = ro.rules_only_tiers(frame(u_n_chars=[30, 30]), fl, cfg)
    assert np.isnan(tiers.iloc[1])


def test_unknown_attachment_count_is_not_assumed_zero(ro, cfg):
    req = frame(u_att_n=[np.nan])
    tiers = ro.rules_only_tiers(req, _ok(flags(has_code=[False])), cfg)
    # unknown never satisfies a rule (P-6); the safe tier decides
    assert tiers.tolist() == [cfg.routing.decision_router.safe_tier]


def test_tiers_match_the_domain_policy_for_every_distinct_row(ro, cfg):
    """The cached-by-combination speed-up gives the same answer as calling the
    real policy once per row."""
    rng = np.random.default_rng(3)
    n = 60
    req = frame(
        u_n_chars=rng.integers(1, 4000, n).tolist(),
        u_att_n=rng.integers(0, 2, n).tolist(),
        turn=rng.integers(0, 12, n).tolist(),
    )
    fl = _ok(
        flags(
            has_code=(rng.random(n) < 0.2).tolist(),
            has_coding_intent=(rng.random(n) < 0.2).tolist(),
            is_greeting=(rng.random(n) < 0.2).tolist(),
        )
    )
    fast = ro.rules_only_tiers(req, fl, cfg)
    slow = ro.rules_only_tiers(req, fl, cfg, cache=False)
    assert fast.tolist() == slow.tolist()


def test_no_router_backend_is_needed_or_called(ro, cfg):
    """Rules-only: the policy gets no decision result, so no backend exists to
    call (ADR-0047 point 4)."""
    assert ro.NO_BACKEND_NOTE
    import ast

    tree = ast.parse(PATH.read_text(encoding="utf-8"))
    imported = {
        (n.module or "") if isinstance(n, ast.ImportFrom) else a.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in (n.names if isinstance(n, ast.Import) else [n])
    }
    for name in imported:
        top = name.split(".")[0]
        assert top not in {"httpx", "openai", "requests", "urllib", "socket"}, name
        assert not name.startswith(
            ("metis_auto.adapters", "metis_auto.wiring.routers", "metis_auto.ports")
        ), name


def test_hosted_router_must_be_off(ro, cfg):
    loaded = load_settings(environ={}, dotenv=None, runtime=None)
    ro.require_offline(loaded.settings)  # defaults: mode off, nothing approved
    bad = loaded.settings.model_copy(
        update={"router": loaded.settings.router.model_copy(update={"mode": "hosted"})}
    )
    with pytest.raises(SystemExit, match="router.mode"):
        ro.require_offline(bad)


def _ok(fl: pd.DataFrame) -> pd.DataFrame:
    fl = fl.copy()
    fl["label_state"] = "ok"
    return fl
