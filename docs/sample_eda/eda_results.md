# Sample EDA results

This document summarizes `experiments/sample_eda/eda.ipynb`. All results describe the provided sample only (100 sessions, 907 messages); they are not production estimates.

## Dataset structure and integrity

### Question
What is present, and do basic session/message records agree?

### Method
Parse the JSON root and nested records; count roles, fields, IDs, counters, and timestamp validity/order.

### Result
The file contains four equal opaque category groups of 25 sessions, 100 unique sessions, 465 user messages, and 442 bot messages. All session counters match parsed arrays; roles are only `user`/`bot`; all messages have nonempty string content and parseable timestamps; no within-session timestamp decreases were detected.

### Interpretation
Basic structural consistency is good. Optional fields are role-dependent: 27 bot records have null model/provider/instructions; `rag` appears on 71 bot records; attachments on 14 user messages (15 attachment items); `input` on 29 bot records across 8 sessions.

### Business relevance
A sound sample structure supports descriptive prioritization, but does not establish representativeness or provide optimization outcomes.

### Limitation / confidence
High confidence for counts from this JSON parse; semantics of `input`, `instructions`, and absent retrieval metadata remain uncertain. See `schema_presence.csv`, `data_dictionary.csv`, and `integrity_checks.csv`.

## Request size and conversation depth

### Question
How variable are request and session sizes?

### Method
Character/word/line/sentence/script metrics and character/4 proxy; per-session turn, text, duration, and model/provider summaries.

### Result
User-message character count has median 29, p90 182, p95 424, p99 2,655, and maximum 4,666. The corresponding character/4 proxy has median 8 and p90 46—not billed tokens. Sessions have median 6 messages and median 3 user turns; every session has more than one user turn. The median observed session duration is 124.5 seconds, but p90 is about 22.6 hours and maximum about 45.4 days, indicating substantial idle-gap/outlier sensitivity.

### Interpretation
Traffic has a right tail and substantial depth variation. Short/long requests and context-dependent multi-turn sessions are plausible segmentation dimensions.

### Business relevance
Prompt size/depth may help prioritize routing, context, and cache experiments, but there is no matched cost/quality outcome.

### Limitation / confidence
Descriptive; sentence counts and token estimates are rough. Duration measures timestamp span, not active conversation or API latency. See `user_request_length.png`, `session_depth.png`, `text_numeric_summary.csv`, and `session_numeric_summary.csv`.

## Language and request complexity

### Question
Does observable request heterogeneity justify later routing investigation?

### Method
Unicode-script heuristic plus nonexclusive keyword task flags and a four-component complexity proxy.

### Result
User messages classify as 422 Persian-script (90.8%), 28 English/Latin (6.0%), 13 mixed Persian/English (2.8%), and 2 other/unknown. The complexity proxy places 446 user messages in low (0–1), 12 in medium (2), and 7 in high (3+) bands. Keyword flags find 15 coding, 11 translation, 10 structured-output, 7 rewrite/edit, 2 summarization, 1 math, and 0 long-form-generation matches (nonexclusive).

### Interpretation
The traffic spans language, length, code, formatting, and depth features, but these heuristics are not ground-truth task or difficulty labels.

### Business relevance
These can seed evaluation strata and routing features for later offline tests; they cannot support model selection decisions by themselves.

### Limitation / confidence
Script and keyword rules are approximate, especially for Persian paraphrases, transliteration, and short messages. See `language_distribution.png`, `complexity_proxy.png`, and `exploratory_request_heuristics.csv`.

## Models and providers

### Question
Are multiple model/provider assignments and request profiles present?

### Method
Count logged bot model/provider combinations and associate session-level dominant model with prompt length, language, retrieval, attachment, input proxy, code, and depth.

### Result
There are 18 non-null model labels and 7 non-null provider labels, plus 27 nulls. `deepseek-v4-flash` accounts for 127/442 bot messages (28.7%); `deepseek` for 129/442 (29.2%). `default`/`workflow` appears 36 times. No model/provider switches were observed within a session; 98 sessions have one non-null model label and 2 have none.

### Interpretation
Assignment is heterogeneous across sessions, while within-session assignment is stable in the export. Some short-looking prompts and much longer prompts appear across model labels, but assignment differences may reflect workflow/task/provider availability rather than inefficiency.

### Business relevance
The sample supports building matched model comparisons, not choosing a cheaper default or claiming waste.

### Limitation / confidence
Association only: no exact model version normalization, prices, billed tokens, quality, reliability, or complete request-level matching. See `model_provider_usage.png`, `model_by_prompt_length_bucket.csv`, and `model_by_request_characteristics.csv`.

## Semantic-cache opportunity

### Question
How much exact or near repeated user traffic appears?

### Method
Literal, whitespace-only, and conservative NFKC/casefold/whitespace duplicate grouping; local character 3–5 gram TF-IDF cosine scores for 107,880 user-prompt pairs, with a 0.70 candidate threshold.

### Result
Each exact/normalized method finds 21 duplicate groups covering 76 user-message occurrences (16.3%); 11 groups span multiple sessions. Similarity yields 424 candidate pairs at ≥0.70, of which 367 are conservative-normalized exact matches and 57 are nonidentical near matches. Score distribution has median 0 and p99 0.237, with the upper tail strongly influenced by repeats.

### Interpretation
There is direct evidence of repeated text in this sample, including cross-session repeats. The volume is a plausible cache-opportunity signal, not the safely cacheable share.

### Business relevance
Worth measuring context-aware cache eligibility and outcomes on the full dataset. Exact requests can still be personalized, time-sensitive, context-dependent, or affected by changed retrieval context; near matches have additional entity/intent false-hit risk.

### Limitation / confidence
High confidence in lexical counts under stated normalization; no semantic equivalence, safe-hit rate, production hit rate, quality, or savings claim. Candidate files contain hashed IDs, lengths, and scores only. See `prompt_similarity_distribution.png`, `exact_repetition_summary.csv`, and `near_duplicate_candidates_ge_070.csv`.

## Retrieval and context

### Question
Is logged retrieval context large or variable enough to investigate as an overhead source?

### Method
Join context list strings in memory; measure characters, words, character/4 proxy, and context/query length ratio; segment by model/provider, retrieval-query script, prior user complexity, and session depth.

### Result
71 bot messages across 24 sessions include RAG metadata. Joined context size has median 1,476 characters, p90 4,019, and maximum 4,019; 10 messages are exactly 4,019 characters. Median context/query character ratio is 44.7 and p90 167.5. Most RAG queries classify Persian-script (67/71); the remaining 4 are mixed Persian/English. One prior-request complexity group is tiny (one medium example).

### Interpretation
Logged contexts can be large relative to their query, so context-size/ranking experiments are justified. The 4,019-character ceiling may reflect truncation or export limits but must be verified. Length is not evidence of irrelevance or safe removability.

### Business relevance
Context reduction could plausibly affect token use if these fields correspond to provider prompts, but prompt composition and billing are unknown; quality-preserving ablations are essential.

### Limitation / confidence
Good for size of logged fields, not full provider context, tokens, relevance, or savings. See `retrieval_context_length.png` and retrieval-context CSV summaries.

## Time and data-quality caveat

### Question
Can this sample show temporal traffic patterns or latency?

### Method
Aggregate message/session timestamps by month and compare session creation to first message time.

### Result
Session `created_at` runs January–September 2026, but message timestamps run March 2–September 9. One session has a different creation/first-message month; five have an absolute timestamp gap over one hour, including one first message earlier than `created_at`.

### Interpretation
Monthly counts describe this export only. Timestamp semantics or export behavior require clarification before interpreting time windows. User-to-next-bot gaps are not API latency.

### Business relevance
Reliable lifecycle timestamps are required for latency observability and temporal cache invalidation.

### Limitation / confidence
Observed timestamp facts are high confidence; interpretation is uncertain. See `traffic_over_time.png` and `session_timestamp_consistency.csv`.

# Executive Findings

1. The parsed sample is structurally coherent at basic counter/role level: 100 sessions and 907 messages.
2. User prompts are highly right-skewed in length (median 29 characters, p99 2,655); character/4 is only a rough proxy.
3. Traffic is predominantly Persian-script by an approximate heuristic and includes varied code/format/language/depth signals.
4. Logged model/provider assignments are heterogeneous across sessions, with no within-session switches; no efficiency judgment is supported.
5. Exact repetition covers 76 user messages in 21 groups; this is a cache investigation signal, not safe cache eligibility.
6. Retrieval appears on 71 bot messages with median joined context 1,476 characters; the maximum/plateau at 4,019 merits export-semantics validation.
7. Every session has multiple user turns, making history-aware caching and routing relevant.
8. Session/message timestamps have a mismatch in one session and large gaps in five; timestamp differences cannot stand in for API latency.

# Business-Value Assessment

## Directly supported by the sample

- There is exact repeated prompt text, model/provider usage heterogeneity, variable prompt size/depth, and sizeable logged retrieval context.
- Some sessions have attachments or the uncertain input-configuration proxy.
- Candidate observability dimensions can be identified from available fields.

## Suggestive but requires validation

- Semantic caching may help repeated, context-independent requests; eligibility, hit quality, and safe invalidation need evaluation.
- Intelligent routing may benefit from heterogeneous lengths/languages/code/depth; paired cost/quality/latency evidence is missing.
- Context optimization is worth testing against relevance and answer-quality labels; long does not mean redundant.
- Token/cost observability could be valuable if exact billing and decision/outcome events are logged.

## Cannot yet be determined

- Dollar savings, billed tokens, provider pricing, model quality differences, maintained quality, true API latency, cache safety, customer profitability, production representativeness, or user model-selection burden.

# Requirements for the Full Dataset

Collect request-linked exact input/output/billed tokens; normalized model/version/provider; request and provider cost; request lifecycle latency including time-to-first-token; retries/failures; selected model and routing decision/reason; cache eligibility/lookup/hit/invalidation and outcome; retrieval document IDs/scores and actual prompt composition; quality/evaluation labels; and privacy-safe customer/workload grouping. Preserve timezone and clock semantics plus stable request/session correlation IDs.

## Request/response association and pairing limitations

The notebook retains the established latest-preceding-user-by-array-order convention. It links 436 bot records to 434 distinct user-message events; 2 user events have multiple associated bot records, while 6 bot records have no preceding user. There are 16 consecutive-user transitions across 11 sessions and 3 consecutive-bot transitions across 3 sessions. Consequently, paired request/response summaries are descriptive and heuristic, not request-keyed measurements. In particular, consecutive user turns may be skipped by the convention, and a bot record may not be a one-to-one response to the selected request.

See `response_pairing_diagnostics.csv`, `requests_with_multiple_bot_associations.csv`, and `response_level_analysis.csv` (feature-only, with opaque IDs).

## Logged instructions

Among 442 bot records, 27 instructions are null and 7 are blank non-null values; 408 are nonempty. There are 79 distinct exact non-null strings and 78 nonempty groups after NFKC/casefold/whitespace normalization. Seventy-four normalized groups recur, covering 404 bot records. These counts describe logged metadata only; they do not establish that instructions were sent to a provider or were stable system prompts.

For the 408 nonempty instruction strings, median size is 3,578 characters (p90 8,258; maximum 271,155); the character/4 median is 895, not a tokenizer count. Reuse is mostly within opaque category groupings: 11 normalized groups appear across multiple sessions, none across categories, 2 across model labels, and 1 across providers. Missing/blank instruction prevalence differs by category in this sample (for example, 32/127 bot rows in `general_athena`, versus none in two other strata); category labels remain uninterpreted. See `instruction_summary.csv`, `instruction_size_statistics.csv`, `instruction_group_reuse.csv`, and `instruction_missingness_by_features.csv`.

## Hypothetical full-history input-size scenario

For matched bot records, the notebook constructs a **scenario** by adding all earlier message content in the session, the matched current user content, the bot row's logged instruction string, and its logged RAG context. The calculation is not a claim about actual provider-prompt composition. Missing metadata contributes zero only to the logged-field scenario; it is not evidence that the field was absent upstream. Attachments and the uncertain `input` configuration proxy are presence signals only.

Across matched records, summed scenario characters are 1.16% current request, 13.80% earlier transcript history, 82.58% logged instructions, and 2.46% logged RAG context. The instruction share reflects the unusually large logged strings and should not be read as provider input-token share or cost share. At user turn 1 (98 response rows), median scenario size is 3,661 characters; at turn 10 (12 rows), it is 6,876. Median prior-history characters rise from 0 at turn 1 to 2,645 at turn 10. Later-turn samples are smaller and summaries count repeated prior transcript content by construction. Character/4 is only a rough size proxy.

See `hypothetical_input_growth_by_turn.csv`, `hypothetical_input_growth_by_session.csv`, `hypothetical_input_component_shares.csv`, `hypothetical_input_growth.png`, and `session_input_growth_examples.png`.

## Repeated requests and progressively restricted cache-candidate screens

At the conservative normalized-request level, 21 repeated prompt groups cover 76 user-message events. Comparing all event pairs yields 367 same-request pairs. At least one associated bot record had the same nonempty normalized instruction in 9 such pairs; 6 of those also had no logged RAG on either side. No pairs passed both the no-prior-history screen and the final response-similarity threshold of 0.85. These pair counts overlap and are not cache hit or safety rates. Exact, whitespace, and NFKC/casefold/whitespace repetition counts happen to be equal in this sample (17 repeated request groups among the response-associated request rows; 62 request events in those groups), but association multiplicity and denominator differ from prompt-only counts elsewhere in the notebook.

Among repeated request groups, instruction assignment often varies: 6 groups had one nonmissing instruction group and no missing instruction associations, 9 had multiple instruction groups; the remaining groups include missing instructions. Same-prompt response pairs also span different model/provider labels. For the 226 pairs with different non-null model labels, median response lexical cosine is about 0.105 (p90 0.258); this is lexical dissimilarity only, not a quality or correctness comparison. A pair can differ in hidden context, routing, time, or prompt composition even when its user text is identical.

The response-level candidate screens deliberately use the logged instruction, logged-RAG, prior-history, and response similarity fields. Their zero count at the strictest stages does not establish zero cache opportunity: it shows only that none of these sample pairs satisfies this specific evidence screen. Conversely, passing a screen would not establish safe reuse. See `request_instruction_by_normalization.csv`, `repeated_request_instruction_consistency.csv`, `repeated_request_response_pair_comparisons.csv`, `repeated_request_response_variability.csv`, and `restricted_cache_candidate_screens.csv`.

## Bot response sizes and repetition

Bot response content has median 210 characters (p90 1,025; maximum 13,795) and median character/4 proxy 53 (p90 257); these are content-size summaries, not output-token billing. Thirteen exact/normalized repeated response groups cover 33 bot records (7.5%), with four groups crossing sessions. At a 0.70 character n-gram similarity threshold, 129 response candidate pairs are identified, 98 nonidentical after conservative normalization. Similarity is not answer equivalence or quality. Response size segments by model/provider, request characteristics, instruction, RAG, and depth are exploratory, with sparse groups in places.

See `bot_response_numeric_summary.csv`, `bot_response_token_proxy_by_segments.csv`, `bot_response_repetition_summary.csv`, and `bot_near_duplicate_pair_summary.csv`.

## Retrieval, observed timestamp gaps, and routing patterns

The request↔logged-context character n-gram cosine has median 0.195 (p90 0.322); logged-context↔bot-response cosine has median 0.315 (p90 0.600), each across 71 logged RAG records with an inferred request association. These are lexical-overlap proxies only. Logged context size correlates descriptively with response length in this sample (Spearman rho 0.580, n=71); this does not show usefulness or causation. RAG occurrence and context sizes vary across observed model, request, instruction, and category strata, but some cells are small. Actual retrieval-to-provider prompt construction requires application code or payload instrumentation.

There are 436 paired user-to-bot observed timestamp gaps: median 2 seconds, p90 7 seconds, maximum 118 seconds; all are nonnegative for the matched pairs under this sample. These are not confirmed API latency measurements. Exploratory Spearman associations with log1p of nonnegative gaps are modest (for example, response character count rho 0.305 and request character count rho 0.238, n=436), not causal and not evidence that routing would reduce latency.

Opaque categories differ in request mix, logged RAG prevalence, instruction missingness, response sizes, and model/provider labels. The notebook reports these cross-tabs without assigning semantic meaning to category names or inferring model quality, efficiency, or a routing policy. Consecutive bot turns (3), same-request pairs within sessions (23), and short/error-keyword-like bot outputs followed by a user message (11) are sequence/text proxies only. The export has no explicit retry, fallback, failure, escalation, or outage labels.

See `rag_lexical_overlap_summary.csv`, `rag_usage_by_features.csv`, `rag_context_exploratory_associations.csv`, `observed_user_to_bot_gap_summary.csv`, `observed_gap_by_features.csv`, `model_assignment_by_request_features.csv`, `opaque_category_workload_comparison.csv`, and `retry_fallback_pattern_proxies.csv`.

## Updated executive interpretation

The sample supports prioritizing instrumented experiments around repeated requests, context construction, long logged instructions, history growth, and workload-aware routing. It does **not** establish the actual provider prompt, token billing, cost savings, API latency, safe-cache share, response quality, or retry/failover behavior. The attached project draft's characterization of `input` as structured-input widgets is not confirmed by the export: the observed field is a bot-side `input.items` configuration object, retained as a cautious proxy. Routed-versus-baseline evaluation or LLM-as-a-judge scoring remains out of scope until paired outputs and suitable quality labels exist.
