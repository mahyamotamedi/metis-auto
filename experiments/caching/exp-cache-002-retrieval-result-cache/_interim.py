"""INTERIM stand-in for S-3 (``analysis/replay_scope.py``,
``analysis/baselines_full.py``, ``config/evaluation/sprint.toml``), which exist
on no branch yet (checked 2026-11-02). Pipeline B's run script uses it for R-B1,
R-B2 and F-2 only. Every result built with it carries ``INTERIM_LABEL`` in its
assumptions and stays out of any final comparison. Switch-over:
docs/experiments/pipeline_b_interim_contracts.md (final plan S-3; QA-REPRO, H-3;
ADR-XXXX (retrieval-result-cache-accounting)).

- ``llm_request``: False for workflow bots (``bot_provider_name == "workflow"``,
  which have empty billing). An unknown provider stays unknown (``<NA>``).
- ``assign_periods``: tune March to July 2026, report August to October 2026,
  **by whole session**. The session's period is the one holding its first
  request time (user time, else answer time). Timestamps are naive (Q-06).
  A report row whose duplicate family (``u_h_norm``) first appeared in a tune
  session gets ``family_leak = True``, so it can be left out of report numbers.
  Tune decisions read tune rows only, so no report session or family can inform
  them.
- Baselines: only ``as_logged`` (recorded cost units) is computed. The other
  three need repricing, which is S-3's job (``NOT_COMPUTED`` says why).
"""

from __future__ import annotations

import pandas as pd

INTERIM_LABEL = "interim split/baselines, not the shared implementation"
WORKFLOW_PROVIDER = "workflow"
PERIODS = {
    "tune": (pd.Timestamp("2026-03-01"), pd.Timestamp("2026-07-31 23:59:59.999999")),
    "report": (
        pd.Timestamp("2026-08-01"),
        pd.Timestamp("2026-10-31 23:59:59.999999"),
    ),
}
COMPUTED_BASELINES = ("as_logged",)
NOT_COMPUTED = {
    "premium_gpt_5_5": "needs repricing at gpt-5.5 prices (S-3)",
    "todays_models": "needs repricing at each logged model's price (S-3)",
    "best_single_cheap": "needs repricing at the cheapest callable model (S-3)",
}


def llm_request(req: pd.DataFrame) -> pd.Series:
    """Nullable boolean: False for workflow bots, ``<NA>`` when unknown."""
    name = req["bot_provider_name"].astype("string").str.lower()
    return (name != WORKFLOW_PROVIDER).astype("boolean").rename("llm_request")


def assign_periods(req: pd.DataFrame) -> pd.DataFrame:
    """``period`` (``tune``, ``report``, ``outside``) and ``family_leak`` per
    row, aligned with ``req.index``."""
    t = req["u_timestamp"].fillna(req["a_timestamp"])
    start = t.groupby(req["session_id"]).transform("min")
    period = pd.Series("outside", index=req.index, dtype=object)
    for name, (lo, hi) in PERIODS.items():
        period[(start >= lo) & (start <= hi)] = name
    family = req["u_h_norm"]
    tune_families = set(family[(period == "tune") & family.notna()])
    leak = (period == "report") & family.isin(tune_families) & family.notna()
    return pd.DataFrame({"period": period, "family_leak": leak.astype(bool)})
