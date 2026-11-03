"""The Metis-Auto demo UI in the browser (Demo milestone B; brief §10).

    .venv/bin/python scripts/demo_ui.py            # opens http://localhost:8501

A thin Streamlit page over ``metis_auto.wiring.chat.ChatSession`` (the same
backend as ``scripts/chat.py``) and ``metis_auto.wiring.demo_ui`` (the view
model). No routing, caching, or accounting logic here: the page holds the
history and sends it every turn (P-8), shows each ``TurnReport``, and maps the
widgets to the session's toggles.

- Header (UI spec Stage 2, UI-H01..H05): the text wordmark, the language switch
  (فا / EN), the Fake/Live chip, the budget, the theme toggle and a "Local demo"
  chip; below, the Chat and Results tabs. Built here, not with Streamlit's top
  navigation, which cannot hold these controls (ADR-0052).
- Main area: the chat (Persian right-to-left, English left-to-right), the
  live-call banner, and per-message details.
- Sidebar: bot setup (instructions, one retrieved document per block,
  SYNTHETIC presets) and settings (fake or live, routing mode, the DEMO cache
  settings, EXPERIMENTAL compression, DeepSeek thinking, new user, reset).
- Right: the cost panel (paid vs the premium estimate, the savings
  decomposition, the budget).
- Results (D-2, the offline lever results): ``scripts/demo_pages/results.py``
  over ``wiring.lever_view``.

Theme (dark default, light) and language (fa default, en) live in the session
and the URL (``?theme=…&lang=…``); every colour, size and string comes from
``config/demo/theme.toml`` and ``config/demo/ui_strings.toml`` through
``wiring.ui_config`` and ``wiring.ui_style``; the style sheet is the first
element of every page.

Live calls need both keys (ADR-0018): the Live switch here and
``[live] enabled = true`` in config/local.toml, plus METIS_API_KEY in .env.
Every live call goes through the spend guard and the ledger. The page never
shows, logs, or stores the key and logs no message content. Usage statistics
are off and the server listens on localhost only (also in .streamlit/).

Run with plain Python: the script starts ``streamlit run`` on itself with
those options. Streamlit (extra ``ui``, requirements-ui.lock) is imported only
here (tested).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

from metis_auto.settings import SettingsError
from metis_auto.wiring.chat import (
    ChatSession,
    CompressionMode,
    RoutingMode,
    TurnReport,
)
from metis_auto.wiring.demo_ui import (
    CostView,
    blocked_banner,
    budget_view,
    cost_view,
    detail_sections,
    friendly_failure,
    live_banner,
    live_check,
    load_presets,
    money,
    routing_kind,
    text_direction,
    waterfall_rows,
)
from metis_auto.wiring.ui_config import (
    DEFAULT_LANGUAGE,
    LANGUAGE_SHORT,
    LANGUAGES,
    load_strings,
    load_theme,
    translator,
    ui_state,
)
from metis_auto.wiring.ui_style import (
    altair_config,
    budget_html,
    card_title_html,
    chip_html,
    empty_state_html,
    header_brand_html,
    kind_rows,
    kind_scale,
    ltr,
    page_css,
)

STREAMLIT_OPTIONS = (
    "--browser.gatherUsageStats=false",
    "--server.address=localhost",
    "--client.toolbarMode=minimal",
    "--server.fileWatcherType=none",
)
RESULTS_PAGE = "demo_pages/results.py"  # D-2 Results page, relative to this file
FAKE, LIVE = "Fake (free, no key)", "Live (real models, budgeted)"
MODE_KEYS = {FAKE: "mode_fake_option", LIVE: "mode_live_option"}
ROUTER_MODES = (
    "off",
    "local",
    "hosted",
    "hybrid_local_first",
    "hybrid_hosted_first",
)

# --- session state -------------------------------------------------------


def _s():
    return st.session_state


def _injected(name: str):
    """Test hooks (offline tests set these before the first run)."""
    return _s().get(f"_test_{name}")


def S(key: str, **fields: object) -> str:
    """One string from config/demo/ui_strings.toml in the session's language."""
    t = _s().get("ui_text") or translator(load_strings(), DEFAULT_LANGUAGE)
    return t(key, **fields)


def _init() -> None:
    s = _s()
    if "chat" in s:
        return
    s.presets = load_presets(_injected("presets_path"))
    s.preset_key = None
    s.instructions = ""
    s.doc_ids = []
    s.next_doc = 0
    s.mode = FAKE
    s.routing = RoutingMode.STICKY_V1.value
    s.router_mode = "local"
    s.compression = CompressionMode.OFF.value
    s.bot_cache = False
    s.seed = False
    s.thinking = True
    s.messages = []
    s.notice = None
    s.blocked = None
    s.chat = _build_chat(live=False)
    s.fixed_model = s.chat.model_id


def _documents() -> list[str]:
    s = _s()
    return [s.get(f"doc_{i}", "") for i in s.doc_ids]


def _build_chat(*, live: bool) -> ChatSession:
    s = _s()
    routing = RoutingMode(s.routing)
    return ChatSession(
        s.get("fixed_model") if routing == RoutingMode.FIXED else None,
        live=live,
        instructions=s.instructions or None,
        retrieved=_documents(),
        routing=routing,
        compression=CompressionMode(s.compression),
        bot_cache=s.bot_cache,
        seed=s.seed,
        deepseek_thinking=s.thinking,
        settings_loader=_injected("settings_loader"),
        client_factory=_injected("client_factory"),
        compressor_factory=_injected("compressor_factory"),
        seed_path=_injected("seed_path"),
        router_mode=s.get("router_mode", "local"),
    )


def _notice(level: str, text: str) -> None:
    _s().notice = (level, text)


def _loader():
    from metis_auto.settings import load_settings

    return _injected("settings_loader") or (lambda o: load_settings(overrides=o))


# --- callbacks (run before the page is drawn) ---------------------------


def _on_mode() -> None:
    s = _s()
    live = s.mode == LIVE
    if live:
        allowed, reasons = live_check(_loader())
        if not allowed:
            s.mode, s.blocked = FAKE, "; ".join(reasons)
            return
    try:
        chat = _build_chat(live=live)
    except (SettingsError, ValueError) as exc:
        s.mode = FAKE
        s.blocked = str(exc).removeprefix("live calls refused: ")
        return
    s.chat, s.messages, s.blocked = chat, [], None
    _notice(
        "info",
        S(
            "notice_new_run",
            mode=S("mode_live" if live else "mode_fake"),
            run=ltr(chat.run_id),
        ),
    )


def _apply(key: str, change, current) -> None:
    """Apply one toggle to the session; on failure restore the widget."""
    s = _s()
    try:
        change(s[key])
    except Exception as exc:  # noqa: BLE001 - shown to the presenter
        s[key] = current
        _notice("error", S("notice_setting_failed", error=exc))


def _on_routing() -> None:
    s = _s()
    chat: ChatSession = s.chat

    def change(value: str) -> None:
        if value == RoutingMode.FIXED.value:
            chat.switch_model(s.fixed_model)
        else:
            chat.set_routing(RoutingMode(value))

    _apply("routing", change, chat.routing.value)


def _on_router_mode() -> None:
    s = _s()
    chat: ChatSession = s.chat
    _apply("router_mode", chat.set_router_mode, chat.router_mode)


def _on_fixed_model() -> None:
    s = _s()
    _apply("fixed_model", s.chat.switch_model, s.chat.model_id)


def _on_compression() -> None:
    chat: ChatSession = _s().chat
    _apply(
        "compression",
        lambda v: chat.set_compression(CompressionMode(v)),
        chat.compression.value,
    )


def _on_bot_cache() -> None:
    chat: ChatSession = _s().chat
    _apply("bot_cache", chat.set_bot_cache, chat.bot_cache)


def _on_seed() -> None:
    chat: ChatSession = _s().chat
    _apply("seed", chat.set_seed, chat.seed)


def _on_thinking() -> None:
    chat: ChatSession = _s().chat
    _apply("thinking", chat.set_deepseek_thinking, chat.deepseek_thinking)


def _on_new_user() -> None:
    s = _s()
    s.chat.new_user()
    s.messages = []
    _notice("info", S("notice_new_user", n=ltr(s.chat.users)))


def _on_reset() -> None:
    s = _s()
    s.chat.reset()
    s.messages = []
    _notice("info", S("notice_reset"))


def _on_degrade() -> None:
    _s().chat.degrade_next()
    _notice("info", S("notice_degrade"))


def _load_preset(key: str) -> None:
    s = _s()
    preset = next(p for p in s.presets if p.key == key)
    for i in s.doc_ids:
        s.pop(f"doc_{i}", None)
    s.doc_ids = []
    for text in preset.documents:
        _add_doc(text)
    s.instructions = preset.instructions
    s.preset_key = key
    s.chat.reset()
    s.messages = []
    _notice("info", S("notice_preset", title=preset.title))


def _clear_bot() -> None:
    s = _s()
    for i in s.doc_ids:
        s.pop(f"doc_{i}", None)
    s.doc_ids, s.instructions, s.preset_key = [], "", None


def _add_doc(text: str = "") -> None:
    s = _s()
    s[f"doc_{s.next_doc}"] = text
    s.doc_ids = [*s.doc_ids, s.next_doc]
    s.next_doc += 1


def _remove_doc(doc_id: int) -> None:
    s = _s()
    s.doc_ids = [i for i in s.doc_ids if i != doc_id]
    s.pop(f"doc_{doc_id}", None)


# --- one turn ------------------------------------------------------------


def _send(message: str) -> None:
    s = _s()
    chat: ChatSession = s.chat
    chat.set_instructions(s.instructions or None)
    chat.set_retrieved(_documents())
    with st.spinner(S("spinner_answering")):
        response, report = chat.ask(message)
    s.messages.append({"role": "user", "text": message})
    s.messages.append(
        {"role": "assistant", "text": response.answer or "", "report": report}
    )


# --- drawing ---------------------------------------------------------------


def _sidebar() -> None:
    s = _s()
    chat: ChatSession = s.chat
    t = s.ui_text  # bound now: format functions also run outside the script run
    with st.sidebar:
        st.header(S("bot_setup"))
        st.caption(S("presets_note"))
        for preset in s.presets:
            st.button(
                preset.title,
                key=f"preset_{preset.key}",
                on_click=_load_preset,
                args=(preset.key,),
                help=preset.description,
                width="stretch",
                type="primary" if s.preset_key == preset.key else "secondary",
            )
        st.text_area(S("instructions"), key="instructions", height=160)
        st.markdown(S("retrieved_context"))
        for n, doc_id in enumerate(s.doc_ids, 1):
            st.text_area(S("document_n", n=n), key=f"doc_{doc_id}", height=110)
            st.button(
                S("remove_document_n", n=n),
                key=f"rm_{doc_id}",
                on_click=_remove_doc,
                args=(doc_id,),
                type="tertiary",
            )
        c1, c2 = st.columns(2)
        c1.button(S("add_document"), on_click=_add_doc, width="stretch")
        c2.button(S("clear_bot"), on_click=_clear_bot, width="stretch")

        st.divider()
        st.header(S("settings"))
        st.radio(
            S("mode"),
            [FAKE, LIVE],
            key="mode",
            format_func=lambda v: t(MODE_KEYS[v]),
            on_change=_on_mode,
        )
        st.radio(
            S("routing_label"),
            [m.value for m in RoutingMode],
            key="routing",
            format_func=lambda v: t(f"routing_{v}"),
            on_change=_on_routing,
            horizontal=True,
            help=S("routing_help"),
        )
        if s.routing == RoutingMode.DECISION_ROUTER.value:
            st.selectbox(
                S("decision_backends"),
                list(ROUTER_MODES),
                key="router_mode",
                format_func=lambda v: t(f"router_{v}"),
                on_change=_on_router_mode,
                help=S("decision_backends_help"),
            )
        if s.routing == RoutingMode.FIXED.value:
            models = [
                e.model_id for e in chat.loaded.reference.catalogue.entries if e.enabled
            ]
            st.selectbox(
                S("model"), models, key="fixed_model", on_change=_on_fixed_model
            )
        st.toggle(
            S("bot_cache"),
            key="bot_cache",
            on_change=_on_bot_cache,
            help=S("bot_cache_help"),
        )
        st.toggle(
            S("demo_seed"),
            key="seed",
            on_change=_on_seed,
            help=S("demo_seed_help"),
        )
        st.radio(
            S("compression"),
            [
                CompressionMode.OFF.value,
                CompressionMode.FAKE.value,
                CompressionMode.LLMLINGUA2.value,
            ],
            key="compression",
            format_func=lambda v: t(f"compression_{v}"),
            on_change=_on_compression,
            horizontal=True,
        )
        if s.compression == CompressionMode.LLMLINGUA2.value:
            st.warning(S("llmlingua_warning"), icon=":material/warning:")
        elif s.compression == CompressionMode.FAKE.value:
            st.caption(S("compression_fake_note"))
        st.toggle(
            S("thinking"),
            key="thinking",
            on_change=_on_thinking,
            help=S("thinking_help"),
        )
        c1, c2 = st.columns(2)
        c1.button(
            S("new_user"),
            key="new_user",
            on_click=_on_new_user,
            width="stretch",
        )
        c2.button(
            S("reset_conversation"),
            key="reset",
            on_click=_on_reset,
            width="stretch",
        )
        if not chat.live:
            with st.expander(S("more_fake")):
                st.button(
                    S("cut_off_next"),
                    on_click=_on_degrade,
                    width="stretch",
                )
        if s.seed and chat.seeded:
            with st.expander(S("seeded_questions")):
                st.caption(S("seeded_note"))
                for n, question in enumerate(chat.seeded):
                    if st.button(question, key=f"seedq_{n}"):
                        _send(question)
        st.caption(S("run_footer", run=ltr(chat.run_id), user=ltr(chat.users)))


def _banner() -> None:
    s = _s()
    chat: ChatSession = s.chat
    if s.blocked:
        banner = blocked_banner(s.blocked)
    else:
        allowed, reasons = (True, ()) if chat.live else live_check(_loader())
        banner = live_banner(
            live=chat.live,
            allowed=allowed,
            reasons=reasons,
            stopped=chat.pipeline.live_stopped,
        )
    show = {
        "off": st.info,
        "on": st.warning,
        "blocked": st.error,
        "stopped": st.error,
    }[banner.state]
    show(f"**{S(f'banner_{banner.state}')}.** {banner.detail}")
    if s.notice:
        level, text = s.notice
        {"info": st.toast, "error": st.error}[level](text)
        s.notice = None


def _message(i: int, message: dict) -> None:
    role, text = message["role"], message["text"]
    with st.chat_message(role):
        with st.container(key=f"{text_direction(text)}-m{i}"):
            st.markdown(text or S("no_answer"))
        report: TurnReport | None = message.get("report")
        if report is None:
            return
        failure = friendly_failure(report)
        if failure:
            st.warning(failure)
        view = cost_view(report.parts)
        parts = [
            f"**{routing_kind(report)}**",
            S("served_by", by=report.served_by),
            f"`{ltr(report.model_id or '-')}`",
        ]
        if view is not None and view.paid is not None:
            saved = (
                S("badge_less", share=ltr(f"{view.saved_fraction:.0%}"))
                if view.saved_fraction is not None
                else ""
            )
            parts.append(
                S(
                    "badge_paid",
                    paid=ltr(money(view.paid)),
                    premium=ltr(money(view.premium)),
                    saved=saved,
                )
            )
        with st.container(key=f"badge-{i}"):
            st.markdown(" · ".join(parts))
        with st.expander(S("details")):
            for title, rows in detail_sections(report):
                st.markdown(f"**{title}**")
                st.table(pd.DataFrame(rows, columns=["", S("col_value")]).set_index(""))


def _chat_column() -> None:
    s = _s()
    box = st.container(height=430, border=False, key="mx-chat-box")
    with box:
        if not s.messages:
            st.html(empty_state_html("forum", S("chat_empty"), S("chat_empty_action")))
        for i, message in enumerate(s.messages):
            _message(i, message)
    preset = next((p for p in s.presets if p.key == s.preset_key), None)
    if preset and preset.suggested:
        picked = st.pills(
            S("try_synthetic"),
            preset.suggested,
            key=f"try_{len(s.messages)}",
            label_visibility="collapsed",
        )
        if picked:
            _send(picked)
            st.rerun()
    prompt = st.chat_input(S("chat_placeholder"))
    if prompt:
        _send(prompt)
        st.rerun()


def _chart(chart: alt.TopLevelMixin) -> None:
    """Every chart gets the theme's Altair config (UI-G05, UI-G06)."""
    s = _s()
    config = altair_config(load_theme(s.ui_theme), s.ui_lang)
    st.altair_chart(chart.configure(**config), width="stretch", theme=None)


def _waterfall(view: CostView) -> None:
    rows = waterfall_rows(view)
    if not rows:
        st.html(empty_state_html("bar_chart", S("nothing_computed")))
        return
    s = _s()
    domain, colours = kind_scale(load_theme(s.ui_theme), s.ui_text)
    data = pd.DataFrame(kind_rows(rows, s.ui_text))
    order = list(data["term"])
    bars = (
        alt.Chart(data)
        .mark_bar(cornerRadius=3, height=16)
        .encode(
            y=alt.Y(
                "term:N", sort=order, title=None, axis=alt.Axis(labelOverlap=False)
            ),
            x=alt.X("start:Q", title=view.currency, axis=alt.Axis(format=".6f")),
            x2="end:Q",
            color=alt.Color(
                "kind_label:N",
                scale=alt.Scale(domain=domain, range=colours),
                legend=alt.Legend(title=None),
            ),
            tooltip=[
                alt.Tooltip("term:N", title=S("col_term")),
                alt.Tooltip("label:N", title=view.currency),
            ],
        )
    )
    _chart(bars.properties(height=alt.Step(26)))


def _cost_tab(view: CostView | None, scope: str) -> None:
    if view is None:
        st.html(empty_state_html("receipt_long", S("no_answer_yet", scope=scope)))
        return
    cards = (
        (S("actually_paid"), ltr(money(view.paid, ""))),
        (S("premium_estimate"), ltr(money(view.premium, ""))),
        (
            S("saved"),
            ltr(
                f"{view.saved_fraction:.1%}" if view.saved_fraction is not None else "-"
            ),
        ),
    )
    with st.container(key=f"mx-row-cost-{scope}", horizontal=True):
        for n, (label, value) in enumerate(cards):
            with st.container(key=f"mx-kpi-cost-{scope}-{n}"):
                st.metric(label, value)
    _waterfall(view)


def _cost_panel() -> None:
    s = _s()
    chat: ChatSession = s.chat
    last = next((m["report"] for m in reversed(s.messages) if m.get("report")), None)
    message_view = cost_view(last.parts) if last else None
    session_view = cost_view(last.session_parts) if last else None
    with st.container(key="mx-card-cost"):
        st.html(card_title_html(S("cost")))
        tab1, tab2 = st.tabs([S("tab_message"), S("tab_session")])
        with tab1:
            _cost_tab(message_view, S("scope_message"))
        with tab2:
            _cost_tab(session_view, S("scope_session"))
            if session_view is not None:
                st.caption(
                    S(
                        "session_counts",
                        messages=ltr(session_view.messages),
                        hits=ltr(session_view.cache_hits),
                    )
                )
        if message_view or session_view:
            rows = []
            m_terms = dict(message_view.terms) if message_view else {}
            s_terms = dict(session_view.terms) if session_view else {}
            for label, _ in (message_view or session_view).terms:
                rows.append(
                    {
                        S("col_term"): label,
                        S("col_message"): ltr(money(m_terms.get(label), "")),
                        S("col_session"): ltr(money(s_terms.get(label), "")),
                    }
                )
            st.table(pd.DataFrame(rows).set_index(S("col_term")))
            st.caption(S("decomposition_note"))
        st.caption(f"{S('premium_caveat')} {S('demo_caveat')}")

    with st.container(key="mx-card-budget"):
        st.html(card_title_html(S("budget")))
        budget = budget_view(chat)
        if budget is None:
            st.html(empty_state_html("account_balance_wallet", S("budget_none")))
            return
        st.progress(
            min(budget.lifetime_fraction, 1.0),
            text=S(
                "budget_lifetime",
                spent=ltr(f"{budget.lifetime_spent:.6f}"),
                cap=ltr(f"{budget.lifetime_cap} {budget.currency}"),
                share=ltr(f"{budget.lifetime_fraction:.2%}"),
            ),
        )
        if budget.run_cap is not None:
            st.progress(
                min(budget.run_fraction or 0.0, 1.0),
                text=S(
                    "budget_run",
                    spent=ltr(f"{budget.run_spent:.6f}"),
                    cap=ltr(f"{budget.run_cap} {budget.currency}"),
                ),
            )
        marks = " / ".join(ltr(f"{w:.0%}") for w in budget.warn_at)
        if budget.crossed is not None and budget.crossed >= max(budget.warn_at):
            st.error(S("budget_over_tell", share=ltr(f"{budget.crossed:.0%}")))
        elif budget.crossed is not None:
            st.warning(S("budget_over", share=ltr(f"{budget.crossed:.0%}")))
        st.caption(
            S("budget_note", marks=marks)
            + " "
            + S("budget_fake_free" if not chat.live else "budget_live_charged")
        )


def _chat_page() -> None:
    _init()
    _sidebar()
    st.title(S("chat_title"))
    st.caption(S("chat_subtitle"))
    _banner()
    left, right = st.columns([3, 2], gap="large")
    with left:
        _chat_column()
    with right:
        _cost_panel()


# --- shell: theme, language, header (UI spec Stage 2) ----------------------------


def _ui_state() -> tuple[str, str]:
    """Theme and language from the session, else the URL, else dark and fa
    (UI-T03); written back to the URL so a reload keeps them."""
    s = _s()
    current = None if "ui_dark" not in s else ("dark" if s.ui_dark else "light")
    theme, lang = ui_state(
        st.query_params.to_dict(), theme=current, lang=s.get("ui_lang")
    )
    s.ui_theme, s.ui_dark, s.ui_lang = theme, theme == "dark", lang
    s.ui_text = translator(load_strings(), lang)
    st.query_params["theme"], st.query_params["lang"] = theme, lang
    return theme, lang


def _header(pages: list, current) -> None:
    """Two rows, full width (images 3 and 4): brand | language, mode, budget,
    theme, local demo; then the tabs with a line icon, active = filled pill."""
    s = _s()
    chat: ChatSession | None = s.get("chat")
    live = bool(chat and chat.live)
    with st.container(key="mx-header", gap=None):
        with st.container(
            key="mx-header-row1",
            horizontal=True,
            horizontal_alignment="distribute",
            vertical_alignment="center",
        ):
            st.html(header_brand_html(s.ui_text), width="content")
            with st.container(
                key="mx-header-tools",
                horizontal=True,
                vertical_alignment="center",
                width="content",
            ):
                st.segmented_control(
                    S("language"),
                    LANGUAGES,
                    format_func=LANGUAGE_SHORT.get,
                    required=True,
                    key="ui_lang",
                    label_visibility="collapsed",
                )
                st.html(
                    chip_html(
                        S("mode_live" if live else "mode_fake"),
                        kind="live" if live else "fake",
                    ),
                    width="content",
                )
                st.html(
                    budget_html(
                        s.ui_text, live=live, budget=budget_view(chat) if live else None
                    ),
                    width="content",
                )
                st.toggle(
                    S("theme_dark"),
                    key="ui_dark",
                    label_visibility="collapsed",
                    help=S("theme_help"),
                )
                st.html(chip_html(S("local_demo"), icon="computer"), width="content")
        with st.container(
            key="mx-header-row2", horizontal=True, vertical_alignment="center"
        ):
            query = {"theme": s.ui_theme, "lang": s.ui_lang}
            for name, page, icon in pages:
                active = page.url_path == current.url_path
                key = f"mxtab-active-{name}" if active else f"mxtab-{name}"
                with st.container(key=key, width="content"):
                    st.page_link(
                        page, label=S(f"nav_{name}"), icon=icon, query_params=query
                    )


def main() -> None:
    st.set_page_config(
        page_title="Metis-Auto prototype",
        page_icon=":material/savings:",
        layout="wide",
    )
    theme, lang = _ui_state()
    st.html(page_css(load_theme(theme), lang))  # first element (UI-T04)
    pages = [
        (
            "chat",
            st.Page(_chat_page, title=S("nav_chat"), url_path="chat", default=True),
            ":material/chat:",
        ),
        (
            "results",
            st.Page(RESULTS_PAGE, title=S("nav_results"), url_path="results"),
            ":material/bar_chart:",
        ),
    ]
    current = st.navigation([p for _, p, _ in pages], position="hidden")
    _header(pages, current)
    current.run()


def _launch() -> int:
    """Plain ``python scripts/demo_ui.py``: run Streamlit on this file."""
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(Path(__file__).resolve()),
        *STREAMLIT_OPTIONS,
        *sys.argv[1:],
    ]
    return subprocess.call(command, cwd=Path(__file__).resolve().parents[1])


if __name__ == "__main__":
    if get_script_run_ctx(suppress_warning=True) is None:
        sys.exit(_launch())
    main()
