# EDA methodology

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

## Interpretation and privacy

Counts and percentages are descriptive; medians/percentiles are emphasized for skewed distributions. Small groups are not overinterpreted. No significance tests, causal claims, fabricated prices, or savings estimates are made. Sensitive text, attachment payloads, and URLs are not included in notebook outputs or exported candidate tables. Hashes are pseudonymous join aids, not anonymization guarantees.
