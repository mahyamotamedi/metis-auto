# Full-dataset EDA: detailed findings

Companion to the [short report](full_eda_report.md). Written for a newcomer. Dataset `poriniki/metis`, revision `30f578f283b903cdbd06cd1b5f7f962f76452ded`. Every number is rendered from `reports/full_eda/tables/claims_ledger.csv`. Evidence classes: observed, metadata-derived, heuristic label, hypothetical reconstruction, simulation. Nothing here is experimentally validated. Tables referenced live in `reports/full_eda/tables/`.

## How to read the numbers

- A **request** is an AI message paired with the preceding USER message by order. There is no call ID, so pairing is heuristic ({{pairing.clean:pct}} clean). One visible request may involve several internal calls: {{red.multi_call_messages:pct}} of billed messages carry more than one token-billed item.
- **Missing is unknown.** {{bill.state.empty_list:pct}} of AI messages have an empty billing list (almost all `workflow` bots) and {{bill.state.null:pct}} have none; they are excluded from token and cost figures, never counted as zero.
- **Recorded cost** is Metis's own `totalCost` field, in an unstated currency, with income at {{cost.income_over_cost:f2}} times cost. It is not recomputed from the price file.

## 1. Language

Heuristic labels (script ratios plus short function-word lists; Arabic script is not assumed Persian, Latin script is not assumed English). Of requests with USER text: Persian {{lang.user.fa:pct}}, English {{lang.user.en:pct}}, Persian-English mixed {{lang.user.fa_en_mixed:pct}}, Arabic script without Persian signals {{lang.user.arabic_script_other:pct}}, too short to label {{lang.user.short_uncertain:pct}}, Finglish {{lang.user.finglish:pct}}. Weighted by billed input tokens Persian is {{lang.tokw.fa:pct}}, because Persian requests carry the long instructions and RAG context. {{lang.sess_switch:pct}} of sessions show more than one language label. Instruction texts are Persian-labelled on {{lang.instr_bots.fa:pct}} of bots and English-labelled on {{lang.instr_bots.en:pct}}, but English instructions front {{lang.instr_reqs.en:pct}} of requests. Digit and character-variant shapes: Latin digits in {{text.user_has_latin_digits:pct}} of USER messages, Persian digits in {{text.user_has_persian_digits:pct}}, ZWNJ in {{text.user_has_zwnj:pct}}, Arabic yeh/kaf in {{text.user_has_arabic_variants:pct}}. **Unvalidated:** a 40-per-label review sheet is exported (`reports/full_eda/review/language_validation.csv`, labels pending a Persian-capable reviewer). Finglish is almost absent by this heuristic, which may reflect its short word list.

## 2. Structure and history

Sessions have a median of {{session.user_turns_median:int}} user messages and {{session.single_turn:pct}} are single-turn. USER messages are short: median {{user.chars.median:int}} characters, {{user.chars_le_100:pct}} at most 100 characters. Answers have median {{ai.chars.median:int}} characters. The timestamp gap from USER to AI message has median {{gap.user_to_ai_s.median:f1}} s and p99 {{gap.user_to_ai_s.p99:int}} s; this is not API latency.

At turn 0 median billed input is {{hist.median_input_turn0:int}} tokens and at turn 20+ it is {{hist.median_input_turn20p:int}}, while median logged prior characters grow to {{hist.median_prior_chars_turn20p:int}}. Within a bot, billed input is {{hist.ratio_to_t0.1:f2}}x its turn-0 median at turn 1 and {{hist.ratio_to_t0.20+:f2}}x at turn 20+ (no-RAG requests). Within-bot Spearman correlation between billed input and logged prior characters has median {{hist.within_bot_spearman_median:f2}}, so history does reach the model in some form. {{bot.memory_enabled_requests:int}} requests are on memory-enabled bots and {{bot.summarizer_requests:int}} on bots that summarise. The policy (full window, token budget, summary) cannot be identified from this export.

## 3. Tokens and cost

Billed messages carry {{tok.input_total:m1}} effective input tokens, {{tok.output_total:m1}} output tokens and {{tok.cached_total:m1}} cached tokens ({{tok.cached_share:pct}} of input). Per billed message, input has median {{dist.input_tokens.median:int}} tokens, p90 {{dist.input_tokens.p90:int}} and p99 {{dist.input_tokens.p99:int}}. Total recorded cost is {{cost.recorded_total:int}} units: input tokens {{cost.split.input:pct}}, output {{cost.split.output:pct}}, cached input {{cost.split.cached_input:pct}}, per-call fees {{cost.split.per_call:pct}}. The top 1% of bots take {{cost.top1pct_bot:pct}} of cost, the top 10% {{cost.top10pct_bot:pct}}; the top 1% of sessions take {{cost.top1pct_session:pct}}.

**Per-call fees.** {{fee.per_call_rows:int}} billing items are charged per call without token usage. Their modal charge is {{fee.per_call_modal_amount:g}} units ({{fee.per_call_modal_share:pct}} of them), {{fee.percall_msgs_with_rag_queries:pct}} of the messages that have them log RAG queries, and the count tracks logged queries closely (correlation {{fee.corr_percall_items_rag_queries:f2}}). My reading is a per-retrieval-query fee; Metis must confirm.

**Model labels.** The label sits on the bot. `gemini-2.5-flash` is {{model.req_share.gemini-2.5-flash:pct}} of requests and {{model.cost_share.gemini-2.5-flash:pct}} of cost; `gemini-2.5-flash-lite` is {{model.req_share.gemini-2.5-flash-lite:pct}} and {{model.cost_share.gemini-2.5-flash-lite:pct}}; `gpt-4o-mini` {{model.req_share.gpt-4o-mini:pct}} and {{model.cost_share.gpt-4o-mini:pct}}; `claude-4-opus` {{model.req_share.claude-4-opus:pct}} of requests but {{model.cost_share.claude-4-opus:pct}} of cost. Implied unit rates differ by model and from the 2026-10-18 price file (`implied_unit_rates.csv`), so repricing against that file uses a different basis from the recorded cost.

**Token fidelity.** Counts are recorded usage (observed, provenance unverified). The turn-0 slope implies about {{tok.chars_per_token_slope.fa:f1}} instruction characters per input token for Persian-labelled bots and {{tok.chars_per_token_slope.en:f1}} for English-labelled ones (hypothetical; slope-based, so fixed overhead is absorbed by the intercept). Both are well under the chars/4 rule, so chars/4 would understate token counts here.

## 4. Instructions, RAG, attachments, tools

**Instructions.** {{instr.n_bots_with_text:int}} used bots hold instruction text; {{instr.n_groups:int}} distinct normalised texts; {{instr.bots_in_shared_group:pct}} of those bots share a text with another bot. Instruction length has median {{instr.chars.median:int}}, p90 {{instr.chars.p90:int}}, p99 {{instr.chars.p99:int}} characters. The 10 largest groups cover {{instr.top10_group_request_share:pct}} of requests. Fits at turn 0 give about {{recon.t0.all.coef_instr:f2}} tokens per instruction character, so instructions are very probably sent every call: about {{comp.instr_share:pct}} of billed input (hypothetical).

**RAG.** {{rag.requests_with_chunks:pct}} of AI messages log chunks, {{rag.chunks_per_req.median:int}} per request at the median, {{rag.chars_per_req.median:int}} characters (p99 {{rag.chars_per_req.p99:int}}). The chunk table has {{rag.chunk_rows:int}} rows but only {{rag.distinct_chunks:int}} distinct texts, so {{rag.chunk_dup_rows:pct}} of chunk rows repeat an earlier chunk. {{rag.chunk_repeat_in_session:pct}} repeat one already supplied earlier in the same session and {{red.rag_dup_within_message:pct}} duplicate another chunk in the same message. Chunk lengths cluster at a ceiling near 2,500 characters. Retrieved chunks are about {{comp.rag_share:pct}} of billed input (hypothetical). Whether retrieval improved any answer is untestable here.

**Attachments, tools, actions.** {{att.requests_user_attachments:pct}} of paired USER messages have attachments ({{att.type.IMAGE:int}} image items, {{att.type.FILE:int}} file, {{att.type.AUDIO:int}} audio, {{att.type.VIDEO:int}} video); content was not analysed. {{tool.requests:pct}} of AI messages log tool calls and {{actions.requests:pct}} carry moderation/action records. Bots define functions for {{bot.functions_requests:int}} requests and enable Google search for {{bot.google_search_requests:int}}.

## 5. Exact cache

See the report table. Additional detail: {{cache.bot_text_dup_cross_session:pct}} of duplicate bot-plus-text groups span more than one session. Among eligible first-turn requests, {{cache.firstturn_repeat_share:pct}} belong to a repeated bot-plus-text key and the 100 most frequent keys cover {{cache.firstturn_top100_share:pct}}. Candidate hits on memory-enabled bots are {{cache.hits_memory_bot:pct}} and those with logged RAG chunks {{cache.hits_rag_bot:pct}}; both groups are unsafe to reuse without a state-aware key. Timestamps are naive, so reuse intervals and TTL effects carry that caveat. Only same-user reuse could be measured; cross-user is unmeasured because each bot has one owner.

## 6. Semantic cache

Only a lexical floor exists: {{sem.candidate_pairs:int}} same-bot candidate pairs in a seeded sample of {{sem.sample_size:int}} distinct first-turn requests. Review sheet: `semantic_pair_validity.csv`. Embedding-based matching, thresholds, precision and recall are pending.

## 7. Context reduction and routing

Structural sizing only. Requests above 32,000 input tokens are {{red.input_over_32000.reqs:pct}} of billed requests but {{red.input_over_32000.tokens:pct}} of input tokens. Provider caching covers {{red.cached_share_single:pct}} of input on single-call requests. A same-basis routing simulation gives an upper bound of {{route.sim_save.all_billed_requests:pct}} of recorded cost if every billed request ran on the cheapest high-volume model at its recorded rate; this ignores quality, capability, context limits and the fee block, and it is not a savings estimate. Price-file repricing relative to the premium baseline `gpt-5.4`: `gpt-5-nano` costs {{fin.reprice_vs_premium.metis-gpt-5-nano:f3}} of it and `gpt-4o-mini` {{fin.reprice_vs_premium.metis-gpt-4o-mini:f3}} for the same tokens (simulation, tokens assumed model-independent). {{route.finish_length:pct}} of answers end with `LENGTH`; {{ans.json_like:pct}} parse as JSON.

## 8. Answers to the questions in the execution brief

1. **Language mix:** see §1; validation pending.
2. **Representativeness:** the full export, dominated by a few user IDs ({{tenant.top5_user_requests:pct}} of requests from 5); differs from the sample in structure and Persian share.
3. **Field meaning:** `model`, `provider` and `instructions` are bot configuration; `input` holds widget definitions; `rag` holds retrieved chunks; instructions and chunks are very probably sent in full. Confidence: moderate, from fits, not verified payloads.
4. **History:** stored in full, transmitted in some reduced form; policy unidentified.
5. **Concentration:** by bot ({{cost.top1pct_bot:pct}} of cost in the top 1%), by model label, and by per-call fees ({{cost.split.per_call:pct}}).
6. **RAG:** see §4; unknown whether non-configured bots log chunks legitimately ({{rag.unconfigured_with_chunks:pct}} do).
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
| U-01 | billed or actual token counts | recorded per AI message for {{bill.state.items:pct}} of messages; provenance of counts unverified | resolved in part (observed) |
| U-02 | verified prices and label mapping | recorded cost uses its own unit rates, different from the 2026-10-18 price file; labels mapped in `config/reference/label-mapping-full-v1.toml` | partly |
| U-03 | latency, retries, failures | no latency, retry or failure fields; only a user-to-answer timestamp gap | not measurable |
| U-04 | provider prompt composition | instructions and chunks very probably sent in full; history reduced; composition estimate is hypothetical | partly |
| U-05 | quality labels, who chose the model | no quality labels; model is a bot setting, selection flow unknown | not measurable |
| U-06 | why models were assigned | not logged | not measurable |
| U-07 | signal for "unsatisfactory" | only `finish_reason` ({{route.finish_length:pct}} `LENGTH`) and moderation actions ({{actions.requests:pct}}) | thin |
| U-08 | cache safety factors | memory, RAG, tools and summaries are bot flags; time sensitivity unlabelled | partly |
| U-09 | meaning of `input`, `default`/`workflow`, plateau | `input` is a widget definition; `workflow` bots carry no token billing; the 4,019 plateau is not reproduced | resolved in part |
| U-10 | does the sample represent the full set | no: structure, language share and cost concentration differ | refuted |
| Q-04 | failover availability target | no failure events logged | not measurable |
| Q-06 | timezone semantics | timestamps are naive; `created_at` precedes the first message month for {{scope.sessions_created_before_msgs:pct}} of sessions | open |
| Q-09 | `input`, labels, plateau | see U-09 | resolved in part |
| Q-22 | traffic source identifiable | no explicit field; `user_id`, `bot_id` and the `public` flag exist; the owner link covers {{tenant.users_with_owner:pct}} of user rows | partly (proxies only) |
