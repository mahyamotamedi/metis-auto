# Questions and data requests for Metis

Prioritised by the decision each one blocks. P0 blocks a design decision now; P1 blocks a validated saving; P2 improves confidence. IDs refer to the register ([`assumptions_and_questions.md`](../project/assumptions_and_questions.md)) where one exists.

| # | Priority | Question or request | Decision it blocks |
|---|---|---|---|
| 1 | P0 | Was `provider_model` on a bot chosen by the bot owner, by an end user, or assigned by Metis? Is it a per-message log or the bot's current setting? Which model served each message? | whether automatic routing replaces a bot setting or is a new feature; the meaning of every as-logged baseline |
| 2 | P0 | What exactly is charged per call (the 0.002 unit items tied to RAG queries)? Retrieval, reranking, embedding, something else? Which currency are `totalCost` and `totalIncome` in, and why does the recorded unit rate differ from the public price page? | where the cost levers are (fees are the largest single block); repricing |
| 3 | P0 | What reaches the provider on each call: instructions (as stored or a later snapshot), history window or summary policy, memory, RAG chunks (top-k, reranking, truncation), tool definitions, attachments' extracted text? Is there a logged copy of the final payload for a sample? | context-reduction design; reconstruction status (currently hypothetical) |
| 4 | P0 | Does `inputTokens` include or exclude `cachedInputTokens` for each provider and key? Are Gemini implicit-cache hits recorded? | cached-share and prefix-cache savings; repricing |
| 5 | P0 | Is a licence exception possible for publishing aggregate results beyond Rahnama College, and may derived feature tables be shared with the team? The licence limits use to education and forbids redistribution. | what can be committed and shared |
| 6 | P1 | A call or request ID linking each AI message to its billing item and USER message, plus start and completion times and time-to-first-token. | exact pairing, latency, cache replay timing |
| 7 | P1 | Is there a traffic-source or channel field (embedded bot, direct user, API key type) (Q-22)? Do bots with a single owner serve many end users, and are end users identifiable by a privacy-safe ID? | cache sharing scope (ADR-0007, ADR-0016); curated-cache experiment |
| 8 | P1 | Timezone and clock semantics for `created_at` and `timestamp`, and why sessions are created in 2024 while messages start in 2026-03 (Q-06). | TTL and temporal-holdout design |
| 9 | P1 | Failures, retries, fallbacks and moderation outcomes: are any logged? What availability target did the brief's truncated failover sentence mean (Q-04)? | failover design and SLA |
| 10 | P1 | Quality signals: user ratings, regenerations, thumbs, edits, conversation abandonment; any human-reviewed subset. | quality benchmark size; escalation signals |
| 11 | P1 | Which `workflow`/`default` bots are non-LLM workflows, and are their steps billed elsewhere? | scope of the router (about three in ten requests) |
| 12 | P2 | Meaning of the `input` widget objects and whether widget values are sent to the provider (Q-09). | structured-input routing features |
| 13 | P2 | Were bot instructions and models edited over time? A history of bot configuration (version table). | cache invalidation; instruction-version keys |
| 14 | P2 | Why do bots without RAG configuration log retrieved chunks on a small share of requests? | RAG-presence as a cache-key component |
| 15 | P2 | Persian-capable reviewers for the review sets in `reports/full_eda/review/` (language labels, history dependence, cache-pair validity, answer quality). | label validation; semantic-cache precision |

**Added 2026-11-01** (from [`session_config_report.md`](session_config_report.md)):

| # | Priority | Question or request | Decision it blocks |
|---|---|---|---|
| 16 | P0 | `session.user_id` equals the bot's owner on every session. Is there a sender ID? Who is actually chatting? Are the five largest accounts organisations, service accounts, or something else? | any per-person analysis; cross-user caching |
| 17 | P0 | What does a `workflow` bot do, and can its instructions, model and retrieval configuration be exported? Every session has a `bot_id`: how does a direct LLM conversation appear in this data, if at all? | classifying over a quarter of sessions; routing scope |
| 18 | P1 | Can the chatbot name and an instruction and model history be exported? | bot purpose; configuration change analysis |

**Security note for the owner:** the execution prompt contained a literal Hugging Face access token. It should be rotated and kept out of shared files.
