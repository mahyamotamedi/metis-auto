# Full dataset: data dictionary

Source: `poriniki/metis`, revision `30f578f283b903cdbd06cd1b5f7f962f76452ded` (relational Parquet; the dataset card calls it the "Rahnama Chat Benchmark"). All names are as exported. Shapes only, no content. Missing is **unknown** (a null) and is kept apart from **empty** (`[]`, `{}`, blank string) and **malformed** (unparsable JSON; none found in the JSON columns). Rates below are shares of rows of the whole table; per-metric rates are in the claims ledger and `reports/full_eda/tables/field_states.csv`.

Join keys: `chat_message.session_id → chat_session.session_id`, `chat_session.user_id → users.user_id`, `chat_session.bot_id → chat_bot.bot_id`. All joins resolve (no orphan sessions or messages).

## `chat_message` (13 Parquet shards)

| Field | Type | Meaning | Availability | Unresolved |
|---|---|---|---|---|
| `message_id` | string `m_<int>` | unique message ID | all; no duplicates | whether the integer encodes creation order |
| `session_id` | string | owning session | all | |
| `type` | `USER`, `AI`, `SYSTEM`, `TOOL` | role (`AI` is the bot) | all | SYSTEM content is short and bot-side; purpose unclear |
| `timestamp` | timestamp, naive | message time | 2 nulls | timezone (Q-06); file order and timestamp order disagree in 2 sessions |
| `content` | string | message text; AI content can itself be JSON | blank on a small share of AI messages | |
| `finish_reason` | string | `STOP`, `LENGTH`, rare `CONTENT_FILTER`, `TOOL_CALL`, `ASYNC_TASK_RUNNING` | AI messages | meaning of values beyond the names |
| `attachments` | JSON list `{contentType, content}` | user attachments | rare; types IMAGE, FILE, AUDIO, VIDEO, TEXT | content not analysed (NG-07) |
| `rag` | JSON list `{query, relevantChunks[{id, content, corpusId, reference, relevancy}]}` | retrieval queries and chunks logged on the AI message | non-empty on a minority of AI messages | whether this is the final supplied context or the raw retrieval; top-k and reranking per message |
| `billing` | JSON list of call items | recorded usage and cost per internal call: `inputTokens`, `outputTokens`, `cachedInputTokens`, `cacheWriteTokens`, audio tokens, `webSearchCalls`, `totalCost`, `totalIncome`, `costBreakdown`, `providerKeyName`, `providerAccount` | AI messages; empty list for `workflow` bots | currency; token provenance; whether `inputTokens` includes cached tokens (it does not for several models) |
| `input` | JSON `{items:[{name,type,label,choices,default,required,placeholder}]}` | form-widget definition attached to the message | a minority of AI messages | whether it reaches the provider |
| `tool_calls`, `citations`, `actions`, `google_search_query` | JSON / string | tool calls, citations, moderation actions, search query | rare | `reason` in actions is always null |

Derived tables under `data/derived/` (billing, rag, rag_chunks, input, actions, tool_calls) explode these JSON columns; the EDA reads the message JSON and the chunk table and uses the billing table only for cost breakdown.

## `chat_session`

`session_id`, `user_id`, `bot_id`, `created_at` (naive), `last_update_date`, `dialogue_length` (equals the observed message count for every session), `headline` (almost always null; not read). `created_at` starts in 2024; messages start in 2026-03.

## `chat_bot` (1,830 rows; 675 used in sessions)

Configuration snapshot, not a history. Key fields: `instructions` (text on most bots; blank or null on a minority), `provider_name`, `provider_model` (the **model label**; `workflow`/`default` marks non-LLM workflow bots), `provider_args` (JSON), `corpus_ids`, `rag_top_k`, `rag_reranking`, `rag_source_urls_enabled`, `memory_enabled`, `summarizer_mode` (`IGNORE` or `AI_SUMMARIZE`) with summarizer provider fields, `functions`, `google_search_enabled`, `public`, `enabled`, `bot_type`, `created_at`, `updated_at`, `deleted_at`, `user_id` (owner).

Unresolved: whether `instructions` and `provider_model` were the values in force when each message was produced (a single snapshot; most used bots show `updated_at` after `created_at`); whether a user or Metis assigned the model.

## `users` (448 rows)

`user_id`, `activated`, `owner_user_id`, `username_anon` (not read). Only part of the table appears in sessions. Each bot has one owner `user_id`, so cross-user cache sharing cannot be measured.

## Derived tables of this EDA (local, git-ignored, in `data/derived/full_eda/`)

| Table | Rows | Holds |
|---|---|---|
| `messages_*.parquet` | one per message | content-free features, local grouping hashes, JSON column states, billing sums |
| `chunks/*.parquet` | one per RAG chunk row | chunk length, relevancy, text hash |
| `bots.parquet`, `sessions.parquet`, `users.parquet` | per entity | features and keys |
| `requests.parquet` | one per AI message | heuristic pairing, pairing flag, session/bot/billing/history features |

Committed tables in `reports/full_eda/tables/` hold aggregates only: no content, no content hashes, no bot or user IDs.

## Reconstruction status

| Item | Status |
|---|---|
| Current user message | observed |
| Instructions | partially verified: billed input tracks instruction length (turn-0 fits); stored text may postdate the call |
| Retrieved chunks | partially verified: billed input tracks chunk characters; final supplied context unconfirmed |
| History | hypothetical: reduced form, policy unknown |
| Tool definitions, memory, summaries | unknown |
| Attachments (extracted content) | unknown |

Anything not listed as observed is a reconstruction.
