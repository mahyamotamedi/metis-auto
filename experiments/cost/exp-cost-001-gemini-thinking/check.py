"""EXP-COST-001: does hidden "thinking" inflate the output of gemini-2.5-flash?
(sprint plan F-1; FR-ACCT-01, H-7, QA-REPRO; ADR-0042/0043 stretch trigger.)

Free, offline, on the logged requests. For each answered request the ratio is

    billed output tokens / (answer characters / chars_per_token)

that is, what the provider billed for output against what the visible answer
should have cost. A model that bills much more than its visible answer needs is
spending tokens on something the answer does not show (hidden reasoning). The
characters-to-tokens step uses an assumed slope (the EDA's turn-0 slope, a
**hypothetical reconstruction**: it was fitted on input, and tokenizers differ),
so the ratio is a signal for comparing models on the same slope, not a measure.

Rules:
- only rows of the given model label count; rows with an unknown billed output or
  an unknown or zero answer length are left out and counted (never read as 0);
- "no cached tokens logged" is a **logging gap**, never "no caching": a model whose
  cached-token field is empty on every row is reported as
  ``logging_gap_not_no_caching``;
- the verdict compares the model's median ratio with the median of the other
  high-volume models' medians, and its p90 (the tail) with theirs; the factor 1.5
  is a **placeholder** threshold. A model can look ordinary at the median and
  still carry a heavy tail of requests that bill far more than the answer needs.

Pure over a frame; aggregates only (model labels are public names; no ID or text).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

EVIDENCE = "hypothetical reconstruction"
FACTOR = 1.5
TAIL_RULE = (
    "heavy tail looks likely when the model's p90 ratio is at least "
    f"{FACTOR}x the median of the other high-volume models' p90 "
    "(placeholder threshold, not tuned)"
)
RULE = (
    "hidden thinking looks likely when the model's median ratio is at least "
    f"{FACTOR}x the median of the other high-volume models' medians "
    "(placeholder threshold, not tuned)"
)


def _stats(
    rows: pd.DataFrame, label: str, chars_per_token: float, left_out: int
) -> dict[str, Any]:
    answer_tokens = rows["a_n_chars"] / chars_per_token
    ratio = rows["a_bill_outputTokens"] / answer_tokens
    cached = rows["a_bill_cachedInputTokens"]
    return {
        "model": label,
        "n": int(len(rows)),
        "n_left_out": int(left_out),
        "median_ratio": float(ratio.median()) if len(ratio) else None,
        "p90_ratio": float(np.percentile(ratio, 90)) if len(ratio) else None,
        "cached_tokens": "logged"
        if cached.notna().any()
        else "logging_gap_not_no_caching",
    }


def _usable(req: pd.DataFrame) -> pd.Series:
    llm = req["llm_request"].astype(bool)
    return (
        llm
        & req["a_bill_outputTokens"].notna()
        & req["a_n_chars"].notna()
        & (req["a_n_chars"] > 0)
    )


def gemini_thinking(
    req: pd.DataFrame,
    *,
    model_label: str,
    chars_per_token: float,
    min_n: int = 1000,
    top: int = 5,
) -> dict[str, Any]:
    """The ratio's median and p90 for ``model_label`` against the other
    high-volume models (the ``top`` by usable rows with at least ``min_n``)."""
    if not chars_per_token or chars_per_token <= 0:
        raise ValueError("chars_per_token must be positive")
    ok = _usable(req)
    llm = req["llm_request"].astype(bool)
    label = req["bot_provider_model"].eq(model_label)
    mine = req[ok & label]
    out_mine = _stats(
        mine, model_label, chars_per_token, int((llm & label).sum() - len(mine))
    )
    others = []
    counts = req[ok & ~label]["bot_provider_model"].value_counts()
    for name, n in counts.items():
        if len(others) >= top:
            break
        if n < min_n:
            continue
        rows = req[ok & req["bot_provider_model"].eq(name)]
        left = int((llm & req["bot_provider_model"].eq(name)).sum() - len(rows))
        others.append(_stats(rows, str(name), chars_per_token, left))
    base = [o["median_ratio"] for o in others if o["median_ratio"] is not None]
    other_median = float(np.median(base)) if base else None
    tails = [o["p90_ratio"] for o in others if o["p90_ratio"] is not None]
    other_p90 = float(np.median(tails)) if tails else None
    mine_median = out_mine["median_ratio"]
    likely = bool(
        mine_median is not None
        and other_median is not None
        and other_median > 0
        and mine_median >= FACTOR * other_median
    )
    heavy = bool(
        out_mine["p90_ratio"] is not None
        and other_p90 is not None
        and other_p90 > 0
        and out_mine["p90_ratio"] >= FACTOR * other_p90
    )
    return {
        "evidence": EVIDENCE,
        "chars_per_token": float(chars_per_token),
        "model": out_mine,
        "others": others,
        "others_median_of_medians": other_median,
        "others_median_p90": other_p90,
        "verdict": {
            "hidden_thinking_looks_likely": likely,
            "rule": RULE,
            "heavy_tail_looks_likely": heavy,
            "tail_rule": TAIL_RULE,
        },
    }
