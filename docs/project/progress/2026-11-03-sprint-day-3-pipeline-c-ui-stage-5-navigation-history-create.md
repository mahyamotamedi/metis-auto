## Pipeline C, UI Stage 5: browser Back, back-tracking, saved history, create chatbot (2026-11-03)

Branch `ui-stage5-navigation-history-create` (main at 589c0d0). Spec `docs/design/metis-auto-ui-spec.md` Stage 5 (UI-A10..A12, UI-A31, UI-L05, UI-K02) and the owner's navigation requirement; ADR drafts ADR-0058 and ADR-0057.

**Done**
- **Part 1a, browser history.** Finding from the installed Streamlit 1.65.0 frontend and a real Chrome run: a script run that changes the query string pushes one history entry (replace during a Back/Forward rerun); page switches also push. The URL now carries `screen`, `journey`, `bot` (identifiers only) with `theme`, `lang`. `DemoWorkspace.sync_url` follows the bar when it differs from what it last wrote (Back, Forward, refresh, brand link `?screen=entry`) and falls back to the nearest valid earlier step for stale or invalid URLs, without an error. One writer (`_sync_url`) per run. Chrome check: Start, Chatbot, Settings, Chat, then Back x3 gave settings, bots, entry; Forward gave entry, bots; a refresh on a chat URL gave settings, no exception. Chats, switches, theme, language and the create draft survive.
- **Part 1b, visible back-tracking.** Step indicator Start > Chatbot > Settings > Chat (`wiring.demo_nav`; finished steps are tertiary buttons, the arrow mirrors in RTL); "Change chatbot" and "Change settings" in the chatbot chat; "Back to start" in the direct chat; the brand link has a hover pill, pointer and focus ring; the header Chat tab carries the current step. Strings fa/en.
- **Part 2a, UI-A31, UI-R11.** `wiring/demo_store.py`: one JSON file per conversation under `runs/demo/conversations/`, restored on first open of a (journey, bot) with the model-side history rebuilt; unreadable files are skipped and counted with a note. `runs/` is git-ignored (`git check-ignore` confirmed).
- **Part 2b, UI-A10..A12.** Create screen S03 (name, instructions, passages; upload, corpus and sharing disabled with reasons), saved to `runs/demo/bots/mine-*.json`, listed "yours" in the sidebar, S02 -> S03 -> S04 in the back trail, draft kept across Back.
- **Part 2c, UI-L05, UI-K02.** At 390 px and 768 px (an iframe in Chrome, fa, light) entry, create, settings and direct chat have no horizontal overflow. Keyboard focus ring checked on the brand link, step buttons, the CTA and the theme toggle. Contrast: the light theme's `accent_text` was 3.7:1 on the page, so `config/demo/theme.toml` now uses `#2F4FD8` (was sampled `#4E80EE`); a test requires 4.5:1 for every text and surface pair in both themes.
- Tests: router transitions, URL mapping, stale URLs, store, create, restart (`tests/unit/wiring/test_demo_navigation.py`); AppTest flows (`tests/integration/test_demo_ui_navigation.py`); a Playwright Back test (`test_demo_ui_browser.py`). An autouse fixture in `tests/conftest.py` keeps every test out of the real `runs/demo/`.

**Not done / partly done**
- **Option B search (2d): not started**, by the brief's order (only if all else was done and green).
- **The Playwright test has not run here:** Python Playwright is not installed in `.venv` or any system Python, so it skips with that reason. The same walk was checked by hand in Chrome (above).
- Restored answers have no cost badge and the savings panel starts empty after a restart (reports are not saved; ADR-0057).
- Changing language or theme pushes a history entry, so Back may show one step with no visible change; the first load adds one entry (ADR-0058).
- No screenshots (owner instruction).

**Open**
- Persian strings are placeholders until reviewed.
- Re-verify the push/replace finding after any Streamlit upgrade.
