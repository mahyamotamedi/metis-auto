# ADR-XXXX (demo-workspace-shell): The demo's shell is session-state wiring with one ChatSession per journey and bot

- Status: **provisional**, the agent's reading of the approved UI spec (`docs/design/metis-auto-ui-spec.md` §1, §4.3, §4.4, §5, §7, Stage 3) and the owner's decisions of 2026-11-03 (Pipeline C, Day 3), until the owner reviews it.
- Date: 2026-11-03
- Relates to: [ADR-0024](0024-demo-ui-streamlit.md) (thin page), [ADR-0052](0052-demo-ui-design-system.md) (header, tokens), spec UI-S01, S04..S06, UI-A20..A24, UI-A30..A32, UI-B01..B05, UI-SB01..SB07, UI-L04, UI-L05.
- Code: `src/metis_auto/wiring/demo_workspace.py`, `src/metis_auto/wiring/savings_panel.py`, `scripts/demo_pages/workspace.py`, `scripts/demo_ui.py`; tests `tests/unit/wiring/test_demo_workspace.py`, `tests/integration/test_demo_ui_journeys.py`.

## Context
The spec fixes the screens and the settings behaviour but not where the state lives in Streamlit, how the brand link returns to the entry screen without losing the session, or how the savings panel becomes an expander on small screens.

## Decision
1. **A session-state router in wiring**, not `st.navigation` pages per screen. `DemoWorkspace` (one per browser session) holds the journey, the screen, the selected bot, one `ChatWorkspace` per (journey, bot) with its real `ChatSession` and conversations, and the user-level state (banner dismissal, settings highlight, fake/live). The Chat page draws the screen the router names; Results stays a separate page.
2. **The switches are never stored.** The three optimisation switches are read from the real `ChatSession` on every run (`bot_cache`, `compression != off`, `routing != fixed`), so they cannot disagree with the backend. A change that fails returns its reason and the session keeps its previous setting.
3. **The brand link is a query parameter.** An invisible `st.page_link` over the wordmark navigates client-side to the Chat page with `?screen=entry`; the router consumes it once. A plain `href` would reload the page and lose the session.
4. **Per-bot vs user-level settings.** Settings belong to the bot's session; the direct chat has its own session. The banner dismissal, the settings highlight and fake/live are user-level. Switching fake/live rebuilds every session, as before Stage 3.
5. **Conversations** are kept in memory per session; reopening one puts its turns back into the session's history, so the next request resends them. Files are Stage 5.
6. **The savings panel** reuses `cost_view` and `waterfall_rows` unchanged and adds chart rows only from the session's answered messages. In fake mode the actual cost carries "est." because every figure is an estimate from token counts.
7. **Small screens.** The panel is always an expander (open); a media query hides its header from 641 px up and keeps it below, so the saving titles the collapsible block on a phone.
8. **Fake-mode banner.** The calm "fake mode" banner moves under Advanced next to the mode switch (the header chip already says Fake); Live ON, blocked and stopped stay prominent above the chat.

## Alternatives considered
- **`st.navigation` page per screen:** each screen then needs its own state hand-over and the header tabs cannot say "current workspace". Rejected.
- **Storing the switch values beside the session:** two copies that can drift (UI-SB01). Rejected.
- **A JavaScript click to open the sidebar from the banner link:** needs a component (UI-R01). Rejected: the link highlights the settings block instead.

## Consequences
- The banner's "Open settings" link cannot expand a collapsed sidebar (Streamlit has no API for it); on a phone the user opens the sidebar first.
- The bot instructions and document editors of the old sidebar are gone from the workspace: the bots are the SYNTHETIC presets for now, and editing returns with "create chatbot" (Stage 5).
- Stage 4 swaps `synthetic_bots` for the real bot list; `BotProfile` and the screens stay.
