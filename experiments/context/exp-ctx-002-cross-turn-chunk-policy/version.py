"""R-B2 cross-turn chunk policy: drop a retrieved chunk that was already supplied
earlier in the same session, when the model is *assumed* to still see it, and
send a short pointer instead (final plan R-B2; H-1, FR-CTX-02, FR-CTX-03, QA-PRIV).

Evidence: **tokens only, quality not measured** and *hypothetical
reconstruction*. Chunk tokens come from ``n_chars * tokens_per_char`` (the EDA's
turn-0 slope, claim ``recon.t0rag.coef_rag``, about 0.34). Visibility is an
argument, because the history policy is unidentified (EDA section 2). A chunk
that appears in the log is not proof that the model still sees it.

**Chunks frame** (one row per logged chunk occurrence, built by the run script):
``req`` (request label), ``session``, ``scope`` (tenant and bot), ``turn`` (the
request's 0-based position in its session), ``chunk_id``, ``content_hash``
(``None`` when unknown), ``n_chars``.

**Requests frame:** ``llm_request``, ``input_tokens_ordinary`` (input tokens that
were not provider-cached, by ``ordinary_input_tokens``), ``input_cost_ordinary``
(the recorded ``costBreakdown.input_tokens`` cost), ``block_token_cost``;
optional ``served_from_cache``.

**Rule per chunk occurrence** (``decide``):

- Only LLM rows not served by an *answer* cache take part. Rows where R-B1
  reused retrieval stay eligible. A skipped row's chunks never count as
  supplied (``skipped_not_active``).
- A repeat of ``(chunk_id, content_hash)`` inside the same request is
  ``within_message``. That is S-6's scope (within-message dedup), so R-B2 never
  counts it.
- A drop candidate needs the same session, the same scope, the same ID **and**
  hash fully supplied at an earlier turn ``t0``, and ``assume_visible(k)`` true
  for ``k = turn - t0`` (``k`` = how many requests back the last *full* supply
  was; ``k >= 1``). A dropped chunk is not re-supplied, so ``k`` keeps growing
  until the chunk is not visible and is sent again. The conservative default
  when history cannot be reconstructed is ``lambda k: False`` (drop nothing).
  Wider windows are hypothetical scenarios, reported separately.
- Kept: ``kept_first_seen``, ``kept_changed_hash`` (same ID, other hash: Review
  Focus 4), ``kept_hash_unknown``, ``kept_not_visible``.
- Per request, the replacement costs ``pointer_tokens`` per dropped chunk or,
  with ``session_ledger``, one append-only block of ``pointer_tokens`` per
  distinct chunk supplied earlier in the session (sent only on turns that drop).
  If removed tokens do not exceed added tokens, nothing is dropped
  (``kept_net_nonpositive``). If the request's input rate is unknown, nothing is
  dropped (``kept_cost_unknown``).
- The net saving is capped at ``input_tokens_ordinary``, so input never goes
  below zero.

**Cost.** Only ``block_token_cost`` is lowered: net tokens × the request's
recorded ordinary input rate (``input_cost_ordinary / input_tokens_ordinary``).
Removed tokens are priced as ordinary input. Provider-cached input is not
repriced (``ordinary_input_tokens``). Fees, output and every other cost are
unchanged.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable
from typing import Any

import pandas as pd

CHUNK_COLUMNS = (
    "req",
    "session",
    "scope",
    "turn",
    "chunk_id",
    "content_hash",
    "n_chars",
)


def _missing(value: object) -> bool:
    if value is None or value is pd.NA:
        return True
    return isinstance(value, float) and math.isnan(value)


def ordinary_input_tokens(
    input_tokens: float,
    cached_tokens: float,
    model: object,
    separate_models: frozenset[str],
) -> float:
    """Input tokens that were not provider-cached.

    For models in ``separate_models`` (the EDA's ``cached_reported_separately``,
    ``reports/full_eda/tables/cached_token_convention.csv``), ``inputTokens``
    already excludes cached tokens. For the others it includes them, so the
    cached count is subtracted (never below zero). Unknown input stays unknown.
    """
    if _missing(input_tokens):
        return float("nan")
    cached = 0.0 if _missing(cached_tokens) else float(cached_tokens)
    if model in separate_models:
        return float(input_tokens)
    return max(float(input_tokens) - cached, 0.0)


class CrossTurnChunkPolicy:
    """``StepVersion``-shaped context version (``step = "context"``)."""

    step = "context"

    def __init__(
        self,
        pointer_tokens: int,
        assume_visible: Callable[[int], bool],
        session_ledger: bool,
        *,
        chunks: pd.DataFrame,
        tokens_per_char: float,
    ) -> None:
        if isinstance(pointer_tokens, bool) or not isinstance(pointer_tokens, int):
            raise TypeError("pointer_tokens must be an int")
        if pointer_tokens < 0:
            raise ValueError("pointer_tokens must not be negative")
        if not tokens_per_char > 0:
            raise ValueError("tokens_per_char must be positive")
        missing = [c for c in CHUNK_COLUMNS if c not in chunks]
        if missing and len(chunks):
            raise ValueError(f"chunks lack columns {missing}")
        self.pointer_tokens = pointer_tokens
        self.assume_visible = assume_visible
        self.session_ledger = session_ledger
        self.chunks = chunks
        self.tokens_per_char = float(tokens_per_char)
        ledger = ".ledger" if session_ledger else ""
        self.name = f"cross_turn_chunks.ptr{pointer_tokens}{ledger}"

    def _active(self, req: pd.DataFrame) -> pd.Series:
        if "llm_request" not in req:
            raise ValueError("llm_request is missing; run the scope step first")
        if req["llm_request"].isna().any():
            raise ValueError("llm_request has unknown rows; unknown is not False")
        active = req["llm_request"].astype(bool)
        if "served_from_cache" in req:
            active &= ~req["served_from_cache"].fillna(False).astype(bool)
        return active

    def _run(self, req: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        active = self._active(req)
        tokens = req["input_tokens_ordinary"]
        rate = (req["input_cost_ordinary"] / tokens).where(tokens > 0)
        ch = self.chunks
        ch = ch[ch["req"].isin(req.index)] if len(ch) else ch
        ch = ch.sort_values(["session", "scope", "turn"], kind="stable")
        per_req: dict[object, tuple[int, float, float, float]] = {}
        labels = ch["req"].tolist()
        groups = list(zip(ch["session"].tolist(), ch["scope"].tolist(), strict=True))
        turns = ch["turn"].tolist()
        cids = ch["chunk_id"].tolist()
        hs = [None if _missing(h) else h for h in ch["content_hash"].tolist()]
        chars = ch["n_chars"].astype(float).tolist()
        is_active = active.to_dict()
        rates = rate.to_dict()
        reasons: list[str | None] = [None] * len(labels)
        last_full: dict[tuple[str, str], int] = {}
        hashes: dict[str, set[str]] = {}
        n, i = len(labels), 0
        while i < n:
            j = i
            while j < n and labels[j] == labels[i]:
                j += 1
            if i == 0 or groups[i] != groups[i - 1]:
                last_full, hashes = {}, {}
            label, turn = labels[i], int(turns[i])
            if not is_active.get(label, False):
                reasons[i:j] = ["skipped_not_active"] * (j - i)
                i = j
                continue
            seen: set[tuple[str, str | None]] = set()
            drops: list[int] = []
            for r in range(i, j):
                cid, h = cids[r], hs[r]
                if (cid, h) in seen:
                    reasons[r] = "within_message"
                    continue
                seen.add((cid, h))
                if h is None:
                    reasons[r] = "kept_hash_unknown"
                elif (cid, h) in last_full:
                    k = turn - last_full[(cid, h)]
                    if k >= 1 and self.assume_visible(k):
                        drops.append(r)
                    else:
                        reasons[r] = "kept_not_visible"
                elif cid in hashes:
                    reasons[r] = "kept_changed_hash"
                else:
                    reasons[r] = "kept_first_seen"
            removed = math.fsum(chars[r] * self.tokens_per_char for r in drops)
            n_entries = len(last_full) if self.session_ledger else len(drops)
            added = float(self.pointer_tokens * n_entries)
            verdict = "dropped"
            if drops and _missing(rates.get(label)):
                verdict = "kept_cost_unknown"
            elif drops and removed - added <= 0:
                verdict = "kept_net_nonpositive"
            for r in drops:
                reasons[r] = verdict
            if drops and verdict == "dropped":
                net = min(removed - added, float(tokens[label]))
                per_req[label] = (len(drops), removed, added, net)
            for r in range(i, j):
                h = hs[r]
                if reasons[r] == "dropped" or h is None:
                    continue
                last_full[(cids[r], h)] = turn
                hashes.setdefault(cids[r], set()).add(h)
            i = j
        decisions = ch[["req", "session", "turn", "content_hash"]].copy()
        decisions["reason"] = pd.Series(reasons, index=ch.index, dtype=object)
        cols = ["ctx_chunks_dropped", "ctx_tokens_removed", "ctx_tokens_added"]
        cols.append("ctx_tokens_saved")
        frame = pd.DataFrame.from_dict(per_req, orient="index", columns=cols)
        frame = frame.reindex(req.index).fillna(0.0)
        frame["ctx_chunks_dropped"] = frame["ctx_chunks_dropped"].astype(int)
        frame["ctx_cost_saved"] = (frame["ctx_tokens_saved"] * rate).fillna(0.0)
        return decisions.reindex(
            self.chunks.index.intersection(ch.index, sort=False)
        ), frame

    def decide(self, req: pd.DataFrame) -> pd.DataFrame:
        """Per chunk occurrence: ``req``, ``session``, ``turn``, ``content_hash`` and
        ``reason`` (see module doc). In memory only: it holds hashes."""
        return self._run(req)[0]

    def apply(self, req: pd.DataFrame, ctx: Any) -> pd.DataFrame:
        """A copy of ``req`` (same index) with ``block_token_cost`` lowered by the
        recorded cost of the net tokens saved, plus the ``ctx_*`` columns and
        ``input_tokens_after``."""
        return self.run(req)[1]

    def run(self, req: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """``decide`` and ``apply`` from one pass."""
        decisions, frame = self._run(req)
        out = req.copy()
        for col in frame.columns:
            out[col] = frame[col]
        out["input_tokens_after"] = (
            out["input_tokens_ordinary"] - out["ctx_tokens_saved"]
        )
        out["block_token_cost"] = (
            out["block_token_cost"] - out["ctx_cost_saved"]
        ).where(out["ctx_cost_saved"] > 0, out["block_token_cost"])
        if (out["block_token_cost"] < -1e-12).any():
            raise ValueError("a context saving exceeded the recorded token cost")
        out["block_token_cost"] = out["block_token_cost"].clip(lower=0.0)
        return decisions, out


def summarise(
    decisions: pd.DataFrame, after: pd.DataFrame, req: pd.DataFrame
) -> dict[str, Any]:
    """Content-free counts: reasons, tokens, recorded cost saved and its shares,
    and the EDA-style repeat reference (chunk rows whose content hash already
    appeared earlier in the session, within-message copies included)."""
    llm = req["llm_request"].astype(bool)
    known = llm & req["block_token_cost"].notna() & req["input_cost_ordinary"].notna()
    token_cost = math.fsum(req.loc[known, "block_token_cost"])
    fees = (
        math.fsum(req.loc[known, "block_fees"].fillna(0.0))
        if "block_fees" in req
        else 0.0
    )
    saved_cost = math.fsum(after.loc[known, "ctx_cost_saved"])
    reasons = Counter(r for r in decisions["reason"] if r is not None)
    return {
        "reasons": dict(reasons),
        "n_requests_all": len(req),
        "n_requests_llm": int(llm.sum()),
        "n_requests_changed": int((after["ctx_tokens_saved"] > 0).sum()),
        "tokens": {
            "removed": math.fsum(after["ctx_tokens_removed"]),
            "added": math.fsum(after["ctx_tokens_added"]),
            "saved": math.fsum(after["ctx_tokens_saved"]),
            "supported_input": math.fsum(
                req.loc[llm, "input_tokens_ordinary"].dropna()
            ),
        },
        "cost": {
            "saved": saved_cost,
            "token_cost": token_cost,
            "saving_share_of_token_cost": saved_cost / token_cost
            if token_cost
            else None,
            "saving_share_of_total": saved_cost / (token_cost + fees)
            if token_cost + fees
            else None,
        },
        "repeat_reference": _repeat_reference(decisions, req),
    }


def _repeat_reference(decisions: pd.DataFrame, req: pd.DataFrame) -> dict[str, Any]:
    """The EDA's ``rag.chunk_repeat_in_session`` definition on these rows."""
    rows = decisions.sort_values(["session", "turn"], kind="stable")
    rows = rows[rows["content_hash"].notna()]
    if rows.empty:
        return {"share_rows_repeating_in_session": None, "n_chunk_rows": 0}
    repeat = rows.duplicated(["session", "content_hash"])
    return {
        "share_rows_repeating_in_session": float(repeat.mean()),
        "n_chunk_rows": len(rows),
    }
