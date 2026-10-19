# Context-reduction experiment plan (Stage 8)

Status: **planned**; `pass_through` is the only context strategy, and nothing is promoted without a quality-preserving ablation (FR-CTX-03). The `context_strategy` candidate slot exists (framework.md §4). Thresholds marked *proposed* are **confirmed as provisional placeholders** (Q-38, 2026-10-19): every run reports its measured values against all of them, and they are revisited with the full dataset. Last updated 2026-10-18.
Framework: [framework.md](framework.md). Architecture: [context_construction.md](../architecture/context_construction.md). Requirements: FR-CTX-01…05, H-1, H-2; owner brief [§9](../project/live_testing_and_demo_brief.md#9-context-reduction-in-the-demo).

## 1. Why, and what the sample suggests (provisional, ADR-0008)

Measured on the sample in Stage 8 (sizes only, `reports/cost/overhead-2026-10-18-sample-sizes-*.json`): instructions are present on 400 of 465 cases, median 3,578 characters, p95 79,050, max 271,155; history median 490 characters (p95 8,711) over a median of 4 turns; retrieved context on 71 cases, median 1,472 characters; the message median is 29 characters. Under the assumed composition (`logged_full`), **instructions dominate input tokens**, then history. The real composition sent to providers is unknown (A-03, TODO-04), so every result is conditional on that assumption.

Two different levers:
- **Send fewer tokens** (this plan): compress history and retrieved context, window history, deduplicate instructions.
- **Pay less for the same tokens**: the provider's prefix cache (caching plan C5). Compressing or reordering the stable prefix can **break** provider caching, so every compression result is reported with and without the provider-cache model.

## 2. Ablation protocol (every strategy)

- **Arms:** `pass_through` (control) vs the strategy, on the same cases, the same target model, and the same answer source.
- **Quality:** judge score and non-inferiority within δ (−3 % overall, −5 % per stratum, Q-13), primary; agreement with the pass-through answer, secondary. Answers must be real (`recorded` / `live`): **both arms are generated**, because a compressed input changes the answer. Logged answers cannot serve as the treatment arm.
- **Cost:** the `compression_saving` term of the savings decomposition (brief §6) at the target's price, net of the compressor's own cost.
- **Overhead:** compression time counts against the 100 ms p95 budget (brief §9), measured on CPU with the hardware recorded.
- **Strata:** opaque category, language (Persian / English / mixed), turn depth, retrieved context present.
- **Data:** synthetic sessions in the sample's shape first (long instructions, multi-turn, Persian-dominant, marked synthetic), then sample cases only with the owner's per-run approval (ADR-0018), then the full dataset.
- **Estimate before any live call;** the 10 USD lifetime cap covers generations and judge calls.

## 3. Strategies

| ID | Strategy | Applies to | Notes |
|---|---|---|---|
| X1 | **History window**: last *N* turns (N ∈ {0, 2, 4, 8}) or last *T* tokens | history | The cheapest. Changes the cache key's history component too (caching plan C1b). |
| X2 | **History summary**: earlier turns summarised by a cheap model | history | The summary is a model call: a measurement (P-1), its cost is overhead, and it can be cached per session prefix. |
| X3 | **LLMLingua-2** compression | history, retrieved context | Token classification over an XLM-RoBERTa-large encoder (`microsoft/llmlingua-2-xlm-roberta-large-meetingbank`). Its training data is the English MeetingBank set (brief §9), so **Persian quality is unknown: measure it**. Heavy dependencies (torch, transformers, llmlingua) go in an optional extra, never the runtime lock. Model card, licence, and version to be checked and recorded before use. |
| X4 | **Original LLMLingua** (perplexity-based, a small causal LM) | history, retrieved context | Heavier and slower; an optional comparison arm (brief §9). Persian depends on the small LM's tokenizer and training data: check before use. |
| X5 | **Retrieved-context trimming**: top-*k* items, or a token budget, by the caller's order or score | retrieved | Items flagged `possibly_truncated` (A-14) are reported as a stratum. |
| X6 | **Instruction handling**: (a) exact deduplication within a request; (b) keep instructions verbatim but first (for the provider cache, C5); (c) instruction compression | instructions | **Never compress instructions by default** (brief §9). (c) is only an experiment arm, and a decision record backed by ablation evidence is needed before it could ever serve (context_construction.md §5). |
| X7 | **Overflow trim** (the existing rule): drop the oldest turns, then the lowest-ranked items, only when the input does not fit | history, retrieved | Not a saving strategy: the context-overflow path (A-41). Measured for how often it triggers. |

For X3 and X4, each target component is compressed separately at rates 0.33, 0.5, and 0.7 (kept tokens); the current message is never compressed.

## 4. Persian quality and overhead

- **Token-level check** (no model call): compression rate achieved per language, measured with the target's tokenizer (o200k, DeepSeek, MiMo), because a rate in the compressor's tokens isn't a rate in billed tokens.
- **Answer-level check:** the ablation (§2) per language stratum. A strategy that passes overall but fails the Persian stratum fails.
- **Overhead:** p50 and p95 per call on CPU by input length (1K, 10K, 50K characters), including model load (reported separately, once per process).

## 5. Hypotheses, success, and kill criteria

- **H-1:** stable-prefix handling (X6 b) and provider caching save more than compressing instructions (X6 c) would, at no quality risk.
- **H-2:** history windowing or compression (X1–X4) reduces input tokens by ≥ 30 % on multi-turn sessions (proposed) with non-inferior quality.
- **Success (proposed, Q-38):** net saving ≥ 15 % of input cost on the affected strata, quality non-inferior within δ overall **and** in the Persian stratum, overhead p95 ≤ 100 ms including compression. Then promotion (repository_structure §6.2) with a decision record.
- **Kill:** X3/X4 failing the Persian stratum at every rate, or overhead p95 > 100 ms on CPU at the typical length; X1 failing non-inferiority at N = 4 (then history matters, and only X2 remains).

## 6. Data needs

Recorded answers for both arms (live generation under the budget); a judge calibrated on Persian (TODO-05); the actual prompt composition (TODO-04), which would replace the `logged_full` assumption; the language detector (FR-FEAT) for strata.
