"""exp-ctx-003 reranker cut (final plan R-A2), a context step version.

Every frame here is [SYNTHETIC]: ``m-1``-style labels stand in for message IDs,
``h-1`` for text fingerprints, and ``text ...`` strings for chunk and question
text. The scorer is injected, so no model is loaded. The version is loaded by
file path through ``wiring.experiments.load_candidate``, as scripts load it.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from metis_auto.analysis.levers import ReplayContext, combine
from metis_auto.settings import StrategySettings, StrategySlot
from metis_auto.wiring.experiments import load_candidate

ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments" / "context" / "exp-ctx-003-reranker-cut"
SLOPE = 0.5  # [SYNTHETIC] tokens per chunk character, easy arithmetic


def _load(obj: str):
    spec = StrategySettings(
        slot=StrategySlot.CANDIDATE_INDEX, file="version.py", object=obj
    )
    return load_candidate(spec, EXP, ROOT / "experiments")


@pytest.fixture(scope="module")
def RerankerCut():
    return _load("RerankerCut")


@pytest.fixture(scope="module")
def lexical_overlap():
    return _load("lexical_overlap")


def ctx() -> ReplayContext:
    return ReplayContext(
        period_bounds={},
        price_table={
            "version": "prices-synthetic",
            "per_tokens": 1_000_000,
            "prices": [
                {"price_ref": "p-syn", "input": 1.0, "cached_input": 0.1, "output": 2.0}
            ],
        },
        catalogue={"models": [{"model_id": "syn-model", "price_ref": "p-syn"}]},
        seed=7,
    )


def chunks(rows: list[tuple]) -> pd.DataFrame:
    """[SYNTHETIC] (message, chunk_id, h_exact, n_chars, relevancy[, content])."""
    cols = ["message_id", "chunk_id", "h_exact", "n_chars", "relevancy", "content"]
    rows = [r if len(r) == 6 else (*r, f"text {r[2]}") for r in rows]
    return pd.DataFrame(rows, columns=cols)


def six(message: str = "m-1") -> list[tuple]:
    """[SYNTHETIC] six unique chunks, best first; chars 100..600."""
    scores = (0.9, 0.8, 0.7, 0.6, 0.5, 0.4)
    return [
        (message, f"c-{i}", f"h-{message}-{i}", 100 * i, s)
        for i, s in enumerate(scores, start=1)
    ]


def requests(*messages: str, **over) -> pd.DataFrame:
    """[SYNTHETIC] one RAG LLM request per message; 10,000 input tokens."""
    n = len(messages)
    data = {
        "ai_message_id": list(messages),
        "session_id": [f"s-{i}" for i in range(n)],
        "llm_request": True,
        "a_rag_state": "ok",
        "bot_provider_model": "syn-model",
        "a_bill_inputTokens": 10_000.0,
        "a_bill_cachedInputTokens": 0.0,
        "a_bill_outputTokens": 100.0,
        "block_fees": 0.002,
        "block_token_cost": 0.05,
    } | over
    return pd.DataFrame(data, index=pd.RangeIndex(10, 10 + n))


def cut(RerankerCut, rows, req=None, **kw):
    params = {"floor": 0, "threshold": None, "top_k": None} | kw
    scorer = params.pop("scorer", None)
    version = RerankerCut(
        scorer,
        params.pop("floor"),
        params.pop("threshold"),
        params.pop("top_k"),
        chunks=chunks(rows),
        tokens_per_char=SLOPE,
        **params,
    )
    req = requests("m-1") if req is None else req
    return version.apply(req, ctx())


def todays_models(RerankerCut, req, out):
    """Before and after blocks at the logged model's price."""
    return RerankerCut.baseline_frames(
        req,
        out,
        ctx(),
        baseline="todays_models",
        premium_model="syn-model",
        cheap_model="syn-model",
    )


# --- the curve ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("top_k", "threshold", "floor", "removed_chars"),
    [
        (None, None, 0, 0),
        (5, None, 0, 600),
        (3, None, 0, 400 + 500 + 600),
        (None, 0.65, 0, 400 + 500 + 600),
        (4, 0.75, 0, 300 + 400 + 500 + 600),
        (None, 0.85, 0, 200 + 300 + 400 + 500 + 600),
        (None, 0.85, 3, 400 + 500 + 600),
    ],
)
def test_curve_is_tokens_saved_against_top_k_and_threshold(
    RerankerCut, top_k, threshold, floor, removed_chars
):
    out = cut(RerankerCut, six(), top_k=top_k, threshold=threshold, floor=floor)
    assert out["rc_cut_chars"].iloc[0] == removed_chars
    assert out["rc_saved_tokens"].iloc[0] == pytest.approx(removed_chars * SLOPE)
    assert out["rc_raw_chunk_tokens"].iloc[0] == pytest.approx(2100 * SLOPE)


def test_minimum_chunk_floor(RerankerCut):
    out = cut(RerankerCut, six(), threshold=0.99, floor=3)
    assert out["rc_n_kept"].iloc[0] == 3  # threshold alone would keep none
    assert out["rc_cut_chars"].iloc[0] == 400 + 500 + 600  # the three best stay
    few = cut(RerankerCut, six()[:2], top_k=1, floor=3)
    assert few["rc_n_kept"].iloc[0] == 2 and few["rc_cut_chars"].iloc[0] == 0


def test_scorer_injected_so_tests_need_no_model(RerankerCut):
    calls = []

    def by_length(query: str, texts: list[str]) -> list[float]:
        calls.append((query, list(texts)))
        return [float(len(t)) for t in texts]  # [SYNTHETIC] longer = better

    rows = [
        ("m-1", "c-1", "h-1", 100, 0.9, "text a"),
        ("m-1", "c-2", "h-2", 200, 0.1, "text aaaa"),
        ("m-1", "c-3", "h-3", 300, 0.5, "text aa"),
    ]
    out = cut(RerankerCut, rows, top_k=1, scorer=by_length, queries={"m-1": "question"})
    assert calls == [("question", ["text a", "text aaaa", "text aa"])]
    assert out["rc_cut_chars"].iloc[0] == 100 + 300  # kept only the longest text


def test_curve_is_monotone_in_top_k(RerankerCut):
    rng = np.random.default_rng(3)
    rows = []
    for m in range(40):
        for i in range(int(rng.integers(0, 20))):
            score = float(rng.random()) if rng.random() > 0.1 else math.nan
            rows.append(
                (
                    f"m-{m}",
                    f"c-{i}",
                    f"h-{m}-{i % 15}",
                    int(rng.integers(1, 900)),
                    score,
                )
            )
    req = requests(*[f"m-{m}" for m in range(40)])
    saved = [
        cut(RerankerCut, rows, req, top_k=k, threshold=0.3, floor=3)[
            "rc_saved_tokens"
        ].sum()
        for k in (12, 10, 8, 5, 3)
    ]
    assert saved == sorted(saved)  # a smaller top_k never saves fewer tokens


# --- duplicates (S-6 runs first) ------------------------------------------------------


def test_duplicates_are_collapsed_before_ranking_and_not_counted_as_saving(
    RerankerCut,
):
    rows = [
        ("m-1", "c-1", "h-1", 100, 0.5),
        ("m-1", "c-9", "h-1", 100, 0.95),  # same text, other ID: a copy of h-1
        ("m-1", "c-2", "h-2", 200, 0.9),
        ("m-1", "c-2", "h-2b", 300, 0.2),  # same ID, changed text: not a copy
        ("m-1", "c-3", "h-3", 400, 0.8),
        ("m-1", "c-3", "h-3", 400, 0.1),  # copy of h-3
    ]
    out = cut(RerankerCut, rows, top_k=2).iloc[0]
    assert out["rc_n_chunks"] == 6 and out["rc_n_unique"] == 4
    # unique scores: h-1 0.95 (max of copies), h-2 0.9, h-3 0.8, h-2b 0.2;
    # top 2 unique keep h-1 and h-2, so h-3 and h-2b are cut
    assert out["rc_dup_chars"] == 100 + 400
    assert out["rc_cut_chars"] == 400 + 300
    assert out["rc_dedup_tokens"] == pytest.approx(500 * SLOPE)
    assert out["rc_saved_tokens"] == pytest.approx(700 * SLOPE)  # dedup not in it


def test_a_row_without_text_fingerprint_is_never_a_duplicate(RerankerCut):
    rows = [
        ("m-1", "c-1", None, 100, 0.9),
        ("m-1", "c-1", None, 100, 0.9),
    ]
    out = cut(RerankerCut, rows).iloc[0]
    assert out["rc_n_unique"] == 2 and out["rc_dup_chars"] == 0


# --- unknown, eligibility, untouched columns -----------------------------------------


def test_missing_score_is_kept_and_counted_never_zero(RerankerCut):
    rows = six()[:4] + [("m-1", "c-x", "h-x", 999, math.nan)]
    out = cut(RerankerCut, rows, top_k=2, threshold=0.75).iloc[0]
    assert out["rc_n_unscored"] == 1
    assert out["rc_cut_chars"] == 300 + 400  # the unscored 999 chars stay
    assert out["rc_n_kept"] == 3


def test_no_chunks_means_no_change(RerankerCut):
    req = requests("m-1", "m-2")
    out = cut(RerankerCut, six("m-1"), req, top_k=3)
    other = out.loc[out["ai_message_id"].eq("m-2")].iloc[0]
    assert not other["rc_eligible"]
    assert other["rc_saved_tokens"] == 0 and other["rc_cut_chars"] == 0
    before, after = todays_models(RerankerCut, req, out)
    assert after.loc[other.name, "block_token_cost"] == pytest.approx(
        before.loc[other.name, "block_token_cost"]
    )


def test_requests_outside_eligibility_are_untouched(RerankerCut):
    req = requests(
        "m-1",
        "m-2",
        "m-3",
        llm_request=[True, False, True],
        a_rag_state=["ok", "ok", "malformed"],
        served_from_cache=[True, False, False],
    )
    rows = six("m-1") + six("m-2") + six("m-3")
    out = cut(RerankerCut, rows, req, top_k=3)
    assert not out["rc_eligible"].any()
    assert out["rc_saved_tokens"].eq(0).all()
    before, _ = todays_models(RerankerCut, req, out)
    assert before.loc[~req["llm_request"], "block_token_cost"].isna().all()  # workflow


def test_combine_skips_cache_hits_and_workflow_rows(RerankerCut):
    class Hit:
        name, step = "cache.synthetic", "cache"

        def apply(self, req, ctx):
            out = req.copy()
            out["served_from_cache"] = out["ai_message_id"].eq("m-1")
            return out

    req = requests("m-1", "m-2", "m-3", llm_request=[True, True, False])
    version = RerankerCut(
        None,
        0,
        None,
        3,
        chunks=chunks(six("m-1") + six("m-2") + six("m-3")),
        tokens_per_char=SLOPE,
    )
    out = combine(req, Hit(), version, None, ctx())
    saved = out.set_index("ai_message_id")["rc_saved_tokens"]
    assert saved["m-2"] == pytest.approx(1500 * SLOPE)
    assert pd.isna(saved["m-1"]) and pd.isna(saved["m-3"])  # never given to it


def test_nothing_outside_the_chunk_tokens_changes(RerankerCut):
    req = requests("m-1")
    out = cut(RerankerCut, six(), req, top_k=3)
    pd.testing.assert_frame_equal(out[req.columns], req)  # recorded cost unchanged
    added = set(out.columns) - set(req.columns)
    assert added and all(c.startswith("rc_") for c in added)


# --- tokens and repriced cost ---------------------------------------------------------


def test_saving_comes_from_uncached_input_after_dedup(RerankerCut):
    # 1,000 uncached tokens of room: dedup takes 300 (600 chars), the cut 700 of
    # its 900 wanted (1,800 chars); the rest is not counted.
    rows = [*six(), ("m-1", "c-1b", "h-m-1-1", 100, 0.9)]
    rows += [("m-1", "c-2b", "h-m-1-2", 200, 0.8), ("m-1", "c-3b", "h-m-1-3", 300, 0.7)]
    req = requests("m-1", a_bill_inputTokens=1_100.0, a_bill_cachedInputTokens=100.0)
    out = cut(RerankerCut, rows, req, top_k=2).iloc[0]
    assert out["rc_dup_chars"] == 100 + 200 + 300
    assert out["rc_dedup_tokens"] == pytest.approx(300)
    assert out["rc_cut_chars"] == 300 + 400 + 500 + 600
    assert out["rc_saved_tokens"] == pytest.approx(1000 - 300)


def test_cost_is_repriced_at_the_logged_model_and_kept_apart(RerankerCut):
    req = requests("m-1")
    out = cut(RerankerCut, six(), req, top_k=3)
    before, after = todays_models(RerankerCut, req, out)
    raw = (10_000 * 1.0 + 100 * 2.0) / 1e6
    assert before["block_token_cost"].iloc[0] == pytest.approx(raw)
    assert after["block_token_cost"].iloc[0] == pytest.approx(raw - 750 * 1.0 / 1e6)
    assert out["block_token_cost"].iloc[0] == 0.05  # recorded block untouched


def test_unpriced_model_cost_is_unknown_not_zero(RerankerCut):
    req = requests("m-1", bot_provider_model="unpriced-model")
    out = cut(RerankerCut, six(), req, top_k=3)
    assert out["rc_saved_tokens"].iloc[0] == pytest.approx(750)
    before, after = todays_models(RerankerCut, req, out)
    assert pd.isna(before["block_token_cost"].iloc[0])
    assert pd.isna(after["block_token_cost"].iloc[0])


def test_score_mass_kept_is_reported(RerankerCut):
    out = cut(RerankerCut, six(), top_k=3).iloc[0]
    assert out["rc_score_total"] == pytest.approx(3.9)
    assert out["rc_score_kept"] == pytest.approx(2.4)


# --- lexical scorer and settings -----------------------------------------------------


def test_lexical_overlap_is_share_of_question_words_after_normalize_safe(
    lexical_overlap,
):
    # [SYNTHETIC] Arabic yeh/kaf and Persian forms normalise to the same word.
    scores = lexical_overlap(
        "Order KITAB كتاب علي",
        ["order کتاب", "nothing here", "ORDER kitab کتاب علی"],
    )
    assert scores == pytest.approx([0.5, 0.0, 1.0])


def test_lexical_overlap_without_question_words_is_missing(lexical_overlap):
    assert all(math.isnan(s) for s in lexical_overlap("  ?! ", ["text a", "text b"]))


def test_text_scorer_without_question_is_unscored_not_zero(RerankerCut):
    out = cut(
        RerankerCut,
        six(),
        top_k=3,
        scorer=lambda q, t: [1.0] * len(t),
        queries={},
    ).iloc[0]
    assert out["rc_n_unscored"] == 6 and out["rc_cut_chars"] == 0


@pytest.mark.parametrize(
    ("floor", "threshold", "top_k"),
    [(-1, None, 3), (3, None, 0), (3, math.nan, 3), (True, None, 3), (3, None, 2.5)],
)
def test_bad_settings_are_refused(RerankerCut, floor, threshold, top_k):
    with pytest.raises(ValueError):
        RerankerCut(
            None, floor, threshold, top_k, chunks=chunks(six()), tokens_per_char=SLOPE
        )


def test_lever_id_names_the_scorer(RerankerCut, lexical_overlap):
    observed = RerankerCut(
        None, 3, None, 8, chunks=chunks(six()), tokens_per_char=SLOPE
    )
    lexical = RerankerCut(
        lexical_overlap,
        3,
        None,
        8,
        chunks=chunks(six()),
        tokens_per_char=SLOPE,
        queries={},
    )
    assert observed.lever_id == "context.reranker_cut.observed_relevancy"
    assert lexical.lever_id == "context.reranker_cut.lexical_overlap"
    assert observed.name == observed.lever_id and observed.step == "context"
    assert observed.evidence_class == "hypothetical reconstruction"
    assert lexical.evidence_class == "heuristic"
