## Pipeline C, UI Stage 4: real bots from the local database (2026-11-03)

Branch `ui-stage4-real-bots` (main at 97cfbc2, #45). Spec `docs/design/metis-auto-ui-spec.md` Stage 4 (UI-A01..A06, UI-A33); owner decisions of 2026-11-03; ADR draft `docs/adr/draft-demo-real-bots.md`.

**Done**
- New `wiring/demo_bots.py`: `BotCard` (label `bot-001`.. ranked by traffic, language label of the instructions, RAG and top-k, memory, summariser, configured model, instruction length, sessions; no id, no text), `BotDirectory` (private ids, prints nothing), `BotProfile` (a real bot's instructions and passages read once, only for the model request), `filter_cards`, `real_data_reasons`, `PostgresBotSource`. A database that cannot be read gives the unavailable state.
- `data_access`: `bot_directory_rows`, `bot_instructions`, `latest_rag_texts` (the chunk text of the bot's most recent logged AI turn with chunks; `chunks_for` returns hashes only, so a sibling reads the text).
- A-84 order: `DatasetPositionsStrategy` (instructions, history, message, then the chunks), registered in `wiring.pipeline`, `ChatSession(context_layout=...)`; a real bot's chat uses it. A test compares the request with `golden_answers.request.build_request` on the same synthetic fixture.
- S02 (chatbot selection) in `DemoWorkspace` and the page: the sidebar lists the SYNTHETIC samples first, then the dataset's bots with search over the label, filters (language, RAG, memory, has instructions), 50 at a time with "more"; "Your chatbots", the details card (derived facts), "Create new chatbot" (disabled: "available in the next stage"), "Continue". Back links S04 → S02 → S01.
- Live with a real bot needs `live.enabled`, the key and `golden_answers.real_data_approved`: enforced in the session factory and at bot selection while live; the Live option is disabled with the missing reasons. Ledger and caps unchanged.
- The chat shows "knowledge: passages from one logged turn" or "instructions only" for a real bot. Strings fa/en (Persian marked as placeholder), module_reference rows.

**Real data check (aggregates only):** on the local database 590 bots are listed, 38 workflow bots are left out; 208 have RAG, 27 memory, 69 a summariser; the top bot has 14,964 sessions. One RAG bot and one plain bot were read and chatted with in fake mode; no live call was made.

**Not done on purpose**
- No screenshots (owner instruction). The app was started once (`/` and the health check 200, no errors in the log).
- Option B (search over the bot's chunk pool), "Create new chatbot" (Stage 5), history files (Stage 5).

**Open**
- `imagination` bots (12 used) are listed if they have instructions; whether they are LLM bots is unverified.
- Option A fixes the passages for the conversation, so a new question may not match them; labelled in the chat.
