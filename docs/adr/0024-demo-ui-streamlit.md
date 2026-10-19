# ADR-0024: Demo B UI: a thin Streamlit page over `ChatSession`, in its own extra and lock, local only

- Status: **decided for the demo** (Demo milestone, part B: the UI, 2026-10-19). The layout and presets are **provisional**; nothing here changes the serving path or its defaults.
- Date: 2026-10-19
- Decision owner: the project owner (Demo B request of 2026-10-19; [brief](../project/live_testing_and_demo_brief.md) §6, §8–§10).
- Relates to: ADR-0001 (locked dependencies), ADR-0003 / ADR-0018 (live calls, budget), ADR-0009 (scripts are thin), ADR-0020 (decomposition), ADR-0021, ADR-0023 (the Demo A backend).

## Context

Demo A built the backend ("the brain"): `wiring.chat.ChatSession` and its content-free `TurnReport`, used by the terminal chat. The brief (§10) asks for a browser UI in Streamlit: a chat window, a bot-setup sidebar with SYNTHETIC presets, the demo toggles, and a cost panel per message and session. The UI must add no routing, caching, or accounting logic, must keep the two-key rule for live calls, and must never show, log, or store the key or log message content.

## Decision

1. **One page, `scripts/demo_ui.py`, over `ChatSession`.** The page holds the history (P-8), maps widgets to the session's existing toggles (`set_routing`, `switch_model`, `set_compression`, `set_bot_cache`, `set_seed`, `set_deepseek_thinking`, `new_user`, `reset`, `degrade_next`), and draws each `TurnReport`. Switching fake ↔ live builds a new `ChatSession` (a new run, so a new per-run cap).
2. **A Streamlit-free view model, `wiring/demo_ui.py`.** Presets, the live banner, the cost and budget views, the details rows, friendly failure texts, and the display direction live here and are tested without Streamlit. The numbers come from `TurnReport` (which gained `parts` and `session_parts`, the decompositions as numbers, so the page never parses strings) and from the spend ledger; the only arithmetic is the "% saved" ratio and the waterfall's running level.
3. **Streamlit in an optional extra `ui`, with its own lock `requirements-ui.lock`** (= the dev lock + `ui`), never in the runtime or dev lock. Its shared packages are constrained to the pins of `requirements-compress.lock`, so the UI and compression locks can be installed into one venv. Streamlit 1.65.0 (released 2026-10-02; the newest release at least two weeks old on 2026-10-19). Streamlit and Altair are imported only by the page and its test (`tests/architecture/test_ui_imports.py`).
4. **Local only, no telemetry.** The page starts Streamlit itself (`python scripts/demo_ui.py`) with `browser.gatherUsageStats=false` and `server.address=localhost`; `.streamlit/config.toml` repeats them for a direct `streamlit run`. `.streamlit/secrets.toml` is git-ignored and unused: the key stays in `.env`, read only by the settings loader.
5. **Live calls: the same two keys.** The Live switch supplies the experiment's key; `config/local.toml` must still set `[live] enabled = true`, and `METIS_API_KEY` must be set. If refused, the page stays in fake mode and its banner lists every reason (`live_permission`). Every live call goes through the spend guard, the ledger, and the recording decorator, as in the terminal chat. A refused call (`budget_exhausted`) and a stopped run are explained in plain words.
6. **SYNTHETIC presets as configuration** in `config/demo/presets-synthetic.toml`: a Persian online-shop support bot and an English software FAQ bot, each with long instructions and three documents (1,261–2,451 tokens together, above providers' minimum cacheable prefix). Never copied from the sample; the loader refuses any text without the `[SYNTHETIC]` marker.
7. **Right-to-left display by CSS, not HTML.** Each message sits in a keyed container (`rtl-…` or `ltr-…`, from `text_direction`: Persian letters ≥ Latin letters outside code); a static style sheet sets the direction, keeps code left-to-right, and uses a Persian-capable font stack. Message text is rendered as Markdown with HTML escaped; the only `unsafe_allow_html` call carries the static style sheet.

## Alternatives considered

- **Logic in the page** (formatting the decomposition by parsing strings, computing warnings inline). Untestable without Streamlit and against the "thin wrapper" rule. Rejected.
- **Streamlit in the dev lock.** Every developer and CI would install ~30 more packages for a demo. Rejected, like the `compress` extra.
- **Gradio, or a small HTML front end over the in-process API.** The brief names Streamlit; it renders chat, sidebars, charts, and tests offline (`AppTest`) with little code. Rejected.
- **Wrapping message content in `<div dir="rtl">` with `unsafe_allow_html`.** Simple, but it renders model answers as HTML (script injection) and breaks code blocks. Rejected for the CSS approach.

## Consequences

- One more lock to keep in step (`requirements-ui.lock`); re-lock it with the others at the next deliberate upgrade. Like the compress lock it was resolved on macOS arm64 with hashes for every published wheel.
- The demo page is for one presenter on one computer; it is not a deployment and is not in the Docker images.
- The quickstart (§7) is the teammate guide for the UI, with a 5-minute demo script.
