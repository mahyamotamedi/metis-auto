# EXP-CTX-001: within-message chunk dedup and stable prompt order

- **Task:** final plan S-6. **Traceability:** FR-CTX-02 (RAG trimming and stable-prefix ordering are experimental context strategies), FR-CTX-03 (nothing is promoted without a quality-preserving ablation), H-1 (prefix handling; the stable order below is its precondition), X5 (retrieved-context trimming, [context_plan.md](../../../docs/experiments/context_plan.md)), Review Focus 4 (same chunk ID with changed text), U-04 (what reaches the provider is unknown).
- **Hypothesis:** the same chunk text appears more than once in one message's retrieved context. Sending it once lowers input tokens and only the `token_cost` block (ADR-0032, ADR-0036), with no quality change, because the model gets the same text. The EDA reference is 33.3% of chunk rows (ledger `red.rag_dup_within_message`). That figure is re-checked here, not used as an input.
- **Strategy:** `version.py`, `WithinMessageDedup`, a `StepVersion` with step `"context"` ([levers.py](../../../src/metis_auto/analysis/levers.py)). It is built from the chunk table and joins it to requests on `message_id = ai_message_id`.
- **Evidence class:** the counts are *observed* (metadata-derived fingerprints). Any saving would be a *simulation*: tokens only, with quality not measured.

## Rules

1. **A duplicate is the same `h_exact` (the fingerprint of the exact text) as an earlier row in the same message.** The first copy is kept. `chunk_id` is not used: two IDs with one text are duplicates, and one ID with two texts (a corpus update) is not, so a changed text is never a safe drop (Review Focus 4). A row without text is never a duplicate. Nothing is deduplicated across messages (cross-turn reuse is R-B2).
2. **Normalised duplicates are reported separately and are never drop candidates.** `h_norm` is `fingerprint(normalize_safe(text))`, the only normaliser. The shared ingest writes no normalised fingerprint, so `scripts/derive_chunk_norm_fingerprints.py` builds it locally: it reads the raw chunk text in memory and writes only `(h_exact, h_norm)` to `data/derived/context/` (git-ignored; owner decision 2026-11-02). Without that file the normalised figures are "not computed" (missing), never 0.
3. **No saving yet.** `apply` adds `ctx_*` counts and leaves the cost blocks alone until the owner picks a tokens-per-character conversion and a price basis per baseline (see the progress entry for 2026-11-02).
4. **Stable prompt order (documented rule, no code):** instructions first, then retrieved chunks (deduplicated, in the retriever's order), then history, then the current message. The fixed part of the prompt stays a byte-identical prefix across turns, which is what provider-side prompt caching needs (FR-CTX-02, H-1). No check needs code yet: the logs do not record the order that was sent (U-04).

## Assumptions

- *Current:* `h_exact` equal means the text is equal. The fingerprint is a 12-byte blake2b, so the collision risk is negligible.
- *Current:* every chunk row joins to a request. Checked on 2026-11-02: 994,031 of 994,031 rows do.
- *Speculative:* duplicate chunks were actually sent to the provider, once per copy (U-04). The EDA's turn-0 fit of 0.34 tokens per chunk character says chunks are sent in full. It does not say whether duplicates were removed before sending.
- *Speculative:* dropping an exact copy does not change the answer. This is not measured (FR-CTX-03), and the plan's paid context ablation is "cut first".
- *Future:* with the paid ablation, the decision rule in the plan ("Context") applies.

## Run

```sh
.venv/bin/python scripts/derive_chunk_norm_fingerprints.py   # local h_norm map, ~10 s
.venv/bin/python scripts/context_dedup_report.py             # writes reports/context/exp-ctx-001/summary.csv
```

The summary holds counts and shares by fitting split (`replay_scope.split_by_session`) and in total, over all requests and over LLM requests only. Numerators count LLM rows only, because workflow rows are excluded from every rate.
