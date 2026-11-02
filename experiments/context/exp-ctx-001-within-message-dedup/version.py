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
``ai_message_id``; a request with no chunk rows has 0. It does **not** change
``block_token_cost`` yet: turning duplicate characters into a cost saving needs
a tokens-per-character conversion and a price basis that the owner has not
chosen (README). Evidence class: *observed* for the counts; any saving would be
a *simulation*, tokens only, quality not measured.

Candidate code: loaded by file path only (scripts, tests); ``metis_auto`` never
imports it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from metis_auto.analysis.levers import ReplayContext, Step

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
    """Context version: count the chunk copies inside one message (no saving yet)."""

    name = "exp-ctx-001-within-message-dedup"
    step: Step = "context"

    def __init__(self, chunks: pd.DataFrame) -> None:
        self._per_message = within_message_duplicates(chunks)
        self._norm_computed = "h_norm" in chunks

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
        return out


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
