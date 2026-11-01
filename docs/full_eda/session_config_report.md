# Sessions, chatbot configurations, dominant accounts, and the golden-set proposal

Dataset `poriniki/metis`, revision `30f578f283b903cdbd06cd1b5f7f962f76452ded`, processed 2026-11-01, all 80,179 sessions. Status: **draft for review**. Every number comes from `reports/full_eda/tables/claims_ledger_d.csv` or a CSV in `reports/full_eda/sessions/`. No message, instruction or knowledge text appears here. Reproduce with `python scripts/full_eda_sessions.py`.

## 1. Short answers

- **Chatbot vs direct LLM.** Inferred chatbot sessions: 57,437 (71.6% of all sessions). Inferred direct: 359 (0.4%). That is 160.0 chatbot sessions per direct session, but 22,383 sessions (27.9%) cannot be classified, almost all on `workflow` bots whose real configuration is not exported.
- **The direct group is probably not "people chatting directly with an LLM".** Every session has a `bot_id`. A session with neither instruction nor RAG is a bot left blank. The export has no field that marks a direct conversation.
- **Users vs chatbots.** 1,830 bots belong to 446 accounts (4.1 per account). 675 bots were used, by 133 accounts (5.1 per account). **People chatting with those bots cannot be counted:** `session.user_id` equals the bot's owner in 100% of sessions.
- **Same instruction and same RAG.** Only 1 group of bots has both identical (2 bots, 2 sessions). Counting all configuration kinds, 39 groups hold 312 bots, most of them never used. Among used bots: 11 groups, 33 bots, 6.1% of chatbot sessions.
- **Top five.** The 5 largest `user_id`s produce 96.7% of requests (user turns), or 97.0% on the earlier AI-message basis. **They are owner accounts, not five people.**
- **Categories are weak.** Local rules leave 44.4% of requests `unknown`. Quotas are a proposal until humans review the labels.

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

**Repeated histories.** Successive records do **not** repeat earlier conversations: the table is one row per message, with 0 duplicate IDs. So no records were removed and nothing is double counted. Two real kinds of repetition are kept: identical whole transcripts across sessions, and user turns that repeat earlier text. Both are genuine traffic.

## 3. Classification rules

| Decision | Rule |
|---|---|
| Custom instruction | non-blank `instructions` that is not a platform placeholder |
| Platform placeholder | exact text only on `workflow` bots and on at least 5 owners. No phrase list is assumed. It found 1 text. |
| Blank vs null | whitespace-only is absent; null is unknown |
| RAG positive | non-empty `corpus_ids`, or chunks or a retrieval query on **any** AI turn |
| RAG absent | only `corpus_ids` explicitly empty and nothing observed. A turn without retrieval proves nothing. |
| RAG unknown | `corpus_ids` null or malformed and nothing observed |
| Not counted as instructions | `SYSTEM` messages and instructions typed in user messages |
| Workflow bots | instruction unknown, so group (e) even with RAG observed |

Limits: 1,681 custom-instruction sessions use text shared by 2 or more owners and 11 use text of at most 30 characters. These may be generic, and they stay custom. SYSTEM messages occur in 5,453 sessions, 0 of them in the direct group.

## 4. Session report

Raw session rows 80,179, unique 80,179, classified 57,796, ambiguous 22,383, excluded 0. **Reconciliation:** the five groups sum to 80,179.

| group | sessions | share_all_sessions | share_classified_sessions | user_turns | share_user_turns | all_messages | share_all_messages | bots | accounts |
|---|---|---|---|---|---|---|---|---|---|
| a_direct_llm_inferred | 359 | 0.004 | 0.006 | 1,107 | 0.003 | 1,678 | 0.002 | 29 | 21 |
| b_instruction_only | 42,254 | 0.527 | 0.731 | 203,294 | 0.571 | 399,721 | 0.562 | 345 | 66 |
| c_rag_only | 9 | 0.000 | 0.000 | 24 | 0.000 | 48 | 0.000 | 3 | 3 |
| d_instruction_and_rag | 15,174 | 0.189 | 0.263 | 53,014 | 0.149 | 105,140 | 0.148 | 213 | 38 |
| e_unknown_or_ambiguous | 22,383 | 0.279 |  | 98,526 | 0.277 | 204,053 | 0.287 | 88 | 38 |

`share_user_turns` and `share_all_messages` are the secondary, turn-weighted views. Inside group (e):

| subtype | sessions | user_turns | bots | share_all_sessions |
|---|---|---|---|---|
| blank_no_rag | 359 | 1,107 | 29 | 0.004 |
| custom_no_rag | 42,254 | 203,294 | 345 | 0.527 |
| blank_and_rag | 9 | 24 | 3 | 0.000 |
| custom_and_rag | 15,174 | 53,014 | 213 | 0.189 |
| blank_rag_unknown | 166 | 221 | 16 | 0.002 |
| custom_rag_unknown | 195 | 1,646 | 36 | 0.002 |
| platform_default_no_rag_evidence | 15,632 | 47,024 | 36 | 0.195 |
| platform_default_rag_positive | 6,390 | 49,635 | 13 | 0.080 |

**Sensitivity.** Adding sessions with positive evidence that (e) holds (RAG on workflow bots, and custom instructions with unknown RAG) gives 64,022 sessions (79.8%). Workflow sessions without any evidence (15,632) stay unresolved.

**Changing evidence.** 9,330 sessions show retrieval on only some AI turns; 6,403 show retrieval with no configured corpus, nearly all on workflow bots. 5,527 sessions have no AI message and 5,956 have no USER message.

**Bot IDs against the proxy.** All sessions have a `bot_id`, so the ID cannot separate chatbot from direct. The breakdown by `public`, `bot_type` and workflow is in `group_by_bot_flags.csv`.

**Accounts, not users.** These are not proportions of people:

| account_kind | accounts |
|---|---|
| chatbot_only | 87 |
| unknown_only | 25 |
| direct_only | 11 |
| both | 10 |

## 5. Repeated instructions and RAG

Equality key: exact instruction hash plus configured-corpus hash. No trimming, case folding or Persian-Arabic normalisation. Corpus list order is preserved. Model is excluded. Bots with neither are excluded. `bot_id` is the chatbot identity and a fingerprint is only a configuration.

| scope | kind | unique_configurations | bots | repeated_groups | bots_in_repeated_groups | extra_bots_beyond_one_per_group | cross_owner_groups | same_owner_groups | sessions_in_repeated_groups | share_of_chatbot_sessions |
|---|---|---|---|---|---|---|---|---|---|---|
| all_bots | all | 1,290 | 1,563 | 39 | 312 | 273 | 12 | 27 | 3,533 | 0.062 |
| all_bots | instruction_only | 671 | 706 | 21 | 56 | 35 | 10 | 11 | 3,531 | 0.061 |
| all_bots | rag_only | 9 | 9 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| all_bots | both | 505 | 506 | 1 | 2 | 1 | 0 | 1 | 2 | 0.000 |
| all_bots | instruction_rag_unknown | 105 | 342 | 17 | 254 | 237 | 2 | 15 | 0 | 0 |
| used_bots | all | 570 | 592 | 11 | 33 | 22 | 5 | 6 | 3,509 | 0.061 |
| used_bots | instruction_only | 325 | 346 | 10 | 31 | 21 | 5 | 5 | 3,507 | 0.061 |
| used_bots | rag_only | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| used_bots | both | 208 | 209 | 1 | 2 | 1 | 0 | 1 | 2 | 0.000 |
| used_bots | instruction_rag_unknown | 36 | 36 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Extra entities means bots beyond one per group, not the total in repeated groups. `instruction_rag_unknown` has a null corpus field, so RAG equality cannot be claimed. Group sizes are in `shared_group_sizes_*.csv`. Largest groups:

| config | kind | bots | owners | sessions | user_turns | ins_chars | models |
|---|---|---|---|---|---|---|---|
| G01 | instruction_rag_unknown | 58 | 1 | 0 | 0 | 1,304 | gpt-4.1-nano:58 |
| G02 | instruction_rag_unknown | 31 | 1 | 0 | 0 | 405 | gpt-4.1-nano:31 |
| G03 | instruction_rag_unknown | 30 | 1 | 0 | 0 | 382 | gpt-4.1-nano:30 |
| G04 | instruction_rag_unknown | 21 | 1 | 0 | 0 | 562 | gpt-4.1-nano:21 |
| G05 | instruction_rag_unknown | 21 | 1 | 0 | 0 | 783 | gpt-4.1-mini:21 |
| G06 | instruction_rag_unknown | 16 | 1 | 0 | 0 | 818 | gpt-4.1-nano:16 |
| G07 | instruction_rag_unknown | 15 | 1 | 0 | 0 | 351 | gpt-4.1-nano:15 |
| G08 | instruction_only | 13 | 1 | 1,324 | 5,592 | 1,436 | gpt-5.2:1;claude-4-sonnet:1;gemini-2.5-flash:1;gemini-2.5-flash-lite:1;gpt-5:1;gpt-5.1:1;gpt-4.1-mini:1;gpt-4.1:1;claude-sonnet-4-6:1;claude-4-opus:1;claude-3-7-sonnet:1;claude-3-opus:1;gpt-4.1-nano:1 |
| G09 | instruction_rag_unknown | 12 | 1 | 0 | 0 | 551 | gpt-4.1-nano:12 |
| G10 | instruction_rag_unknown | 12 | 1 | 0 | 0 | 342 | gpt-4.1-nano:12 |
| G11 | instruction_rag_unknown | 10 | 1 | 0 | 0 | 443 | gpt-4.1-nano:10 |
| G12 | instruction_rag_unknown | 10 | 1 | 0 | 0 | 567 | gpt-4.1-nano:10 |
| G13 | instruction_rag_unknown | 5 | 1 | 0 | 0 | 884 | gpt-4.1-nano:5 |
| G14 | instruction_rag_unknown | 5 | 1 | 0 | 0 | 699 | gpt-4.1-nano:5 |
| G15 | instruction_only | 4 | 1 | 136 | 351 | 214 | leonardo:1;gpt-4o-mini:1;gpt-5-mini:1;grok-4-1-fast:1 |
| G16 | instruction_only | 3 | 1 | 0 | 0 | 733 | gpt-5-nano:1;gpt-5.4-nano:1;gemini-2.5-flash-lite:1 |
| G17 | instruction_only | 2 | 2 | 796 | 796 | 1,765 | gemini-2.5-flash:1;gpt-4.1-mini:1 |
| G18 | instruction_only | 2 | 2 | 476 | 2,917 | 348 | gemini-2.5-flash-lite:1;gpt-4o-mini:1 |
| G19 | instruction_only | 2 | 1 | 245 | 604 | 36 | Flux-Schnell:1;Flux-Pro:1 |
| G20 | instruction_only | 2 | 1 | 157 | 2,073 | 4,147 | deepseek-v4-flash:2 |
| G21 | instruction_only | 2 | 2 | 138 | 967 | 383 | metis-gpt:1;gpt-4o-mini:1 |
| G22 | instruction_only | 2 | 2 | 128 | 392 | 506 | gpt-4o-mini:2 |
| G23 | instruction_only | 2 | 2 | 64 | 181 | 290 | gpt-4o-mini:2 |
| G24 | instruction_only | 2 | 1 | 43 | 501 | 3,129 | deepseek-v4-flash:2 |
| G25 | instruction_only | 2 | 2 | 21 | 71 | 432 | gpt-4o-mini:2 |

- **Most large groups were never used.** They are many unused bots of one owner with the same text, and bot sharing there looks like bulk creation; the data does not say why.
- **G08 is a notable case:** one owner, one instruction, many models (see `models`). It looks like a side-by-side model comparison, but that is an inference. It may be useful later for routing work, though it has no quality labels.
- **Optional, separately labelled comparisons.** Exact instruction texts 1,113, after Persian-aware normalisation 1,106. Corpus lists with order 510, ignoring order 509.
- **Same retrieved chunks is a different question.** 63,415 AI turns hold 62,254 distinct chunk sets, which vary per turn and do not prove the same knowledge base. 13 workflow bots retrieve from 13 distinct observed corpus sets, a limited proxy.
- **Configured vs observed corpus:**

| relation | bots |
|---|---|
| configured_empty | 4 |
| configured_null | 14 |
| disjoint | 5 |
| partial_overlap | 52 |
| subset_of_configured | 117 |

- **Configuration change is not observable.** One snapshot per bot; 638 used bots have `updated_at` after `created_at`, with no record of what changed. Partial overlap and disjoint rows above may reflect edits.

## 6. The five dominant accounts

**Verified.** Request = a USER turn; 355,965 in total, 0 without `user_id`, across 132 accounts. Top five: 96.7%. The reported 97% used AI messages (97.0% here), so the two agree closely and the difference is the unit.

**Identity.** The ID is the **bot owner** on every session. Traffic is implausible for one person: User A averages 622 requests per active day over 36,876 sessions. Five human end users cannot be established. These accounts could be organisations or service accounts; the data does not say, and no automation is claimed. Pseudonyms are used; the mapping is in git-ignored `runs/`.

| account | requests | share_requests | cumulative_share | sessions | requests_per_session | bots_owned | bots_used | top_bot_request_share | chatbot_session_share | unknown_session_share | median_context_chars | exact_repeat_share | after_input_widget_share | median_gap_between_user_turns_s | gap_under_5s_share | peak_month | peak_month_share | last_month |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| User A | 139,376 | 0.392 | 0.392 | 36,876 | 3.780 | 448 | 188 | 0.310 | 0.405 | 0.595 | 2618.500 | 0.576 | 0.437 | 19.765 | 0.154 | 2026-09 | 0.257 | 2026-10 |
| User B | 112,124 | 0.315 | 0.707 | 24,662 | 4.546 | 123 | 81 | 0.804 | 0.993 | 0 | 3170.500 | 0.210 | 0 | 61.701 | 0.010 | 2026-04 | 0.560 | 2026-10 |
| User C | 49,224 | 0.138 | 0.845 | 5,569 | 8.839 | 186 | 180 | 0.096 | 0.971 | 0.029 | 8,272 | 0.231 | 0 | 42.881 | 0.038 | 2026-05 | 0.313 | 2026-10 |
| User D | 33,327 | 0.094 | 0.938 | 6,678 | 4.991 | 4 | 2 | 0.989 | 1 | 0 | 9,653 | 0.211 | 0 | 79.532 | 0.003 | 2026-04 | 0.530 | 2026-08 |
| User E | 10,345 | 0.029 | 0.967 | 2,123 | 4.873 | 2 | 1 | 1 | 1 | 0 | 8,866 | 0.229 | 0 | 55.901 | 0.006 | 2026-05 | 0.314 | 2026-10 |

Requests by category for each account (`user_by_category.csv`); bots for each account (`user_by_bot.csv`). Bot purposes below come from **local keyword tags on instructions, not from reading them**, and they over-fire: treat them as weak leads, and names are not in the export.

**User A: support-style flows on workflow bots.** 69.1% of requests go to workflow bots (`default` label), the three largest of which carry 60.5% of requests; 28.9% go to instruction-plus-RAG bots, mainly `gemini-2.5-flash`. Largest labelled category: account and service support (38.8%), with finance terms common in requests. 43.7% of turns follow an input widget and 57.6% of texts repeat exactly, which fits button-driven flows. Owns 448 bots, uses 188.

**User B: one dominant instruction-only bot.** 80.4% of requests go to one `gemini-2.5-flash-lite` bot, with weak language-learning and role tags. After `unknown`, factual questions lead. 56.0% of its requests fall in one month, and volume has almost ended by the last month in the export (`top5_profiles.json`). A second bot has about one request per session, which looks like one-shot use.

**User C: many longer role-style bots.** Uses 180 bots with no dominant one (top bot 9.6%), 8.8 requests per session, and few first turns (6.9%). Instructions on the largest bots run to thousands of characters with role tags; `gpt-4o-mini` and `deepseek-v4-flash` appear among them. Conversational turns are notable. Companion use is plausible but unverified.

**User D: one short-instruction bot, ended.** 98.9% of requests on one `gpt-4o-mini` bot with a very short instruction. Long tail of context (p90 160,955 characters). Factual and conversational are the leading labelled categories. Its last active month is in the table above.

**User E: one RAG support bot.** All requests go to one `gpt-4o-mini` bot with instruction and RAG; tags point to support and finance. Coding-labelled turns are the highest of the five (11.4%), but this is doubtful: the Persian word for "code" also covers things like verification codes, so the rule likely over-fires for support traffic.

**Concentration.** No account shares a dominant instruction with another owner beyond the small cases in `user_by_bot.csv`. Hourly activity is flat across accounts (peak hour about 6.0%). That is compatible with many end users or with automation, and it proves neither.

**Top five vs the rest:**

| View | Requests | Accounts | Bots | Median context chars | Requests with retrieved chunks | Requests on 10 largest bots |
|---|---|---|---|---|---|---|
| Full corpus | 355,965 | 132 | 669 | 4,350 | 17.8% | 68.2% |
| Top five | 344,396 | 5 | 452 | 4,301 | 18.0% | 70.5% |
| Remaining | 11,569 | 127 | 217 | 9,189 | 9.7% | 71.2% |

Full distributions by category, language, class, context and history are in `cohort_comparison.csv`. **Overall findings mainly describe these five accounts.** The rest differ in useful ways (more mixed-language turns, more coding, more first turns, longer median context), so a set drawn by traffic alone would hide them.

## 7. Prompt categories

Labels are **heuristic**, from local rules in `analysis/prompt_labels.py`, on the first 4,000 characters of each turn. No API or LLM was used. Precedence for mixed intent: coding, media, translation, summarisation, reasoning/math, writing, account support, advice, factual, conversational; other matches become secondary tags. Coding, intent to code and debugging are one category, with optional subtags. Account support is added because the data calls for it. Media generation is kept separate because it needs different evaluation.

| category | requests | share_requests | sessions | accounts | bots | share_top_five | fa_share | median_chars | first_turn_share |
|---|---|---|---|---|---|---|---|---|---|
| coding_intent_debugging | 6,034 | 0.017 | 3,729 | 41 | 164 | 0.921 | 0.801 | 67 | 0.348 |
| media_generation | 1,202 | 0.003 | 647 | 10 | 40 | 0.933 | 0.493 | 86 | 0.465 |
| translation_language | 6,983 | 0.020 | 2,811 | 17 | 128 | 0.985 | 0.694 | 38 | 0.211 |
| summarization_extraction | 1,838 | 0.005 | 1,074 | 18 | 88 | 0.905 | 0.849 | 70 | 0.291 |
| reasoning_math | 4,758 | 0.013 | 2,712 | 24 | 164 | 0.963 | 0.842 | 61 | 0.270 |
| writing_editing | 10,354 | 0.029 | 4,160 | 28 | 202 | 0.964 | 0.919 | 74 | 0.198 |
| account_service_support | 57,945 | 0.163 | 24,406 | 26 | 257 | 0.992 | 0.967 | 26 | 0.197 |
| advice_planning | 5,776 | 0.016 | 3,712 | 31 | 241 | 0.968 | 0.956 | 64 | 0.211 |
| factual_question | 69,063 | 0.194 | 26,080 | 64 | 484 | 0.961 | 0.911 | 42 | 0.199 |
| conversational_support | 34,014 | 0.096 | 20,583 | 54 | 451 | 0.950 | 0.479 | 11 | 0.431 |
| unknown_uncertain | 157,998 | 0.444 | 47,584 | 95 | 538 | 0.968 | 0.671 | 19 | 0.159 |

**The `unknown` problem.** 44.4% of requests match no rule. They are mostly short later turns (84.1% later, 43.6% at most 15 characters, 16.5% after a widget), such as replies that only make sense with context. These shares overlap. Labelling them needs the conversation, which is a reason for review and not a claim about intent. Their real category mix is unmeasured, so shares of other categories are floors.

Illustrations ([SYNTHETIC], not from the data): coding "[SYNTHETIC] fix this Python error"; account support "[SYNTHETIC] my withdrawal has not arrived"; unknown "[SYNTHETIC] the second one".

**Secondary tags** (`secondary_tag_prevalence.csv`): language; session class; first turn, likely history-dependent, or later turn without signal; context short, medium or long (at most 4,350 characters, then at most 44,855, then above; these are corpus p50 and p90 of logged context); reasoning demand (a proxy needing an explicit signal, not difficulty); format constraint; attachment; tool call; template hint; after widget; bot size via quota caps. RAG answerability cannot be measured without review.

**Human review.** `category_review_idonly.csv` holds up to 30 turns per category. Text is in git-ignored `runs/full_eda/sessions/category_review_with_text_LOCAL_ONLY.csv`. Two Persian-capable reviewers label blind; compare with the rules, report confusion per category and agreement, then revise the rules and quotas before freezing.

## 8. Allocation of exactly 300

Policy: a floor of 12 per category, then the rest by the square root of traffic, so rare but important tasks get coverage without ignoring volume. `unknown` is fixed at 12 as a label audit, far below its traffic share, because it has no defined evaluation target.

| category | quota | traffic_share | proportional_quota |
|---|---|---|---|
| factual_question | 50 | 0.194 | 58.205 |
| account_service_support | 46 | 0.163 | 48.835 |
| conversational_support | 38 | 0.096 | 28.666 |
| writing_editing | 27 | 0.029 | 8.726 |
| translation_language | 24 | 0.020 | 5.885 |
| coding_intent_debugging | 23 | 0.017 | 5.085 |
| advice_planning | 23 | 0.016 | 4.868 |
| reasoning_math | 22 | 0.013 | 4.010 |
| summarization_extraction | 18 | 0.005 | 1.549 |
| media_generation | 17 | 0.003 | 1.013 |
| unknown_uncertain | 12 | 0.444 | 133.157 |

Cohorts: 60 samples reserved for all 127 other accounts; the rest split among the five by floor plus square root of traffic. The tradeoff is deliberate: matching traffic would give the remaining accounts about ten samples and make the set a test of two bots. Cover each workflow, then weight back to traffic when reporting.

| cohort | quota | traffic_share | proportional_quota |
|---|---|---|---|
| Remaining accounts | 60 | 0.033 | 9.750 |
| User A | 63 | 0.392 | 117.463 |
| User B | 59 | 0.315 | 94.496 |
| User C | 45 | 0.138 | 41.485 |
| User D | 41 | 0.094 | 28.087 |
| User E | 32 | 0.029 | 8.719 |

Both margins are exact in one table, so no extra sample set exists:

| category | Remaining accounts | User A | User B | User C | User D | User E | total |
|---|---|---|---|---|---|---|---|
| factual_question | 9 | 9 | 8 | 10 | 7 | 7 | 50 |
| account_service_support | 3 | 32 | 1 | 1 | 0 | 9 | 46 |
| conversational_support | 9 | 7 | 3 | 16 | 2 | 1 | 38 |
| writing_editing | 5 | 1 | 8 | 3 | 10 | 0 | 27 |
| translation_language | 3 | 0 | 11 | 2 | 8 | 0 | 24 |
| coding_intent_debugging | 5 | 6 | 1 | 0 | 1 | 10 | 23 |
| advice_planning | 3 | 3 | 4 | 6 | 4 | 3 | 23 |
| reasoning_math | 5 | 3 | 7 | 2 | 4 | 1 | 22 |
| summarization_extraction | 9 | 0 | 5 | 1 | 3 | 0 | 18 |
| media_generation | 7 | 0 | 9 | 0 | 1 | 0 | 17 |
| unknown_uncertain | 2 | 2 | 2 | 4 | 1 | 1 | 12 |
| total | 60 | 63 | 59 | 45 | 41 | 32 | 300 |

**Procedure** (`scripts/full_eda_sessions.py`, seed 20261101):

1. Pool: one turn per distinct (bot, normalised text), 247,111 turns. Repeats stay in population analysis and are only prevented from filling the set.
2. Raking gives the category × cohort table, with no sample in empty cells.
3. Within a cell, round robin across language × class × history strata, ordered by a seeded hash. This gives joint coverage without a full cross-product.
4. At most one turn per session and at most 25 per bot. The cap is waived for 2 cohorts with at most two bots, since their quota could not otherwise be met.
5. If a cell runs short, take from the same cohort first, then any cohort, and log it. This run: 0 cells; 0 cells differ from quota.

**Proposed candidates (not an approved golden set):** 300 turns, 300 sessions, 113 bots, largest bot 40, 66.7% after the first turn, 55.7% labelled Persian. IDs in `golden_candidates_proposed_idonly.csv`; the manifest with text is in git-ignored `runs/`. The leakage check against full session order found 0 errors.

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

- `workflow` configuration is not exported, so 27.9% of sessions stay unclassified, and "direct" cannot be confirmed as a product mode.
- No sender ID exists, so all user analysis is by owner account.
- Category and tag labels are unvalidated rules, with a large unknown share; bot purposes are keyword tags, and no instruction was read during this analysis. Real redacted examples exist only in the local review sheet.
- Context sizes are logged characters, not what was sent to the provider.
- Timestamps are naive. One bot snapshot means instructions may postdate a request.
- Conclusions describe this export only.
