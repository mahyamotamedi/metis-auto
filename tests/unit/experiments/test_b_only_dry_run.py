"""I-1 (B-only dry run) helpers, experiments/pipelines/b-only-dry-run/run.py.
SYNTHETIC only. Traces: plan I-1, Review Focus 1, ADR-0036 (units)."""

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

RUN = "pipelines/b-only-dry-run/run.py"
D = Decimal


@pytest.fixture(scope="module")
def i1(load_experiment):
    return load_experiment(RUN)


class Recorder:
    """A routing version that records the input tokens it was given."""

    name = "route.recorder"
    step = "routing"

    def __init__(self):
        self.seen = None

    def apply(self, req, ctx):
        self.seen = req["a_bill_inputTokens"].tolist()
        return req.assign(routed_model=req["bot_provider_model"])


def test_routing_after_context_reprices_the_reduced_tokens(i1):
    req = pd.DataFrame(
        {
            "bot_provider_model": ["m-incl", "m-sep"],
            "a_bill_inputTokens": [1000.0, 1000.0],
            "a_bill_cachedInputTokens": [300.0, 300.0],
            "ctx_tokens_saved": [900.0, 200.0],
        }
    )
    rec = Recorder()
    step = i1.PostContextRouting(rec, cached_separately=frozenset({"m-sep"}))
    assert step.step == "routing" and step.name == "route.recorder.post-context"
    out = step.apply(req, ctx=None)
    # Inside input: never below the cached tokens; separate: never below 0.
    assert rec.seen == [300.0, 800.0]
    assert out["a_bill_inputTokens"].tolist() == [300.0, 800.0]
    rec2 = Recorder()
    i1.PostContextRouting(rec2, cached_separately=frozenset()).apply(
        req.drop(columns="ctx_tokens_saved"), ctx=None
    )
    assert rec2.seen == [1000.0, 1000.0]


def test_units_decide_which_steps_a_baseline_combines(i1):
    cells = i1.unit_cells()
    # R-B3 prices as_logged at implied recorded rates (ADR-0046 point 5).
    assert cells["as_logged"]["combined_steps"] == ("cache", "context", "routing")
    assert cells["as_logged"]["not_computed"] == {}
    for key in ("premium_gpt_5_5", "todays_models", "best_single_cheap"):
        assert cells[key]["combined_steps"] == ("context", "routing")
        assert "cache" in cells[key]["not_computed"]
        assert "not computed in these units" in cells[key]["not_computed"]["cache"]


def test_sum_rule_allows_equality_and_flags_excess(i1):
    assert i1.sum_rule(D("3"), [D("1"), D("2")]) == {
        "combined": D("3"),
        "standalone_sum": D("3"),
        "holds": True,
        "equal": True,
    }
    assert i1.sum_rule(D("2.5"), [D("1"), D("2")])["equal"] is False
    assert i1.sum_rule(D("3.5"), [D("1"), D("2")])["holds"] is False


def test_overlaps_count_requests_touched_by_two_steps(i1):
    after = pd.DataFrame(
        {
            "retrieval_reused": [True, True, False, False, np.nan],
            "ctx_tokens_saved": [5.0, 0.0, 5.0, 0.0, np.nan],
            "route_reason": ["moved", "moved", "moved", "kept", np.nan],
            "llm_request": [True] * 5,
        }
    )
    o = i1.overlaps(after)
    assert o == {
        "cache": 2,
        "context": 2,
        "routing": 3,
        "cache&context": 1,
        "cache&routing": 2,
        "context&routing": 2,
        "all_three": 1,
    }


def test_retrieval_cache_rows_are_never_served_from_cache(i1):
    ok = pd.DataFrame(
        {"retrieval_reused": [True, False], "served_from_cache": [False, False]}
    )
    assert i1.retrieval_rows_not_served(ok) is True
    bad = ok.assign(served_from_cache=[True, False])
    assert i1.retrieval_rows_not_served(bad) is False
