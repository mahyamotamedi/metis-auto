## Pipeline C, UI Stage 3: application shell and both journeys (2026-11-03)

Branch `ui-stage3-journeys` (main at ee8c353, #44). Spec `docs/design/metis-auto-ui-spec.md` Stage 3; owner decisions of 2026-11-03.

**Done**
- New `wiring/demo_workspace.py` (router, one `ChatSession` per journey and bot, switches read from the real session, conversations in memory, banner, model selector, view models) and `wiring/savings_panel.py` (existing `cost_view` / `waterfall_rows` plus session chart rows, est. labels, last-message facts); new page file `scripts/demo_pages/workspace.py` (entry S01, settings S04, workspaces S05 and S06, savings panel beside the chat); `scripts/demo_ui.py` keeps the shell (header, theme, language) and the brand link back to the entry screen.
- Stage 2b fixes: the Results interval card kept its Persian note inside the LTR isolate (now a caption outside it); every number interpolated into a Results string is isolated; unranked version bars use the muted gray token in both themes.
- Strings (`[entry]`, `[settings]`, `[workspace]`, fa and en, Persian marked as placeholder), CSS (entry glows and hero, settings cards, banner, toggles in both directions, panel expander), tests, `module_reference.md` rows, `docs/adr/draft-demo-workspace-shell.md`.

**Not done on purpose**
- No screenshots were taken or looked at in this stage (owner instruction); the app was started once and served `/` and the health check without errors.
- Real bot list and instructions (Stage 4), saving history to files and "create chatbot" (Stage 5).

**Open**: Persian review of all new strings; visual check against images 1 and 3 to 6; the old sidebar's instruction and document editors are not in the workspace (Stage 5).
