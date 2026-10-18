# ADR-0020: Token and cost accounting — tokenizers per family as configuration, strict fidelity, tiered prices, a labelled premium estimate, an exact savings decomposition

- Status: **decided** (methods, rules, schema). Chat templates and the Grok approximation are **provisional** until the Stage 7.5 live check compares them with provider-reported usage. The gpt-5.4 tokenizer mapping was accepted by the owner on 2026-10-18 (Q-31).
- Date: 2026-10-18
- Resolves: A-52 (gpt-5.4 price tiers, the "270K" reading); contracts.md O-3 except the label mapping (moved to Stage 8); the Stage 7 items of the [owner brief](../project/live_testing_and_demo_brief.md) §12.
- Relates to: FR-ACCT-01…06, H-7, ADR-0002, ADR-0006 pt 3, ADR-0008, ADR-0017, ADR-0018, ADR-0019, MP§3.8
- Detail: [token_accounting.md](../architecture/token_accounting.md)

## Context

Stage 6 left accounting with a chars/4 approximation for every model, input and output prices only, and gpt-5.4's tiered prices kept aside, so its cost was "not computed". The brief needs: tokenizers for the six catalogue models, cached input, cache writes, and context tiers in the price schema, a premium-baseline estimate that never calls the premium model, and a savings decomposition that sums exactly. The sample is mostly Persian, where tokenizers differ most (A-08). Every fact must be sourced, and nothing may pretend to be exact when it isn't (MP§3.8).

## Decision

1. **Tokenizers are configuration per family** (`config/reference/tokenizers.toml`), linked from the catalogue's `tokenizer_ref`. Each row names a backend (`tiktoken` encoding, Hugging Face `tokenizer.json`, or `approx_chars`), its fidelity, and evidence with a check date. For the six models: `o200k_base` via tiktoken for the four OpenAI models (exact_local, from tiktoken's model map; gpt-5.4 by its `gpt-5` family mapping, A-53, accepted as exact_local by the owner, Q-31); DeepSeek-V4-Flash's own `tokenizer.json` (exact_local, A-54); **chars/4 for grok-4-1-fast** (approximation: no public Grok 4 tokenizer exists).
2. **Libraries in an optional extra, files fetched once.** `tiktoken` and `tokenizers` are imported only in `adapters/tokenizers/`, in the `tokenizers` extra (dev lock yes, runtime lock no). Tokenizer files are downloaded only by `scripts/fetch_tokenizer_assets.py`, pinned by sha256, stored git-ignored, and re-checked before each load. Nothing downloads at run time or in tests. A missing library or file falls back to chars/4 **labelled as approximation** for that ref.
3. **Strict fidelity.** A sum's fidelity is its worst part. Chat-template framing is an approximation until verified against provider-reported usage, so counted inputs are `approximation` even with exact content. `template_overhead` is reported separately so the difference stays visible.
4. **Usage inclusion rules.** `input` includes cached input, cache writes, and template overhead. `output` includes hidden reasoning. Adapters map provider formats onto these rules.
5. **Price schema.** Token types `input`, `output`, `cached_input`, `cache_write` (with TTL variants), and `reasoning` (unused). Optional context tier with inclusive input-token bounds. The tier is **chosen by the call's input tokens and prices the whole call** (OpenAI's "full session" rule). Overlapping tiers are rejected. An optional `max_input_tokens_uncertain_up_to` marks an ambiguous bound.
6. **gpt-5.4 "≤ 270K" = 270,000 input tokens** (the conservative reading: never priced below the bill). 270,001–276,480 is priced long-tier with the caveat `context_tier_boundary_uncertain`.
7. **Cost caveats** are part of `Cost` (`reasoning_not_counted`, `answer_length_assumed`, `template_overhead_approximated`, `context_tier_boundary_uncertain`, `cached_input_not_reported`), so a figure is never shown without its known biases. Hidden-reasoning lower bounds apply only to models with a **verified** `hidden_reasoning_billed_as_output` capability (gpt-5-nano, gpt-5.4).
8. **Premium baseline = an estimate, never a call:** the full uncompressed context counted with the premium tokenizer, plus framing, no provider cache; output = the served answer re-counted with the premium tokenizer. Labelled `baseline_estimate`, with caveats.
9. **Savings decomposition** in the brief's order, plus an explicit **`extra_cost`** remainder (Metis overhead, extra attempts, count differences) so `premium − routing − compression − cache − provider cache + extra = paid` holds exactly in `Decimal`. Per message, summed per session; unknown inputs make dependent terms "not computed". The contract validates the identity.
10. **Contracts 0.2 → 0.3:** `TokenUsage` gains `cache_write`, `cache_write_ttl`, and `template_overhead` (with consistency checks); `Cost` gains `price_tier` and `caveats`; `PriceEntry` gains the tier fields and `cache_ttl`; new `ChatTemplate`, `AccountedUsage`, `SavingsDecomposition`, `TermValue`, `DecompositionTerm`, `CostCaveat`. The Stage 6 `PendingPriceRow` workaround is removed.

## Alternatives considered

- **Provider token-counting APIs.** Exact for the provider, but network, budget-consuming, not documented for the Metis wrapper, and unusable for the never-called premium model. Rejected as the default; any future one is an opt-in backend.
- **Vendor the tokenizer files in git** (≈10 MB). Fully offline from a fresh clone, but it bloats the repository with third-party binaries, and the licence and attribution would need tracking per file. Rejected: a pinned, hashed fetch step is reproducible and keeps git small. Revisit if the fetch step causes friction.
- **Let tiktoken download on first use** (its default). Simple, but it is silent network access at run time and in tests. Rejected.
- **Grok-2's published tokenizer as a Grok 4 proxy.** It comes from the same vendor, but there is no evidence it matches Grok 4, and it uses a custom format with its own loader. Rejected; chars/4, clearly labelled, until reported usage exists.
- **Label overhead-inclusive inputs with the content's fidelity** (exact). The label would look better, but it would be untrue for the framing tokens. Rejected (point 3).
- **Read "270K" as 276,480 or 272,000.** Either might match the bill, but neither is stated by the Metis page. Rejected for the conservative reading plus a caveat.
- **Marginal tier pricing** (only tokens above the threshold at the long rate). Rejected: OpenAI states the full-session rule.
- **Only the brief's five terms.** Rejected: with retries, escalations, or count differences they can't sum exactly. The extra term keeps the brief's order and shows the remainder instead of hiding it in another term.

## Consequences

- Adding a model or price needs configuration only. A new tokenizer format is one small adapter (token_accounting.md §4).
- Fresh clones run `scripts/fetch_tokenizer_assets.py` once (guide §2). Without it, tokenizer tests skip and counts are approximations, and both say so. The Docker images do not contain the files (they are git-ignored data, `.dockerignore`), so the container counts with the approximation until a fetch step is added there (Stage 10 roadmap).
- Overhead stays far below the budget on synthetic requests. Large instructions make counting the dominant cost, especially with the Hugging Face tokenizer (reports/cost/README.md).
- Stage 7.5 must verify the templates, cached and reasoning token reporting, and Grok's count error, against provider-reported usage, and record the result.
- The as-logged baseline's label mapping moves to Stage 8.
