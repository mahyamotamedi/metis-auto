"""EXP-CTX-001: within-message chunk dedup, a context ``StepVersion`` (final plan
S-6; FR-CTX-02, FR-CTX-03, H-1, X5; Review Focus 4).

A chunk row is an **exact duplicate** when an earlier row of the same message
has the same ``h_exact`` (the fingerprint of the exact chunk text). The first
copy is kept. Identity is the text fingerprint, never ``chunk_id``: two IDs with
one text are duplicates, and one ID with two texts (a corpus update) is not, so
a changed text is never a safe drop. A row without text (``h_exact`` missing)
is never a duplicate. Nothing is deduplicated across messages.

A **normalised duplicate** uses ``h_norm`` (the fingerprint of
``text_features.normalize_safe`` of the text; built locally by
``scripts/derive_chunk_norm_fingerprints.py``) the same way. It is reported
separately and is never a drop candidate: the texts differ, so dropping one
needs a quality check. Without an ``h_norm`` column the normalised figures are
"not computed" (missing), never 0; a text row with no ``h_norm`` makes its
message's figures missing.

``apply`` adds per-request counts (``REQUEST_COLUMNS``) joined on
``ai_message_id``; a request with no chunk rows has 0. Without
``tokens_per_char`` it changes no cost.

**Saving (S-6b; ADR-XXXX (context-token-saving-conversion)).** With
``tokens_per_char`` (the owner's choice: ledger ``recon.t0rag.coef_rag``),
duplicate characters become wanted tokens, taken from **uncached** input only
(``baselines_full.lower_uncached_input``), once per request however many calls
it made: ``SAVED_TOKENS``. With ``input_rate_per_m`` (each model's implied
input rate per 1M tokens, recorded units) ``apply`` also lowers
``block_token_cost`` (the ``as_logged`` saving). A request with a saving but no
rate keeps its cost and gets ``SAVING_KNOWN`` False: unknown, never zero.
``block_fees`` is never changed. ``baseline_frames`` gives the before and
after cost blocks for one baseline (repriced baselines lower the input and
reprice, so a tier can change); ``lever_result`` turns them into a
``LeverResult``. Evidence class: *observed* for the counts, *hypothetical
reconstruction* for the saving; quality not measured (FR-CTX-03).

Candidate code: loaded by file path only (scripts, tests); ``metis_auto`` never
imports it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from decimal import Decimal

import numpy as np
import pandas as pd

from metis_auto.analysis.baselines_full import (
    REPRICED_KEYS,
    best_single_cheap_model,
    lower_uncached_input,
    repriced_row_costs,
    token_counts,
)
from metis_auto.analysis.lever_result import LeverResult, Manifest
from metis_auto.analysis.levers import (
    BLOCKS,
    ReplayContext,
    Step,
    block_column,
    summarise_slices,
)

EXACT_COLUMNS = (
    "n_chunks",
    "n_with_text",
    "chunk_chars",
    "n_dup_exact",
    "dup_chars_exact",
)
NORM_COLUMNS = ("n_dup_norm", "dup_chars_norm", "n_dup_norm_only")
REQUEST_COLUMNS = {
    "n_chunks": "ctx_n_chunks",
    "n_with_text": "ctx_n_with_text",
    "chunk_chars": "ctx_chunk_chars",
    "n_dup_exact": "ctx_dup_chunks_exact",
    "dup_chars_exact": "ctx_dup_chars_exact",
    "n_dup_norm": "ctx_dup_chunks_norm",
    "dup_chars_norm": "ctx_dup_chars_norm",
}
TOTAL = "__total__"
SAVED_TOKENS = "ctx_saved_input_tokens"
SAVING_KNOWN = "ctx_saving_known"
SAVING_UNKNOWN = "ctx_saving_unknown"
VERSION_ID = "ctx.within_message_dedup"
EVIDENCE = "hypothetical reconstruction"


def within_message_duplicates(chunks: pd.DataFrame) -> pd.DataFrame:
    """Per ``message_id``: ``EXACT_COLUMNS`` and ``NORM_COLUMNS``."""
    text = chunks["h_exact"].notna()
    chars = chunks["n_chars"].fillna(0).astype(int)
    exact = chunks.duplicated(["message_id", "h_exact"]) & text
    rows = {
        "n_chunks": 1,
        "n_with_text": text.astype(int),
        "chunk_chars": chars.where(text, 0),
        "n_dup_exact": exact.astype(int),
        "dup_chars_exact": chars.where(exact, 0),
    }
    norm_computed = "h_norm" in chunks
    if norm_computed:
        has_norm = chunks["h_norm"].notna()
        norm = chunks.duplicated(["message_id", "h_norm"]) & text & has_norm
        rows |= {
            "n_dup_norm": norm.astype(int),
            "dup_chars_norm": chars.where(norm, 0),
            "n_dup_norm_only": (norm & ~exact).astype(int),
            "_norm_unknown": (text & ~has_norm).astype(int),
        }
    frame = pd.DataFrame(rows, index=chunks.index).assign(
        message_id=chunks["message_id"]
    )
    per_msg = frame.groupby("message_id", sort=True).sum()
    if norm_computed:
        unknown = per_msg.pop("_norm_unknown") > 0
    else:
        unknown = pd.Series(True, index=per_msg.index)
    for col in NORM_COLUMNS:
        known = per_msg[col] if norm_computed else pd.Series(0, index=per_msg.index)
        per_msg[col] = known.astype("Int64").mask(unknown)
    return per_msg


class WithinMessageDedup:
    """Context version: count the chunk copies inside one message and, with a
    conversion, the input tokens and recorded cost they would save."""

    name = "exp-ctx-001-within-message-dedup"
    step: Step = "context"

    def __init__(
        self,
        chunks: pd.DataFrame,
        *,
        tokens_per_char: float | None = None,
        input_rate_per_m: Mapping[str, float] | None = None,
        cached_separately: frozenset[str] = frozenset(),
    ) -> None:
        if input_rate_per_m is not None and tokens_per_char is None:
            raise ValueError("input_rate_per_m needs tokens_per_char")
        self._per_message = within_message_duplicates(chunks)
        self._norm_computed = "h_norm" in chunks
        self._tokens_per_char = tokens_per_char
        self._rates = input_rate_per_m
        self._cached_separately = cached_separately

    def apply(self, req: pd.DataFrame, ctx: ReplayContext) -> pd.DataFrame:
        out = req.copy()
        ids = out["ai_message_id"]
        logged = ids.isin(self._per_message.index).to_numpy()
        joined = self._per_message.reindex(ids.to_numpy())
        for source, column in REQUEST_COLUMNS.items():
            values = joined[source].astype("Int64").to_numpy(copy=True)
            if source in NORM_COLUMNS and not self._norm_computed:
                out[column] = pd.array(values, dtype="Int64")
                continue
            values[~logged] = 0
            out[column] = pd.array(values, dtype="Int64")
        if self._tokens_per_char is None:
            return out
        wanted = out["ctx_dup_chars_exact"].astype(float) * self._tokens_per_char
        tokens = token_counts(req, self._cached_separately)
        saved = lower_uncached_input(tokens, wanted)["saved"]
        out[SAVED_TOKENS] = saved.where(wanted > 0, 0.0)  # no copy: exactly 0
        if self._rates is None:
            return out
        rate = req["bot_provider_model"].map(self._rates).astype(float)
        cut = np.minimum(out[SAVED_TOKENS] * rate / 1e6, out["block_token_cost"])
        out[SAVING_KNOWN] = out[SAVED_TOKENS].eq(0) | cut.notna()
        out["block_token_cost"] = out["block_token_cost"] - cut.where(
            out[SAVED_TOKENS] > 0, 0.0
        ).fillna(0.0)
        return out


def baseline_frames(
    req: pd.DataFrame,
    out: pd.DataFrame,
    ctx: ReplayContext,
    *,
    baseline: str,
    premium_model: str,
    cached_separately: frozenset[str] = frozenset(),
    cheap_model: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Before and after cost blocks of one baseline, for ``summarise_slices``.

    ``req`` is the frame before ``apply`` (with ``levers.with_blocks``), ``out``
    after it. ``as_logged``: the recorded blocks; a row whose saving is unknown
    (no implied rate) leaves both sides, so the baseline and the saving cover
    the same rows. Repriced baselines (price-file units): the logged tokens and
    the tokens less ``SAVED_TOKENS`` are repriced, so the tier is chosen again;
    ``block_fees`` is 0 on both sides only so the slices can be summed, and
    ``lever_result`` drops the baseline fee (ADR-0036: not priced). ``after``
    carries ``SAVED_TOKENS`` and ``SAVING_UNKNOWN`` (LLM rows with a known
    baseline cost whose saving is unknown).
    """
    llm = req["llm_request"].astype(bool)
    before = req[["llm_request"]].copy()
    after = before.copy()
    saved = out[SAVED_TOKENS]
    cols = [block_column(b) for b in BLOCKS]
    if baseline == "as_logged":
        if SAVING_KNOWN not in out:
            raise ValueError("as_logged needs input_rate_per_m in the version")
        unknown = ~out[SAVING_KNOWN].fillna(False).astype(bool)
        base_known = req[cols].notna().all(axis=1)
        for col in cols:
            before[col] = req[col].where(~unknown)
            after[col] = out[col].where(~unknown)
    elif baseline in REPRICED_KEYS:
        tokens = token_counts(req, cached_separately)
        if cheap_model is None:
            cheap_model = best_single_cheap_model(
                req, ctx, cached_separately=cached_separately
            )
        costs = [
            repriced_row_costs(
                req,
                ctx,
                premium_model=premium_model,
                cached_separately=cached_separately,
                tokens=t,
                cheap_model=cheap_model,
            )[baseline]
            for t in (tokens, tokens.assign(input=tokens["input"] - saved))
        ]
        base_known = costs[0].notna()
        unknown = costs[1].isna()
        for frame, cost in zip((before, after), costs, strict=True):
            cost = cost.where(~unknown)
            frame[cols[0]] = (cost * 0.0).where(cost.notna())
            frame[cols[1]] = cost
    else:
        raise ValueError(f"unknown baseline {baseline}")
    after[SAVED_TOKENS] = saved
    after[SAVING_UNKNOWN] = llm & base_known & unknown
    return before, after


def _decimal(value: float) -> Decimal:
    """Fixed nine-decimal Decimal (and no negative zero), as in ``levers``."""
    return Decimal(f"{value + 0.0:.9f}")


def lever_result(
    before: pd.DataFrame,
    after: pd.DataFrame,
    *,
    baseline: str,
    manifest: Manifest,
    assumptions: Sequence[str] = (),
) -> LeverResult:
    """One ``LeverResult`` from ``baseline_frames``: slices ``all`` and
    ``llm_only`` plus ``n_saving_unknown`` and ``saved_input_tokens``; top-level
    blocks and totals from ``llm_only``. Fees saving is always 0."""
    slices = summarise_slices(before, after)
    llm = before["llm_request"].astype(bool)
    known = before[[block_column(b) for b in BLOCKS]].notna().all(axis=1) & llm
    saved = after[SAVED_TOKENS]
    repriced = baseline in REPRICED_KEYS
    for name, rows in (("all", pd.Series(True, index=llm.index)), ("llm_only", llm)):
        s = slices[name]
        s["n_saving_unknown"] = Decimal(int((rows & after[SAVING_UNKNOWN]).sum()))
        s["saved_input_tokens"] = _decimal(
            math.fsum(saved[rows & known].to_numpy(dtype=float))
        )
        if repriced:
            del s["baseline:fees"]
    top = slices["llm_only"]
    names = (*BLOCKS, "total")
    baseline_cost = {b: top[f"baseline:{b}"] for b in names if f"baseline:{b}" in top}
    saving = {b: top[f"saving:{b}"] for b in names}
    return LeverResult(
        lever_id=f"{VERSION_ID}.{baseline}",
        step="context",
        version=VERSION_ID,
        n_requests=len(before),
        n_eligible=int((llm & (saved > 0)).sum()),
        baseline=baseline,
        baseline_cost=baseline_cost,
        saving=saving,
        slices=slices,
        evidence_class=EVIDENCE,
        correctness_state="unmeasured",
        assumptions=tuple(assumptions),
        manifest=manifest,
    )


def _share(num: object, den: float) -> float:
    if pd.isna(num) or not den:
        return np.nan
    return float(num) / float(den)


def _known_sum(values: pd.Series) -> object:
    return pd.NA if values.isna().any() else int(values.sum())


def _scope_row(group: pd.DataFrame, scope: str) -> dict[str, object]:
    llm = group[group["llm_request"].astype(bool)]
    den = group if scope == "all" else llm
    row: dict[str, object] = {
        "requests": len(den),
        "requests_with_chunks": int((den["ctx_n_chunks"] > 0).sum()),
        "chunk_rows": int(den["ctx_n_with_text"].sum()),
        "chunk_chars": int(den["ctx_chunk_chars"].sum()),
        "dup_rows_exact": int(llm["ctx_dup_chunks_exact"].sum()),
        "dup_chars_exact": int(llm["ctx_dup_chars_exact"].sum()),
        "dup_rows_norm": _known_sum(llm["ctx_dup_chunks_norm"]),
        "dup_chars_norm": _known_sum(llm["ctx_dup_chars_norm"]),
        "requests_with_dup": int((llm["ctx_dup_chunks_exact"] > 0).sum()),
    }
    for kind in ("exact", "norm"):
        row[f"dup_row_share_{kind}"] = _share(
            row[f"dup_rows_{kind}"], row["chunk_rows"]
        )
        row[f"dup_char_share_{kind}"] = _share(
            row[f"dup_chars_{kind}"], row["chunk_chars"]
        )
    row["requests_with_dup_share"] = _share(row["requests_with_dup"], row["requests"])
    return row


def summarise(out: pd.DataFrame, *, by: str) -> pd.DataFrame:
    """Aggregates per value of ``by`` and in total, for scopes ``all`` and ``llm_only``.

    Numerators count LLM rows only (workflow rows are excluded from every rate).
    Denominators count every row (``all``) or LLM rows (``llm_only``). A share
    with a zero denominator, or a normalised figure that is not computed, is
    missing, never 0.
    """
    groups = [(key, out[out[by] == key]) for key in sorted(out[by].dropna().unique())]
    rows = [
        {by: key, "scope": scope} | _scope_row(group, scope)
        for key, group in [*groups, (TOTAL, out)]
        for scope in ("all", "llm_only")
    ]
    return pd.DataFrame(rows)
