# Metis-Auto demo UI: design and build specification (Streamlit)

Owner: Pipeline C (Mahya). Written 2026-11-03 for sprint task **D-2** and the demo redesign.
Status: **approved by the owner** as the build spec. Every item has an ID (`UI-…`). Every stage report must list each ID it touched as **done / partial / not done / not possible (reason)**.

Source of the design: the owner's frontend design brief (the six Metis screenshots plus the written design), adapted to **Streamlit** (owner decision 2026-11-03: Streamlit, not Next.js) and to the project's rules. Section 9 maps every part of the brief to an ID, so nothing is dropped silently.

---

## 0. Ground rules (apply to every stage)

| ID | Rule | Source |
|---|---|---|
| UI-R01 | **Streamlit only.** No Next.js, React, Node, or new frontend framework. Altair stays the chart library. Streamlit and Altair are imported **only** in `scripts/demo_ui.py` (and any new page files under `scripts/demo_pages/`, if pages are split; then extend `tests/architecture/test_ui_imports.py` to allow exactly those files) | ADR-0024, owner |
| UI-R02 | **No logic in the page.** Every computation, filter, label, ranking, string choice and data load lives in `src/metis_auto/wiring/` (existing `demo_ui.py`, `lever_view.py`, `chat.py`, plus new wiring modules) and is unit-tested. The page only lays out and calls wiring | ADR-0024 |
| UI-R03 | **Preserve working behaviour.** The existing chat path (`wiring.chat.ChatSession`), cost panel (`wiring.demo_ui.cost_view`, `waterfall_rows`), budget view (`budget_view`), live/fake banner (`live_banner`, `blocked_banner`), detail sections, presets, routing/compression/bot-cache toggles and failure messages keep working. Restyle and reorganise them; do not rewrite their calculations | owner brief §4.4 |
| UI-R04 | **No fabricated features or data.** If something is not supported, show it **disabled with a one-line reason**, never a fake success. No invented numbers in charts | owner brief, CLAUDE.md |
| UI-R05 | **Licence.** The dataset is licensed for education only, no redistribution. Real bots appear only as labels (`bot-007`) with derived facts. **Never display** a real bot's instructions, chunk text or logged conversations. Real content may be **sent** to a model only in live mode with `golden_answers.real_data_approved = true` (the owner's existing switch) and within the budget ledger | licence, ADR-0018, ADR-0030 |
| UI-R06 | **Live calls.** Fake mode is the default. Live mode follows ADR-0018: spend ledger, caps, warnings, refusal at the cap; never raise caps from the UI | ADR-0018, ADR-0003 |
| UI-R07 | **Demo components are placeholders.** The toggles drive the existing demo components (ADR-0023: rule-based and sticky routing, demo cache, LLMLingua-2 compression), which are **not evidence**. The offline sprint levers (S-6, R-B1, R-C1, R-C2, R-C3 …) are shown as **results** from `reports/levers/`, never as live toggles. Label both clearly | ADR-0023, ADR-0031 |
| UI-R08 | **Brand.** Use official Metis logo/wordmark assets **only** if present in the repo with the owner's confirmation of permission. Otherwise show the text wordmark "Metis-Auto" with no imitation logo. Label the app "Metis-Auto prototype". **No login, sign-up or payment screens** | owner brief §2.4, safety |
| UI-R09 | **Visual reference.** The six screenshots in `docs/design/metis-screens/` are the primary visual source of truth (see §2). If the folder is missing or incomplete, say so and use the written tokens below; never guess what a screenshot shows | owner brief §2 |
| UI-R10 | **Repo rules.** No commits (the owner commits). ADR drafts as `docs/adr/draft-<slug>.md`, title line `# ADR-XXXX (<slug>): Title`. A NEW progress file per stage. `module_reference.md` rows for new modules. Tests first. `ruff check`, `ruff format --check`, full pytest green. New dependency only with an ADR and a hash-pinned lock (avoid: fonts and icons should be local files or CSS, not packages) | CLAUDE.md |
| UI-R11 | **Privacy of local files.** Conversation history and user-made bots are stored under git-ignored `runs/demo/` only (check with `git check-ignore`). They may contain content; never commit or print them | CLAUDE.md |

---

## 1. Information architecture

### 1.1 Screens and navigation

| ID | Screen | Reached from |
|---|---|---|
| UI-S01 | **Entry: choose your path** (Chatbot / Direct chat) | app start; the header brand link returns here |
| UI-S02 | **Chatbot selection** (Journey A) | entry → "Chatbot" |
| UI-S03 | **Create chatbot** (Journey A) | chatbot selection → "Create new chatbot" |
| UI-S04 | **Optimisation settings** (Journey A) | after selecting or creating a bot |
| UI-S05 | **Chat workspace: chatbot** (Journey A) | settings → "Start chatting" |
| UI-S06 | **Chat workspace: direct chat** (Journey B) | entry → "Direct chat" (no bot steps) |
| UI-S07 | **Results dashboard** (D-2: the sprint lever results, Metis analytics style) | header nav "Results" |

Navigation sequence: **A:** S01 → S02 → (S03 →) S04 → S05. **B:** S01 → S06. Header nav (UI-H03) is available on every screen: **Chat** (returns to the current journey's workspace, or S01 if none), **Results** (S07). Use Streamlit multipage navigation (`st.navigation` / `st.Page`) if the installed version supports it (verify in Streamlit 1.65.0 from `requirements-ui.lock`); otherwise a session-state router in wiring. Back links on S02–S04.

### 1.2 Application shell

| ID | Element |
|---|---|
| UI-L01 | Top header on every screen (UI-H01…H08) |
| UI-L02 | Left sidebar (Streamlit sidebar) for navigation, lists and settings on S02, S05, S06 |
| UI-L03 | Central workspace (chat or content) |
| UI-L04 | **Savings panel visible alongside the chat** on S05 and S06: a right-hand column (desktop) with the live session savings (UI-D01…D13), not a separate page. The chat keeps at least ~60% of the width: **a usable chat comes before dashboard density** |
| UI-L05 | Small screens: the sidebar collapses (Streamlit's built-in collapse); the savings column stacks below the chat inside a collapsible `expander` titled with the session saving; the chat stays the primary area; no horizontal scrolling (test at ~390 px and ~768 px widths) |
| UI-L06 | Clear spacing between areas; consistent paddings (tokens §2.5) |

---

## 2. Visual design system ("feel like a natural extension of Metis")

### 2.1 Overall style (UI-V01)
Minimal, premium SaaS: clean layouts with generous but controlled spacing; rounded rectangular cards with thin borders; high-contrast typography; subtle surfaces rather than heavy shadows; **bright blue** as the main interactive accent; **pink–purple–blue gradients** only for prominent branding and the selected main action; compact navigation; professional analytics charts; consistent visual hierarchy; restrained, little decoration.
**Avoid (UI-V02):** generic AI-dashboard styling, excessive gradients, glassmorphism, oversized floating cards, unnecessary animations.

### 2.2 Theme tokens (UI-V03): CSS variables, one source of truth
Implement as semantic CSS variables injected once per page (generated by a wiring function from a tokens table, e.g. `config/demo/theme.toml`, so the page holds no colours). Values are **approximations inferred from the screenshots**: compare against the screenshots and adjust; record the final values and their source.

| Token | Dark | Light | Usage |
|---|---|---|---|
| `--bg` | `#0E0E12` | `#FFFFFF`…`#FAFAFC` | application background |
| `--surface` (card) | `#090911`…`#0C0C14` | `#FFFFFF` | dashboard cards |
| `--header` | `#171719` | `#F7F7FA` | top navigation |
| `--elevated` | `#13131B` | (derive from screenshots) | dropdowns, selected surfaces |
| `--border` | `#242A3B` | `#E0E3EA` | cards, inputs, dividers |
| `--text` | `#F5F6FA` | `#192234` | headings and values |
| `--text-muted` | `#9CA3B5` | `#606879` | labels and descriptions |
| `--accent` | `#3D63FF` | `#3D63FF` | buttons, links, active states, focus |
| `--brand-gradient` | magenta → purple → blue | same | brand mark, the one primary CTA, selected main action only |
| `--chart-1..n` | from screenshots (teal/green line, distinguishable series) | same family, tuned for white | charts |
| `--success`, `--warning`, `--danger`, `--info` | restrained, from screenshots | same | banners, states |

**Light mode is not an inverted dark mode (UI-V04):** soft gray borders, dark typography, restrained shadows, blue interactive elements, colourful chart series, as in screenshots 2, 3 and 6.

### 2.3 Dark dashboard structure (UI-V05, from screenshots 1, 4, 5)
Full-width dark header; Metis brand at the far right (RTL); main navigation horizontal; account area, balance and theme toggle on the opposite side; background almost black; cards slightly differentiated from the background; fine blue-gray card borders; white metric values with muted labels; charts in clear accent colours with subtle grid lines.

### 2.4 Typography and language (UI-V06…V09)
- UI-V06 **Persian first, RTL.** The audience and screenshots are Persian. The UI ships with **two languages**: `fa` (default, right-to-left layout) and `en` (left-to-right), switchable in the header. All UI strings live in a strings table (e.g. `config/demo/ui_strings.toml`, keys × `fa`/`en`) read through wiring. Persian strings are marked `[PLACEHOLDER: Persian review]` until reviewed (K-2/K-3).
- UI-V07 **Mixed content readable in RTL:** numbers, costs, model identifiers, token counts and English technical terms are wrapped LTR-isolated (`<bdi>` / `unicode-bidi: isolate` with `direction: ltr`), so "gpt-4.1-nano", "$0.0123" and "12,345" never reorder. Chat messages use the existing `wiring.demo_ui.text_direction` per message.
- UI-V08 **Font:** Vazirmatn for Persian, **bundled locally** (font files committed under `assets/fonts/` with their OFL licence file, loaded by CSS `@font-face`; no web font CDN, the demo runs offline). Fallback system UI font for Latin. If the font files cannot be added, use the system font and say so.
- UI-V09 Do not force RTL on the `en` language setting.

### 2.5 Spacing, radius, sizes (UI-V10) (approximate; adjust from screenshots)
Spacing scale 4 / 8 / 12 / 16 / 24 / 32 px. Card radius 8–12 px; input/button radius 8 px. Card padding 16–20 px. Gap between cards 16 px. Header height ~56–64 px (**not tall**). Sidebar width: Streamlit default, styled. Button height consistent (~40 px). Breakpoints: ≤ 640 px (mobile), ≤ 1024 px (tablet), > 1024 px (desktop).

### 2.6 Components

**Header (UI-H01…H08)**
- UI-H01 Slim, full-width horizontal bar, styled with `--header`, bottom border `--border`.
- UI-H02 Brand: logo (UI-R08) + "Metis-Auto prototype" wordmark; at the **right** in RTL (`fa`), left in `en`; clicking returns to S01.
- UI-H03 Main navigation items: Chat, Results; **clear active state** (accent underline or filled pill).
- UI-H04 Opposite side: **theme toggle** (moon/sun, compact), **language toggle** (فا / EN), **mode chip** (Fake / Live), **budget chip** ("Budget left $x of $y" from the real `budget_view`, the honest equivalent of Metis's balance; hidden in fake mode or shown as "fake mode: no spend"), and a "Local demo" account chip (no login, UI-R08).
- UI-H05 Consistent spacing, restrained borders, keyboard-focusable controls.
- UI-H06…H08 reserved.

**Cards (UI-C01…C04):** thin border, minimal shadow, radius 8–12, consistent padding, compact muted label above a prominent value, consistent gaps. Metric cards: label, value (LTR-isolated), optional delta in success/danger colour.

**Controls (UI-K01…K08):**
- UI-K01 Rounded rectangular dropdowns with subtle borders, high-contrast text.
- UI-K02 Blue (`--accent`) focus and active states; **visible keyboard focus ring** on every control.
- UI-K03 Simple toggle switches (Streamlit `toggle`), styled.
- UI-K04 Consistent button heights; one primary style (accent; the brand gradient only for the one main CTA per screen), one secondary (outlined), one tertiary (text).
- UI-K05 **States:** loading (spinner or skeleton), empty (icon + one line + action), disabled (muted + reason tooltip or caption), error (danger-tinted card + what to do).
- UI-K06 Banners: info / warning / danger, dismissible where stated.
- UI-K07 Icons: a small consistent set (Streamlit Material icons `:material/...:` if available in the installed version, else simple Unicode); no emoji clutter.
- UI-K08 Inputs (chat input, text areas) styled with `--surface`, `--border`, accent focus.

**Charts (UI-G01…G08), Altair, themed from tokens:**
- UI-G01 **Cost trend:** teal/green line with a subtle filled area (from screenshots).
- UI-G02 **Token chart:** two distinguishable series (input vs output tokens).
- UI-G03 **Cost by model or provider:** grouped or stacked bars.
- UI-G04 **Cost breakdown:** simple donut.
- UI-G05 Axes and grid lines subtle; labels readable in both modes.
- UI-G06 **Tooltips follow the theme** (background, text, border).
- UI-G07 Charts re-render with the theme and language (axis titles from the strings table; Persian titles RTL).
- UI-G08 **No invented data:** a chart with no real data shows the empty state (UI-K05), never sample numbers.

**Theme switching (UI-T01…T05):**
- UI-T01 Moon/sun toggle in the header.
- UI-T02 Light and dark apply consistently to **every** screen: header, sidebar, cards, inputs, chat bubbles, banners, dialogs/expanders, charts and tooltips together.
- UI-T03 Persistence: keep the choice in `st.session_state` **and** in the URL query parameter (`?theme=dark&lang=fa`) so a reload keeps it (Streamlit has no local storage access without a component; this is the client-side mechanism). Default: dark.
- UI-T04 Avoid a flash of the wrong theme on load where reasonably possible: inject the theme CSS as the first element of every page; also set `.streamlit/config.toml` `[theme]` base colours to the default theme's tokens so Streamlit's own first paint matches.
- UI-T05 Only semantic tokens; no hard-coded colours outside the tokens table (test: grep the page and CSS generator for hex colours).

---

## 3. Entry screen (UI-S01)

- UI-E01 Metis-branded header (UI-H*).
- UI-E02 Clean central area with **two prominent selection cards**, side by side on desktop, stacked on mobile, balanced whitespace, strong alignment.
- UI-E03 Each card: simple icon, title, one-line explanation, clear CTA button.
  - **Chatbot**: "Chat with an existing configured assistant or create your own."
  - **Direct chat**: "Start chatting with AI directly, with automatic cost optimization."
  (Both in `fa` and `en` through the strings table.)
- UI-E04 Correct light and dark styling.
- UI-E05 **No extra onboarding steps.**

---

## 4. Journey A: Chatbot

### 4.1 Chatbot selection (UI-S02)
- UI-A01 **Left sidebar lists all chatbots** from the full dataset (bots used in sessions; ~600), each as a **label, never a real ID or instructions** (UI-R05): `bot-007 · فارسی · RAG · 4,210 chats` (rank by traffic; language of instructions; RAG yes/no; sessions count), plus user-made bots (UI-A10) marked "yours".
- UI-A02 **Search and filters** above the list: text search over the label, filters for language, RAG, memory, and "has instructions". Sorted by traffic. A clear **selected state**.
- UI-A03 Data source (verified): the local PostgreSQL `src.chat_bot` (columns include `bot_id`, `instructions`, `provider_model`, `provider_name`, `memory_enabled`, `summarizer_mode`, `corpus_ids`, `rag_top_k`, `public`, `enabled`, `functions`) and the full-EDA tables for traffic counts. Read through a new **wiring** module (e.g. `wiring/demo_bots.py`) that returns content-free `BotCard` records (label, facts) and keeps the real `bot_id` internal (never rendered). If the database is not running, the list shows the empty state with "start the local database (docs/guides/team_setup.md)", and synthetic presets stay available. Bot names do not exist in the export (Metis question 18): never invent names.
- UI-A04 **Main area:** heading **"Your chatbots"** (strings table); the selected bot's **details card with derived facts only** (label, language, model as configured, RAG on/off and top-k, memory, summariser, instruction length in characters, traffic rank), and a prominent **"Create new chatbot"** button.
- UI-A05 Existing instructions and retrieval configuration are **preserved and used behind the scenes**; the user never re-enters them.
- UI-A06 After selecting, a primary button **"Continue"** → optimisation settings (S04).

### 4.2 Create chatbot (UI-S03)
- UI-A10 Fields supported by the existing backend: **name** (local only), **instructions** (text), **knowledge passages** (one or more pasted text blocks, the existing `_add_doc` / retrieved-context path). Saved to git-ignored `runs/demo/bots/<id>.json` (UI-R11), listed in the sidebar as "yours".
- UI-A11 **Not supported, shown disabled with a reason:** uploading files to a knowledge base, connecting a corpus, sharing a bot. No fake persistence beyond the local file.
- UI-A12 After saving → optimisation settings (S04).

### 4.3 Optimisation settings (UI-S04)
- UI-A20 Three separate options, each a card with **name, short non-technical explanation, on/off switch, and a clear state indication** ("On" / "Off" chip):
  1. **Cache**: "Reuse a previously generated answer when the same question has already been answered. This can reduce response time and avoid unnecessary AI costs." Drives the existing demo cache (bot-level cache toggle). **Semantic matching is not available** (only exact matches exist): say so in a caption; do not call it "semantic cache".
  2. **Context optimization**: "Reduce unnecessary conversation context sent to the AI while keeping the important information needed to answer your question." Drives the existing compression mode (LLMLingua-2, **experimental**; requires the optional `compress` extra and its pinned weights; if not installed, the switch is disabled with that reason).
  3. **Intelligent model routing**: "Automatically select a suitable, cost-efficient AI model for each request instead of always using an expensive model." Drives `RoutingMode` (rule-based / sticky, ADR-0023).
- UI-A21 **Defaults:** routing **on**; cache and context optimisation take the **actual backend defaults** (`ChatSession`: `bot_cache=False`, `compression=OFF`; verify in code and state them).
- UI-A22 Settings are **functional**: changing a switch changes the next request (through the existing `_on_routing`, `_on_compression`, `_on_bot_cache` behaviour, moved into wiring if needed).
- UI-A23 A caption under all three: "These switches drive demo rules; the measured savings of the project's methods are on the Results page" (UI-R07).
- UI-A24 A prominent **"Start chatting"** button below the settings (the screen's one gradient CTA).

### 4.4 Chat workspace, chatbot (UI-S05)
- UI-A30 **Left sidebar:** the bot list (UI-A01, compact), the current bot highlighted, **this bot's chat history** (previous conversations, newest first, titled by first message or "Conversation n"), **"New conversation"**, and the **three optimisation switches** (UI-A20), changeable during the chat.
- UI-A31 **Switching to another bot keeps** each bot's conversations and the current one (state per bot in session state and in `runs/demo/conversations/`, UI-R11).
- UI-A32 **Central area:** the selected bot's label as title; messages (existing `_message` rendering: per-message direction, details sections); the message composer and send (`st.chat_input`); loading state while answering; streaming if the existing chat path supports it (verify; do not add streaming otherwise); friendly error states (existing `friendly_failure`).
- UI-A33 **Behind the scenes:** a real bot's **instructions** and its **retrieved passages** are sent to the model (UI-R05 rules). Passages for a typed question: **Option A (build now):** the bot's chunk set from one representative logged turn (the most recent logged turn with RAG for that bot), fixed for the conversation, labelled "knowledge: passages from one logged turn". **Option B (later, only if time):** keyword search over the bot's pool of logged chunks per question (no new dependency), labelled "knowledge: passages seen in the logs". Bots without RAG use instructions only.
- UI-A34 **Savings panel alongside** (UI-L04, UI-D*).

---

## 5. Journey B: Direct chat (UI-S06)

- UI-B01 No bot selection and no bot setup.
- UI-B02 **Left sidebar:** previous direct conversations, **"New chat"**, **model selection** (existing fixed-model selectbox; when routing is on it becomes "Preferred model" and is greyed with the caption "routing chooses the model"), and the three optimisation switches (UI-A20), with the same defaults (routing on).
- UI-B03 **Main area:** chat history, messages, input; above the messages, a status line showing **"Model: chosen by routing"** or **"Model: <fixed model>"**; each assistant message shows the **model actually used**.
- UI-B04 **Default cost-saving banner** on entering direct chat, visible but non-intrusive, **dismissible**, with a link that opens the settings in the sidebar:
  > "Cost optimization is on. Metis-Auto may choose a different AI model from the one you selected to reduce cost while aiming to keep response quality. You can change this in Settings."
  It must not guarantee identical quality, must explain that the selected model may change, and where to turn it off. Dismissal is remembered for the session.
- UI-B05 The same savings panel as Journey A (UI-D*), adapted to direct chat.

---

## 6. Savings and results

### 6.1 Live savings panel (S05, S06) (UI-D01…D12)
Restyle and reuse the existing cost panel (`cost_view`, `waterfall_rows`, `budget_view`, tabs "This message" / "Session"); do not rewrite the calculations.
- UI-D01 **Cost without optimisation** (the project's premium baseline, gpt-5.5, **estimated**, ADR-0026).
- UI-D02 **Actual cost** (provider-reported in live mode, estimated in fake mode: label which).
- UI-D03 **Amount saved**; UI-D04 **percentage saved** (where computable; "not computed" otherwise, never 0).
- UI-D05 **Model selected** vs UI-D06 **model actually used** per message.
- UI-D07 Whether **cache**, UI-D08 **context optimisation**, UI-D09 **routing** were applied (chips per message).
- UI-D10 **Input/output tokens** per message, with their method/fidelity label.
- UI-D11 **Latency** where available (live: measured; fake: "not measured").
- UI-D12 Charts: session **cost trend** (UI-G01: actual vs baseline per message, cumulative), **tokens** (UI-G02: input vs output per message), **cost by model used** (UI-G03), **savings breakdown** donut (UI-G04: the existing decomposition terms). Estimated vs observed values are visually distinguished (e.g. hatched or "est." tag).
- UI-D13 **Keep the existing metrics that already work:** the budget bars with the refusal at the cap (`budget_view`), the per-message detail sections (`detail_sections`), the routing kind (`routing_kind`), and the friendly failure messages. Restyle, don't remove.

### 6.2 Results dashboard: D-2 (UI-S07) (UI-R20…R32)
The sprint's offline lever results, in the Metis analytics style (screenshots 3–6). Data only from `reports/levers/*.json` through `wiring/lever_view.py` (D-1), plus `reports/levers/final.json` when it exists.
- UI-R20 **Baseline selector** (premium gpt-5.5, as-logged, today's models, best single cheap) and **slice selector** (all, LLM only, over 8k, by language, traffic-weighted). One baseline at a time; recorded and price-file units never mixed (ADR-0036).
- UI-R21 **Savings overview**: metric cards (baseline cost, saving, saving %, interval) for the combined result (`final.json`) if present, else per step.
- UI-R22 **Waterfall by cost block** including F-2's **"other"** block when present; repriced baselines show **"token cost only, fees not priced"** (not "unknown").
- UI-R23 **Version comparison per step** (cache, context, routing): table plus bars, ranked within a step only, with evidence class, correctness state, n eligible, interval; "insufficient evidence" rows never ranked.
- UI-R24 **Version switch per step**: choose one version per step and watch the combined view update (the plan's demo step 2), using `combine`-based results where available.
- UI-R25 **Cache monitor**: hits, misses, guard blocks (by reason), shadow-check result, from the cache versions' results.
- UI-R26 **Routing per bot**: ranks (`bot-07`), moved share, saving, caveats; per-tenant and traffic-weighted rows; tenants over 0.35 flagged.
- UI-R27 The greeting gate's token saving is read from its result's slice (R-C1, ADR-0039).
- UI-R28 Every number shows its **evidence class** and the line "simulation on logged data; quality not proven" where applicable.
- UI-R29 Persian right-to-left labels (the plan's `test_rtl_for_persian_labels`).
- UI-R30 Empty state when no results exist.
- UI-R31 Request explorer: **not in scope** (stretch, needs Langfuse).
- UI-R32 Charts per UI-G* (bars for comparison, donut for blocks, line only where a real time series exists; never invent one).

---

## 7. Settings behaviour (UI-SB01…SB07)
- UI-SB01 Switch states always reflect the real `ChatSession` configuration.
- UI-SB02 Changes apply to the next request.
- UI-SB03 Settings survive navigation between screens (session state).
- UI-SB04 Switching bots does not discard any conversation.
- UI-SB05 Bot-specific settings (per bot) and user-level preferences (theme, language, direct-chat settings) are stored separately.
- UI-SB06 The user can always see whether routing is active (header of the chat, per-message chip).
- UI-SB07 With routing off, the fixed model selection is respected, as the backend defines.

---

## 8. Stages (build in this order; stop after any stage; each ends with a commit)

| Stage | Contents | IDs | Done when |
|---|---|---|---|
| **0. Inspect** | read ADRs 0023, 0024, 0026, 0031, 0032, 0036, 0039; `scripts/demo_ui.py`, `wiring/demo_ui.py`, `wiring/chat.py`, `wiring/lever_view.py`, `config/demo/presets-synthetic.toml`, `.streamlit/config.toml`, `tests/architecture/test_ui_imports.py`, `tests/unit/wiring/test_lever_view.py`; `data_access/postgres/models.py` (`src.chat_bot`, `src.rag_chunk`); check the screenshots folder and any logo asset; check Streamlit 1.65.0 features used here (navigation, toggles, icons, AppTest). Write the gap list | all | written in the stage report; no code |
| **1. D-2 results dashboard** | S07 on real results; plan tests `test_cache_monitor_counts_match_lever_result`, `test_rtl_for_persian_labels` | UI-R20…R30, UI-G05/G08 | the 18:00 milestone; tests green |
| **2. Design system** | tokens, CSS generator, header, cards, controls, charts theme, theme and language toggles, fonts, logo rule, strings table | UI-V*, UI-H*, UI-C*, UI-K*, UI-G*, UI-T* | both themes and both languages on S07 and the existing chat |
| **3. Shell and journeys** | S01, S04, S05 and S06 with the existing chat and cost panel; banner; savings panel alongside; layout and responsive | UI-L*, UI-E*, UI-A20…A24, UI-A30…A32, UI-A34, UI-B*, UI-D*, UI-SB* | both journeys from entry to chat in fake mode |
| **4. Real bots** | S02 bot list from the database, details card, Option A passages, live with the approval switch | UI-A01…A06, UI-A33 | choose bot-007 and chat (fake; live only with approval) |
| **5. Persistence, create bot, polish** | conversation history files, S03 create bot, Option B search (only if time), mobile checks, accessibility pass | UI-A10…A12, UI-A31, UI-L05, UI-K02 | history survives a restart; create works locally |

**Time box (sprint):** stage 1 by Day 3 18:00; stages 2–3 next; stages 4–5 only if time remains before **Day 4 12:00 code freeze**. Record a 90-second screen recording of whatever works before the freeze (the plan's fallback).

---

## 9. Coverage of the owner's design brief

| Brief section | Covered by |
|---|---|
| Role and goal: Metis visual identity + Metis-Auto cost experience | §2, §6 |
| Replace Streamlit with Next.js | **Overridden by the owner (2026-11-03): Streamlit** (UI-R01) |
| Preserve backend, algorithms, calculations | UI-R02, UI-R03 |
| Separate business logic from UI, smallest safe path | UI-R02, stage 0 |
| Persian RTL, light/dark, both journeys, persistent conversations, functional controls, savings dashboard | UI-V06…V09, UI-T*, §3–5, UI-A31, UI-A20…A22, §6 |
| Phase 1: understand the repo, no invented endpoints, ADRs as constraints, report discrepancies, missing capabilities explicit | stage 0, UI-R04, UI-R10 |
| Phase 2: six screenshots as primary reference | UI-R09 |
| 2.1 overall style + avoid list | UI-V01, UI-V02 |
| 2.2 dark tokens + dark dashboard structure | UI-V03, UI-V05 |
| 2.3 light tokens, not inverted | UI-V03, UI-V04 |
| 2.4 branding (logo, no substitute, wordmark, gradients sparingly) | UI-R08, UI-H02, UI-V03 `--brand-gradient` |
| 2.5 typography, localisation, RTL, mixed content, Vazirmatn, no forced RTL | UI-V06…V09 |
| 2.6 header | UI-H01…H05 |
| 2.6 cards | UI-C01…C04 |
| 2.6 controls and states | UI-K01…K08 |
| 2.6 charts (trend, tokens, by model, donut, subtle axes, readable, themed tooltips, no invented data) | UI-G01…G08 |
| 2.6 theme switching (toggle, consistent, persistence, no flash, tokens) | UI-T01…T05 |
| Phase 3 entry screen and copy | UI-E01…E05 |
| Journey A: 2A selection (sidebar of dataset bots, no fabricated identities, "Your chatbots", create) | UI-A01…A06 |
| Journey A: create chatbot, no fake persistence or upload | UI-A10…A12 |
| Journey A: 3A three settings, copy, switches, defaults, functional, "Start chatting" | UI-A20…A24 |
| Journey A: 4A sidebar, central chat, savings alongside | UI-A30…A34 |
| Journey B: 2B direct chat, sidebar, model selection, routing status | UI-B01…B03, UI-B05 |
| Direct chat notification (text, dismissible, settings link, no guarantee, preferred vs routed) | UI-B04 |
| 4.1 layout shell, desktop and small screens | UI-L01…L06 |
| 4.2 cost transparency list | UI-D01…D12 |
| 4.3 settings behaviour | UI-SB01…SB07 |
| 4.4 preserve existing functionality | UI-R03 |
| Phase 5 verification and delivery | §10 |
| Plan D-2 (overview, waterfall incl. other, comparison, cache monitor, routing per bot, RTL, two tests) | UI-R20…R30 |
| Plan demo script (waterfall, version switch, cache monitor, per-bot table, chat with cost panel, budget bars and refusal at the cap) | UI-R21…R26, UI-S05/S06, UI-H04, UI-D* |

**Adaptations to project rules (not drops):** "semantic cache" → "Cache (exact; semantic not available)" (UI-A20); real chatbots shown as labels, content never displayed (UI-R05); toggles drive demo components (UI-R07); no login (UI-R08); real-bot knowledge = logged passages (UI-A33).

---

## 10. Verification (every stage reports the items it touched)

- Both journeys work from the entry screen to the chat (fake mode).
- All real bots load as labels; no real ID, instructions or chunk text is rendered (test the wiring output types and a rendered-page scan).
- Real instructions and passages are used behind the scenes (test the request built by wiring).
- Create chatbot works locally; unsupported actions are disabled with reasons.
- Chat history loads per bot and per direct chat; switching bots loses nothing.
- The three switches reflect and change the real `ChatSession`; routing is on by default.
- The direct-chat banner is shown, dismissible and accurate.
- Savings values equal the existing calculations (tests compare wiring output with `cost_view` / `waterfall_rows`).
- Results dashboard values equal the `LeverResult` files (tests).
- Light/dark and fa/en work on every screen and chart; no hard-coded colours outside the tokens.
- Desktop (≥ 1280 px) and mobile (~390 px) layouts work; no horizontal scroll.
- `tests/architecture` (Streamlit/Altair imports only in the page files), ruff, full pytest green.
- If Streamlit's `AppTest` is available in 1.65.0, a smoke test renders each screen in fake mode without errors.
- Each stage: a list of every UI-ID touched with done / partial / not done / not possible.
