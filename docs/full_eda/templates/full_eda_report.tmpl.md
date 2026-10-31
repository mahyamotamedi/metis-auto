# Metis full-dataset EDA: short report

Dataset `poriniki/metis`, revision `30f578f283b903cdbd06cd1b5f7f962f76452ded` (pinned). Run date 2026-10-30. Status: **draft for review**. Every number below is rendered from [`claims_ledger.csv`](../../reports/full_eda/tables/claims_ledger.csv) and checked by `scripts/full_eda_render.py --check`. No message content, instructions or retrieved text appears here. Evidence classes: *observed* (read from the export), *metadata-derived*, *heuristic label*, *hypothetical reconstruction*, *simulation*. Detail: [`eda_findings.md`](eda_findings.md), [`experiment_plan.md`](experiment_plan.md), [`metis_questions.md`](metis_questions.md).

## 1. Bottom line

- **The export is small in tenants and very concentrated.** {{scope.sessions:int}} sessions, {{scope.messages:int}} messages, {{scope.requests:int}} candidate request-response pairs, but the 5 largest `user_id`s produce {{tenant.top5_user_requests:pct}} of requests and the top 1% of users {{cost.top1pct_user:pct}} of recorded cost. Findings describe this export, not production.
- **Per-call fees are a larger cost block than any token lever.** {{cost.split.per_call:pct}} of recorded cost is per-call charges (modal amount {{fee.per_call_modal_amount:g}} units), which track logged RAG queries (correlation {{fee.corr_percall_items_rag_queries:f2}}). Input tokens are {{cost.split.input:pct}} and output {{cost.split.output:pct}}. Token reduction and routing cannot touch the fee block.
- **Exact caching is safe only in narrow forms.** With a key that includes bot, text and full history, {{cache.bot+full_history.global.hit_elig:pct}} of eligible requests are *candidate* hits, all across sessions, covering {{cache.bot+full_history.global.avoided_cost:pct}} of recorded cost. Within one session the key never repeats. A bot-plus-text key reaches {{cache.bot+text.global.hit_elig:pct}} but ignores history.
- **Logged history is not fully resent, and one model label carries the cost.** Median logged prior text at turn 20+ is {{hist.median_prior_chars_turn20p:int}} characters, yet median billed input is {{hist.median_input_turn20p:int}} tokens. The label `gemini-2.5-flash` is {{model.req_share.gemini-2.5-flash:pct}} of requests and {{model.cost_share.gemini-2.5-flash:pct}} of recorded cost.
- **Quality cannot be established from this data.** No quality labels, no alternative-model outputs, no latency, no failure log. Routing, cascade and reduction savings below are simulations or structural sizing, not quality-preserving savings.

## 2. Data and representativeness

**Analysed:** all {{scope.sessions:int}} sessions in the pinned revision (the team's "about 100k" is not borne out; the dataset card agrees with the count), {{scope.messages:int}} messages ({{scope.msg_n.USER:int}} USER, {{scope.msg_n.AI:int}} AI, {{scope.msg_n.SYSTEM:int}} SYSTEM, {{scope.msg_n.TOOL:int}} TOOL), {{scope.bots_total:int}} bot configurations ({{scope.bots_in_sessions:int}} used) and {{scope.users:int}} user IDs in sessions. Message timestamps run {{scope.first_ym:ym}} to {{scope.last_ym:ym}}; session `created_at` starts {{scope.session_first_ym:ym}}, and {{scope.sessions_created_before_msgs:pct}} of sessions were created before the first message month (naive timestamps, timezone unknown, Q-06). `dialogue_length` matches observed messages for {{integrity.dialogue_len_match:pct0}} of sessions; there are {{scope.dup_message_ids:int}} duplicate message IDs and {{scope.null_timestamps:int}} null timestamps.

**Pairing is heuristic.** There is no call ID, so each AI message is paired with the preceding USER message: {{pairing.clean:pct}} clean, {{pairing.no_preceding_user:pct}} with no preceding USER, {{pairing.consecutive_user:pct}} after consecutive USER messages, {{pairing.multiple_answers:pct}} after another AI message. {{pairing.unanswered_user:pct}} of USER messages have no AI answer.

**Differences from the sample.** The sample was four opaque categories of 25 sessions and 100 sessions in all; the export has no category field, relational tables instead of nested JSON, a `bot` table that holds model, provider and instructions, billing records with token counts and cost, and user IDs. Persian share of USER messages is {{lang.user.fa:pct}} here against about nine in ten in the sample. Categories as strata are not available; bots and configured model labels are used instead (NG-08).

**What generalizes.** Conclusions hold for this export. Traffic is dominated by a few tenants and bots ({{tenant.top10_bot_requests:pct}} of requests from 10 bots), the dataset license limits use to educational purposes and forbids redistribution (committed outputs here are aggregates only), and no sampling probabilities are known, so no traffic weighting is applied.

## 3. What the fields mean and how sure we are

- **`model` is a bot setting, not a per-message log.** Provider and model live on the bot record, a single current snapshot ({{model.bots_updated_after_created:pct}} of used bots were edited after creation). Whether a user or Metis chose it, and which model served each message, is unverified (see questions). {{model.workflow_share:pct}} of requests belong to `workflow`/`default` bots, which carry no token billing ({{model.workflow_billing_empty:pct}} of them have an empty billing list).
- **`instructions` are bot configuration**, present as text on {{instr.n_bots_with_text:int}} used bots in {{instr.n_groups:int}} distinct normalised texts; the stored text may postdate a given request. At turn 0 billed input rises about {{recon.t0.en.coef_instr:f2}} (English-labelled) and {{recon.t0.fa.coef_instr:f2}} (Persian-labelled) tokens per instruction character, with R² {{recon.t0.fa.r2:f2}} for the Persian-labelled fit, so the text is very probably sent in full. Status: *partially verified*; the stored text may still postdate a request.
- **Billing is the best token evidence**: {{bill.state.items:pct}} of AI messages carry billing items, with {{tok.input_total:m1}} input tokens and {{tok.output_total:m1}} output tokens recorded. For {{tok.models_cached_separate:int}} models cached tokens are reported outside `inputTokens`; I add them back. Recorded costs follow their own unit rates, which differ from the 2026-10-18 price file (see the implied-rate table), so as-logged cost and repriced cost are never mixed.
- **`rag`**: {{rag.requests_with_chunks:pct}} of AI messages log at least one chunk; {{rag.configured_with_chunks:pct}} of RAG-configured requests do, and {{rag.unconfigured_with_chunks:pct}} of non-configured ones also do. Billed input at turn 0 rises {{recon.t0rag.coef_rag:f2}} tokens per chunk character (R² {{recon.t0rag.r2:f2}}), so retrieved chunks are sent in full. Chunk lengths cap near 2,500 characters; the sample's 4,019 plateau is not a per-request cap here (per-request context median {{rag.chars_per_req.median:int}} characters, p99 {{rag.chars_per_req.p99:int}}).
- **`input`** objects appear on {{input.requests_with_items:pct}} of AI messages and hold form-widget definitions (name, type, label, choices), a bot-side configuration; user widget use is not observable.
- **History**: logged history is complete, but what reaches the provider is unknown. Billed input grows only modestly with turn, so history is windowed, summarised or both. A rough decomposition of billed input (turn-0 fits applied to all single-call requests; *hypothetical*) attributes {{comp.instr_share:pct}} to instructions, {{comp.rag_share:pct}} to retrieved chunks, {{comp.user_share:pct}} to the current message and {{comp.remainder_share:pct}} to the rest (history, memory, summaries, formatting, fit error).

## 4. Findings by lever

### 4.1 Exact response cache (simulation, candidate hits)

Replay is chronological with answer-completion times taken from the logged AI timestamp, no future answers, and {{cache.elig.timestamps_valid:pct}} of AI messages eligible after excluding missing text, non-STOP finishes, attachments, tool calls and moderation actions. Duplicate-occurrence counts, the n−1 upper bound and realistic candidate hits are different quantities: for bot plus text across all users, {{cache.bot+text.global.reusable_ub:int}} requests are reusable in the cold-cache upper bound, which comes from {{cache.bot+text.global.pairs:int}} pairs.

![Exact cache replay](../../reports/full_eda/figures/fig4_exact_cache.png)

| Key (scope) | Candidate hits / eligible | Recorded cost of hits / total |
|---|---|---|
| request text only (all users) | {{cache.text_only.global.hit_elig:pct}} | {{cache.text_only.global.avoided_cost:pct}} |
| bot + text (all users; bots belong to one user) | {{cache.bot+text.global.hit_elig:pct}} | {{cache.bot+text.global.avoided_cost:pct}} |
| bot + text (same session) | {{cache.bot+text.session.hit_elig:pct}} | {{cache.bot+text.session.avoided_cost:pct}} |
| bot + full history (cross-session) | {{cache.bot+full_history.global.hit_elig:pct}} | {{cache.bot+full_history.global.avoided_cost:pct}} |
| bot + full history + RAG set | {{cache.bot+full_history+rag_set.global.hit_elig:pct}} | {{cache.bot+full_history+rag_set.global.avoided_cost:pct}} |

Cross-user reuse is unmeasurable: every bot belongs to one `user_id`, so shared scope across tenants has no data. Median gap between the first answer and a later bot-plus-text candidate hit is {{cache.reuse_gap_h.median:int}} hours, so short TTLs lose much of the opportunity. {{cache.hits_first_turn:pct}} of candidate hits are at turn 0. **Unproven:** hit correctness, freshness, personalisation. Cost shown is the as-logged cost of avoided calls, before lookup and storage overhead.

### 4.2 Semantic response cache (heuristic; embeddings not run)

A seeded lexical screen over {{sem.sample_size:int}} distinct first-turn requests found {{sem.candidate_pairs:int}} same-bot candidate pairs (estimated word-bigram Jaccard at least 0.8), so {{sem.requests_in_near_pairs:pct}} of sampled requests have a near-duplicate partner beyond exact matches. This is a floor for lexical similarity only. No Persian-capable embedding model was run; precision, recall and incorrect-hit rate are **pending** a labelled review set (exported, unlabelled). Similarity is not correctness.

### 4.3 Context reduction (structural sizing; quality unverified)

![Logged history vs billed input](../../reports/full_eda/figures/fig3_history_growth.png)

- **History/memory:** relative to each bot's own turn-0 median, billed input is {{hist.ratio_to_t0.3-4:f2}}x at turns 3-4 and {{hist.ratio_to_t0.20+:f2}}x at turn 20+. Input above the turn-0 level is {{hist.excess_over_t0_all:pct}} of billed input in single-call, no-RAG requests, an upper-bound proxy for history, memory and summary tokens. Windowing already exists in some form; further trimming needs a quality test.
- **Input mass is concentrated:** requests over 8,000 input tokens are {{red.input_over_8000.reqs:pct}} of requests but {{red.input_over_8000.tokens:pct}} of input tokens.
- **RAG:** {{red.rag_dup_within_message:pct}} of chunk rows duplicate another chunk in the same message, and {{rag.chunk_repeat_in_session:pct}} repeat a chunk already supplied earlier in the session. Those are candidate removals, not proven redundancy.
- **Instructions** are about {{comp.instr_share:pct}} of billed input (hypothetical); the 10 largest instruction groups cover {{instr.top10_group_request_share:pct}} of requests and the median instruction is {{instr.chars.median:int}} characters. Provider caching already covers {{tok.cached_share:pct}} of effective input overall and {{red.cached_share_instr_heavy:pct}} where instructions exceed 1,500 characters; Gemini rows record no cached tokens, which is a data gap, not proof of no caching.

### 4.4 Routing, cascade, failover (simulation; no quality evidence)

![Cost composition](../../reports/full_eda/figures/fig2_cost_composition.png)

Configured model labels: {{model.n_labels:int}} labels across {{model.n_providers:int}} providers. A transparent rule ("short, no RAG, no attachments, no tools, no JSON") matches {{route.simple_rule_share:pct}} of billed requests, {{route.simple_rule_cost_share:pct}} of recorded cost, and {{route.simple_rule_already_on_target:pct}} of those already run on the cheapest high-volume model. A same-basis simulation (recorded rates of that model, never routing upward, per-call fees excluded) gives a hypothetical upper-bound saving of {{route.sim_save.simple_rule:pct}} of recorded cost for the rule group and {{route.sim_save.all_billed_requests:pct}} for all billed requests, assuming acceptable quality, which is unverified. Historical model choice is bot configuration, not an optimal-routing label. Escalation signals available in the data are thin: {{route.finish_length:pct}} of answers end with `LENGTH`, and {{ans.json_like:pct}} are JSON-like structured outputs. No failure, retry or fallback events exist.

## 5. Prior-signal check

| ID | Sample claim | Full-data result | Verdict |
|---|---|---|---|
| F-1 | short, right-skewed prompts | median {{user.chars.median:int}} chars, p90 {{user.chars.p90:int}}, p99 {{user.chars.p99:int}} | confirmed |
| F-2 | about 91% Persian | {{lang.user.fa:pct}} of requests (heuristic) | partly: Persian majority, lower share |
| F-3 | instructions large, reused | median {{instr.chars.median:int}} chars; {{instr.n_groups:int}} groups for {{instr.n_bots_with_text:int}} bots; top 10 groups {{instr.top10_group_request_share:pct}} of requests | confirmed; they are bot config |
| F-4 | instructions 82.6% of hypothetical prompt | instructions about {{comp.instr_share:pct}} of billed input, RAG {{comp.rag_share:pct}} (hypothetical decomposition) | refuted for billed input |
| F-5 | RAG plateau at 4,019 chars | chunk cap about 2,500; request context median {{rag.chars_per_req.median:int}} | not reproduced |
| F-6 | repeat groups cover 16.3% of messages | {{user.repeat_occurrences:pct}} of USER texts repeat | confirmed, higher (short texts) |
| F-7 | no safe cache pairs | session scope {{cache.bot+full_history.session.hit_elig:pct}}; cross-session {{cache.bot+full_history.global.hit_elig:pct}} | partly |
| F-8 | 7.5% repeated answers | {{ai.repeat_occurrences:pct}} | confirmed, higher |
| F-9 | median 2 s gap | median {{gap.user_to_ai_s.median:f1}} s, p90 {{gap.user_to_ai_s.p90:f1}} s (not latency) | confirmed |
| H-1 | instructions/prefix the largest lever | instructions {{comp.instr_share:pct}} of input, RAG {{comp.rag_share:pct}}, fees {{cost.split.per_call:pct}} of cost | partly: major, not largest |
| H-2 | history trimming cuts input | excess over turn 0 is {{hist.excess_over_t0_all:pct}} of input | supported structurally; quality untested |
| H-3 | full-key exact cache small but safe | {{cache.bot+full_history.global.hit_elig:pct}} eligible, {{cache.bot+full_history.global.avoided_cost:pct}} of cost | supported as small; validity untested |
| H-4 | semantic beats lexical | lexical floor {{sem.requests_in_near_pairs:pct}}; embeddings not run | inconclusive |
| H-5 | cheap features route | no quality labels | not measurable |
| H-6 | cascade beats single model | no quality signal or failure log | not measurable |
| H-7 | chars/4 misestimates tokens | about {{tok.chars_per_token_slope.fa:f1}} (fa) and {{tok.chars_per_token_slope.en:f1}} (en) chars per token, slope-based | supported directionally |
| H-8 | curated first-turn cache | top 100 keys cover {{cache.firstturn_top100_share:pct}} of first-turn requests; {{cache.firstturn_repeat_share:pct}} repeat | inconclusive; no traffic-source label |

## 6. Decision table

| Lever | Evidence | Eligibility | Expected benefit | Failure modes | Priority | Next validation |
|---|---|---|---|---|---|---|
| Exact cache, full key, session or tenant scope | simulation | {{cache.elig.timestamps_valid:pct}} of requests eligible | small: {{cache.bot+full_history.global.avoided_cost:pct}} of cost | stale or personalised answers | now, narrow | hit-correctness review |
| Semantic cache | heuristic | first-turn, same bot | unknown | wrong reuse | later | labelled pairs, embeddings |
| History/RAG reduction | structural | multi-turn, RAG bots | large input share, unquantified | lost facts | small experiment | fixed-model A/B with judge |
| RAG query fees | observed | RAG-configured bots | up to {{cost.split.per_call:pct}} of cost is fees | stale retrieval | small experiment | count and cache retrieval queries |
| Routing | simulation | rule group {{route.simple_rule_share:pct}} | upper bound {{route.sim_save.simple_rule:pct}} | quality loss | needs data | benchmark with judge |
| Cascade, failover | none | all | unknown | latency, double cost | needs data | failure/retry logging |

**Can implement now:** exact cache with the full key (behind a flag), per-call-fee and cache-hit logging, input-composition fingerprints. **Small experiment:** retrieval-query caching, history windows, RAG dedupe, semantic pairs review. **Needs data:** routing, cascade, failover, cross-user caching.

**Sequence:** (1) log call IDs, per-call fees, cached tokens and the served model; (2) measure hit correctness on a labelled pair set; (3) test RAG query caching and chunk dedupe; (4) history-window A/B; (5) only then routing benchmarks.

## 7. Blockers and data requests

- No quality evidence, no alternative-model outputs, no latency or failure logs, no traffic-source label, and one user per bot (no cross-tenant cache evidence).
- Top requests to Metis: whether `model` is user-selected; the exact prompt composition and history policy; `inputTokens`/`cachedInputTokens` semantics per provider; what the per-call fee covers; Gemini caching; per-message served model; timezone (Q-06). Full list in [`metis_questions.md`](metis_questions.md).
- Hygiene: the execution prompt contained a literal Hugging Face token. It should be rotated. Embedding-based semantic analysis was not run (no local embedding model installed).
