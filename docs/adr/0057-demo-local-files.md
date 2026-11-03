# ADR-0057: Conversation history and user-made chatbots are small JSON files under runs/demo/

- Status: **provisional**, the agent's reading of spec UI-A10..A12, UI-A31, UI-R11 and the owner's Stage 5 brief of 2026-11-03, until the owner reviews it.
- Date: 2026-11-03
- Relates to: [ADR-0054](0054-demo-workspace-shell.md) (in-memory conversations), [ADR-0056](0056-demo-real-bots.md) (real bots), ADR-0058, spec UI-R05, UI-R11.
- Code: `src/metis_auto/wiring/demo_store.py`, `src/metis_auto/wiring/demo_workspace.py` (`ChatWorkspace`, `create_bot`, `CreateDraft`), `scripts/demo_pages/workspace.py` (`create`); tests `tests/unit/wiring/test_demo_navigation.py`, `tests/integration/test_demo_ui_navigation.py`, `tests/conftest.py` (the autouse temporary folder).

## Context
Conversations lived in memory and the create-chatbot screen did not exist. The spec wants history that survives a restart, one file per conversation, and made bots saved locally and listed as "yours", all under the git-ignored `runs/demo/` (UI-R11). The files hold the user's own text, so they are never committed, printed or logged.

## Decision
1. **Layout.** `runs/demo/conversations/<journey>__<bot>__<n>.json` (one file per conversation: role, text and, for an answer, the model id; no cost report, no trace) and `runs/demo/bots/mine-<8 hex>.json` (name, instructions, passages). `version: 1` in each file; names are made of safe characters only.
2. **Restore.** A (journey, bot) workspace loads its files when it is first opened and opens the newest conversation; the model-side history is rebuilt from the saved messages, so the next question still carries it. An answer restored from a file has no cost badge (the report is not saved).
3. **Never a crash.** A file that is missing, unreadable, of another version or not what we wrote is skipped and counted; the page shows "n saved files could not be read and were skipped" (no names, no content). Writes are atomic (temporary file, then rename). A folder that cannot be written gives the create screen a one-line error.
4. **Reset removes the file;** nothing is written for an empty conversation.
5. **Create (UI-A10..A12).** Name (at most 60 characters), instructions, one to ten passages (at most 8,000 characters each), at least instructions or a passage. A made bot's key starts with `mine-`, so it never clashes with `bot-007` or a preset. It goes through the same `BotProfile` path as the others, so the model receives its instructions and passages and the page shows only its name. File upload, corpus connection and sharing are shown disabled with a reason (UI-A11). What is typed is kept as a draft in the workspace, so Back and Forward lose nothing.
6. **Testability.** The store folder is `demo_store.default_root()`; tests replace it with a temporary folder (an autouse fixture) and pass their own where a restart is tested, so no test reads or writes the real `runs/demo/`, which does not exist on CI.

## Alternatives considered
- **SQLite or the PostgreSQL database:** a new dependency or a coupling to an optional service for a few small records. Rejected.
- **One file per bot with all its conversations:** a corrupt file would lose all of them. One file per conversation limits the loss (and is what the brief asks).
- **Saving the cost report:** the savings panel would then show restored values the session did not compute. Rejected; the panel's data are the answered messages of this run.

## Consequences
- The savings panel and charts start empty after a restart, although the conversation text is back.
- Restored conversations hold user text under `runs/demo/`; the folder is git-ignored (checked with `git check-ignore`). A user who wants it gone deletes the folder.
- Live mode: a restored conversation of a real bot is only text; the content of the bot itself is still read from the database on use (ADR-0056).
