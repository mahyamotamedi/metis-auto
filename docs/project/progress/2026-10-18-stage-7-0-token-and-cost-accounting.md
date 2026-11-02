## Stage 7 — Token & cost accounting (2026-10-18)

### Small fix first
- `.gitattributes`: `docs/references/*.csv -text`, so the byte-identical CRLF price extract is stored as-is. Checked: index and working tree both CRLF, sha256 unchanged (`15197ad9…4178`).

### Research (sources and dates in [token_accounting.md §2](../../architecture/token_accounting.md#2-tokenizers-supported-models-methods-fidelity); all checked 2026-10-18)
- **OpenAI** (gpt-5-nano, gpt-4.1-nano, gpt-4o-mini, gpt-5.4): tiktoken 0.14.0 maps all four to `o200k_base`; exact local. gpt-5.4 rests on tiktoken's `gpt-5` family mapping; OpenAI's model page names no tokenizer (A-53, Q-31).
- **DeepSeek** (deepseek-v4-flash): the model's own `tokenizer.json` on Hugging Face (MIT, pinned revision); exact local (A-54). Its chat template comes from the repository's `encoding/README.md`.
- **Grok** (grok-4-1-fast): no public tokenizer. Grok-2's is a different model; a tokenize-text endpoint is unverified and not in the wrapper docs. **Labelled chars/4 approximation.**
- **gpt-5.4 long context:** OpenAI's page says ">272K input tokens … 2x input and 1.5x output for the full session"; Metis says "≤ 270K". The conservative reading is chosen (§ below).
- **Reasoning:** OpenAI's reasoning guide confirms hidden reasoning tokens are billed as output and not visible.

### Outputs
- **Contracts** (schema `0.2` → `0.3`): `TokenUsage` (cache writes, TTL variant, template overhead, consistency checks); `Cost` (`price_tier`, `caveats`); `PriceEntry` (context tier fields, uncertain bound, `cache_ttl`; overlap check in `PriceTable`); `TokenType.CACHE_WRITE`; new `ChatTemplate`, `AccountedUsage`, `SavingsDecomposition` (validates the exact sum), `TermValue`, `DecompositionTerm`, `CostCaveat`. `contracts_reference.md` regenerated.
- **Domain** (`domain/accounting/`): `cost.py` rewritten (uncached / cached / cache-write / output prices, tier by input tokens over the whole call, caveats, `provider_cache_discount`, overhead in the pre-call estimate); new `overhead.py`, `baseline.py` (brief §5), `savings.py` (brief §6, plus the explicit `extra_cost` remainder).
- **Application:** new `application/accounting/service.py` (`AccountingService.account`, `.premium_estimate`, `.decompose`); `MeasurementService` gains chat templates, `overhead_for`, and overhead in `counted_usage`; `request_roles`. The pipeline adds framing overhead to counted usage and to the spend guard's estimate.
- **Adapters:** `tiktoken_backend.py`, `hf_backend.py`, `assets.py` (sha256 check; no download ever).
- **Settings and wiring:** `TokenizerTable`, `TokenizerSpec`, `TokenizerAsset`; `paths.tokenizer_assets`; `[reference] tokenizers`; the reader handles tiers and cache-write variants, rejects unknown price keys, and checks every `tokenizer_ref`. Stage 6's `PendingPriceRow` is removed. `wiring/tokenizers.py` builds the backends with a labelled fallback. `build_pipeline_from_settings` injects tokenizers and templates; new `build_accounting_service`.
- **Config:** new `reference/tokenizers.toml`; prices `-s7` (gpt-5.4 tiers; no amount changed); catalogue `-s7` (tokenizer refs; verified `hidden_reasoning_billed_as_output` on gpt-5-nano and gpt-5.4).
- **Dependencies:** extra `tokenizers` (tiktoken 0.14.0, tokenizers 0.23.2), in the dev lock only; existing pins unchanged; `constraints-min-age.txt` keeps new packages ≥ 2 weeks old (ADR-0001 update).
- **Scripts:** `fetch_tokenizer_assets.py` (the one network step; `--check`); `measure_overhead.py` (brief §11); `estimate_sample_tokens.py` (optional item; aggregates only).
- **Reports:** [reports/cost/](../../../reports/cost/README.md): overhead runs (7 JSON files) and `sample_token_estimates.json`.
- **Docs:** [token_accounting.md](../../architecture/token_accounting.md) (new); [ADR-0020](../../adr/0020-token-and-cost-accounting.md); ADR-0001 and ADR-0019 updates; contracts.md, providers.md, configuration.md, overview (CMP-12), module_reference (12 rows), architecture README, docs index, local development guide, README, config README, GLOSSARY (8 terms), `CLAUDE.md` (one pointer and rule), register.
- **Tests (+55 test cases, 4 updated):** `tests/unit/adapters/test_adapters_tokenizers.py` (Persian, English, mixed, code: pinned counts per tokenizer; counts differ by tokenizer; chars/4 off by script; the asset and fallback rules), `tests/unit/domain/test_domain_accounting_stage7.py` (tiers at 270,000 / 270,001 / 276,480 / 276,481; cached input; cache-write variants; caveats; provider-cache discount; templates; pre-call estimate; premium estimate; decomposition miss, hit, unknown, session, invalid sum), `tests/integration/test_accounting.py` (pipeline miss and hit decomposed exactly; the service on the Metis catalogue), settings tests for tiers, cache-write variants, overlap, unknown keys, and tokenizer refs; contract examples and privacy list extended.

### Key results
- **chars/4 is only an approximation, and its error depends on the script** (synthetic texts, pinned): Persian −17 % vs o200k and −35 % vs DeepSeek; code about −30 %; English +6 to +10 %. On the sample's text fields (estimates, ADR-0008): Arabic-script −20 to −29 % (o200k) and −33 to −40 % (DeepSeek); DeepSeek needs 13–21 % more tokens than o200k for Arabic-script text.
- **Overhead (A-38 re-measured):** p95 ≤ 0.17 ms per miss with exact tokenizers on short synthetic requests; with 40,000-char synthetic instructions, 0.96 ms (o200k) and 7.06 ms (DeepSeek). All far inside 100 ms. Counting long instructions dominates ([reports/cost/README.md](../../../reports/cost/README.md)).
- **gpt-5.4 is priced** (A-52 resolved): standard tier ≤ 270,000 input tokens, long tier above; 270,001–276,480 flagged.

### Validation
- **Full suite: 447/447 pass** offline in the venv, warnings as errors (392 before + 55). With the tokenizer files moved away: 439 pass, 8 skip, each saying why. With the optional libraries hidden: every exact ref falls back to the labelled approximation.
- ruff check and format clean on the whole repository.
- Import rules pass unchanged (tokenizer libraries only in `adapters/tokenizers`); module reference matches the code.
- No Mermaid diagram changed.
- Raw sample data unchanged (sha256 `e0f56a2f…49e1`); `estimate_sample_tokens.py` only reads it.
- No live call, no `.env` access. Network use: PyPI and Hugging Face metadata, OpenAI, DeepSeek, and xAI documentation pages, and downloads of the two public tokenizer files.

### Decisions and drift
- [ADR-0020](../../adr/0020-token-and-cost-accounting.md). Defaults chosen and stated: strict fidelity (framing makes counted inputs `approximation`); 270,000 conservative reading; `extra_cost` term so the decomposition sums exactly; Grok on chars/4 rather than Grok-2's tokenizer; tokenizer files fetched and pinned, not vendored; label mapping moved to Stage 8.
- Drift fixed: configuration.md, providers.md, contracts.md, and ADR-0019 described pending tiered rows and a provisional price schema.

**Assumptions added:** A-53…A-56. A-38 re-measured; A-52 resolved. **Questions:** Q-31. **TODOs:** TODO-12 (Stage 7.5 checks); TODO-02 updated.

**Carried into later stages:**
- **Stage 7.5:** TODO-12, comparing local counts with provider-reported usage (framing, DeepSeek, Grok's error, cached and reasoning reporting, DeepSeek and Grok hidden reasoning); A-55 (message layout) when the adapter is written; then tokenizer and catalogue configuration only.
- **Stage 8:** label mapping and the as-logged baseline; savings per baseline in `ResponseMetadata`; a per-fingerprint token-count cache if realistic sizes need it; structured-input counting.
- **Demo milestone:** show `AccountingService.decompose` per message and `sum_decompositions` per session, with the baseline caveats.
- **Stage 10 roadmap:** a tokenizer-fetch step in the `dev` image.

**Exit criteria:** "Tests pass offline; adding a new model or price requires only configuration or a small adapter." **Met.** 447/447 offline (the tokenizer files are fetched once at setup, like packages; without them the exact tests skip, never download). A model or price is catalogue, price, and tokenizer-table rows (token_accounting.md §4); a new tokenizer format is one adapter plus one enum value.

### Stage 7 follow-up — answer to Q-31 (2026-10-18)

| Question | Status | Answer |
|---|---|---|
| Q-31 | answered | Accepted: tiktoken's `gpt-5` family mapping (`o200k_base`) counts `gpt-5.4` as `exact_local`, with the source recorded (A-53, now decided). The premium cost stays labelled an estimate. |

**Changes:** register (Q-31 answered, A-53 decided), ADR-0020 (status and decision point 1), token_accounting.md (§2 row, §9 open items), docs index (ADR-0020 row), and this file. No code or configuration changed: `config/reference/tokenizers.toml` already applied this default.
