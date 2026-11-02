## Sprint Day 2, Pipeline C: within-message chunk dedup and stable prompt order (2026-11-02)

Final sprint plan, task S-6. Branch `context-within-message-dedup`. **Awaiting review.** Traceability: FR-CTX-02, FR-CTX-03, H-1, X5, Review Focus 4, U-04.

- **New:** [`experiments/context/exp-ctx-001-within-message-dedup/`](../../../experiments/context/exp-ctx-001-within-message-dedup/README.md): `version.py` (`WithinMessageDedup`, a context `StepVersion`; `within_message_duplicates`; `summarise`) and a README (hypothesis, rules, assumptions, evidence class, the stable prompt order rule). `scripts/derive_chunk_norm_fingerprints.py` (local `h_norm` map). `scripts/context_dedup_report.py` (aggregates). `reports/context/exp-ctx-001/summary.csv` (counts and shares only). Tests: `tests/unit/experiments/test_exp_ctx_001_within_message_dedup.py`, on synthetic frames.
- **Rule:** a duplicate is the same `h_exact` as an earlier row in the same message. `chunk_id` is ignored, so one ID with a changed text is never a drop (Review Focus 4). Normalised duplicates (`h_norm`) are reported separately and are never drop candidates. Without `h_norm` they are "not computed", never 0.
- **Owner decision (2026-11-02), option B:** the chunk table has no normalised fingerprint. A separate script reads the raw chunk text in memory and writes only `(h_exact, h_norm)` per distinct text to `data/derived/context/` (git-ignored). The shared ingest is not changed.
- **TDD:** tests 1 and 2 first failed because `version.py` was missing, then failed against a `chunk_id` stub (`1 == 2`, `1 == 0`), then passed. Test 3, the summary test and the script test failed (`KeyError: 'n_dup_norm'`, no `summarise`, no script) and then passed.
- **No saving written, no LeverResult.** `apply` leaves the cost blocks alone until the owner picks the conversion (below).

### Results (full data, aggregates only, naive timestamps)

- **EDA re-check:** 331,310 of 994,031 chunk rows with text are exact within-message duplicates, **33.33%**, which matches `red.rag_dup_within_message` exactly (same rule, all chunk rows, workflow included). Every chunk row joins to a request.
- `h_norm`: 25,989 distinct texts fold into 25,571 normalised texts. Normalisation adds only 296 duplicate rows over LLM requests (274,435 exact, 274,731 normalised).
- Workflow requests carry 275,931 chunk rows. They are excluded from every numerator.

| Split | Scope | Requests | Chunk rows | Exact dup rows | Row share | Char share | Norm row share | Requests with a dup |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| tune | all | 234,759 | 566,551 | 166,424 | 0.294 | 0.386 | 0.294 | 0.116 |
| tune | LLM only | 213,007 | 440,011 | 166,424 | 0.378 | 0.414 | 0.379 | 0.128 |
| report | all | 73,063 | 365,386 | 93,106 | 0.255 | 0.395 | 0.255 | 0.199 |
| report | LLM only | 20,750 | 237,323 | 93,106 | 0.392 | 0.426 | 0.393 | 0.702 |
| total | all | 349,079 | 994,031 | 274,435 | 0.276 | 0.389 | 0.276 | 0.127 |
| total | LLM only | 245,518 | 718,100 | 274,435 | 0.382 | 0.418 | 0.383 | 0.181 |

In "all", numerators count LLM rows only and denominators count every row. Duplicate characters over LLM requests: 382,449,060 (tune 200,477,966; report 163,063,465). The `excluded` split rows are in the CSV. The report period was read once.

### What a token_cost saving would need (owner decision pending)

1. **Characters to tokens (hypothetical).** Candidates: (a) the ledger's `recon.t0rag.coef_rag` = 0.338 tokens per retrieved-chunk character (OLS over 8,495 turn-0 single-call billed RAG requests; evidence class *hypothetical reconstruction*); (b) chars/4 = 0.25 (the repo's reference estimate, not a measurement); (c) exact counts with each model's tokenizer (`adapters/tokenizers`) in a local pass like option B, tokens only. Any of them is labelled hypothetical with its source. Whether Metis sent the duplicates at all is unknown (U-04).
2. **Price basis per baseline.** `as_logged` is in recorded units. `block_token_cost` mixes input, output, cached and other cost, so a per-row input price would have to be implied, for example from the logged model's price ratios. 150,089 of 245,518 LLM rows have no price for their logged model, so they stay unknown. The three repriced baselines (price-file units) would lower the effective input by the saved tokens and reprice with the same tier rule, so a lower input can drop a context tier. Two choices are open: whether the saved tokens come out of the cached part or the uncached part (Review Focus 3), and whether multi-call requests save once or once per call.
3. **Helper.** `levers.py` has no tokens-to-cost helper. `combine` and `summarise_slices(before, after)` give the per-block saving once the version lowers `block_token_cost`. The repricing (`baselines_full._tokens`, `_reprice`) is private. A version should not call it, so a public repricing helper in `baselines_full.py` (a shared file) would need the team's OK. The plan's `input_tokens` column does not exist; the real column is `a_bill_inputTokens`.

- **Open:** the conversion and price-basis choice above; the quality of a dropped copy is not measured (FR-CTX-03).
