# ADR-0058: The address bar carries the demo's step, so the browser's Back and Forward move between steps

- Status: **provisional**, the agent's reading of the owner's requirement of 2026-11-03 (UI Stage 5) and spec `docs/design/metis-auto-ui-spec.md` §1.1, UI-SB03, UI-R05, until the owner reviews it.
- Date: 2026-11-03
- Relates to: [ADR-0024](0024-demo-ui-streamlit.md) (Streamlit only in page files), [ADR-0052](0052-demo-ui-design-system.md) (header, URL theme and language), [ADR-0054](0054-demo-workspace-shell.md) (router in wiring), ADR-0057.
- Code: `src/metis_auto/wiring/demo_workspace.py` (`url_params`, `sync_url`), `src/metis_auto/wiring/demo_nav.py`, `scripts/demo_ui.py` (`_sync_url`); tests `tests/unit/wiring/test_demo_navigation.py`, `tests/integration/test_demo_ui_navigation.py`, `tests/integration/test_demo_ui_browser.py` (needs Python Playwright, skipped without it).

## Context
The router lived only in session state, so the URL never changed: the browser's Back did nothing useful. Streamlit 1.65.0 offers `st.navigation` / `st.Page` (a page per `url_path`), `st.switch_page`, `st.page_link` and `st.query_params`. Which of them add a browser history entry was not assumed but read from the installed frontend (`.venv/.../streamlit/static/static/js/index.*.js`) and tried in Chrome.

## Finding (Streamlit 1.65.0, checked 2026-11-03: re-verify after an upgrade)
- A script run that changes the **query string** (`st.query_params` assignment or `from_dict`) reaches the frontend as a page-info message. The handler calls `history.pushState` when the query string differs from the address bar, and `history.replaceState` instead when the run answers a history navigation (Back or Forward, `historyNavigationEpoch` set). So a state change that rewrites the URL at the end of a run adds one entry, and the rerun caused by Back does not add another.
- Switching page (`st.navigation`, `st.page_link`, `st.switch_page`) also pushes the new page's URL (`pushState` with the page path and the current query string).
- Back and Forward fire `popstate`; the frontend reruns the script with the URL's query string and `isHistoryNavigation`. The script therefore sees the old URL and can follow it.
- In Chrome with the app running, the sequence Start, Chatbot, Settings, Chat, then Back three times and Forward twice showed, in order: settings, bots, entry, then entry, bots; a refresh on a chat URL fell back to settings. One extra entry exists at the start (the bare address, then the same address with the step).

## Decision
1. **One Chat page, the URL carries the step.** Separate `st.Page`s per step were rejected (below). The query string carries `screen` (`entry`, `bots`, `create`, `settings`, `chat`), `journey` (`chatbot`, `direct`) and, from settings on, `bot` (the bot's key), next to `theme` and `lang`. Identifiers only: never message text, instructions or passages (UI-R05; tested).
2. **Who is the truth.** `DemoWorkspace.sync_url(params)` remembers the parameters it wrote last (`url_written`). If the address bar shows them (or no router parameters), the state is the truth: a click moved it, and the page writes the new URL (one write per run, only when it differs, so one history entry). If the bar shows something else, the user navigated (Back, Forward, a typed or refreshed address, the brand link `?screen=entry`) and the state follows the bar.
3. **Stale or invalid URLs fall back, never raise.** Unknown screen or journey: the entry. Direct chat: opens. Chatbot journey: selection and create always; settings need a bot this session knows and can read (the existing live and approval checks apply, UI-R05, UI-R06); chat needs the chat to exist in this session (the settings step has been passed), else settings. An unknown bot: selection. Values are bounded to 64 characters.
4. **Going back loses nothing (UI-SB03).** Following the URL only moves the router; the chats, their settings, the theme, the language and the create draft stay in the workspace. The Chat tab link carries the workspace's current step, so a round trip through Results returns to it.
5. **One writer.** `_ui_state` no longer writes theme and language; `_sync_url` writes all parameters in one `from_dict`, so a first load or a click is one push, not two.
6. **Visible back-tracking** is a view model in `wiring.demo_nav` (step indicator Start > Chatbot > Settings > Chat, finished steps are tertiary buttons; "change chatbot" and "change settings" in the chat; "back to start" in the direct chat), drawn by the page; arrows are CSS and mirror in RTL.

## Alternatives considered
- **A `st.Page` per step with its own `url_path`:** native pushState, but each page is a separate script run context for a single in-memory workspace, the header and sidebar would be re-declared per page, and a step that is invalid for the session (a chat after a refresh) would need the same fallback logic anyway. Rejected as more code for the same result.
- **Only `st.query_params` with state in the URL as the truth (no `url_written`):** a click would need to write the URL before the render and the callbacks would have to read the bar; a stale URL after a callback would undo the click. Rejected.
- **JavaScript `history` calls:** no component or script injection (UI-R01, no new dependency).

## Consequences
- Changing the language or the theme also rewrites the URL (a push), so Back after a toggle may show one step that looks like nothing happened, because the session's choice wins over the old URL. Streamlit gives no way to replace instead of push outside a history navigation.
- The first load adds one entry (bare address, then the address with the step). Back there stays on the entry screen.
- A refresh keeps the screen where it can: direct chat, selection, create, settings (re-read), but a chatbot chat falls back to its settings, because the in-memory session is gone. Conversation history comes back from files (ADR-0057).
- If a later Streamlit changes the push/replace rule, the browser test and the finding above are the places to re-check.
