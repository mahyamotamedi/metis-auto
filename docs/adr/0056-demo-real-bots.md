# ADR-0056: The demo lists the dataset's bots as content-free cards and sends a real bot's content only to the model

- Status: **provisional**, the agent's reading of the approved UI spec (`docs/design/metis-auto-ui-spec.md` §4.1, §4.4, Stage 4) and the owner's decisions of 2026-11-03 (Pipeline C, Day 3), until the owner reviews it.
- Date: 2026-11-03
- Relates to: [ADR-0018](0018-live-calls-for-development-under-a-lifetime-budget.md) (live calls), [ADR-0027](0027-local-postgresql-foundation.md) (local database), [ADR-0030](0030-golden-answers-gpt-5-5.md) (A-84 layout, real-data approval), [ADR-0054](0054-demo-workspace-shell.md) (shell), spec UI-R05, UI-R06, UI-A01..A06, UI-A33.
- Code: `src/metis_auto/wiring/demo_bots.py`, `src/metis_auto/wiring/demo_workspace.py`, `src/metis_auto/domain/context/pass_through.py` (`DatasetPositionsStrategy`), `src/metis_auto/data_access/postgres/repository.py` (`bot_directory_rows`, `bot_instructions`, `latest_rag_texts`), `scripts/demo_pages/workspace.py`; tests `tests/unit/wiring/test_demo_bots.py`, `tests/integration/test_demo_ui_bots.py`, `tests/integration/test_demo_bots_postgres.py` (opt-in).

## Context
The spec asks for the dataset's bots as a list of labels with derived facts, and for a chat that uses a real bot's instructions and retrieved passages behind the scenes. The licence forbids redistribution, so the page may never show them. The spec does not fix how a bot is ranked, which bots count, where the passages for a typed question come from in code, in which order the request is laid out, or what a real bot's live use requires beyond ADR-0018.

## Decision
1. **Cards, not records.** `BotCard` holds a label (`bot-001`, ranked by traffic: USER turns, then sessions, then the private id as the last tie-break, so the labels are stable) and derived facts (language label of the instructions from the existing heuristic, RAG yes/no and top-k, memory, summariser, configured model, instruction length in characters, sessions). It has no id and no text field (tested); `BotDirectory` and `BotProfile` print neither.
2. **Which bots.** Bots used in at least one session, that are LLM bots, and have instructions or a corpus (`corpus_ids_state = 'ok'`). Provider `workflow` is not an LLM bot (the full EDA: no token billing) and is counted in a note, not listed. The set of non-LLM providers is one constant, checked against the export on 2026-11-03.
3. **Content is read late, once.** A real bot's instructions and passages are read when the user continues to the settings, memoised in its profile, and go only into the model request. The passages are Option A: the chunk set of the bot's most recent logged AI turn that has chunks (`latest_rag_texts`). `chunks_for` returns hashes only, so a sibling function reads the text. Bots without RAG send instructions only, and the page says which (`knowledge: ...`).
4. **A-84 order through a context strategy.** `ChatSession` sent instructions, history, retrieved, message (`pass_through`). A real bot's chat uses `dataset_positions`: instructions, history, message, then the chunks, as the golden answers do (ADR-0030). It is a second promoted strategy in `wiring.pipeline` and a `context_layout` argument of `ChatSession`; the composition record names it. A test compares the request with `evaluation.golden_answers.request.build_request` on the same synthetic fixture.
5. **Live with a real bot needs three things.** `live.enabled`, the key (the usual live check) and `golden_answers.real_data_approved`. It is enforced in the session factory (so the page cannot bypass it) and in bot selection while live; the Live option is disabled with the missing reasons otherwise. The spend ledger and caps are unchanged.
6. **The database is optional.** If it cannot be read the list shows "start the local database" and the SYNTHETIC samples stay; the error text is never shown (a driver message may name a user or a host). Each read opens and disposes its own engine.

## Alternatives considered
- **Reorder in `ChatSession` or the page:** logic in the page (UI-R02) or a second path that could drift from the pipeline. Rejected: the layout is a context strategy, like the other.
- **Option B now (search over the bot's chunk pool):** out of scope by the owner's decision.
- **Rank by sessions:** the EDA reports traffic in requests; sessions are shown, requests rank.
- **Hold one engine for the session:** leaves a pooled connection open after the list is built. Rejected.

## Consequences
- The demo's real-bot answers are only as faithful to the bot as the logged turn's chunks are to the new question (Option A): the passages are fixed for the conversation. This is labelled in the chat.
- `bot_type` (STANDARD or DRAFT) is not used: it does not separate workflow bots. `imagination` bots (12 used) are listed if they have instructions; whether they are LLM bots is unverified (open question).
- Live answers with a real bot send licensed content to a provider; this happens only with the owner's switch.
