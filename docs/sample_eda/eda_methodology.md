# EDA methodology

> **Preliminary — sample-only, exploratory.** This EDA ran on a 100-session sample to judge whether the project was worth doing. Its numbers are provisional signals to re-verify on the full dataset, not established facts, and its helper code is simplified and not reusable. See [ADR-0008](../adr/0008-sample-eda-is-exploratory.md).

## Loading and grain

`eda_helpers.load_sessions` reads the JSON array and flattens category/session pairs without changing the source. `flatten_messages` creates one message row with category, session linkage, array index, role, timestamp, text, model/provider, separate `instructions`, separate `rag` query/context, attachment metadata, and an `input`-configuration indicator. Session and message identifiers in candidate outputs are hashed; raw prompts and attachment URLs are not exported.

The source is hashed before and after notebook execution. Derived CSVs/figures are written under `reports/sample_eda/`; raw JSON is never rewritten.

## Text features and approximate tokens

For message `content`, the helpers calculate raw and whitespace-normalized character counts, Unicode word count, line/newline count, approximate sentence count from `. ! ? ؟ ۔`, Unicode punctuation and digit counts, question marks, URL/code/fenced-code/Markdown indicators, Persian-script and Latin letter counts/proportions, language heuristic, empty/short/long indicators, and token proxy.

Approximate tokens are `ceil(character_count / 4)` with zero for empty text. This simple character heuristic is intentionally labeled an approximation; it is not a provider tokenizer or exact input/output/billed token value and is especially unreliable across Persian, code, and structured payloads.

## Language heuristic

Count characters in Persian/Arabic Unicode blocks and Latin A–Z. Label as mixed Persian/English when Persian share is at least 0.30 and Latin share at least 0.15; Persian-script when Persian share is at least 0.50; English/Latin-script when Latin share is at least 0.70; otherwise mixed/other or other/unknown. This is explainable, but not language ground truth: Arabic/Persian script overlaps, transliteration is missed, and short strings are uncertain.

## Request labels and complexity proxy

Nonexclusive keyword patterns flag coding, math, translation, rewrite/edit, summarization, structured output, and long-form generation. Patterns include a small set of English and Persian terms. They are reproducible exploration aids; false positives/negatives and unclassified requests are expected.

For user messages only, the score adds one each for at least 500 characters, at least three punctuation-based sentence marks, a code-like pattern, and two or more broad instruction markers. Bands are 0–1 low, 2 medium, and 3+ high. The score does not use retrieval metadata that belongs to bot messages and is not a production classifier or quality label.

## Session aggregates and timestamps

Session features aggregate message/turn counts, user/bot characters and approximate tokens, character ratio, number of distinct logged models/providers, switches in bot-message sequence, retrieval/attachment/input-proxy presence, duration, and nonnegative observed user-to-next-bot timestamp gaps. Session duration is max minus min parsed message timestamp; timestamp gaps may span idle periods and are not API latency. Timestamps are naive and have no timezone suffix.

Declared session length/user turns/bot turns are compared with parsed arrays. Creation timestamps are compared with first message timestamps separately; observed month mismatches and large gaps are disclosed.

## Missingness and data dictionary

Field presence is counted at category/session/message grain. Null values are distinct from absent optional fields conceptually; role-dependent omissions of model/provider/instructions are expected. Summary tables avoid complete raw transformed datasets.

## Exact repetition and normalization

Exact prompt repetition groups nonempty user messages by literal content. Whitespace normalization trims and collapses whitespace only, preserving case and punctuation. Conservative normalization applies Unicode NFKC, casefold, and whitespace collapse while preserving punctuation and wording. Groups contain counts, opaque sequential group labels, and hashed message identifiers—not prompt text or reversible prompt digests. A duplicate is lexical repetition, not a safe cache hit.

## Near repetition

User messages are transformed locally using scikit-learn `TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), norm="l2")`; cosine similarity is computed for all unordered nonempty-message pairs. Candidate outputs use a 0.70 exploratory threshold and hashed session/message IDs only. Similarity-score distribution includes exact repeats; candidate rows mark conservative-normalized exact matches so they can be separated from nonidentical near matches. No embeddings, external services, or paid APIs are used. Threshold is an inspection aid, not a cache policy; lexical similarity risks entity, intent, temporal, personalization, and context false hits.

## Retrieval/context calculations

For each `rag` record, nested context is recursively converted to text in memory. Character/word counts and character/4 token proxies are computed, plus context-character / logged-query-character ratio. Summaries segment by provider/model, retrieval-query script, preceding user complexity band, and session depth. The ratio is not complete provider prompt composition. Missing `rag` does not necessarily mean retrieval was absent. Context length alone is not evidence that content is irrelevant or removable.

## Inferred user-to-bot association and response-level analysis

`pair_bot_responses_with_preceding_users` is preserved: each bot record is associated with the latest earlier user record in the same session by message-array order, regardless of timestamp. This is a heuristic, not an explicit request ID. Consecutive user messages can be bypassed; a user message can be associated with multiple bot records; bot records without a prior user remain unmatched. Pairing diagnostics report affected records and role-transition counts. Paired user-to-bot timestamp differences retain their sign and remain observed timestamp gaps, not API latency.

`build_response_level_analysis` joins request features to bot rows and keeps raw text in memory only. The exported response-level tables contain features, opaque category labels, opaque normalized-text group labels, and hashed session/message IDs, but no prompt, response, instruction, RAG text, or attachment URL. Instruction group IDs are sequential labels within the run after NFKC/casefold/whitespace normalization; they are not content hashes.

## Instructions and response sizes

`instructions` is treated as a separate bot-side logged string, not assumed to be a system prompt or actual provider input. Null and blank values are distinguished. Instruction character/word/token-proxy summaries use nonempty strings; reuse groups use NFKC, casefold, and whitespace collapse. Group comparisons across request/category/model/provider are descriptive associations only.

Bot response sizes use the same character, word, line, sentence, and `ceil(characters / 4)` proxy metrics as messages generally. Exact and conservative-normalized response repeats, plus near-duplicate candidates, are calculated in memory. The near-duplicate output uses character n-gram TF-IDF cosine and a 0.70 exploratory threshold. No response text is displayed or exported; repetition and similarity do not measure response correctness, answer equivalence, or quality.

## Hypothetical input/history growth scenario

For each matched bot row, the scenario character total is:

`all earlier transcript message content in the session + matched current user content + this bot row's logged instructions + this bot row's logged RAG context`.

Each component is reported separately. Missing logged instruction/context contributes zero to this *logged-field scenario* only; it does not establish that the component was absent from the provider request. Attachments and the `input` configuration proxy are presence signals and are not converted to text/token counts. The aggregate character/4 estimate applies `ceil(total characters / 4)` and is not a provider tokenizer, actual prompt composition, input-token count, or billing estimate. Prior history counts every earlier user and bot `content` in array order and can therefore include messages that an application did not send, filtered, summarized, or truncated. Turn/session growth is descriptive and may count overlapping history across successive hypothetical calls.

## Repeated request → instruction → model/provider → response comparisons

Repeated request events are grouped using conservative NFKC/casefold/whitespace normalization. For pairwise response comparisons, each user-message event is represented by its first associated bot record; that choice does not resolve ambiguous pairing. Comparisons include request group, instruction group/presence, logged RAG state and context similarity, prior transcript size, model/provider labels, response size, and local response character n-gram TF-IDF cosine. Similarity at or above 0.85 is an exploratory comparison threshold, not a semantic-equivalence judgment.

Progressive cache-candidate screens require (1) the same normalized request, (2) the same nonempty normalized instruction, (3) no logged RAG on either record, (4) no earlier transcript messages before either request, and (5) response similarity at least 0.85. These are conservative inspection screens—not cache-hit rates, cache-safety rates, counterfactual savings, or proof a cache would preserve quality. Actual cache safety also depends on user/session identity, time sensitivity, personalization, data freshness, hidden context, and application behavior that are not established here.

## Segment, routing, RAG, and retry-pattern summaries

Response size, instruction presence/size, logged RAG rate/context size, observed timestamp gap, and model assignment are grouped by available category, model/provider, request language/length/complexity/task flags/code/URL, attachment and input-config proxies, instruction status/group, and session depth. Counts accompany summaries; small strata should not be overinterpreted. Opaque categories remain labels, and their definitions are not inferred.

For logged RAG rows, request↔context and context↔response character n-gram cosine similarities are computed in memory. These are lexical overlap proxies only; they do not show that context was included in the provider prompt, useful, or causally influential. Timestamp-gap rank associations and RAG/context size associations are exploratory, noncausal descriptions. Consecutive bot turns, repeated requests, model/provider variation, and short/error-keyword-like responses followed by another user message are pattern proxies only; the export contains no explicit retry, fallback, escalation, failure, or outage outcome.

## Interpretation and privacy

Counts and percentages are descriptive; medians/percentiles are emphasized for skewed distributions. Small groups are not overinterpreted. No significance tests, causal claims, fabricated prices, or savings estimates are made. Sensitive text, attachment payloads, and URLs are not included in notebook outputs or exported candidate tables. Hashes are pseudonymous join aids, not anonymization guarantees. Categories are opaque. The project draft's description of `input` as structured-input widgets is not verifiable from the export: only bot-side `input.items` configuration is observed, so the EDA retains cautious proxy wording. No LLM-as-a-judge or routed-versus-baseline quality analysis is possible without paired routed outputs or quality labels.
