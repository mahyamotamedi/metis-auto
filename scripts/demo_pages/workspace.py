"""The demo's entry screen, optimisation settings and chat workspaces (UI spec
Stage 3: UI-S01, UI-S04, UI-S05, UI-S06) as one page file.

A thin page over ``metis_auto.wiring.demo_workspace`` (the router, one
``ChatSession`` per journey and bot, the three switches), ``wiring.savings_panel``
(the existing cost calculations plus the session charts) and ``wiring.demo_ui``
(the per-message view model): every decision, label, number and colour comes
from wiring or config (spec UI-R02); this file lays them out and maps widgets to
wiring calls. The session holds one ``DemoWorkspace`` (created by
``scripts/demo_ui.py``, which also draws the header and the style sheet).

- Entry (S01): a gradient headline and two journey cards, one gradient CTA each.
- Settings (S04): three cards (cache, context optimisation, routing), one
  gradient CTA "Start chatting".
- Workspace (S05, S06): sidebar with the bot list (chatbot journey), the
  conversations, the three switches and an Advanced block (the former sidebar
  settings, kept); the chat; the savings panel beside it (UI-L04), stacked below
  inside an expander on narrow screens (UI-L05).

Streamlit and Altair are imported only here, in ``scripts/demo_ui.py`` and in
``scripts/demo_pages/results.py`` (tested). Makes no model call of its own: a
message goes through ``DemoWorkspace.ask``.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from metis_auto.wiring.chat import (
    ROUTER_MODES,
    CompressionMode,
    RoutingMode,
    TurnReport,
)
from metis_auto.wiring.demo_ui import (
    CostView,
    blocked_banner,
    budget_view,
    detail_sections,
    friendly_failure,
    live_banner,
    live_check,
    routing_kind,
    routing_kind_text,
    served_text,
    term_text,
    text_direction,
)
from metis_auto.wiring.demo_workspace import (
    ChatWorkspace,
    DemoWorkspace,
    Journey,
    Screen,
    banner_for,
    entry_cards,
    setting_cards,
)
from metis_auto.wiring.savings_panel import Charts, PanelView, panel_view
from metis_auto.wiring.ui_config import (
    DEFAULT_LANGUAGE,
    load_strings,
    load_theme,
    translator,
)
from metis_auto.wiring.ui_format import fmt
from metis_auto.wiring.ui_style import (
    altair_config,
    axis_format,
    banner_text_html,
    bar_layout,
    bot_facts_html,
    card_title_html,
    chip_html,
    empty_state_html,
    entry_card_html,
    entry_hero_html,
    facts_html,
    kind_rows,
    kind_scale,
    legend_html,
    ltr,
    md_safe,
    series_scale,
    setting_text_html,
    side_title_html,
    workspace_title_html,
)

FAKE, LIVE = "Fake (free, no key)", "Live (real models, budgeted)"
MODE_KEYS = {FAKE: "mode_fake_option", LIVE: "mode_live_option"}
METHODS = (RoutingMode.STICKY_V1, RoutingMode.PER_REQUEST, RoutingMode.DECISION_ROUTER)
CHAT_BOX_HEIGHT = 430
CHART_HEIGHT = 170


def _s():
    return st.session_state


def S(key: str, **fields: object) -> str:
    """One string from config/demo/ui_strings.toml in the session's language."""
    t = _s().get("ui_text") or translator(load_strings(), DEFAULT_LANGUAGE)
    return t(key, **fields)


def _ws() -> DemoWorkspace:
    return _s().workspace


def _notice(level: str, text: str) -> None:
    _s().notice = (level, text)


def _injected(name: str):
    """Test hooks (offline tests set these before the first run)."""
    return _s().get(f"_test_{name}")


def _loader():
    from metis_auto.settings import load_settings

    return _injected("settings_loader") or (lambda o: load_settings(overrides=o))


def _usd(value, currency: str = "USD") -> str:
    """An amount through the one formatter, LTR-isolated (UI-V07)."""
    return ltr(fmt(value, "money", currency=currency, unknown=S("not_computed")))


# --- callbacks (run before the page is drawn) ---------------------------------------


def _choose(journey: Journey) -> None:
    _ws().choose_journey(journey)


def _on_switch(name: str) -> None:
    chat = _ws().current()
    value = bool(_s()[f"sw_{name}"])
    setter = {
        "cache": chat.set_cache,
        "context": chat.set_context,
        "routing": chat.set_routing,
    }[name]
    error = setter(value)
    if error:
        _notice("error", S("notice_setting_failed", error=error))


def _on_model() -> None:
    error = _ws().current().set_preferred_model(_s().preferred_model)
    if error:
        _notice("error", S("notice_setting_failed", error=error))


def _on_method() -> None:
    error = _ws().current().set_routing_method(RoutingMode(_s().routing_method))
    if error:
        _notice("error", S("notice_setting_failed", error=error))


def _on_router_mode() -> None:
    error = _ws().current().set_router_mode(_s().router_mode)
    if error:
        _notice("error", S("notice_setting_failed", error=error))


def _on_compression() -> None:
    error = _ws().current().set_compression_mode(CompressionMode(_s().compression))
    if error:
        _notice("error", S("notice_setting_failed", error=error))


def _on_other(change, key: str) -> None:
    error = _ws().current().apply(lambda session: change(session, _s()[key]))
    if error:
        _notice("error", S("notice_setting_failed", error=error))


def _on_mode() -> None:
    s, ws = _s(), _ws()
    live = s.mode == LIVE
    if live:
        allowed, reasons = live_check(_loader())
        if not allowed:
            s.mode, s.blocked = FAKE, "; ".join(reasons)
            return
    error = ws.set_live(live)
    if error:
        s.mode, s.blocked = FAKE, error
        return
    s.blocked = None
    _notice(
        "info",
        S(
            "notice_new_run",
            mode=S("mode_live" if live else "mode_fake"),
            run=ltr(ws.header_session().run_id),
        ),
    )


def _on_new_user() -> None:
    chat = _ws().current()
    chat.new_user()
    _notice("info", S("notice_new_user", n=ltr(chat.session.users)))


def _on_reset() -> None:
    _ws().current().reset_conversation()
    _notice("info", S("notice_reset"))


def _on_degrade() -> None:
    error = _ws().current().apply(lambda session: session.degrade_next())
    _notice("error" if error else "info", error or S("notice_degrade"))


def _open_settings() -> None:
    _ws().open_settings()
    _notice("info", S("set_focus_note"))


# --- one turn ------------------------------------------------------------------------


def _send(message: str) -> None:
    with st.spinner(S("spinner_answering")):
        _ws().ask(message)


# --- entry screen (UI-S01) -----------------------------------------------------------


def entry() -> None:
    t = _s().ui_text
    with st.container(key="mx-entry-hero"):
        st.html(entry_hero_html(t))
        cols = st.columns(2, gap="medium")
        for col, card in zip(cols, entry_cards(t), strict=True):
            with col, st.container(key=f"mx-entry-card-{card.journey.value}"):
                st.html(entry_card_html(card.icon, card.title, card.text))
                st.button(
                    card.cta,
                    key=f"mx-cta-entry-{card.journey.value}",
                    on_click=_choose,
                    args=(card.journey,),
                )


# --- bot list and settings cards


def _bot_list() -> None:
    ws = _ws()
    st.caption(S("ws_bots_note"))
    for card in ws.bot_cards(_s().ui_text):
        st.button(
            card.label,
            key=f"mx-bot-{card.key}",
            on_click=ws.select_bot,
            args=(card.key,),
            type="primary" if card.selected else "secondary",
            width="stretch",
        )
        st.html(bot_facts_html(card.facts))


def _switch(card, *, show_label: bool = False) -> None:
    key = f"sw_{card.key}"
    _s()[key] = card.on  # the real session's state, every run (UI-SB01)
    st.toggle(
        card.name,
        key=key,
        on_change=_on_switch,
        args=(card.key,),
        disabled=not card.enabled,
        help=card.text,
        label_visibility="visible" if show_label else "collapsed",
    )


def settings() -> None:
    ws = _ws()
    t = _s().ui_text
    chat = ws.current()
    with st.sidebar:
        st.html(side_title_html(S("ws_bots")))
        _bot_list()
    st.button(S("set_back"), key="set_back", on_click=ws.go_entry, type="tertiary")
    st.title(S("set_title"))
    st.caption(S("set_for_bot", bot=ltr(chat.title(t))))
    available = ws.context_available(t)
    for card in setting_cards(chat, t, context_available=available):
        with st.container(key=f"mx-card-set-{card.key}"):
            text_col, side_col = st.columns([5, 1], vertical_alignment="center")
            with text_col:
                st.html(
                    setting_text_html(
                        card.name, card.text, card.caption, card.disabled_reason
                    )
                )
            with side_col, st.container(key=f"mx-set-side-{card.key}"):
                _switch(card)
                st.html(chip_html(card.chip, kind="on" if card.on else "off"))
    st.caption(S("set_caption"))
    st.button(S("set_start"), key="mx-cta-start", on_click=ws.start_chatting)


# --- workspace sidebar


def _sidebar(chat: ChatWorkspace, banner) -> None:
    ws = _ws()
    t = _s().ui_text
    direct = chat.journey == Journey.DIRECT
    with st.sidebar:
        if not direct:
            st.html(side_title_html(S("ws_bots")))
            _bot_list()
        st.button(
            S("ws_new_chat" if direct else "ws_new_conversation"),
            key="new_conversation",
            on_click=ws.new_conversation,
            width="stretch",
        )
        st.html(side_title_html(S("ws_conversations")))
        for number, title, current in chat.listing(t):
            st.button(
                title,
                key=f"mx-conv-{'current-' if current else ''}{number}",
                on_click=ws.open_conversation,
                args=(number,),
                type="tertiary",
            )
        st.caption(S("ws_conversations_note"))
        st.html(side_title_html(S("set_header")))
        key = "mx-settings-focus" if ws.settings_focus else "mx-settings"
        with st.container(key=key):
            for card in setting_cards(
                chat, t, context_available=ws.context_available(t)
            ):
                _switch(card, show_label=True)
                if card.disabled_reason:
                    st.caption(card.disabled_reason)
            if direct:
                _model_selector(chat)
        _advanced(chat, banner)


def _model_selector(chat: ChatWorkspace) -> None:
    selector = chat.model_selector(_s().ui_text)
    _s().preferred_model = selector.value
    st.selectbox(
        selector.label,
        list(selector.options),
        key="preferred_model",
        on_change=_on_model,
        disabled=selector.disabled,
    )
    if selector.caption:
        st.caption(selector.caption)


def _advanced(chat: ChatWorkspace, banner) -> None:
    """The former sidebar settings (fake or live, routing method, demo cache
    seed, compression variants, DeepSeek thinking, new user, reset): kept
    (UI-R03), out of the way."""
    s, ws = _s(), _ws()
    t = s.ui_text
    session = chat.session
    with st.expander(S("set_advanced")):
        s.mode = LIVE if ws.live else FAKE
        st.radio(
            S("mode"),
            [FAKE, LIVE],
            key="mode",
            format_func=lambda v: t(MODE_KEYS[v]),
            on_change=_on_mode,
        )
        if banner.state == "off":
            st.caption(f"**{banner.title}.** {banner.detail}")
        s.routing_method = chat.routing_method.value
        st.radio(
            S("set_routing_method"),
            [m.value for m in METHODS],
            key="routing_method",
            format_func=lambda v: t(f"routing_{v}"),
            on_change=_on_method,
            help=S("routing_help"),
        )
        if chat.routing_method == RoutingMode.DECISION_ROUTER:
            s.router_mode = session.router_mode
            st.selectbox(
                S("decision_backends"),
                list(ROUTER_MODES),
                key="router_mode",
                format_func=lambda v: t(f"router_{v}"),
                on_change=_on_router_mode,
                help=S("decision_backends_help"),
            )
        if chat.journey != Journey.DIRECT:
            _model_selector(chat)
        s.compression = session.compression.value
        st.radio(
            S("compression"),
            [m.value for m in CompressionMode],
            key="compression",
            format_func=lambda v: t(f"compression_{v}"),
            on_change=_on_compression,
            horizontal=True,
        )
        if session.compression == CompressionMode.LLMLINGUA2:
            st.warning(S("llmlingua_warning"), icon=":material/warning:")
        elif session.compression == CompressionMode.FAKE:
            st.caption(S("compression_fake_note"))
        s.seed = session.seed
        st.toggle(
            S("demo_seed"),
            key="seed",
            on_change=_on_other,
            args=(lambda session, v: session.set_seed(v), "seed"),
            help=S("demo_seed_help"),
        )
        s.thinking = session.deepseek_thinking
        st.toggle(
            S("thinking"),
            key="thinking",
            on_change=_on_other,
            args=(lambda session, v: session.set_deepseek_thinking(v), "thinking"),
            help=S("thinking_help"),
        )
        c1, c2 = st.columns(2)
        c1.button(S("new_user"), key="new_user", on_click=_on_new_user, width="stretch")
        c2.button(
            S("reset_conversation"), key="reset", on_click=_on_reset, width="stretch"
        )
        if not session.live:
            st.button(S("cut_off_next"), on_click=_on_degrade, width="stretch")
        if s.seed and session.seeded:
            with st.expander(S("seeded_questions")):
                st.caption(S("seeded_note"))
                for n, question in enumerate(session.seeded):
                    if st.button(question, key=f"seedq_{n}"):
                        _send(question)
        st.caption(S("run_footer", run=ltr(session.run_id), user=ltr(session.users)))


# --- banners


def _live_state(chat: ChatWorkspace):
    """The fake/live banner's state for this run (UI-R03, UI-D13)."""
    s = _s()
    session = chat.session
    if s.get("blocked"):
        return blocked_banner(s.blocked, t=s.ui_text)
    allowed, reasons = (True, ()) if session.live else live_check(_loader())
    return live_banner(
        live=session.live,
        allowed=allowed,
        reasons=reasons,
        stopped=session.pipeline.live_stopped,
        t=s.ui_text,
    )


def _live_banner(banner) -> None:
    """Live ON, blocked and stopped stay prominent above the chat; the calm
    fake state is the header chip, with its reason under Advanced."""
    if banner.state == "off":
        return
    show = {"on": st.warning, "blocked": st.error, "stopped": st.error}[banner.state]
    show(f"**{banner.title}.** {banner.detail}")


def _notice_once() -> None:
    s = _s()
    if s.get("notice"):
        level, text = s.notice
        {"info": st.toast, "error": st.error}[level](text)
        s.notice = None


def _direct_banner() -> None:
    """UI-B04: the cost-saving banner of the direct chat, dismissible, with a
    link to the settings in the sidebar."""
    ws = _ws()
    banner = banner_for(ws, _s().ui_text)
    if banner is None:
        return
    with st.container(key="mx-banner"):
        st.html(banner_text_html(banner.text))
        with st.container(key="mx-banner-row", horizontal=True):
            st.button(
                banner.link,
                key="banner_settings",
                on_click=_open_settings,
                type="tertiary",
                icon=":material/tune:",
            )
            st.button(
                banner.dismiss,
                key="banner_dismiss",
                on_click=ws.dismiss_banner,
                type="tertiary",
                icon=":material/close:",
            )


# --- chat


def _message(i: int, message: dict) -> None:
    t = _s().ui_text
    role, text = message["role"], message["text"]
    with st.chat_message(role):
        with st.container(key=f"{text_direction(text)}-m{i}"):
            st.markdown(text or S("no_answer"))
        report: TurnReport | None = message.get("report")
        if report is None:
            return
        failure = friendly_failure(report, t=t)
        if failure:
            st.warning(failure)
        view = _cost_view(report)
        parts = [
            f"**{routing_kind_text(routing_kind(report), t)}**",
            S("served_by", by=served_text(report.served_by, t)),
            f"`{ltr(report.model_id or '-')}`",
        ]
        if view is not None and view.paid is not None:
            saved = (
                S("badge_less", share=ltr(fmt(view.saved_fraction, "percent")))
                if view.saved_fraction is not None
                else ""
            )
            parts.append(
                S(
                    "badge_paid",
                    paid=_usd(view.paid, view.currency),
                    premium=_usd(view.premium, view.currency),
                    saved=saved,
                )
            )
        with st.container(key=f"badge-{i}"):
            st.markdown(md_safe(" · ".join(parts)))
        with st.expander(S("details")):
            for title, rows in detail_sections(report, t=t):
                st.markdown(f"**{title}**")
                st.table(pd.DataFrame(rows, columns=["", S("col_value")]).set_index(""))


def _cost_view(report: TurnReport) -> CostView | None:
    from metis_auto.wiring.demo_ui import cost_view

    return cost_view(report.parts)


def _chat_column(chat: ChatWorkspace) -> None:
    box = st.container(height=CHAT_BOX_HEIGHT, border=False, key="mx-chat-box")
    with box:
        if not chat.messages:
            line = (
                "ws_chat_empty_direct" if chat.profile is None else "ws_chat_empty_bot"
            )
            st.html(empty_state_html("forum", S(line)))
        for i, message in enumerate(chat.messages):
            _message(i, message)
    if chat.profile is not None and chat.profile.suggested:
        picked = st.pills(
            S("try_synthetic"),
            chat.profile.suggested,
            key=f"try_{len(chat.messages)}",
            label_visibility="collapsed",
        )
        if picked:
            _send(picked)
            st.rerun()
    prompt = st.chat_input(S("chat_placeholder"))
    if prompt:
        _send(prompt)
        st.rerun()


def workspace() -> None:
    ws = _ws()
    t = _s().ui_text
    chat = ws.current()
    banner = _live_state(chat)
    _sidebar(chat, banner)
    with st.container(key="mx-ws-head", horizontal=True, vertical_alignment="center"):
        st.html(workspace_title_html(chat.title(t)), width="content")
        st.html(chip_html(chat.status_line(t), icon="route"), width="content")
    _live_banner(banner)
    _notice_once()
    _direct_banner()
    left, right = st.columns([3, 2], gap="large")
    with left:
        _chat_column(chat)
    with right:
        _panel(chat)


# --- savings panel (UI-L04, UI-D01..D13, UI-G01..G04)


def _chart(chart: alt.TopLevelMixin) -> None:
    """Every chart gets the theme's Altair config (UI-G05, UI-G06)."""
    s = _s()
    config = altair_config(load_theme(s.ui_theme), s.ui_lang)
    st.altair_chart(chart.configure(**config), width="stretch", theme=None)


def _waterfall(view: CostView, rows: list[dict]) -> None:
    if not rows:
        st.html(empty_state_html("bar_chart", S("nothing_computed")))
        return
    s = _s()
    t = s.ui_text
    domain, colours = kind_scale(load_theme(s.ui_theme), t)
    data = pd.DataFrame(kind_rows(rows, t))
    data["term"] = [term_text(term, t) for term in data["term"]]
    data["text"] = [
        fmt(v, "money", currency=view.currency, signed=k != "total")
        for v, k in zip(data["amount"], data["kind"], strict=True)
    ]
    layout = bar_layout(s.ui_lang)
    bars = (
        alt.Chart(data)
        .mark_bar(cornerRadius=3, height=16)
        .encode(
            y=alt.Y(
                "term:N",
                sort=list(data["term"]),
                title=None,
                axis=alt.Axis(labelOverlap=False, orient=layout["y_orient"]),
            ),
            x=alt.X(
                "start:Q",
                title=view.currency,
                axis=alt.Axis(format=axis_format("money")),
                scale=alt.Scale(reverse=layout["x_reverse"]),
            ),
            x2="end:Q",
            color=alt.Color(
                "kind_label:N",
                scale=alt.Scale(domain=domain, range=colours),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("term:N", title=S("col_term")),
                alt.Tooltip("text:N", title=view.currency),
            ],
        )
    )
    _chart(bars.properties(height=alt.Step(26)))
    present = set(data["kind_label"])
    st.html(
        legend_html(
            [(k, c) for k, c in zip(domain, colours, strict=True) if k in present]
        )
    )


def _cost_tab(
    view: CostView | None, rows: list[dict], scope: str, p: PanelView
) -> None:
    if view is None:
        st.html(empty_state_html("receipt_long", S("no_answer_yet", scope=scope)))
        return
    cards = (
        (p.actual_label, _usd(view.paid, view.currency)),
        (p.premium_label, _usd(view.premium, view.currency)),
        (S("saved"), ltr(fmt(view.saved_fraction, "percent", unknown="-"))),
    )
    with st.container(key=f"mx-row-cost-{scope}", horizontal=True):
        for n, (label, value) in enumerate(cards):
            with st.container(key=f"mx-kpi-cost-{scope}-{n}"):
                st.metric(label, value)
    _waterfall(view, rows)


def _facts(p: PanelView) -> None:
    f = p.facts
    if f is None:
        return
    rows = [
        (S("ws_fact_selected"), f.model_selected),
        (S("ws_fact_used"), f.model_used),
        (S("ws_fact_input"), ltr(f.input_tokens)),
        (S("ws_fact_output"), ltr(f.output_tokens)),
        (S("ws_fact_latency"), f.latency),
    ]
    chips = [
        (f"{S(label)}: {S('ws_applied' if on else 'ws_not_applied')}", on)
        for label, on in (
            ("ws_chip_cache", f.cache_applied),
            ("ws_chip_context", f.context_applied),
            ("ws_chip_routing", f.routing_applied),
        )
    ]
    st.html(card_title_html(S("ws_facts_title")))
    st.html(facts_html(rows, chips))


def _no_chart(line: str = "ws_chart_empty") -> None:
    st.html(empty_state_html("bar_chart", S(line)))


def _axes(kind: str):
    return alt.X("n:O", title=S("ws_axis_message"), axis=alt.Axis(labelAngle=0))


def _trend_chart(rows) -> None:
    s = _s()
    c = load_theme(s.ui_theme).chart
    data = pd.DataFrame(rows)
    series = list(dict.fromkeys(data["series"]))
    colours = [c["trend"], c["series_a"]][: len(series)]
    scale = alt.Scale(domain=series, range=colours)
    base = alt.Chart(data).encode(
        x=_axes("n"),
        y=alt.Y(
            "value:Q",
            title=S("ws_axis_cost"),
            axis=alt.Axis(format=axis_format("money")),
        ),
        tooltip=[
            alt.Tooltip("series:N", title=""),
            alt.Tooltip("n:O", title=S("ws_axis_message")),
            alt.Tooltip(
                "value:Q", title=S("ws_axis_cost"), format=axis_format("money")
            ),
        ],
    )
    line = base.mark_line(point=True, strokeWidth=2).encode(
        color=alt.Color("series:N", scale=scale, legend=None),
        strokeDash=alt.StrokeDash(
            "series:N",
            scale=alt.Scale(domain=series, range=[[1, 0], [5, 4]][: len(series)]),
            legend=None,
        ),
    )
    area = (
        alt.Chart(data[data["series"] == series[0]])
        .mark_area(color=c["trend_fill"], opacity=0.9)
        .encode(x=_axes("n"), y=alt.Y("value:Q"))
    )
    _chart((area + line).properties(height=CHART_HEIGHT))
    st.html(legend_html(list(zip(series, colours, strict=True))))


def _stacked_chart(
    rows, field: str, group: str, title: str, colours: list[str], domain: list[str]
) -> None:
    data = pd.DataFrame(rows)
    chart = (
        alt.Chart(data)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=_axes("n"),
            y=alt.Y(
                f"{field}:Q",
                title=title,
                axis=alt.Axis(
                    format=axis_format("money" if field == "cost" else "count")
                ),
            ),
            color=alt.Color(
                f"{group}:N", scale=alt.Scale(domain=domain, range=colours), legend=None
            ),
            tooltip=[
                alt.Tooltip(f"{group}:N", title=""),
                alt.Tooltip("n:O", title=S("ws_axis_message")),
                alt.Tooltip(
                    f"{field}:Q",
                    title=title,
                    format=axis_format("money" if field == "cost" else "count"),
                ),
            ],
        )
        .properties(height=CHART_HEIGHT)
    )
    _chart(chart)
    st.html(legend_html(list(zip(domain, colours, strict=True))))


def _tokens_chart(rows) -> None:
    c = load_theme(_s().ui_theme).chart
    domain = [S("ws_series_input"), S("ws_series_output")]
    _stacked_chart(
        rows,
        "tokens",
        "series",
        S("ws_axis_tokens"),
        [c["series_a"], c["series_b"]],
        domain,
    )


def _by_model_chart(rows) -> None:
    models = list(dict.fromkeys(r["model"] for r in rows))
    domain, colours = series_scale(load_theme(_s().ui_theme), models)
    _stacked_chart(rows, "cost", "model", S("ws_axis_cost"), colours, domain)


def _donut_chart(rows) -> None:
    s = _s()
    theme = load_theme(s.ui_theme)
    data = pd.DataFrame(rows)
    domain, colours = series_scale(theme, list(data["term"]))
    chart = (
        alt.Chart(data)
        .mark_arc(innerRadius=46, stroke=theme.colours["surface"], strokeWidth=2)
        .encode(
            theta=alt.Theta("amount:Q"),
            color=alt.Color(
                "term:N", scale=alt.Scale(domain=domain, range=colours), legend=None
            ),
            tooltip=[
                alt.Tooltip("term:N", title=S("col_term")),
                alt.Tooltip(
                    "amount:Q", title=S("ws_axis_cost"), format=axis_format("money")
                ),
            ],
        )
        .properties(height=CHART_HEIGHT)
    )
    _chart(chart)
    st.html(legend_html(list(zip(domain, colours, strict=True))))


def _charts(charts: Charts) -> None:
    sections = (
        (
            "trend",
            "ws_chart_cost_trend",
            charts.cost_trend,
            _trend_chart,
            "ws_chart_empty",
        ),
        ("tokens", "ws_chart_tokens", charts.tokens, _tokens_chart, "ws_chart_empty"),
        (
            "model",
            "ws_chart_by_model",
            charts.by_model,
            _by_model_chart,
            "ws_chart_empty",
        ),
        (
            "breakdown",
            "ws_chart_breakdown",
            charts.breakdown,
            _donut_chart,
            "ws_chart_breakdown_none",
        ),
    )
    for key, title, rows, draw, empty in sections:
        with st.container(key=f"mx-card-chart-{key}"):
            st.html(card_title_html(S(title)))
            if rows:
                draw(rows)
            else:
                _no_chart(empty)


def _budget(chat: ChatWorkspace) -> None:
    session = chat.session
    with st.container(key="mx-card-budget"):
        st.html(card_title_html(S("budget")))
        budget = budget_view(session)
        if budget is None:
            st.html(empty_state_html("account_balance_wallet", S("budget_none")))
            return
        st.progress(
            min(budget.lifetime_fraction, 1.0),
            text=md_safe(
                S(
                    "budget_lifetime",
                    spent=_usd(budget.lifetime_spent, budget.currency),
                    cap=_usd(budget.lifetime_cap, budget.currency),
                    share=ltr(fmt(budget.lifetime_fraction, "percent")),
                )
            ),
        )
        if budget.run_cap is not None:
            st.progress(
                min(budget.run_fraction or 0.0, 1.0),
                text=md_safe(
                    S(
                        "budget_run",
                        spent=_usd(budget.run_spent, budget.currency),
                        cap=_usd(budget.run_cap, budget.currency),
                    )
                ),
            )
        marks = " / ".join(ltr(fmt(w, "percent")) for w in budget.warn_at)
        if budget.crossed is not None and budget.crossed >= max(budget.warn_at):
            st.error(S("budget_over_tell", share=ltr(fmt(budget.crossed, "percent"))))
        elif budget.crossed is not None:
            st.warning(S("budget_over", share=ltr(fmt(budget.crossed, "percent"))))
        st.caption(
            S("budget_note", marks=marks)
            + " "
            + S("budget_fake_free" if not session.live else "budget_live_charged")
        )


def _panel(chat: ChatWorkspace) -> None:
    s = _s()
    p = panel_view(chat, s.ui_text)
    with st.container(key="mx-panel"):
        with st.expander(p.title, expanded=True):
            with st.container(key="mx-card-cost"):
                st.html(card_title_html(S("ws_panel_title")))
                if p.empty:
                    st.html(empty_state_html("savings", S("ws_panel_empty")))
                else:
                    tab1, tab2 = st.tabs([S("tab_message"), S("tab_session")])
                    with tab1:
                        _cost_tab(p.message, p.waterfall_message, S("scope_message"), p)
                    with tab2:
                        _cost_tab(p.session, p.waterfall_session, S("scope_session"), p)
                        if p.session is not None:
                            st.caption(
                                S(
                                    "session_counts",
                                    messages=ltr(p.session.messages),
                                    hits=ltr(p.session.cache_hits),
                                )
                            )
                    _facts(p)
                    with st.expander(S("details")):
                        _decomposition(p)
                st.caption(S("ws_est_note"))
                st.caption(f"{S('premium_caveat')} {S('demo_caveat')}")
            _charts(p.charts)
            _budget(chat)


def _decomposition(p: PanelView) -> None:
    m, ses = p.message, p.session
    view = m or ses
    if view is None:
        return
    m_terms = dict(m.terms) if m else {}
    s_terms = dict(ses.terms) if ses else {}
    t = _s().ui_text
    rows = [
        {
            S("col_term"): term_text(label, t),
            S("col_message"): _usd(m_terms.get(label), view.currency),
            S("col_session"): _usd(s_terms.get(label), view.currency),
        }
        for label, _ in view.terms
    ]
    st.table(pd.DataFrame(rows).set_index(S("col_term")))
    st.caption(S("decomposition_note"))


# --- the Chat page: the router (UI-S01, S04..S06)


def render() -> None:
    """The Chat page: the screen the workspace is on."""
    ws = _ws()
    if ws.consume_query(st.query_params.to_dict()):
        del st.query_params["screen"]
    screen = ws.screen if ws.journey != Journey.NONE else Screen.ENTRY
    {Screen.ENTRY: entry, Screen.SETTINGS: settings, Screen.CHAT: workspace}[screen]()
