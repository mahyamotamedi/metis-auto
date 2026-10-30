# Evaluation Framework: Cost, Latency, Quality (research-backed spec)

Status: **proposal, provisional** (2026-10-30). Extends [evaluation.md](../architecture/evaluation.md), [ADR-0006](../adr/0006-evaluation-metric-definitions.md), [ADR-0002](../adr/0002-configurable-baselines.md), [ADR-0014](../adr/0014-counterfactual-answers-via-model-client.md), [token_accounting.md](../architecture/token_accounting.md). Requirements: FR-EVAL-04/06/08/09, FR-ACCT-05/07, G-1…G-7.

**Evidence labels.** *[proven]* = measured in a cited paper or by us. *[claim]* = vendor or secondary-source statement. *[ours]* = our design or arithmetic, not a literature result. *[verify]* = must be re-checked before use. Literature search was one pass of web searches on 2026-10-30; several points are marked unverified rather than guessed. No prices, token counts or Persian numbers below are measured by us; they come from config or from the sampling run in §5.

---

## 0. Persian-first requirements (added 2026-10-30)

The sample is mostly Persian-script (about 91% of user messages, provisional per ADR-0008), so the overall numbers are Persian numbers. These rules apply to every later section. **Every numeric threshold or size in this document is a planning placeholder or a configuration decision, not a validated value; none is a statistical guarantee.** Unresolved values are listed in §9 and must be set explicitly in `config/`, with no hidden defaults.

**0.1 Persian-first reporting and language classification.** The primary reporting slice is **Persian-only**. Overall results are shown second and labelled "dominated by Persian". English and mixed-language results are reported **separately**, each with its n, its interval, and an explicit label ("insufficient", "low confidence") whenever n is below the configured minimum. Minority slices are never pooled into Persian to look larger, and no ranking or significance claim is made for a slice below its minimum. The language label is itself a classification with error: it is derived from script-letter shares (thresholds are configuration, unresolved), Arabic-script text is not automatically Persian (Arabic and Urdu use the same script; Persian-specific letters are a candidate cue, an open decision), and the classifier is tested on synthetic strings and spot-checked against human labels before use.

**0.2 Sampling allocation is not population weighting.** *Allocation* decides how many requests we draw per stratum, and may deliberately oversample minority languages to give them usable precision. *Weighting* rescales sample results to the population, using stored inverse selection probabilities. Both are recorded. Population-level totals and the overall figures use weights; per-stratum comparisons are made within the stratum. Oversampling improves a minority slice's precision but does not change its population share. Quotas (Persian share, minimum per minority language) are configuration. If the data or budget cannot meet a quota, report the achieved n and mark the slice insufficient. Never describe a result as statistically reliable unless its n meets the configured minimum and a confidence interval is shown.

**0.3 Shared Persian text normalization (one tested component).** The original text is always preserved. Normalization produces **derived views** tagged with a `normalizer_version`, and the model-bound or judge-bound text is never altered by the aggressive view.
- *Non-destructive view* (display and model-bound): Unicode NFC only, unless a decision adds more.
- *Match key* (one-way, used for comparison and grouping only): Arabic Yeh (U+064A) and Alef Maksura (U+0649) → Persian Yeh (U+06CC); Arabic Kaf (U+0643) → Persian Kaf (U+06A9); Persian digits (U+06F0–06F9) and Arabic-Indic digits (U+0660–0669) → one canonical digit form; bidirectional control marks (U+200E, U+200F, U+202A–202E, U+2066–2069) removed; whitespace collapsed. The **zero-width non-joiner (U+200C) is not stripped by default** because it is meaningful in Persian orthography; whether a key treats it as equal to a space is an explicit option.
- *Mixed right-to-left text:* operate on logical (stored) order only, never reorder, leave Latin runs untouched.
- *Open decisions:* diacritics (tashkeel) and tatweel stripping in the key; Latin case folding in the key; whether the key hashes feed ADR-0015's keyed fingerprints.
- *Where applied:* duplicate-prompt grouping, replay-case fingerprints, leakage-safe train/test splits, and the **evaluation-side** analysis of cache candidate matches (how much normalization changes the candidate-hit set). **Not applied to the production cache key or lookup**: that change would alter ADR-0011/0015 behavior and needs its own ADR and approval.

**0.4 Persian judge calibration and gate.** The calibration set is predominantly Persian (the Persian share and total size are configuration), rated by Persian-speaking humans. The agreement measure and the **minimum agreement threshold are configuration with no default** (which agreement statistic to use is an open decision). A judge's scores are labelled **unvalidated** in every report unless the Persian gate passes; English and mixed slices have their own gates and will usually stay unvalidated for lack of items. Unvalidated scores may be shown but never used to claim quality parity, non-inferiority, or oracle labels.

**0.5 Length measurement.** Length buckets are defined on a **tokenizer-neutral** quantity: Unicode characters of the non-destructive view (whether code points or grapheme clusters is an open decision), with boundaries in configuration. Every bucket is compared with token counts: per catalogue tokenizer, the distribution of tokens and tokens per character in the bucket, and the share of requests that would change bucket if buckets were defined by tokens instead. Interpretation rules: character counts are a descriptive feature of the text; token counts are the billed quantity and are tokenizer-specific (measured Persian token-per-character ratios differ by up to about 1.7× across the three exact tokenizers, §2.1); a **verbosity ratio in characters** says how long the visible text is relative to the logged answer and must be converted to tokens with the target model's tokens-per-character for that script and stratum before it prices anything; neither measure sees hidden reasoning tokens.

**0.6 Judge-instruction language comparison.** Run the judge with Persian instructions and with English instructions on Persian and on mixed-language answers. Report, separately for each (instruction language × answer language) cell: human agreement, swap-consistency, and bias diagnostics, each with n and an interval. Do not assume either instruction language is better; record the chosen language in the manifest only after the results exist, and say plainly if the available n cannot distinguish them.

**0.7 Persian model-quality comparison.** The sampling run outputs a table of catalogue models on Persian requests, with columns reported separately and never merged into one score: quality (labelled validated or unvalidated per §0.4), cost, latency (time to first token and total), sample size, and uncertainty. This table decides the cheapest-acceptable baseline and the oracle, so it is produced before those baselines are used for Persian claims.

**0.8 Provenance labels.** Every reported number carries one of: **measured** (provider-reported usage, observed latency, human or validated judge ratings), **estimated** (local tokenizer counts, price-table arithmetic, fitted predictors), or **simulated** (scenario assumptions, fake or replayed sources).

---

## 1. Baselines

| Baseline | Answers the question | Strength | Weakness |
|---|---|---|---|
| (a) **Premium model, always** | "How much cheaper than the quality ceiling?" | The brief's headline comparison; defines 100% quality and 100% cost. | A single model is not the ceiling on every stratum. Premium may over-think simple prompts, so its cost is inflated by reasoning tokens. Premium answers must be sampled (not in logs). |
| (b) **As-logged** (status quo) | "Does the system beat what customers do today?" | Needs no new answers for quality reference; the only baseline grounded in real choices. Already mandatory (ADR-0002). | The logged model was chosen per session by unknown rules and may be neither cheap nor good. Label→catalogue mapping fidelity matters (FR-ACCT-07). Cost needs estimated tokens (no counts logged). |
| (c) **Cheapest acceptable, always** | "Is routing even needed?" | The honest floor. If it is within δ of premium on most strata, routing adds little. | "Acceptable" must be defined by the judge and δ (Q-13), so it is circular without calibration. |
| (d) **Oracle router** (hindsight) | "How much saving is achievable at all?" | Upper bound; turns router quality into a fraction of the available headroom. | Needs every candidate's answer and score on every request (affordable only on the shared sample, §5). Judge noise inflates it (the max of noisy scores is biased upward). Report it as a bound, never a target. |

**Recommended set:** all four, reported together: **(b) as primary "does it help" baseline, (a) as quality ceiling and cost reference, (c) as floor, (d) as headroom**, plus a **random router matched to the candidate's model mix** (isolates routing skill from simply using cheaper models). Premium and cheapest are *configuration* (ADR-0002); name the actual models and the price-table version in every report.

**How the routing literature reports results**

- RouterBench defines the oracle as routing to the best-performing model, choosing the cheapest on ties, and summarises cost–quality curves with a single area score (AIQ). *[proven; paper: [arXiv 2403.12031](https://arxiv.org/pdf/2403.12031)]*. Secondary summaries disagree on the exact AIQ expansion, so *[verify]* against the paper before reusing the formula.
- RouteLLM reports performance-gap recovered (PGR: where the router sits between the weak and strong model), APGR (the average of PGR over ten call-percentage points of the call-performance curve), and CPT (the minimum share of calls to the strong model needed to reach a target performance). *[proven; [arXiv 2406.18665](https://arxiv.org/pdf/2406.18665)]*. Headline savings there use preference-based benchmarks; transfer to Persian chat is untested *[ours]*.
- RouterArena adds optimality (cheapest correct model), robustness, and latency, and notes that earlier benchmarks (RouterBench, RouterEval) report only accuracy or deferral curves; RouterEval records are explicitly cost-blind. *[proven; [arXiv 2510.00202](https://arxiv.org/html/2510.00202), [arXiv 2503.10657](https://arxiv.org/pdf/2503.10657)]*. Leaderboard scores change, so *[verify]* before quoting.

**What we report (metrics, adapted to ADR-0006):**

1. **Cost–quality Pareto curve** of the candidate across its threshold settings, with the baselines as points.
2. **Quality at matched cost** and **cost at matched quality** (the CPT idea): "cost to reach ≥ premium − δ".
3. **PGR/APGR-style recovery** between floor (c) and ceiling (a): `PGR = (Q_router − Q_cheap) / (Q_premium − Q_cheap)`. Undefined when the gap is near zero; report the gap beside it.
4. **Oracle headroom captured:** `(cost_premium − cost_router) / (cost_premium − cost_oracle)`.
5. **Non-inferiority** versus premium and versus as-logged at margin δ (Q-13), per stratum.
6. Agreement, judge score and hit correctness stay separate, as in ADR-0006.

---

## 2. Cost measurement and simulation

Cost of a request = `Σ price_tier × tokens` over input (uncached, cached-read, cache-write), visible output, and reasoning, plus **our own overhead** (router, embedder, detector/judge calls, compressor compute). Everything is computed from events and the versioned price table (FR-ACCT-05).

### 2.1 Input cost

- **Tokenization.** Count the assumed composition (instructions + history + RAG + user) with each catalogue model's tokenizer; this exists since Stage 7 (ADR-0020). Where a tokenizer is not exact, label it approximate. Persian non-Latin script is generally token-expensive and varies by tokenizer; published work on a "token tax" for under-represented languages exists (e.g. [arXiv 2509.05486](https://arxiv.org/html/2509.05486), [arXiv 2510.09947](https://arxiv.org/pdf/2510.09947v2)) but my search found **no Persian-specific cross-vendor figures**. So: **measure it ourselves.** Take the sample's Persian user messages and instructions, count tokens per catalogue model, and report tokens per character and the model × model ratio per stratum. Then recompute cost rankings with and without per-model token counts to show how much ranking changes *[ours; run as a cheap offline experiment, no API calls except where a vendor's token-count endpoint is the only exact tokenizer]*.
- **Measured on the sample (2026-10-30, offline, `scripts/estimate_sample_tokens.py`, sample sha256 unchanged; provisional per ADR-0008).** Tokens per 1,000 characters, aggregates only. Arabic-script bucket (a letter-share heuristic, not language detection): o200k (GPT family) 357 on user messages, 353 on answers; DeepSeek V4 405 / 415; MiMo 571 / 578. Latin-script text is 223–243 on o200k and within about 8% across the three exact tokenizers. So on Persian, DeepSeek is about **1.14–1.18×** and MiMo about **1.60–1.74×** the o200k count for the same text (user messages, answers, retrieved items, instructions), a much larger gap than on English. chars/4 undercounts Persian by 21–29% against the exact tokenizers (it is accurate to within a few percent on English). Grok has no exact tokenizer here (chars/4 only; the live check found it undercounted a small request by about 70%, Q-33), so **Grok is excluded from the ranking claims below**.
  **Effect on cost rankings** (input price × measured tokens, USD per 1M Persian characters, using the 2026-10-18 Metis price table; cached-input discounts ignored): on Persian user messages the exact order of the five exactly-counted models is gpt-5-nano 0.020 < gpt-4.1-nano 0.039 < gpt-4o-mini 0.059 < DeepSeek V4 Flash 0.067 < MiMo 0.088. Under chars/4, MiMo ranks third cheapest, ahead of gpt-4o-mini and DeepSeek; with the real tokenizer it is the most expensive of the five on input, despite a list price below DeepSeek's. Same-tokenizer models (the three OpenAI ones) keep their order. On Persian answers (output prices) MiMo's low output price still keeps it ahead of gpt-4o-mini and DeepSeek (0.178 vs 0.233 and 0.274 per 1M chars), but chars/4 would put it first of all, ahead of gpt-5-nano. **Conclusion:** per-model tokenizers are required for Persian cost comparisons; list price per token is not a valid ranking key. Not yet done: the same comparison on full prompts (instructions + history + RAG + user) per request, with cache discounts, and a ranking sensitivity per stratum.
- **Full-prompt input on the sample (Stage E3, 2026-10-30; `scripts/input_cost_report.py`, [report](../../reports/cost/README.md); provisional per ADR-0008, estimates, no real recorded usage).** Persian slice (n = 421 by the placeholder detector): mean assumed input of about 4,052 tokens (o200k family), 4,453 (DeepSeek, 1.10×) and 5,612 (MiMo, 1.38×); instructions about 56% of the input; 364 of 368 Persian cases with instructions share their literal instruction text with another case (72 distinct texts); no case reaches the long price tier. Input-only uncached lower bounds at the snapshot prices give about 0.022 USD per case for `gpt-5.5`. Ranking models by input cost with exact tokenizers versus chars/4 flips three pairs (gpt-4o-mini, deepseek-v4-flash, mimo-v2.5), so MiMo moves from third-cheapest to fifth. The sample's mean input (about 4,000 tokens) is consistent with the 4,500-token planning figure used for the budget estimate, which was a rough guess. Slices are `descriptive` until a minimum n is configured.
- **Prompt-caching discounts.** Instructions are long, heavily reused and sit at the prompt's start, so they are the natural cacheable prefix. Model it with the tier fields already in the price schema (cached input, cache writes). Parameters that change results: provider minimum cacheable prefix, cache TTL, whether discounts apply automatically or need explicit markers, and write surcharges. All are *[verify]* from the provider's current docs on the price-table date. Simulate hit state from logged session timing, but the logged timestamps have an unknown timezone (A-06), so run it as a scenario (hit rate 0 / measured / ideal), not as a point value.
- **Interaction with our own components:** compression or history trimming that edits the prefix **breaks** provider prefix caching. Every context-construction experiment must report cost with caching on, not only raw token reductions. This is a likely hidden loss *[ours]*.
- **Overhead:** `scripts/measure_overhead.py` already measures router/cache/embedder compute. Add per-call API cost for any LLM-based judge or detector at runtime, billed to request cost (evaluation judges are billed separately; evaluation.md §6).

### 2.2 Output and reasoning cost (the hard problem)

Unknowns: visible output length and hidden reasoning tokens for models not in the logs, and token counts even for the logged model. Options compared:

| Method | What it needs | Accuracy | Cost | Verdict |
|---|---|---|---|---|
| **A. Run a stratified sample through each candidate; record provider-reported usage** (input, output, reasoning, cached) | Live calls, budget | Ground truth for those requests; only sampling error remains | Highest, but bounded (§5) | **Primary.** The only method that observes reasoning tokens for the exact model, effort setting and prompts. |
| **B. Per-model predictive model of output/reasoning tokens from request features**, trained on A | A's data | Literature: length is partly predictable from the prompt. Probing and LLM-based predictors report competitive MAE ([ICLR 2026 EGTP, InferLength](https://github.com/vastava/InferLength); [arXiv 2508.00912](https://arxiv.org/pdf/2508.00912) for hidden reasoning tokens; [Apple LenVM](https://machinelearning.apple.com/research/length-value-model)). These use the model's own hidden states or a trained estimator; the authors also warn static prompt-only estimates are unreliable where completions vary widely. *[verify]* the numbers; none were checked against Persian chat. | Cheap once A exists | **Secondary,** used to extrapolate from the sample to the full replay set; start with simple gradient-boosted or quantile regression on cheap features (lengths, language, turn depth, task flags, RAG, response length of the logged answer), not the hidden-state methods, which need model access we lack for API models. |
| **C. Verbosity ratio** `output_m ≈ r_m × logged_output_chars` (characters; convert to tokens per §0.5) | A's data (to fit r) | Fine for non-reasoning chat; breaks when reasoning dominates, when answers differ in format (code, structured output), or when the logged model refused/truncated | Free after A | **Fallback/baseline for B.** Report where B beats C; if it does not, use C. |
| **D. Public leaderboards** (e.g. [Artificial Analysis](https://artificialanalysis.ai/models/claude-sonnet-5-medium) publishes cost-to-run and reasoning vs answer token splits per model and effort setting) | Nothing | Measured on English benchmark tasks with their own task mix; versioned (their index version changes) | Free | **Sanity check and prior only.** Reasoning-token usage depends heavily on task difficulty, so benchmark averages transfer poorly to short, multi-turn Persian chat *[ours]*. Quote with version and date. |

**Recommendation:** A as the primary, B (quantile regression, per model × effort) to extrapolate, C as the baseline B must beat, D to cross-check. Always report which method produced each cost number (cost fidelity, ADR-0006).

**Reasoning effort / thinking budget.** Effort changes both cost and quality, and the same model at "low" and "high" effort is effectively two candidates with different price distributions (the Artificial Analysis pages list separate low/medium/high/xhigh entries for one model, which shows the spread is material *[claim, vendor-neutral aggregator]*). So treat **(model, effort)** as the routing action. Include at least two effort levels for each reasoning-capable candidate in the sampling run. If the sample shows that effort changes cost by a large factor with little quality change on easy strata, make effort a router output; otherwise fix a default per model. This is an experiment, not an assumption *[ours]*.

**Sample size for cost distributions.** Per (model, effort, stratum) cell:
- Mean cost: standard error `σ/√n`; for a heavy-tailed variable `n ≥ 100` gives a usable mean *only if* the tail is bounded; use a bootstrap and check by sub-sampling.
- p90 needs roughly `n ≥ 200`, p99 `n ≥ 1,000` per cell for a stable estimate (a p99 from 100 points is the max of the sample). *[ours: standard order-statistic reasoning]*. Don't report p99 for cells below that; pool strata (e.g. language × length only) for tail quantiles, and report totals (the budget quantity) by scaling the sample with stratum weights, whose precision is better than per-cell tails.
- Practical plan (§5): ~150–300 requests per major stratum cell, tail quantiles at the pooled level.

### 2.3 Reporting and uncertainty

- Report **median, p90, p99 and totals** per stratum, never only a mean.
- **Scenario table** (mandatory): rerun the headline comparison under (i) optimistic output/reasoning (p25 of fitted distribution), (ii) fitted median, (iii) pessimistic (p90), (iv) verbosity-ratio fallback, and (v) prompt-cache hit rate 0 / measured / ideal. Show which conclusions flip. A conclusion that survives all scenarios is "robust"; one that flips is "assumption-dependent". Show it as a small multiples chart (cost saving vs scenario) with bootstrap bands.
- **Prices are configuration** (`config/` price table, versioned). Record `price_table_version` and check date in every manifest. Keep separate rows for reasoning vs non-reasoning mode and **per serving provider** for open-weight models (the same open model can be priced differently by different hosts; the Metis endpoint's own price is what matters, [verify] against the wrapper docs). Add a CI/script check that flags a table older than N days (N configurable, suggest 30).

---

## 3. Latency

- **Components:** `overhead` (router, cache lookup, embedder, compression, verifier; measured offline today) + `TTFT` (time to first token) + `decode time` (output + reasoning tokens ÷ token rate) + `network`. Reasoning models can emit nothing visible for a long time, so **report TTFT and total completion time separately** and, for reasoning models, also "time to first *visible* token". For streamed demos the user-perceived latency is TTFT; for batch/API callers it is total. *[ours]*
- **Logged message timestamps are not latency** (naive times, unknown timezone A-06, include user think/typing time and gaps between turns, and possibly UI-side times). Do not use them for latency; use them only for ordering and (cautiously) cache-reuse timing.
- **Percentiles:** p50/p95/p99 with bootstrap intervals; p99 needs ≥1,000 calls per cell as in §2.2.
- **Live measurement:** a latency sample is its own run, separate from quality: fixed small prompts and real-length prompts, repeated across **time of day and weekdays**, from the deployment region, with randomized order across models (so drift hits all models equally), concurrency matching expected production, and a warm-up. Public benchmarks (Artificial Analysis publishes speed and latency per provider) are a prior, not a substitute: they measure their own prompts, region and load.
- **Routing/cache/compression overhead** is added to the model latency of the *same* request in the report, with the overhead measured on the actual hardware. A cache hit's latency = lookup + (optional verification), compared with the model path.
- **What to log instead:** monotonic clock timestamps at request received, route decision done, upstream request sent, first byte, first token, last token, response returned (see §7).

---

## 4. Offline replay for multi-turn conversations

Today's replay uses the **logged** history for each turn (evaluation.md §4). Options:

| Option | Fidelity | Cost | Bias |
|---|---|---|---|
| **Next-turn, original history** (teacher-forced) | Valid for *one* decision given a realistic context; the later user turns are real | Low | Ignores the candidate's effect on later turns; history contains the logged model's answers, which may be stronger/weaker/different in style than the candidate's. |
| Single-turn only (drop history) | Low: history dependence is the norm (every sampled session is multi-turn) | Lowest | Discards what routing and context-trimming need to be tested on. |
| **Full re-simulation with the candidate's answers and a simulated user** | Highest in principle | High: needs a user simulator (LLM), each candidate's full path; simulator quality for Persian unproven | Simulator drift; non-reproducible; judge noise compounds. |

**Recommendation:** teacher-forced next-turn as the **default for every run** (it is what `ReplayCase` does), and report it as *"decision quality given a realistic history"*. Add a **small (e.g. ≤ 50-session) full re-simulation study** later, only to estimate how large the teacher-forcing bias is (compare the two on the same sessions). Label the first as the headline limitation (it already is in each manifest). Do not use single-turn evaluation except for stateless cache experiments.

**RAG context:** replay the logged context (it is a feature of the logged answer's conditions), sample-run candidates with the *same* context so answers are comparable; report RAG vs non-RAG strata separately; do not re-retrieve. Judge prompts must include the context so that grounding is evaluated against what the model was given. **Images (~3% of user messages):** exclude attachment-bearing turns from candidates that cannot take images (report the count; FR-EVAL-08), or route only to vision-capable models and use a vision-capable judge; never judge image-dependent turns from text alone. Keep them as a separate stratum so the exclusion bias is visible.

---

## 5. One shared sampling run for cost calibration and quality

**Purpose:** each `(request, model, effort)` call produces (a) provider-reported usage and latency and (b) a candidate answer. Record both once (the `live` source wrapped by the recording decorator, ADR-0014); the cost model, the oracle, the judge and the router training/eval all read from this store.

**Hard constraints** (CLAUDE.md, ADR-0003/0018): live calls only on owner request; sample conversations need **per-run owner approval**; budget cap 10 USD lifetime / 20 USD ceiling; nothing from `data/sample_data/raw/` is written back; no message content in git or reports. **The budget therefore likely cannot fund the run below on the current cap**; treat this as the design for a larger, separately approved budget (Q-29), and the pilot (below) as what the current cap allows.

**Design** *[ours]*

1. **Frame.** Full dataset when available (~100k sessions); sample frame = user turns with a clean pairing flag.
2. **Strata:** opaque category (4) × language (Persian / English / mixed) × length bucket (3: short, medium, long by logged-prompt length) × turn depth (1, 2, 3+) × {RAG, no RAG} × {has attachments, no}. Do not fill every cell uniformly. Allocation is a configured rule (proportional with a per-cell floor, plus a minority-language quota per §0.2); the floor and quota values are configuration decisions, not set here. Rare cells are pooled and reported as pooled. Allocation (what we draw) and weighting (how results scale to the population) are stored separately.
3. **Size (planning placeholders only; set in config after the pilot; they guarantee no precision).** Pilot on the current sample: ~150–200 requests, 3 models. Calibration run: **~2,000 requests**: enough for ~100–250 per major (category × language × length) cell, p90 at the pooled level, and for pairwise judging at ±5–7 pp. A p99 study needs a separate heavy-tail top-up (~1,000 requests chosen by length / reasoning-prone features, weighted back by selection probability).
4. **Models and effort:** premium, status-quo logged model (mapped), cheapest acceptable, and 2–3 mid-tier candidates (8 models max). Add a second effort level (low and default/high) for reasoning-capable ones; skip effort sweeps for non-reasoning models. Names and prices come from `config/` at run time, not from this document.
5. **Replication:** one call per cell for answers; **repeat 3× on a 100-request subset** to measure within-model variance (needed to avoid attributing sampling noise to model differences).
6. **Record:** the usage fields in §7, effort setting, finish reason, truncation, latency (TTFT, total), provider, and model version, stored under `data/recorded/` keyed by case fingerprint × model × composition fingerprint (existing scheme).
7. **Judging** runs offline over the stored answers (separate cost, not billed to requests; opt-in): pairwise vs premium with **position swapped** and tie option; a calibration set of ~100–200 items rated by humans, ideally Persian-speaking (TODO-05), to estimate the judge's agreement and bias. Judges are known to have position and verbosity bias; I did not verify numbers in this pass *[verify]*, which is the reason for the calibration set and swapped order.

8. **Persian model comparison output** (§0.7): the run emits per-model rows on Persian requests with quality (validated/unvalidated), cost, latency, n and intervals as separate columns, plus the same table for English and mixed slices, each labelled with its sample-size limits. Judge-instruction-language results (§0.6) are emitted alongside.

*Implementation status (Stage E4, 2026-10-30):* the sampler, run plan, live guard and tables exist and are tested with fake clients only; no run has been made, no value below is configured, and the pilot is not approved. Config fields and what stays unset: [e4_sampling_run.md](e4_sampling_run.md).

*Implementation status (Stage E5, 2026-10-30):* pairwise judging with swapped orderings, the calibration tooling, agreement and bias diagnostics, the Persian gate and the instruction-language comparison exist and are tested with a deterministic fake judge only. No judge model is chosen, no human ratings exist, and the gate is unset, so every quality score is `unvalidated`. Details: [e5_judging.md](e5_judging.md).

**Cost formula (fill with config prices; do not trust placeholders):**

```
run_cost ≈ N_requests × Σ_models,efforts [ T_in(m) × p_in(m) + T_out(m,e) × p_out(m) ] + judge_cost
T_in  : measured from the assumed composition with that model's tokenizer
T_out : unknown, which is the reason for the run; plan with p90 of the pilot and a 1.5× margin
```

Run the pilot first and compute `T_out` percentiles from it. Then the main run's budget is set from observed numbers, not guesses. **Budget gate:** the runner estimates cost before the call and stops at a hard cap; the existing spend-guard covers un-computable costs (TODO).

**Stop rules:** halt a model if >10% of calls fail or truncate (inspect, don't silently drop); halt all if the realized cost exceeds 1.3× the estimate at 20% progress.

---

## 6. Reporting and statistics

- **Unit of analysis:** the request, paired across systems (same request, same history, same context). Use **paired** tests/intervals (paired bootstrap over requests; for sessions, **cluster bootstrap by session** because turns in a session are correlated). Resample sessions, not messages.
- **Quality comparisons:** win/tie/loss rates and mean score difference with 95% CI; **non-inferiority** `lower CI bound of (Q_candidate − Q_premium) > −δ`. Minimum n for a win-rate CI half-width d (worst case p = 0.5): `n ≈ 0.96 / d²`; d = ±0.10 → ~100, ±0.05 → ~400 per stratum (paired data can be somewhat smaller if the tie rate is high) *[ours: normal approximation; use bootstrap in code]*. Strata below the configured minimum n (a value to be set, §9) are shown as "insufficient", pooled, and never ranked. Persian-only is the primary view (§0.1).
- **Multiple comparisons:** with several strata and baselines, state the family of tests; use a Holm or FDR correction for "significant in stratum X" claims, or present intervals only. Don't tune routers to one stratum (CLAUDE.md: categories are opaque).
- **Cost:** report totals and per-request quantiles with bootstrap bands; paired cost difference per request, because cost distributions are skewed.
- **Dashboard (later; FR-OBS-05):** (1) cost–quality Pareto with baselines and CI; (2) savings decomposition by source (routing, cache, compression; already in `AccountingService.decompose`); (3) latency percentile bars with TTFT vs total; (4) per-stratum heatmap: n, quality diff, cost ratio, flagged cells where the CI crosses −δ; (5) cache panel: hit rate, **hit correctness**, false-hit rate; (6) scenario sensitivity; (7) coverage and exclusion counts (FR-EVAL-08). Every panel shows its `price_table_version`, `counterfactual source`, n.

---

## 7. Online evaluation (later) and logging

**Order of rollout** *[ours]*: shadow → interleaved/canary → A/B.

- **Shadow traffic:** the routed path runs in parallel on a copy; the user still gets the incumbent answer. Gives cost, latency overhead and agreement/judge data without risk; doubles provider spend on the shadowed share, and requires the privacy review for any content leaving the machine.
- **Canary/A-B:** randomize at **session level** (no within-session switching; this matches how the logged model was assigned), stratify the randomization, pre-register the metric and δ, and use ≥ the §6 sample size. Primary metrics: cost per resolved session, retry/regeneration rate, thumbs or follow-up signals (if collected), p95 latency; guardrails: error rate, cache false-hit rate.
- **Interleaving** works for ranking *lists*; for single-answer chat it doesn't apply directly. Use paired/side-by-side only in an annotation setting.
- **Fallbacks:** quality regression triggers an automatic revert threshold.

**Log fields** (production and the full dataset). Content is never logged (existing rule); IDs are hashed.

*Request/session:* request id, session id, turn index, timestamp (UTC, with timezone), caller/app id (hashed), category (opaque), language label, feature flags (RAG present, attachments present, instruction hash, prompt-composition fingerprint), lengths in chars and tokens per prompt part.
*Routing:* policy and version, candidate set, chosen model and effort, decision reason/score, router latency, sticky-state used.
*Cache:* lookup performed, type (exact/semantic), similarity score, threshold, hit/miss, **verified result** (if a check ran), key version, invalidation reason, entry age, lookup latency.
*Provider call (per attempt):* provider, model id and **returned model version**, input tokens, **cached-read tokens, cache-write tokens**, output tokens, **reasoning tokens**, finish reason, truncated flag, effort/thinking budget requested, TTFT, total latency, HTTP status, retry count, failure class, fallback target, time in queue.
*Cost:* computed cost with price table version, fidelity (exact/estimated); request overhead cost (router/embedder/judge).
*Quality signals:* thumbs/regenerate/edit, follow-up rephrase within the session, explicit complaints (if the app has them), judge score (async), human labels.
*Full dataset ask (data owner, Q-04/Q-06/Q-09):* token counts and cost if known, latency, request ids to pair requests and responses (instead of inferring from order), retry/fallback labels, any quality or satisfaction field, timezone and clock source.

---

## 8. Common pitfalls (routers and caches)

1. **Comparing only to a weak baseline** or only to premium; use all of §1 and a random router at the same model mix.
2. **Cost-blind or accuracy-only benchmarking** (RouterEval records are cost-blind; RouterArena criticises deferral-curve-only reports).
3. **Ignoring hidden reasoning tokens** or using list price × visible tokens; cost ranking can flip.
4. **Ignoring the tokenizer gap for Persian**: counting with one tokenizer and pricing with another.
5. **Quoting cost with caching assumptions unstated**; compression that breaks prefix caching.
6. **Teacher-forcing blindness:** forgetting later turns change when the answer changes.
7. **Oracle from noisy scores:** max of noisy judge scores is inflated; use repeated-call variance and a confidence margin.
8. **Router trained and tested on the same prompts or sessions** (leakage); split by session and by duplicate-prompt group (16% of prompts repeat).
9. **Selection bias from `logged_match` coverage**, which only covers requests the logged model handled.
10. **Judge issues:** position and verbosity bias, self-preference (judge from the same family as a candidate), unvalidated Persian ability; calibrate with human ratings; keep judge version fixed.
11. **Cache hit rate without hit correctness.** Semantic-cache studies find large false-hit rates at common thresholds (e.g. [InstCache](https://arxiv.org/pdf/2411.13820) reports ~30% judged mismatches for GPTCache at 0.9 similarity, with a judge model as the arbiter; [MeanCache](https://arxiv.org/pdf/2403.02694) reports precision of 0.52 for GPTCache on its sample; both *[claim/paper-specific, not our data]*). Our own sample found zero safe pairs under strict conditions, so measure precision first and treat hit rate second.
12. **Cache-warm test leakage:** evaluating on traffic the cache was filled from; reset state per run (already done) and report cold vs warm.
13. **Averages hiding tails** and **p99 from tiny samples**.
14. **Reusing stale prices, models, or leaderboards**; quote dates and versions.
15. **Using log timestamps as latency.**
16. **Tuning to one opaque category or to sample quirks** (ADR-0008); the sample is 100 sessions, so results are *signals*, not evidence.
17. **Not counting the evaluator's own cost** (judge, embedder) against the system, or hiding it from the budget.
18. **Treating overall results as general when they are Persian results**, or pooling small English/mixed slices to hide their uncertainty.
19. **Confusing sampling allocation with population weighting**, or claiming reliability for an oversampled slice's population share.
20. **Unnormalized Persian text** splitting one prompt into several (Yeh/Kaf variants, digit forms, ZWNJ, bidirectional marks), which understates duplicates, leaks across splits, and misses cache candidates; and the opposite error, normalizing so aggressively that distinct prompts merge or model-bound text is altered.
21. **Using an unvalidated judge** for Persian claims, or assuming a judge-prompt language is better without measuring.
22. **Reading character, token and verbosity numbers as interchangeable.**

---

## 9. Open items / next steps

1. Decide δ (Q-13) and the judge, then calibrate it with human ratings (TODO-05).
2. Run the Persian tokenizer comparison offline (no API cost) to quantify §2.1.
3. Owner approval and budget for the pilot (150–200 requests × 3 models), then size the main run from observed usage.
4. Add scenario/sensitivity output and a price-table age check to the runner.
5. Add the §7 fields to the event contracts where missing (check [contracts.md](../architecture/contracts.md); `content` fields stay forbidden).
6. Re-verify every *[verify]* item before anyone cites it externally.
7. **Unresolved methodological decisions** (all must be explicit config or an ADR; none has a default here): minimum n per stratum; minority-language quotas and per-cell floor; language-classifier thresholds and the Persian-vs-other-Arabic-script cue; agreement statistic and minimum threshold for the judge gate; calibration-set size and Persian share; length-bucket boundaries and the character unit (code points vs graphemes); diacritic, tatweel, case-fold and ZWNJ-vs-space handling in the match key; whether match keys may feed ADR-0015 fingerprints; whether normalization is ever applied to the production cache key (needs its own ADR); judge model and δ (Q-13); Persian-capable embedder.

## Sources

- RouterBench: [arXiv 2403.12031](https://arxiv.org/pdf/2403.12031)
- RouteLLM (PGR, APGR, CPT): [arXiv 2406.18665](https://arxiv.org/pdf/2406.18665)
- RouterArena: [arXiv 2510.00202](https://arxiv.org/html/2510.00202); RouterEval: [arXiv 2503.10657](https://arxiv.org/pdf/2503.10657)
- Output/reasoning length prediction: [InferLength / EGTP](https://github.com/vastava/InferLength), [arXiv 2508.00912](https://arxiv.org/pdf/2508.00912), [Apple LenVM](https://machinelearning.apple.com/research/length-value-model), [Argus arXiv 2512.22925](https://arxiv.org/pdf/2512.22925)
- Multilingual token cost: [Token Tax arXiv 2509.05486](https://arxiv.org/html/2509.05486), [arXiv 2510.09947](https://arxiv.org/pdf/2510.09947v2), [arXiv 2601.11518](https://arxiv.org/pdf/2601.11518)
- Artificial Analysis methodology and per-effort entries: [example model page](https://artificialanalysis.ai/models/claude-sonnet-5-medium)
- Semantic cache evaluation: [MeanCache](https://arxiv.org/pdf/2403.02694), [InstCache](https://arxiv.org/pdf/2411.13820), [TweakLLM](https://arxiv.org/pdf/2507.23674)

Not found or not verified in this pass: Persian-specific fertility figures across vendors; per-model average reasoning tokens for current models; LLM-judge bias magnitudes for Persian; provider prompt-caching terms (minimums, TTLs, discounts). These need a targeted follow-up before the numbers are used.
