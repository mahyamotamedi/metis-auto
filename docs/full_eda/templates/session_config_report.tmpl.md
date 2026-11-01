# Sessions, chatbot configurations, dominant accounts, and the golden-set proposal

Dataset `poriniki/metis`, revision `30f578f283b903cdbd06cd1b5f7f962f76452ded`, processed 2026-11-01, all {{cls.unique_sessions:int}} sessions. Status: **draft for review**. Every number comes from `reports/full_eda/tables/claims_ledger_d.csv` or a CSV in `reports/full_eda/sessions/`. No message, instruction or knowledge text appears here. Reproduce with `python scripts/full_eda_sessions.py`.

## 1. Short answers

- **Chatbot vs direct LLM.** Inferred chatbot sessions: {{cls.chatbot_sessions:int}} ({{cls.chatbot_share_all:pct}} of all sessions). Inferred direct: {{cls.group_n.a_direct_llm_inferred:int}} ({{cls.group.a_direct_llm_inferred:pct}}). That is {{cls.chatbot_per_direct:f1}} chatbot sessions per direct session, but {{cls.group_n.e_unknown_or_ambiguous:int}} sessions ({{cls.group.e_unknown_or_ambiguous:pct}}) cannot be classified, almost all on `workflow` bots whose real configuration is not exported.
- **The direct group is probably not "people chatting directly with an LLM".** Every session has a `bot_id`. A session with neither instruction nor RAG is a bot left blank. The export has no field that marks a direct conversation.
- **Users vs chatbots.** {{cfg.bots_total:int}} bots belong to {{acct.owning_accounts:int}} accounts ({{acct.bots_per_account_all:f1}} per account). {{cfg.bots_used:int}} bots were used, by {{acct.session_accounts:int}} accounts ({{acct.used_bots_per_session_account:f1}} per account). **People chatting with those bots cannot be counted:** `session.user_id` equals the bot's owner in {{top.session_user_is_bot_owner:pct0}} of sessions.
- **Same instruction and same RAG.** Only {{cfg.all_bots.both.repeated_groups:int}} group of bots has both identical ({{cfg.all_bots.both.bots_in_repeated_groups:int}} bots, {{cfg.all_bots.both.sessions_in_repeated_groups:int}} sessions). Counting all configuration kinds, {{cfg.all_bots.all.repeated_groups:int}} groups hold {{cfg.all_bots.all.bots_in_repeated_groups:int}} bots, most of them never used. Among used bots: {{cfg.used_bots.all.repeated_groups:int}} groups, {{cfg.used_bots.all.bots_in_repeated_groups:int}} bots, {{cfg.used_bots.all.share_of_chatbot_sessions:pct}} of chatbot sessions.
- **Top five.** The 5 largest `user_id`s produce {{top.top5_share:pct}} of requests (user turns), or {{top.top5_share_ai:pct}} on the earlier AI-message basis. **They are owner accounts, not five people.**
- **Categories are weak.** Local rules leave {{cat.unknown_uncertain:pct}} of requests `unknown`. Quotas are a proposal until humans review the labels.

## 2. Schema (verified on this revision)

| Concept | Field path | Notes |
|---|---|---|
| Session | `chat_session.session_id` | unique; `dialogue_length` matches observed messages |
| Turn, role | `chat_message.message_id`, `.type` | `USER`, `AI`, `SYSTEM`, `TOOL`; IDs unique |
| Order | `chat_message.timestamp` | naive, then source order; 2 nulls |
| Account | `chat_session.user_id`, `chat_bot.user_id` | always equal for a session; no sender ID |
| Chatbot | `chat_session.bot_id` → `chat_bot.bot_id` | present on every session |
| Instruction | `chat_bot.instructions` | one snapshot per bot, no version history |
| Model | `chat_bot.provider_name`, `.provider_model` | on the bot, not per message |
| RAG configured | `chat_bot.corpus_ids` (JSON text), `.rag_top_k`, `.rag_reranking` | null differs from `[]` |
| RAG observed | `chat_message.rag` (on AI turns), `derived/chat_message_rag_chunks` | `query`, `relevantChunks`, `corpusId` |
| Attachments, tools | `chat_message.attachments`, `.tool_calls`, `chat_bot.functions` | presence and type only analysed |

**Missing:** chatbot name (the product has one; the export has `description` only), message sender, direct-chat flag, instruction or model history, per-message served model, workflow graph contents, generation settings per call.

**Repeated histories.** Successive records do **not** repeat earlier conversations: the table is one row per message, with {{cls.dup_message_ids:int}} duplicate IDs. So no records were removed and nothing is double counted. Two real kinds of repetition are kept: identical whole transcripts across sessions, and user turns that repeat earlier text. Both are genuine traffic.

## 3. Classification rules

| Decision | Rule |
|---|---|
| Custom instruction | non-blank `instructions` that is not a platform placeholder |
| Platform placeholder | exact text only on `workflow` bots and on at least 5 owners. No phrase list is assumed. It found {{cls.platform_default_texts:int}} text. |
| Blank vs null | whitespace-only is absent; null is unknown |
| RAG positive | non-empty `corpus_ids`, or chunks or a retrieval query on **any** AI turn |
| RAG absent | only `corpus_ids` explicitly empty and nothing observed. A turn without retrieval proves nothing. |
| RAG unknown | `corpus_ids` null or malformed and nothing observed |
| Not counted as instructions | `SYSTEM` messages and instructions typed in user messages |
| Workflow bots | instruction unknown, so group (e) even with RAG observed |

Limits: {{cls.sens_cross_owner_sessions:int}} custom-instruction sessions use text shared by 2 or more owners and {{cls.sens_short_sessions:int}} use text of at most 30 characters. These may be generic, and they stay custom. SYSTEM messages occur in {{cls.sessions_with_system:int}} sessions, {{cls.direct_with_system:int}} of them in the direct group.

## 4. Session report

Raw session rows {{cls.raw_session_rows:int}}, unique {{cls.unique_sessions:int}}, classified {{cls.classified:int}}, ambiguous {{cls.group_n.e_unknown_or_ambiguous:int}}, excluded {{cls.excluded_invalid:int}}. **Reconciliation:** the five groups sum to {{cls.reconciliation_sum:int}}.

{{table:session_groups}}

`share_user_turns` and `share_all_messages` are the secondary, turn-weighted views. Inside group (e):

{{table:session_subtypes:subtype,sessions,user_turns,bots,share_all_sessions}}

**Sensitivity.** Adding sessions with positive evidence that (e) holds (RAG on workflow bots, and custom instructions with unknown RAG) gives {{cls.upper_chatbot:int}} sessions ({{cls.upper_chatbot_share:pct}}). Workflow sessions without any evidence ({{cls.sub.platform_default_no_rag_evidence:int}}) stay unresolved.

**Changing evidence.** {{cls.mixed_rag_n:int}} sessions show retrieval on only some AI turns; {{cls.cfg_disagree_n:int}} show retrieval with no configured corpus, nearly all on workflow bots. {{cls.sessions_no_ai:int}} sessions have no AI message and {{cls.sessions_no_user:int}} have no USER message.

**Bot IDs against the proxy.** All sessions have a `bot_id`, so the ID cannot separate chatbot from direct. The breakdown by `public`, `bot_type` and workflow is in `group_by_bot_flags.csv`.

**Accounts, not users.** These are not proportions of people:

{{table:account_overlap}}

## 5. Repeated instructions and RAG

Equality key: exact instruction hash plus configured-corpus hash. No trimming, case folding or Persian-Arabic normalisation. Corpus list order is preserved. Model is excluded. Bots with neither are excluded. `bot_id` is the chatbot identity and a fingerprint is only a configuration.

{{table:shared_config_summary}}

Extra entities means bots beyond one per group, not the total in repeated groups. `instruction_rag_unknown` has a null corpus field, so RAG equality cannot be claimed. Group sizes are in `shared_group_sizes_*.csv`. Largest groups:

{{table:shared_config_top_groups:config,kind,bots,owners,sessions,user_turns,ins_chars,models}}

- **Most large groups were never used.** They are many unused bots of one owner with the same text, and bot sharing there looks like bulk creation; the data does not say why.
- **G08 is a notable case:** one owner, one instruction, many models (see `models`). It looks like a side-by-side model comparison, but that is an inference. It may be useful later for routing work, though it has no quality labels.
- **Optional, separately labelled comparisons.** Exact instruction texts {{cfg.strict_instruction_texts:int}}, after Persian-aware normalisation {{cfg.normalized_instruction_texts:int}}. Corpus lists with order {{cfg.rag_refs_strict:int}}, ignoring order {{cfg.rag_refs_orderless:int}}.
- **Same retrieved chunks is a different question.** {{cfg.retrieved_payload_turns:int}} AI turns hold {{cfg.retrieved_payload_distinct:int}} distinct chunk sets, which vary per turn and do not prove the same knowledge base. {{cfg.workflow_bots_retrieval:int}} workflow bots retrieve from {{cfg.workflow_distinct_obs_corpus:int}} distinct observed corpus sets, a limited proxy.
- **Configured vs observed corpus:**

{{table:observed_vs_configured_corpus}}

- **Configuration change is not observable.** One snapshot per bot; {{cfg.used_bots_updated_after_created:int}} used bots have `updated_at` after `created_at`, with no record of what changed. Partial overlap and disjoint rows above may reflect edits.

## 6. The five dominant accounts

**Verified.** Request = a USER turn; {{top.request_total:int}} in total, {{top.missing_user_ids:int}} without `user_id`, across {{top.accounts_with_requests:int}} accounts. Top five: {{top.top5_share:pct}}. The reported 97% used AI messages ({{top.top5_share_ai:pct}} here), so the two agree closely and the difference is the unit.

**Identity.** The ID is the **bot owner** on every session. Traffic is implausible for one person: User A averages {{top.A.requests_per_active_day:int}} requests per active day over {{top.A.sessions:int}} sessions. Five human end users cannot be established. These accounts could be organisations or service accounts; the data does not say, and no automation is claimed. Pseudonyms are used; the mapping is in git-ignored `runs/`.

{{table:top5_side_by_side:account,requests,share_requests,cumulative_share,sessions,requests_per_session,bots_owned,bots_used,top_bot_request_share,chatbot_session_share,unknown_session_share,median_context_chars,exact_repeat_share,after_input_widget_share,median_gap_between_user_turns_s,gap_under_5s_share,peak_month,peak_month_share,last_month}}

Requests by category for each account (`user_by_category.csv`); bots for each account (`user_by_bot.csv`). Bot purposes below come from **local keyword tags on instructions, not from reading them**, and they over-fire: treat them as weak leads, and names are not in the export.

**User A: support-style flows on workflow bots.** {{top.A.unknown_request_share:pct}} of requests go to workflow bots (`default` label), the three largest of which carry {{top.A.top3_bot_request_share:pct}} of requests; {{top.A.both_request_share:pct}} go to instruction-plus-RAG bots, mainly `gemini-2.5-flash`. Largest labelled category: account and service support ({{top.A.top_category_share:pct}}), with finance terms common in requests. {{top.A.after_input_widget_share:pct}} of turns follow an input widget and {{top.A.exact_repeat_share:pct}} of texts repeat exactly, which fits button-driven flows. Owns {{top.A.bots_owned:int}} bots, uses {{top.A.bots_used:int}}.

**User B: one dominant instruction-only bot.** {{top.B.top_bot_request_share:pct}} of requests go to one `gemini-2.5-flash-lite` bot, with weak language-learning and role tags. After `unknown`, factual questions lead. {{top.B.peak_month_share:pct}} of its requests fall in one month, and volume has almost ended by the last month in the export (`top5_profiles.json`). A second bot has about one request per session, which looks like one-shot use.

**User C: many longer role-style bots.** Uses {{top.C.bots_used:int}} bots with no dominant one (top bot {{top.C.top_bot_request_share:pct}}), {{top.C.requests_per_session:f1}} requests per session, and few first turns ({{top.C.first_turn_share:pct}}). Instructions on the largest bots run to thousands of characters with role tags; `gpt-4o-mini` and `deepseek-v4-flash` appear among them. Conversational turns are notable. Companion use is plausible but unverified.

**User D: one short-instruction bot, ended.** {{top.D.top_bot_request_share:pct}} of requests on one `gpt-4o-mini` bot with a very short instruction. Long tail of context (p90 {{top.D.p90_context_chars:int}} characters). Factual and conversational are the leading labelled categories. Its last active month is in the table above.

**User E: one RAG support bot.** All requests go to one `gpt-4o-mini` bot with instruction and RAG; tags point to support and finance. Coding-labelled turns are the highest of the five ({{top.E.coding_share:pct}}), but this is doubtful: the Persian word for "code" also covers things like verification codes, so the rule likely over-fires for support traffic.

**Concentration.** No account shares a dominant instruction with another owner beyond the small cases in `user_by_bot.csv`. Hourly activity is flat across accounts (peak hour about {{top.A.peak_hour_share:pct}}). That is compatible with many end users or with automation, and it proves neither.

**Top five vs the rest:**

| View | Requests | Accounts | Bots | Median context chars | Requests with retrieved chunks | Requests on 10 largest bots |
|---|---|---|---|---|---|---|
| Full corpus | {{cohort.full_corpus.requests:int}} | {{cohort.full_corpus.accounts:int}} | {{cohort.full_corpus.bots:int}} | {{cohort.full_corpus.median_context:int}} | {{cohort.full_corpus.rag_observed:pct}} | {{cohort.full_corpus.top10_bot_share:pct}} |
| Top five | {{cohort.top_five.requests:int}} | {{cohort.top_five.accounts:int}} | {{cohort.top_five.bots:int}} | {{cohort.top_five.median_context:int}} | {{cohort.top_five.rag_observed:pct}} | {{cohort.top_five.top10_bot_share:pct}} |
| Remaining | {{cohort.remaining.requests:int}} | {{cohort.remaining.accounts:int}} | {{cohort.remaining.bots:int}} | {{cohort.remaining.median_context:int}} | {{cohort.remaining.rag_observed:pct}} | {{cohort.remaining.top10_bot_share:pct}} |

Full distributions by category, language, class, context and history are in `cohort_comparison.csv`. **Overall findings mainly describe these five accounts.** The rest differ in useful ways (more mixed-language turns, more coding, more first turns, longer median context), so a set drawn by traffic alone would hide them.

## 7. Prompt categories

Labels are **heuristic**, from local rules in `analysis/prompt_labels.py`, on the first 4,000 characters of each turn. No API or LLM was used. Precedence for mixed intent: coding, media, translation, summarisation, reasoning/math, writing, account support, advice, factual, conversational; other matches become secondary tags. Coding, intent to code and debugging are one category, with optional subtags. Account support is added because the data calls for it. Media generation is kept separate because it needs different evaluation.

{{table:category_prevalence:category,requests,share_requests,sessions,accounts,bots,share_top_five,fa_share,median_chars,first_turn_share}}

**The `unknown` problem.** {{cat.unknown_uncertain:pct}} of requests match no rule. They are mostly short later turns ({{cat.unknown.later_turn:pct}} later, {{cat.unknown.at_most_15_chars:pct}} at most 15 characters, {{cat.unknown.after_input_widget:pct}} after a widget), such as replies that only make sense with context. These shares overlap. Labelling them needs the conversation, which is a reason for review and not a claim about intent. Their real category mix is unmeasured, so shares of other categories are floors.

Illustrations ([SYNTHETIC], not from the data): coding "[SYNTHETIC] fix this Python error"; account support "[SYNTHETIC] my withdrawal has not arrived"; unknown "[SYNTHETIC] the second one".

**Secondary tags** (`secondary_tag_prevalence.csv`): language; session class; first turn, likely history-dependent, or later turn without signal; context short, medium or long (at most {{ctx.p50_chars:int}} characters, then at most {{ctx.p90_chars:int}}, then above; these are corpus p50 and p90 of logged context); reasoning demand (a proxy needing an explicit signal, not difficulty); format constraint; attachment; tool call; template hint; after widget; bot size via quota caps. RAG answerability cannot be measured without review.

**Human review.** `category_review_idonly.csv` holds up to 30 turns per category. Text is in git-ignored `runs/full_eda/sessions/category_review_with_text_LOCAL_ONLY.csv`. Two Persian-capable reviewers label blind; compare with the rules, report confusion per category and agreement, then revise the rules and quotas before freezing.

## 8. Allocation of exactly 300

Policy: a floor of 12 per category, then the rest by the square root of traffic, so rare but important tasks get coverage without ignoring volume. `unknown` is fixed at 12 as a label audit, far below its traffic share, because it has no defined evaluation target.

{{table:golden_category_quotas}}

Cohorts: 60 samples reserved for all {{cohort.remaining.accounts:int}} other accounts; the rest split among the five by floor plus square root of traffic. The tradeoff is deliberate: matching traffic would give the remaining accounts about ten samples and make the set a test of two bots. Cover each workflow, then weight back to traffic when reporting.

{{table:golden_cohort_quotas}}

Both margins are exact in one table, so no extra sample set exists:

{{table:golden_joint_allocation}}

**Procedure** (`scripts/full_eda_sessions.py`, seed 20261101):

1. Pool: one turn per distinct (bot, normalised text), {{gold.pool_turns:int}} turns. Repeats stay in population analysis and are only prevented from filling the set.
2. Raking gives the category × cohort table, with no sample in empty cells.
3. Within a cell, round robin across language × class × history strata, ordered by a seeded hash. This gives joint coverage without a full cross-product.
4. At most one turn per session and at most 25 per bot. The cap is waived for {{gold.cohorts_cap_waived:int}} cohorts with at most two bots, since their quota could not otherwise be met.
5. If a cell runs short, take from the same cohort first, then any cohort, and log it. This run: {{gold.shortfall_cells:int}} cells; {{gold.cells_off_quota:int}} cells differ from quota.

**Proposed candidates (not an approved golden set):** {{gold.candidates:int}} turns, {{gold.candidate_sessions:int}} sessions, {{gold.candidate_bots:int}} bots, largest bot {{gold.candidate_max_bot:int}}, {{gold.candidate_later_turn:pct}} after the first turn, {{gold.candidate_fa:pct}} labelled Persian. IDs in `golden_candidates_proposed_idonly.csv`; the manifest with text is in git-ignored `runs/`. The leakage check against full session order found {{gold.manifest_leak_errors:int}} errors.

**Reporting.** Keep traffic-weighted scores (weights from the population) apart from balanced per-category and per-cohort scores. Keep this set out of router training, threshold tuning, cache warm-up and prompt development.

**Manifest schema** (`golden_manifest_schema.json`; code in `evaluation/golden/manifest.py`): source references and revision; ordered `input_messages` ending at the target; `system_instruction`; RAG state plus the message whose `rag` field alone may be read; primary category; secondary tags; pseudonymous cohort; selection metadata; empty reference and review fields. The target answer and later turns cannot enter: the builder cuts at the target and the validator re-checks.

## 9. Later reference stage (not run)

Give the reference model the same information and instructions as the evaluated system, and never the historical target answer. Record model, version and settings. Reviewers check factual correctness, Persian quality, instruction compliance, RAG grounding and uncertainty handling. A strong model's answer is a candidate reference until validated. Do not use exact string similarity for open-ended answers: use rubrics, and executable checks for coding where possible. Cases needing live tools or missing attachments are tagged and either supplied with recorded tool output or excluded with a stated reason. Workflow bots need Metis to supply the real configuration, or those samples can test only the model step.

## 10. What this suggests (nothing here measures quality or savings)

- **Caching:** identical instruction and RAG across bots is rare, so sharing a cache across bots has little configuration support. Most repetition is inside one bot. Widget-driven turns may be strong candidates, pending validity review.
- **Context reduction:** results will be driven by a few bots, so report per account. The long-context tail differs a lot by account.
- **Routing:** the model is a bot setting, and `workflow` traffic hides its model, so routing evaluation can only cover part of traffic until Metis explains workflows. G08 is a possible small same-instruction comparison.
- **All levers:** per-account reporting is required, because a corpus average mostly reflects User A and User B.

## 11. Limitations

- `workflow` configuration is not exported, so {{cls.group.e_unknown_or_ambiguous:pct}} of sessions stay unclassified, and "direct" cannot be confirmed as a product mode.
- No sender ID exists, so all user analysis is by owner account.
- Category and tag labels are unvalidated rules, with a large unknown share; bot purposes are keyword tags, and no instruction was read during this analysis. Real redacted examples exist only in the local review sheet.
- Context sizes are logged characters, not what was sent to the provider.
- Timestamps are naive. One bot snapshot means instructions may postdate a request.
- Conclusions describe this export only.
