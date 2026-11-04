"""EXP-COST-001, the free Gemini thinking check (sprint plan F-1). Frames are
[SYNTHETIC]; the ratio is a hypothetical reconstruction (characters to tokens by
an assumed slope)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
NAN = np.nan


@pytest.fixture(scope="module")
def gt():
    name = "gemini_thinking_check_under_test"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "experiments/cost/exp-cost-001-gemini-thinking/check.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(name, None)


def frame(rows):
    out = pd.DataFrame(
        rows,
        columns=["bot_provider_model", "a_bill_outputTokens", "a_n_chars", "cached"],
    )
    out["llm_request"] = True
    out["a_bill_cachedInputTokens"] = out.pop("cached")
    return out


def test_ratio_is_billed_output_tokens_over_answer_tokens_estimate(gt):
    # 400 chars at 4 chars/token = 100 answer tokens; 300 billed -> ratio 3
    req = frame([("g", 300, 400, 0.0), ("g", 200, 400, 0.0), ("g", 100, 400, 0.0)])
    out = gt.gemini_thinking(req, model_label="g", chars_per_token=4.0)
    assert out["model"]["n"] == 3
    assert out["model"]["median_ratio"] == pytest.approx(2.0)
    assert out["model"]["p90_ratio"] == pytest.approx(2.8)
    assert out["evidence"] == "hypothetical reconstruction"
    assert out["chars_per_token"] == 4.0


def test_only_rows_with_the_given_model_label_are_used(gt):
    req = frame(
        [("g", 300, 400, 0.0), ("other", 100, 400, 0.0), ("other", 100, 400, 0.0)]
    )
    out = gt.gemini_thinking(req, model_label="g", chars_per_token=4.0, min_n=1)
    assert out["model"]["n"] == 1
    assert out["model"]["median_ratio"] == pytest.approx(3.0)
    assert [m["model"] for m in out["others"]] == ["other"]
    assert out["others"][0]["median_ratio"] == pytest.approx(1.0)


def test_no_cached_tokens_logged_reports_logging_gap_not_no_caching(gt):
    req = frame([("g", 300, 400, NAN), ("g", 200, 400, NAN)])
    out = gt.gemini_thinking(req, model_label="g", chars_per_token=4.0)
    assert out["model"]["cached_tokens"] == "logging_gap_not_no_caching"
    logged = frame([("g", 300, 400, 5.0), ("g", 200, 400, 0.0)])
    assert (
        gt.gemini_thinking(logged, model_label="g", chars_per_token=4.0)["model"][
            "cached_tokens"
        ]
        == "logged"
    )


def test_rows_without_a_known_answer_length_or_billing_are_left_out(gt):
    req = frame(
        [
            ("g", 300, 400, 0.0),
            ("g", NAN, 400, 0.0),
            ("g", 300, 0, 0.0),
            ("g", 300, NAN, 0.0),
        ]
    )
    out = gt.gemini_thinking(req, model_label="g", chars_per_token=4.0)
    assert out["model"]["n"] == 1 and out["model"]["n_left_out"] == 3


def test_verdict_compares_the_model_with_the_others(gt):
    rows = [("g", 400, 400, 0.0)] * 5 + [("o", 100, 400, 0.0)] * 5
    out = gt.gemini_thinking(frame(rows), model_label="g", chars_per_token=4.0, min_n=1)
    assert out["verdict"]["hidden_thinking_looks_likely"] is True
    flat = frame([("g", 100, 400, 0.0)] * 5 + [("o", 100, 400, 0.0)] * 5)
    assert not gt.gemini_thinking(flat, model_label="g", chars_per_token=4.0, min_n=1)[
        "verdict"
    ]["hidden_thinking_looks_likely"]
    assert "placeholder" in out["verdict"]["rule"]


def test_chars_per_token_must_be_positive(gt):
    with pytest.raises(ValueError, match="chars_per_token"):
        gt.gemini_thinking(
            frame([("g", 1, 4, 0.0)]), model_label="g", chars_per_token=0
        )


def test_output_has_no_ids_or_text(gt):
    import json

    out = gt.gemini_thinking(
        frame([("g", 300, 400, 0.0)]), model_label="g", chars_per_token=4.0
    )
    text = json.dumps(out)
    for key in ("session_id", "user_id", "bot_id", "message"):
        assert key not in text


def test_a_heavy_tail_is_reported_even_when_the_median_is_ordinary(gt):
    """Most answers bill like the others, but one in five bills ten times more:
    the median verdict stays False while the tail signal is True."""
    mine = [("g", 100, 400, 0.0)] * 8 + [("g", 1000, 400, 0.0)] * 2
    others = [("o", 100, 400, 0.0)] * 10
    out = gt.gemini_thinking(
        frame(mine + others), model_label="g", chars_per_token=4.0, min_n=1
    )
    assert out["verdict"]["hidden_thinking_looks_likely"] is False
    assert out["verdict"]["heavy_tail_looks_likely"] is True
    assert out["others_median_p90"] == pytest.approx(1.0)
    assert "tail" in out["verdict"]["tail_rule"]
