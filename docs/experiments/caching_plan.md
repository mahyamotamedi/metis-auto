# Caching experiment plan (Stage 8)

Status: stage C1 **done on the sample** (EXP-CACHE-001); C1b–C5 **planned**. Last re-run 2026-10-19 with the new loader default (Q-37). Nothing here changes the serving defaults (`session` scope, the full key, `literal` treatment; ADR-0007, ADR-0011). The Demo milestone's bot-level scope rule and demo seed (ADR-0023) are labelled demo settings, off by default, not C4 results. Thresholds marked *proposed* are **confirmed as provisional placeholders** (Q-38, 2026-10-19): results are always reported as measured values against every threshold, and all of them are revisited with the full dataset. Last updated 2026-10-18.
Framework: [framework.md](framework.md). Architecture: [caching.md](../architecture/caching.md). Requirements: FR-XCACHE-*, FR-SCACHE-*, H-3, H-4, H-8; ADR-0006 (hit rate always with hit correctness), ADR-0007, ADR-0011, ADR-0016.

The progression is a chain of **replaceable stages**: each adds one thing behind the same interfaces (`CandidateIndex` in experiments, `CacheStore` / `VectorIndex` in serving) and is compared in the same format against the previous stage and the baselines.

| Stage | Adds | Swap point | Status |
|---|---|---|---|
| C1 | exact candidates: treatments × key compositions × unknown handling × scopes | `CandidateIndex` (`exact`) | **done** (sample) |
| C1b | Persian folding, history windows, first-turn-only, producing-tier rule | treatment / variant config | planned; **Persian folding treatments implemented (Stage E0, ADR-0025), not yet run on data** |
| C2 | semantic tier: embedder, similarity, threshold from measured curves, false-hit analysis, verifier | `CandidateIndex` (`semantic`), `Embedder`, `VectorIndex` | planned |
| C3 | persistent store (PostgreSQL) behind the same ports | `CacheStore`, `VectorIndex` adapters | planned (after the full EDA) |
| C4 | curated shared cache with simulated rebuilds; traffic-source scope (ADR-0016, proposed) | builder + `CandidateIndex` (`curated`) | planned |
| C5 | provider prompt caching: keeping prefixes stable and models warm | context order, sticky routing | planned (with the context and routing plans) |

---

## C1. Exact cache baseline: EXP-CACHE-001 (done 2026-10-18)

- **Hypothesis H-3:** exact repeats exist, but most are unsafe to serve under a conservative key.
- **Method:** [framework.md §3](framework.md#3-runner-kinds), `cache_candidates` kind, built-in `exact` index, in-memory. 5 base compositions (`msg_only`, `msg_instr`, `msg_instr_ctx`, `full_no_model`, `full`) × 3 message treatments (`literal`, `whitespace`, `nfkc_casefold_ws`) × 2 unknown treatments (`strict`, `wildcard`) × 2 scopes (`session`, `global`). Cases in naive logged-time order. Two runs: **primary**, the sample loader treating a missing optional key (`attachments`, `rag`, `input`) as `absent`, since the export lists them only when present (owner decision Q-37, 2026-10-19; A-61); **alternative**, treating it as `unknown`. Co-occurring nulls are `unknown` (`not_in_log`) in both.
- **Results** ([report](../../reports/caching/exp-cache-001/README.md); sample, provisional signals, ADR-0008):
  - **The full serving key gives 0 candidate hits** in both runs, at every treatment and scope. History differs between every pair of repeated messages. This matches the sample EDA's "no pair passed the strictest screen", reproduced here by independent code.
  - Primary run: the full key is eligible for 404 of 465 cases (14 have attachments; 47 have unknown instructions: null labels or no paired answer) and still finds nothing. Alternative run: **every strict variant is ineligible** for the 451 cases without attachments (attachments unknown), so a conservative reading of the export supports no strict key at all.
  - Message only: 47 candidate hits globally (10.1 %, 95 % CI 7.7–13.2 %), of which 10 are within a session and 37 cross sessions. Adding instructions (strict): 9 hits (1.9 %, CI 1.0–3.6 %), 8 within a session. Adding retrieved context and structured input: 6.
  - All three treatments give identical counts on this sample (short messages).
  - Lexical answer-match signal: of the 47 message-only hits, **4** had an identical logged answer. That is *not* hit correctness, but it means most message-only matches were answered differently.
  - Lexical repeat groups: 21 groups covering 76 messages, 11 crossing sessions, under every treatment (the same figures as the sample EDA).
- **Kill/continue:** the C1 kill criterion ("if no variant has candidate hits, stop the cache track on this dataset") is not met: narrow variants do find candidates. They are measurement-only (P-5), and the question moves to C2 (are paraphrases more common?) and to hit correctness. **Continue**, with the warning that the sample is too small to size the opportunity.

## C1b. Normalisation and key refinements

- **Hypotheses:** (a) Persian folding (Arabic yeh/kaf → Persian, ZWNJ, diacritics, tatweel, Persian/Arabic-Indic digits) raises exact candidates without raising false hits; (b) a history window of the last *N* turns (with `N` ∈ {0, 2, 4}) recovers later-turn candidates that the full history blocks; (c) first-turn-only admission (history absent) is a safe subset.
- **Method:** new treatments in `domain.caching.normalise` and history-window treatments (already named in `KeyComponent.treatment`). Same harness; more variants in the params. The producing-tier rule (caching.md §2, open) as a filter on matches.
- **Metrics:** candidate hit rate per variant and scope; hit correctness on a labelled subset (C2's labels); lexical repeat groups.
- **Data needs:** the full dataset (the sample has too few repeats to see differences between treatments).
- **Success (proposed):** a treatment or window adds ≥ 10 % relative candidate hits with no measured rise in false hits. **Kill:** no change in candidates across treatments on the full dataset (as on the sample) → keep `literal`.

## C2. Semantic cache

- **Hypothesis H-4:** paraphrased repeats (same intent, different words) are more frequent than exact ones, and some of them can be served under the same partition key without a measurable quality loss.
- **Method:**
  - **Partition:** the semantic tier matches the partition key exactly (instructions, history or window, retrieved context, structured input, target group, scope) and compares only the message (FR-SCACHE-02, ADR-0011). Variants: partition = full, = instructions only (measurement only), = none (upper bound).
  - **Embedders (candidates; none verified yet).** For each, check the model card for Persian in the training languages, the licence, the size, and the CPU latency, and record the source and date before use:
    - multilingual open models: `intfloat/multilingual-e5` (small, base, large), `BAAI/bge-m3`, `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, LaBSE;
    - Persian-specific sentence encoders on Hugging Face (to be searched and checked);
    - `text-embedding-3-small` through the Metis OpenAI endpoint (brief §3): a live call, so it counts against the budget (10 USD lifetime cap) and needs the owner's approval to send sample text (ADR-0018).
    Local models go in an optional extra (like `tokenizers`), never in the runtime lock. A `TextEmbedder` adapter implements `ports.Embedder`; the index key includes the embedder ID and version, so vectors never mix (caching.md §5).
  - **Similarity:** cosine (default) and dot product on normalised vectors; the index is a brute-force in-memory scan at sample and full-dataset scale (C3 decides on an ANN index).
  - **Thresholds from measured curves, never set in advance (FR-SCACHE-04):** for each embedder, sweep the threshold from 0.70 to 0.99 and plot the candidate hit rate against the false-hit rate measured on the labelled set. Choose the operating point from the curve, per partition variant.
  - **Labelled set for hit correctness.** For each candidate pair (new request, matched entry) above the lowest threshold: is the matched answer acceptable for the new request? Sources, in order of preference: (1) **owner labels** on a stratified sample of pairs (content stays local; no cost); (2) a **synthetic paraphrase set** in Persian, English, and mixed text, written for this purpose and marked synthetic (positives = paraphrases, negatives = near misses such as a different order number or product), which measures the embedder, not the traffic; (3) an **LLM judge** on pairs (a live call: estimate first and owner approval; sample content needs per-run approval). False-hit rate = unacceptable / served, with a Wilson interval.
  - **Answer-validity checks:** the time-sensitivity detector (TODO-07) as an eligibility rule, measured as how many false hits it removes; numbers and named entities that differ between the two messages (a cheap mismatch detector); the optional verifier (FR-SCACHE-06, speculative), whose cost counts as overhead.
- **Metrics:** candidate hit rate and false-hit rate per threshold (the curve), per stratum (category, language, turn depth); embedding overhead p50 and p95 (inside the 100 ms budget, QA-LAT); avoided cost at as-logged prices, net of embedding cost; agreement of the matched answer with the reference (secondary, ADR-0006).
- **Data needs:** the full dataset for frequencies; owner labels or a judge budget for correctness; for agreement, the chosen embedder.
- **Success (proposed, Q-38):** an operating point where the false-hit rate is ≤ 2 % (upper 95 % bound ≤ 5 %), the semantic tier adds ≥ 25 % relative hits over exact, the judge score of served hits is within δ of fresh answers (ADR-0006: −3 % overall, −5 % per stratum), and overhead p95 stays ≤ 100 ms. **Kill:** no threshold reaches the false-hit bound with any added hits, or overhead p95 > 100 ms with the cheapest adequate embedder.

## C3. Persistent store

- **Hypothesis:** a persistent store behind `CacheStore` and `VectorIndex` changes no result (the same hits in the same replay) and keeps lookup overhead inside the budget at full-dataset size.
- **Method:** after the full EDA (Stage 9): PostgreSQL for entries; for vectors, pgvector or an in-process index, chosen by measured latency and size. A conformance test suite shared by every store adapter (get, put, TTL fields, status, scope, embedder partitioning). Replay EXP-CACHE-001 and the C2 winner against the in-memory and the persistent store; the events must match apart from durations.
- **Metrics:** identical candidate counts; lookup p50 and p95; storage size (counts only).
- **Data needs:** the full dataset; Docker PostgreSQL (`compose.yaml`, profile `db`).
- **Success:** identical results and lookup p95 ≤ 10 ms (proposed). **Kill:** none; choose another adapter if the latency fails.

## C4. Curated shared cache and traffic-source scope (ADR-0016, proposed — to be tested)

- **Hypothesis H-8:** for embedded bots, a cache curated from frequent first-turn questions per instruction group, rebuilt daily, serves many requests across sessions with fewer false hits than a dynamic global cache.
- **Method:** a builder simulation over replay: build from window *d−1* (rolling), serve window *d*; admission by frequency per instruction group (threshold and window are parameters); first-turn only at first; answers are logged answers (`logged_match`; agreement only) or regenerated answers (`recorded` / `live` plus a judge). Compared with: no cache, the session-scoped dynamic cache, and a global dynamic cache. Scope by traffic source (ADR-0016 Part 2) is a **stratum and a simulation input only**; inferred traffic sources never choose a scope.
- **Metrics:** hit rate with hit correctness; storage (entries); cost saved net of build cost (regeneration and judge calls charged to the curated cache, amortised over its hits); per traffic source when the data has it (Q-22).
- **Data needs:** the full dataset (the sample is far too sparse for daily windows: mechanics only); a declared traffic source (Q-22, Q-23); the time-sensitivity detector (TODO-07) and a privacy review **before any serving**.
- **Success (proposed):** net saving ≥ the dynamic session cache's with a false-hit rate within C2's bound. **Kill:** the popularity distribution per instruction group is flat (few questions repeat within a day).

## C5. Provider prompt caching (from the live check)

Findings of the [live probe](../references/metis_wrapper_live_check.md#4-follow-up-probe-2026-10-18-owner-decisions-q-32-q-33-b-q-34) (2026-10-18, one pair per model, synthetic):
- A 1,263–1,796-token synthetic prefix sent twice got provider cache hits for gpt-4.1-nano and gpt-4o-mini (1,152 cached tokens), deepseek-v4-flash (1,280), and mimo-v2.5 (1,792), and second-call costs fell 45–95 %. gpt-5-nano did not hit in one pair (provider caching is best effort). MiMo omits the field when nothing is cached.
- So the **largest cheap lever may be the provider's cache, not ours**: the sample's instructions are long and heavily reused (provisional signal), and the provider cache applies to the prefix even when the question differs.
- Whether Metis passes the discount on is still unconfirmed (Q-36).

Plan:
- **Hypothesis:** keeping the stable prefix first (instructions → retrieved → history → message, context_construction.md §2) and keeping a session on one model (sticky routing, routing plan R7) raises the provider-cached share of input tokens, and that saving is larger than what our exact cache saves.
- **Method:** a small live experiment, **only with synthetic sessions** that mimic the sample's shape (long instructions, multi-turn), each model's caching measured over turns; then offline: a model of provider-cache savings driven by measured hit behaviour (cached share as a function of prefix length, model, and delay between turns), applied to replayed sessions. Estimate and owner approval before any live call (ADR-0018).
- **Metrics:** cached share of input tokens per model; `provider_cache_saving` (the savings decomposition, brief §6); latency effect.
- **Success:** provider-cache saving ≥ exact-cache saving on the full dataset model. **Kill:** the dashboard shows the discount is not billed (Q-36).
