# Full-dataset EDA: detailed findings

Companion to the [short report](full_eda_report.md). Written for a newcomer. Dataset `poriniki/metis`, revision `30f578f283b903cdbd06cd1b5f7f962f76452ded`. Every number is rendered from `reports/full_eda/tables/claims_ledger.csv`. Evidence classes: observed, metadata-derived, heuristic label, hypothetical reconstruction, simulation. Nothing here is experimentally validated. Tables referenced live in `reports/full_eda/tables/`.

## How to read the numbers

- A **request** is an AI message paired with the preceding USER message by order. There is no call ID, so pairing is heuristic (94.9% clean). One visible request may involve several internal calls: 1.4% of billed messages carry more than one token-billed item.
- **Missing is unknown.** 29.7% of AI messages have an empty billing list (almost all `workflow` bots) and 0.1% have none; they are excluded from token and cost figures, never counted as zero.
- **Recorded cost** is Metis's own `totalCost` field, in an unstated currency, with income at 1.10 times cost. It is not recomputed from the price file.

## 1. Language

Heuristic labels (script ratios plus short function-word lists; Arabic script is not assumed Persian, Latin script is not assumed English). Of requests with USER text: Persian 76.8%, English 3.8%, Persian-English mixed 3.6%, Arabic script without Persian signals 3.7%, too short to label 11.9%, Finglish 0.0%. Weighted by billed input tokens Persian is 85.7%, because Persian requests carry the long instructions and RAG context. 21.4% of sessions show more than one language label. Instruction texts are Persian-labelled on 53.6% of bots and English-labelled on 35.5%, but English instructions front 82.2% of requests. Digit and character-variant shapes: Latin digits in 10.9% of USER messages, Persian digits in 0.0%, ZWNJ in 7.6%, Arabic yeh/kaf in 0.7%. **Unvalidated:** a 40-per-label review sheet is exported (`reports/full_eda/review/language_validation.csv`, labels pending a Persian-capable reviewer). Finglish is almost absent by this heuristic, which may reflect its short word list.

## 2. Structure and history

Sessions have a median of 2 user messages and 32.6% are single-turn. USER messages are short: median 27 characters, 86.4% at most 100 characters. Answers have median 226 characters. The timestamp gap from USER to AI message has median 1.8 s and p99 26 s; this is not API latency.

At turn 0 median billed input is 727 tokens and at turn 20+ it is 1,024, while median logged prior characters grow to 34,506. Within a bot, billed input is 1.28x its turn-0 median at turn 1 and 1.71x at turn 20+ (no-RAG requests). Within-bot Spearman correlation between billed input and logged prior characters has median 0.49, so history does reach the model in some form. 12,149 requests are on memory-enabled bots and 14,001 on bots that summarise. The policy (full window, token budget, summary) cannot be identified from this export.

## 3. Tokens and cost

Billed messages carry 1,191.6 million effective input tokens, 72.6 million output tokens and 83.2 million cached tokens (7.0% of input). Per billed message, input has median 957 tokens, p90 10,541 and p99 122,431. Total recorded cost is 507 units: input tokens 36.0%, output 14.3%, cached input 0.4%, per-call fees 37.6%. The top 1% of bots take 53.6% of cost, the top 10% 93.5%; the top 1% of sessions take 32.5%.

**Per-call fees.** 90,639 billing items are charged per call without token usage. Their modal charge is 0.002 units (97.6% of them), 99.5% of the messages that have them log RAG queries, and the count tracks logged queries closely (correlation 0.99). My reading is a per-retrieval-query fee; Metis must confirm.

**Model labels.** The label sits on the bot. `gemini-2.5-flash` is 12.5% of requests and 65.0% of cost; `gemini-2.5-flash-lite` is 26.2% and 7.0%; `gpt-4o-mini` 18.7% and 3.4%; `claude-4-opus` 0.0% of requests but 5.6% of cost. Implied unit rates differ by model and from the 2026-10-18 price file (`implied_unit_rates.csv`), so repricing against that file uses a different basis from the recorded cost.

**Token fidelity.** Counts are recorded usage (observed, provenance unverified). The turn-0 slope implies about 3.2 instruction characters per input token for Persian-labelled bots and 3.0 for English-labelled ones (hypothetical; slope-based, so fixed overhead is absorbed by the intercept). Both are well under the chars/4 rule, so chars/4 would understate token counts here.

## 4. Instructions, RAG, attachments, tools

**Instructions.** 614 used bots hold instruction text; 501 distinct normalised texts; 21.8% of those bots share a text with another bot. Instruction length has median 1,173, p90 4,147, p99 9,313 characters. The 10 largest groups cover 75.1% of requests. Fits at turn 0 give about 0.29 tokens per instruction character, so instructions are very probably sent every call: about 22.4% of billed input (hypothetical).

**RAG.** 18.2% of AI messages log chunks, 15 per request at the median, 7,440 characters (p99 45,085). The chunk table has 994,031 rows but only 25,989 distinct texts, so 97.4% of chunk rows repeat an earlier chunk. 61.2% repeat one already supplied earlier in the same session and 33.3% duplicate another chunk in the same message. Chunk lengths cluster at a ceiling near 2,500 characters. Retrieved chunks are about 35.8% of billed input (hypothetical). Whether retrieval improved any answer is untestable here.

**Attachments, tools, actions.** 1.9% of paired USER messages have attachments (12,649 image items, 324 file, 142 audio, 16 video); content was not analysed. 0.1% of AI messages log tool calls and 1.0% carry moderation/action records. Bots define functions for 4,257 requests and enable Google search for 927.

## 5. Exact cache

See the report table. Additional detail: 51.2% of duplicate bot-plus-text groups span more than one session. Among eligible first-turn requests, 23.0% belong to a repeated bot-plus-text key and the 100 most frequent keys cover 16.1%. Candidate hits on memory-enabled bots are 2.6% and those with logged RAG chunks 9.0%; both groups are unsafe to reuse without a state-aware key. Timestamps are naive, so reuse intervals and TTL effects carry that caveat. Only same-user reuse could be measured; cross-user is unmeasured because each bot has one owner.

## 6. Semantic cache

Only a lexical floor exists: 3,002 same-bot candidate pairs in a seeded sample of 40,366 distinct first-turn requests. Review sheet: `semantic_pair_validity.csv`. Embedding-based matching, thresholds, precision and recall are pending.

## 7. Context reduction and routing

Structural sizing only. Requests above 32,000 input tokens are 1.2% of billed requests but 23.1% of input tokens. Provider caching covers 10.7% of input on single-call requests. A same-basis routing simulation gives an upper bound of 41.6% of recorded cost if every billed request ran on the cheapest high-volume model at its recorded rate; this ignores quality, capability, context limits and the fee block, and it is not a savings estimate. Price-file repricing relative to the premium baseline `gpt-5.4`: `gpt-5-nano` costs 0.021 of it and `gpt-4o-mini` 0.053 for the same tokens (simulation, tokens assumed model-independent). 0.4% of answers end with `LENGTH`; 0.5% parse as JSON.

## 8. Answers to the questions in the execution brief

1. **Language mix:** see §1; validation pending.
2. **Representativeness:** the full export, dominated by a few user IDs (97.0% of requests from 5); differs from the sample in structure and Persian share.
3. **Field meaning:** `model`, `provider` and `instructions` are bot configuration; `input` holds widget definitions; `rag` holds retrieved chunks; instructions and chunks are very probably sent in full. Confidence: moderate, from fits, not verified payloads.
4. **History:** stored in full, transmitted in some reduced form; policy unidentified.
5. **Concentration:** by bot (53.6% of cost in the top 1%), by model label, and by per-call fees (37.6%).
6. **RAG:** see §4; unknown whether non-configured bots log chunks legitimately (6.1% do).
7. **Exact cache:** see the report table; per sharing scope, session and same-user only.
8. **Semantic cache:** lexical floor only; incorrect-hit rate unmeasured.
9. **Reduction:** structural hypotheses only; quality unverified.
10. **Routing needs:** language, instruction/RAG size, history depth, attachments, tools, JSON output, context fit, all available before generation.
11. **Quality from logs:** not possible; a small benchmark is specified in `experiment_plan.md`.
12. **Net savings:** not computable honestly without quality and overhead evidence; ledger figures are labelled simulations.
13. **What needs what:** implementation changes (logging), further review (labels, pairs), clarification from Metis (`metis_questions.md`).

## 9. Re-check of unknowns and data-owner questions

| ID | Original question | Result on the full export | Verdict |
|---|---|---|---|
| U-01 | billed or actual token counts | recorded per AI message for 70.2% of messages; provenance of counts unverified | resolved in part (observed) |
| U-02 | verified prices and label mapping | recorded cost uses its own unit rates, different from the 2026-10-18 price file; labels mapped in `config/reference/label-mapping-full-v1.toml` | partly |
| U-03 | latency, retries, failures | no latency, retry or failure fields; only a user-to-answer timestamp gap | not measurable |
| U-04 | provider prompt composition | instructions and chunks very probably sent in full; history reduced; composition estimate is hypothetical | partly |
| U-05 | quality labels, who chose the model | no quality labels; model is a bot setting, selection flow unknown | not measurable |
| U-06 | why models were assigned | not logged | not measurable |
| U-07 | signal for "unsatisfactory" | only `finish_reason` (0.4% `LENGTH`) and moderation actions (1.0%) | thin |
| U-08 | cache safety factors | memory, RAG, tools and summaries are bot flags; time sensitivity unlabelled | partly |
| U-09 | meaning of `input`, `default`/`workflow`, plateau | `input` is a widget definition; `workflow` bots carry no token billing; the 4,019 plateau is not reproduced | resolved in part |
| U-10 | does the sample represent the full set | no: structure, language share and cost concentration differ | refuted |
| Q-04 | failover availability target | no failure events logged | not measurable |
| Q-06 | timezone semantics | timestamps are naive; `created_at` precedes the first message month for 0.9% of sessions | open |
| Q-09 | `input`, labels, plateau | see U-09 | resolved in part |
| Q-22 | traffic source identifiable | no explicit field; `user_id`, `bot_id` and the `public` flag exist; the owner link covers 15.0% of user rows | partly (proxies only) |
