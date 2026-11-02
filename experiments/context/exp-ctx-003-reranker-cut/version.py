"""Reranker cut: keep only the best retrieved chunks of a request (exp-ctx-003).

Final plan R-A2; traces H-2, X5 (retrieved-context trimming), FR-CTX-02,
FR-CTX-03, QA-PERF. A *candidate* context step version for the full-data lever
replay (ADR-0031): it lives here, outside ``metis_auto``, and is loaded only by
scripts and tests through ``wiring.experiments``. It is a **token-sizing
curve, not a quality result**: removing a chunk can remove the one the answer
needed, and answer quality is not measured.

**S-6 runs first.** Inside each request, chunk rows are first collapsed with
the rule of S-6 (``exp-ctx-001-within-message-dedup``, Pipeline C; read on
2026-11-02 from ``origin/context-within-message-dedup``): a row is a duplicate
when an earlier row of the same message has the same ``h_exact``; the first
copy is kept; ``chunk_id`` is ignored (two IDs with one text are copies, one ID
with two texts is not); a row without ``h_exact`` is never a duplicate. A
unique chunk's score is the maximum of its copies' scores (missing only if all
are missing). The characters dedup removes belong to S-6 and are reported
apart (``rc_dedup_tokens``), never in this version's saving.

**Cut.** On the unique chunks of a request, ranked by score (ties by first
position): keep the ``top_k`` best (``None`` = no limit), drop those under
``threshold`` (``None`` = none), but keep at least ``floor`` chunks in all. A
chunk without a score is always kept and counted (``rc_n_unscored``), never
treated as 0. ``scorer=None`` uses the platform's own ``relevancy`` (observed
platform score; higher is more relevant, chunks are sent best-first per query,
checked 2026-11-02). A text scorer ``scorer(question, chunk_texts) -> scores``
is called once per request with its unique chunk texts and needs ``content``
in ``chunks`` and the question text in ``queries`` (by ``ai_message_id``, in
memory only); a request without a question is unscored.

**Tokens.** Characters x ``tokens_per_char`` (EDA ``recon.t0rag.coef_rag``,
*hypothetical reconstruction*), taken from the **uncached** input only, as S-6
does (``baselines_full.lower_uncached_input`` on S-6's branch): the cut's
saving is what dedup + cut remove minus what dedup alone removes, both capped
at ``input - cached``. Effective input adds cached tokens back for the models
in ``cached_separately`` (Review Focus 3).

**Cost (ADR-0038).** ``apply`` changes no cost. ``RerankerCut.baseline_frames``
prices the cut for each of the four baselines, as S-6b does: the three repriced
baselines with ``baselines_full.repriced_row_costs`` (price-file units, tier
chosen again by the new input, no fees), ``as_logged`` with each model's implied
input rate (recorded units; no rate is unknown, never zero; fees never change).

Eligible: an LLM request (``llm_request``) not served from cache, with
``a_rag_state == "ok"`` and chunk rows. Every other row keeps zero counts and
savings; workflow rows get no cost. ``apply`` returns a copy with the same
index; it adds only ``rc_*`` columns (counts, characters, tokens and scores
summed per request). No ID, hash or text leaves memory.
"""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Callable, Mapping

import numpy as np
import pandas as pd

from metis_auto.analysis.baselines_full import (
    REPRICED_KEYS,
    lower_uncached_input,
    repriced_row_costs,
    token_counts,
)
from metis_auto.analysis.levers import BLOCKS, ReplayContext, block_column
from metis_auto.analysis.text_features import normalize_safe

Scorer = Callable[[str, list[str]], list[float]]
OBSERVED = "observed_relevancy"
VERSION = "rc-v1"

COUNT_COLUMNS = (
    "rc_n_chunks",
    "rc_n_unique",
    "rc_n_unscored",
    "rc_n_kept",
    "rc_raw_chars",
    "rc_dup_chars",
    "rc_cut_chars",
)
TOKEN_COLUMNS = ("rc_raw_chunk_tokens", "rc_dedup_tokens", "rc_saved_tokens")
SCORE_COLUMNS = ("rc_score_total", "rc_score_kept")
SAVING_UNKNOWN = "rc_saving_unknown"

_COMMON = (
    "Token sizing, not a quality result: removing a chunk can remove the one the "
    "answer needed; answer quality is not measured (FR-CTX-03).",
    "S-6 (within-message dedup, Pipeline C) runs first: exact copies (same h_exact) "
    "are collapsed before ranking; their tokens are S-6's, not counted here.",
    "Tokens = removed chunk characters x 0.3384 tokens per character (EDA "
    "recon.t0rag.coef_rag, hypothetical reconstruction), from uncached input only.",
    "One result per baseline; recorded and repriced cost are never mixed, and each "
    "result states its unit in a 'Unit:' line (ADR-0036, ADR-0038).",
    "A chunk without a score is kept and counted, never treated as 0; the floor "
    "keeps at least that many unique chunks per request.",
    "The real bge-reranker-v2-m3 run (cut-first item a) was not done.",
)
_OBSERVED = (
    "Scorer: the platform's own relevancy column (observed platform score; most "
    "bots use the platform's reranker, top_k 6 per query).",
)
_LEXICAL = (
    "Scorer: heuristic word overlap of the normalised user message with each "
    "chunk (normalize_safe, word tokens, no stopword list).",
)

_WORD = re.compile(r"\w+")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(normalize_safe(text)))


def lexical_overlap(query: str, texts: list[str]) -> list[float]:
    """Share of the question's distinct words found in each chunk (heuristic).

    Both sides go through ``normalize_safe`` (Persian-safe) and ``\\w+`` word
    tokens; no stopword list. A question without words gives missing scores.
    """
    q = _words(query)
    if not q:
        return [math.nan] * len(texts)
    return [len(q & _words(t)) / len(q) for t in texts]


def _int(name: str, value: object, low: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        raise ValueError(f"{name} must be an int >= {low}, got {value!r}")
    return value


def _real(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number, got {value!r}")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return float(value)


def _label(scorer: Scorer | None) -> str:
    if scorer is None:
        return OBSERVED
    clean = re.sub(r"[^a-z0-9_]+", "_", getattr(scorer, "__name__", "").lower())
    return clean.strip("_") or "custom"


def collapse(chunks: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """S-6's exact dedup inside each message.

    Returns the unique chunks (``message_id``, ``pos``, ``n_chars``,
    ``relevancy`` = max over copies, ``content`` if given) and, per message,
    ``n_chunks``, ``raw_chars`` and ``dup_chars``.
    """
    c = chunks.reset_index(drop=True)
    c["pos"] = c.groupby("message_id", sort=False).cumcount()
    has = c["h_exact"].notna()
    # A row without a fingerprint is its own key (never hex, so never a match).
    c["ukey"] = c["h_exact"].astype(object).where(has, "~row:" + c.index.astype(str))
    dup = c.duplicated(["message_id", "ukey"])
    chars = c["n_chars"].fillna(0).astype(float)
    per = (
        pd.DataFrame(
            {
                "message_id": c["message_id"],
                "n_chunks": 1,
                "raw_chars": chars,
                "dup_chars": chars.where(dup, 0.0),
            }
        )
        .groupby("message_id", sort=False)[["n_chunks", "raw_chars", "dup_chars"]]
        .sum()
    )
    best = c.groupby(["message_id", "ukey"], sort=False)["relevancy"].max()
    keep = ["message_id", "ukey", "pos", "n_chars"] + (
        ["content"] if "content" in c else []
    )
    unique = c.loc[~dup, keep].copy()
    unique["n_chars"] = unique["n_chars"].fillna(0).astype(float)
    unique["relevancy"] = best.reindex(
        pd.MultiIndex.from_frame(unique[["message_id", "ukey"]])
    ).to_numpy()
    return unique.drop(columns="ukey").reset_index(drop=True), per


def cut_unique(
    unique: pd.DataFrame, *, floor: int, threshold: float | None, top_k: int | None
) -> pd.Series:
    """Keep mask over ``unique`` (needs ``message_id``, ``pos``, ``score``)."""
    u = unique.assign(_neg=-unique["score"]).sort_values(
        ["message_id", "_neg", "pos"], na_position="last", kind="stable"
    )
    scored = u["score"].notna()
    rank = u[scored].groupby("message_id", sort=False).cumcount()
    g = u.groupby("message_id", sort=False)
    n_scored = g["score"].count()
    n_unscored = g["score"].size() - n_scored
    above = (
        n_scored
        if threshold is None
        else (u["score"] >= threshold).groupby(u["message_id"], sort=False).sum()
    )
    m = above if top_k is None else np.minimum(above, top_k)
    keep_n = np.minimum(n_scored, np.maximum(m, floor - n_unscored))
    limit = u.loc[scored, "message_id"].map(keep_n)
    keep = pd.Series(True, index=u.index)
    keep[scored] = (rank < limit).to_numpy()
    return keep.reindex(unique.index)


class RerankerCut:
    """Keep the best unique chunks per request; a ``levers.StepVersion`` of step
    ``context``. See the module docstring."""

    step = "context"
    version = VERSION
    correctness_state = "unmeasured"

    def __init__(
        self,
        scorer: Scorer | None,
        floor: int,
        threshold: float | None,
        top_k: int | None,
        *,
        chunks: pd.DataFrame,
        tokens_per_char: float,
        queries: Mapping[str, str] | None = None,
        cached_separately: frozenset[str] = frozenset(),
    ) -> None:
        self.scorer = scorer
        self._set(floor, threshold, top_k)
        self.tokens_per_char = _real("tokens_per_char", tokens_per_char)
        if self.tokens_per_char <= 0:
            raise ValueError("tokens_per_char must be above 0")
        if scorer is not None and "content" not in chunks:
            raise ValueError("a text scorer needs a content column in chunks")
        self.queries = queries or {}
        self.cached_separately = cached_separately
        self._unique, self._per_message = collapse(chunks)
        self._scores: dict[object, np.ndarray] = {}
        self.scorer_name = _label(scorer)
        self.lever_id = f"context.reranker_cut.{self.scorer_name}"
        self.name = self.lever_id
        self.evidence_class = (
            "hypothetical reconstruction" if scorer is None else "heuristic"
        )
        self.assumptions = _COMMON + (_OBSERVED if scorer is None else _LEXICAL)

    def _set(self, floor: object, threshold: object, top_k: object) -> None:
        self.floor = _int("floor", floor, 0)
        self.threshold = None if threshold is None else _real("threshold", threshold)
        self.top_k = None if top_k is None else _int("top_k", top_k, 1)

    def with_params(
        self, *, floor: int, threshold: float | None, top_k: int | None
    ) -> RerankerCut:
        """The same chunks and scores (computed once) with other cut settings."""
        other = copy.copy(self)
        other._set(floor, threshold, top_k)
        return other

    # --- scoring --------------------------------------------------------------------

    def eligible(self, req: pd.DataFrame) -> pd.Series:
        llm = req["llm_request"].fillna(False).astype(bool)
        hit = (
            req["served_from_cache"].fillna(False).astype(bool)
            if "served_from_cache" in req
            else pd.Series(False, index=req.index)
        )
        has_chunks = req["ai_message_id"].isin(self._per_message.index)
        return llm & ~hit & req["a_rag_state"].eq("ok") & has_chunks

    def _scored(self, messages: pd.Index) -> pd.DataFrame:
        u = self._unique[self._unique["message_id"].isin(messages)].copy()
        if self.scorer is None:
            u["score"] = u["relevancy"]
            return u
        scores = np.empty(len(u))
        for mid, rows in u.groupby("message_id", sort=False).indices.items():
            if mid not in self._scores:
                self._scores[mid] = self._score_one(mid, u.iloc[rows])
            scores[rows] = self._scores[mid]
        u["score"] = scores
        return u

    def _score_one(self, mid: object, rows: pd.DataFrame) -> np.ndarray:
        query = self.queries.get(mid)
        if not isinstance(query, str):
            return np.full(len(rows), np.nan)
        texts = rows.sort_values("pos")["content"].fillna("").astype(str).tolist()
        out = np.asarray(self.scorer(query, texts), dtype=float)
        if out.shape != (len(rows),):
            raise ValueError(f"scorer returned {out.shape}, expected ({len(rows)},)")
        order = np.argsort(rows["pos"].to_numpy(), kind="stable")
        back = np.empty_like(out)
        back[order] = out
        return back

    def unique_scores(self, req: pd.DataFrame) -> pd.Series:
        """Scores of the unique chunks of the eligible requests (numbers only)."""
        messages = pd.Index(req.loc[self.eligible(req), "ai_message_id"].unique())
        return self._scored(messages)["score"].reset_index(drop=True)

    # --- replay ---------------------------------------------------------------------

    def apply(self, req: pd.DataFrame, ctx: ReplayContext) -> pd.DataFrame:
        out = req.copy()
        ok = self.eligible(req)
        ids = req["ai_message_id"]
        u = self._scored(pd.Index(ids[ok].unique()))
        keep = cut_unique(
            u, floor=self.floor, threshold=self.threshold, top_k=self.top_k
        )
        scored = u["score"].notna()
        rows = pd.DataFrame(
            {
                "message_id": u["message_id"],
                "rc_n_unique": 1,
                "rc_n_unscored": (~scored).astype(int),
                "rc_n_kept": keep.astype(int),
                "rc_cut_chars": u["n_chars"].where(~keep, 0.0),
                "rc_score_total": u["score"].where(scored, 0.0),
                "rc_score_kept": u["score"].where(scored & keep, 0.0),
            }
        )
        per = rows.groupby("message_id", sort=False).sum()
        per = per.join(
            self._per_message.rename(
                columns={
                    "n_chunks": "rc_n_chunks",
                    "raw_chars": "rc_raw_chars",
                    "dup_chars": "rc_dup_chars",
                }
            )
        )
        joined = per.reindex(ids.to_numpy())
        joined.index = req.index
        out["rc_eligible"] = ok
        for col in COUNT_COLUMNS:
            out[col] = joined[col].where(ok, 0).fillna(0)
        for col in SCORE_COLUMNS:
            out[col] = joined[col].where(ok)

        tokens = token_counts(req, self.cached_separately)
        dup_chars = out["rc_dup_chars"]
        dedup = lower_uncached_input(tokens, dup_chars * self.tokens_per_char)
        both = lower_uncached_input(
            tokens, (dup_chars + out["rc_cut_chars"]) * self.tokens_per_char
        )
        out["rc_raw_chunk_tokens"] = out["rc_raw_chars"] * self.tokens_per_char
        out["rc_dedup_tokens"] = dedup["saved"].where(ok, 0.0)
        out["rc_saved_tokens"] = (both["saved"] - dedup["saved"]).where(ok, 0.0)
        return out

    @staticmethod
    def baseline_frames(
        req: pd.DataFrame,
        out: pd.DataFrame,
        ctx: ReplayContext,
        *,
        baseline: str,
        premium_model: str,
        cheap_model: str,
        input_rate_per_m: Mapping[str, float] | None = None,
        cached_separately: frozenset[str] = frozenset(),
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Before and after cost blocks of one baseline for the cut's own saving
        (S-6's tokens are taken first and never counted), for
        ``levers.summarise_slices``. ``req`` is the frame given to ``apply``
        (with ``levers.with_blocks``), ``out`` what it returned.

        Repriced baselines (``REPRICED_KEYS``, price-file units): the logged
        tokens, the tokens less dedup and the tokens less dedup and cut are
        repriced with ``baselines_full.repriced_row_costs`` (tier chosen again);
        the saving is the second minus the third. ``block_fees`` is 0 on both
        sides only so the blocks can be summed (fees are not priced, ADR-0036).

        ``as_logged`` (recorded units, ADR-0038): the recorded blocks; the saving
        is the cut's tokens x the logged model's ``input_rate_per_m`` / 1e6, taken
        off ``block_token_cost`` after S-6's share and capped at what is left.
        A row with a cut but no rate has an unknown saving; a row with nothing cut
        saves exactly 0. ``block_fees`` never changes.

        ``after`` carries ``SAVING_UNKNOWN``: LLM rows with a known baseline
        whose saving is unknown; such rows leave both sides.
        """
        fees, token = (block_column(b) for b in BLOCKS)
        llm = req["llm_request"].fillna(False).astype(bool)
        dedup, cut = out["rc_dedup_tokens"], out["rc_saved_tokens"]
        before = req[["llm_request"]].copy()
        after = before.copy()
        if baseline in REPRICED_KEYS:
            tokens = token_counts(req, cached_separately)

            def cost(saved: pd.Series | float) -> pd.Series:
                return repriced_row_costs(
                    req,
                    ctx,
                    premium_model=premium_model,
                    cached_separately=cached_separately,
                    tokens=tokens.assign(input=tokens["input"] - saved),
                    cheap_model=cheap_model,
                )[baseline]

            base = cost(0.0)
            saving = cost(dedup) - cost(dedup + cut)
            base_known = base.notna()
            known = base_known & saving.notna()
            before[fees] = (base * 0.0).where(known)
        elif baseline == "as_logged":
            if input_rate_per_m is None:
                raise ValueError("as_logged needs input_rate_per_m (ADR-0038)")
            rate = req["bot_provider_model"].map(input_rate_per_m).astype(float) / 1e6
            base = req[token]
            left = (base - dedup * rate).clip(lower=0)  # what S-6's saving leaves
            saving = np.minimum(cut * rate, left).where(cut > 0, 0.0)
            base_known = req[[fees, token]].notna().all(axis=1)
            known = base_known & saving.notna()
            before[fees] = req[fees].where(known)
        else:
            raise ValueError(f"unknown baseline {baseline}")
        before[token] = base.where(known)
        after[fees] = before[fees]
        after[token] = (base - saving).where(known)
        after[SAVING_UNKNOWN] = llm & base_known & ~known
        return before, after
