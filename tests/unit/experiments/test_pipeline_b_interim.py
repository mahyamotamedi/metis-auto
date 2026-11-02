"""Pipeline B's interim scope stand-in (until S-3's ``replay_scope.py`` exists).
SYNTHETIC fixtures only."""

import pandas as pd
import pytest

INTERIM = "caching/exp-cache-002-retrieval-result-cache/_interim.py"


@pytest.fixture(scope="module")
def interim(load_experiment):
    return load_experiment(INTERIM)


def _req(rows):
    cols = ["session_id", "u_timestamp", "a_timestamp", "u_h_norm", "bot_provider_name"]
    return pd.DataFrame(rows, columns=cols, index=[f"r{i}" for i in range(len(rows))])


def ts(s):
    return pd.Timestamp(s)


def test_workflow_rows_are_not_llm_requests(interim):
    req = _req(
        [
            ("s1", ts("2026-04-01"), ts("2026-04-01"), "f1", "workflow"),
            ("s1", ts("2026-04-01"), ts("2026-04-01"), "f1", "Workflow"),
            ("s2", ts("2026-04-01"), ts("2026-04-01"), "f1", "openai"),
            ("s3", ts("2026-04-01"), ts("2026-04-01"), "f1", None),
        ]
    )
    llm = interim.llm_request(req)
    assert llm.iloc[:3].tolist() == [False, False, True]
    assert llm.isna().iloc[3]  # unknown bot: unknown, never False


def test_period_follows_the_whole_session(interim):
    req = _req(
        [
            ("s1", ts("2026-07-31 23:00"), ts("2026-07-31 23:01"), "f1", "x"),
            ("s1", ts("2026-08-01 01:00"), ts("2026-08-01 01:01"), "f2", "x"),
            ("s2", None, ts("2026-08-02"), "f3", "x"),
            ("s3", ts("2026-02-10"), ts("2026-02-10"), "f4", "x"),
        ]
    )
    out = interim.assign_periods(req)
    assert out["period"].tolist() == ["tune", "tune", "report", "outside"]
    assert out.index.equals(req.index)


def test_report_rows_of_a_tune_family_are_flagged(interim):
    req = _req(
        [
            ("s1", ts("2026-05-01"), ts("2026-05-01"), "fam-a", "x"),
            ("s2", ts("2026-09-01"), ts("2026-09-01"), "fam-a", "x"),
            ("s3", ts("2026-09-02"), ts("2026-09-02"), "fam-b", "x"),
            ("s4", ts("2026-09-03"), ts("2026-09-03"), None, "x"),
        ]
    )
    out = interim.assign_periods(req)
    assert out["family_leak"].tolist() == [False, True, False, False]


def test_interim_label_and_baselines_are_explicit(interim):
    assert "interim" in interim.INTERIM_LABEL
    assert interim.COMPUTED_BASELINES == ("as_logged",)
    assert set(interim.NOT_COMPUTED) == {
        "premium_gpt_5_5",
        "todays_models",
        "best_single_cheap",
    }
