"""The Metis-Auto demo UI in the browser (Demo milestone B; brief §10).

    .venv/bin/python scripts/demo_ui.py            # opens http://localhost:8501

A thin Streamlit page over ``metis_auto.wiring.chat.ChatSession`` (the same
backend as ``scripts/chat.py``) and ``metis_auto.wiring.demo_ui`` (the view
model). No routing, caching, or accounting logic here: the page holds the
history and sends it every turn (P-8), shows each ``TurnReport``, and maps the
widgets to the session's toggles.

- Main area: the chat (Persian right-to-left, English left-to-right), the
  live-call banner, and per-message details.
- Sidebar: bot setup (instructions, one retrieved document per block,
  SYNTHETIC presets) and settings (fake or live, routing mode, the DEMO cache
  settings, EXPERIMENTAL compression, DeepSeek thinking, new user, reset).
- Right: the cost panel (paid vs the premium estimate, the savings
  decomposition, the budget).

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
    DEMO_CAVEAT,
    PREMIUM_CAVEATS,
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

STREAMLIT_OPTIONS = (
    "--browser.gatherUsageStats=false",
    "--server.address=localhost",
    "--client.toolbarMode=minimal",
    "--server.fileWatcherType=none",
)
FAKE, LIVE = "Fake (free, no key)", "Live (real models, budgeted)"
ROUTING_LABELS = {
    RoutingMode.STICKY_V1.value: "Sticky v1",
    RoutingMode.PER_REQUEST.value: "Per request",
    RoutingMode.FIXED.value: "Fixed model",
}
COMPRESSION_LABELS = {
    CompressionMode.OFF.value: "Off",
    CompressionMode.FAKE.value: "Fake (mechanics only)",
    CompressionMode.LLMLINGUA2.value: "LLMLingua-2",
}
# Data-viz palette slots 1-3 (validated all-pairs): totals, savings, extra cost.
KIND_COLOURS = {"total": "#2a78d6", "saving": "#1baf7a", "extra cost": "#eb6834"}

CSS = """
<style>
[class*="st-key-rtl-"] { direction: rtl; text-align: right; width: 100%; }
[class*="st-key-rtl-"] > div { width: 100%; }
[class*="st-key-rtl-"] pre, [class*="st-key-rtl-"] code {
  direction: ltr; text-align: left; unicode-bidi: isolate; }
[class*="st-key-rtl-"] p, [class*="st-key-rtl-"] li {
  font-family: "Vazirmatn", "Tahoma", "Geeza Pro", system-ui, sans-serif;
  line-height: 1.9; }
[class*="st-key-badge-"] p { font-size: 0.82rem; opacity: 0.85; margin: 0; }
.block-container { padding-top: 2.2rem; padding-bottom: 1rem; }
[data-testid="stMetricValue"] { font-size: 1.35rem; }
h1 { font-size: 1.9rem !important; padding-bottom: 0 !important; }
</style>
"""

# --- session state -------------------------------------------------------


def _s():
    return st.session_state


def _injected(name: str):
    """Test hooks (offline tests set these before the first run)."""
    return _s().get(f"_test_{name}")


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
        f"New {'LIVE' if live else 'fake'} run {chat.run_id}: conversation cleared.",
    )


def _apply(key: str, change, current) -> None:
    """Apply one toggle to the session; on failure restore the widget."""
    s = _s()
    try:
        change(s[key])
    except Exception as exc:  # noqa: BLE001 - shown to the presenter
        s[key] = current
        _notice("error", f"Could not change that setting: {exc}")


def _on_routing() -> None:
    s = _s()
    chat: ChatSession = s.chat

    def change(value: str) -> None:
        if value == RoutingMode.FIXED.value:
            chat.switch_model(s.fixed_model)
        else:
            chat.set_routing(RoutingMode(value))

    _apply("routing", change, chat.routing.value)


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
    _notice(
        "info", f"User {s.chat.users} of the same bot: new conversation, same cache."
    )


def _on_reset() -> None:
    s = _s()
    s.chat.reset()
    s.messages = []
    _notice("info", "Conversation reset (the cache keeps its entries).")


def _on_degrade() -> None:
    _s().chat.degrade_next()
    _notice(
        "info",
        "The next model answer comes back cut off (fake mode): watch it escalate.",
    )


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
    _notice("info", f"Loaded the SYNTHETIC preset “{preset.title}”: new conversation.")


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
    with st.spinner("Routing and answering …"):
        response, report = chat.ask(message)
    s.messages.append({"role": "user", "text": message})
    s.messages.append(
        {"role": "assistant", "text": response.answer or "", "report": report}
    )


# --- drawing ---------------------------------------------------------------


def _sidebar() -> None:
    s = _s()
    chat: ChatSession = s.chat
    with st.sidebar:
        st.header("Bot setup")
        st.caption("Presets are SYNTHETIC: written for the demo, never sample data.")
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
        st.text_area("Instructions", key="instructions", height=160)
        st.markdown("**Retrieved context** (one document per block)")
        for n, doc_id in enumerate(s.doc_ids, 1):
            st.text_area(f"Document {n}", key=f"doc_{doc_id}", height=110)
            st.button(
                f"Remove document {n}",
                key=f"rm_{doc_id}",
                on_click=_remove_doc,
                args=(doc_id,),
            )
        c1, c2 = st.columns(2)
        c1.button("Add document", on_click=_add_doc, width="stretch")
        c2.button("Clear bot", on_click=_clear_bot, width="stretch")

        st.divider()
        st.header("Settings")
        st.radio("Mode", [FAKE, LIVE], key="mode", on_change=_on_mode)
        st.radio(
            "Routing",
            list(ROUTING_LABELS),
            key="routing",
            format_func=ROUTING_LABELS.get,
            on_change=_on_routing,
            horizontal=True,
            help="Sticky v1: the first real question anchors the conversation on a "
            "model; similar follow-ups stay, very different ones re-route. Per "
            "request: the rules on every message. Fixed: one model.",
        )
        if s.routing == RoutingMode.FIXED.value:
            models = [
                e.model_id for e in chat.loaded.reference.catalogue.entries if e.enabled
            ]
            st.selectbox("Model", models, key="fixed_model", on_change=_on_fixed_model)
        st.toggle(
            "Bot-level cache [DEMO]",
            key="bot_cache",
            on_change=_on_bot_cache,
            help="DEMO setting, not the serving default: users of the same bot "
            "(same instructions and documents) share cached answers. Try it with "
            "“New user”.",
        )
        st.toggle(
            "Demo seed [DEMO, local only]",
            key="seed",
            on_change=_on_seed,
            help="Answers a few first-turn SAMPLE questions from logged answers, "
            "locally; never sent to a provider. Needs the sample data on this "
            "computer.",
        )
        st.radio(
            "Compression [EXPERIMENTAL]",
            list(COMPRESSION_LABELS),
            key="compression",
            format_func=COMPRESSION_LABELS.get,
            on_change=_on_compression,
            horizontal=True,
        )
        if s.compression == CompressionMode.LLMLINGUA2.value:
            st.warning(
                "LLMLingua-2 is EXPERIMENTAL: slow on CPU (about 0.3 s per long "
                "text, seconds per message), quality unmeasured, and it drops the "
                "Persian half-space (ZWNJ). Instructions are never compressed.",
                icon="⚠️",
            )
        elif s.compression == CompressionMode.FAKE.value:
            st.caption("A labelled fake: shows the mechanics, measures nothing.")
        st.toggle(
            "DeepSeek thinking",
            key="thinking",
            on_change=_on_thinking,
            help="On is DeepSeek's default; off sends thinking disabled.",
        )
        c1, c2 = st.columns(2)
        c1.button(
            "New user (same bot)",
            key="new_user",
            on_click=_on_new_user,
            width="stretch",
        )
        c2.button(
            "Reset conversation",
            key="reset",
            on_click=_on_reset,
            width="stretch",
        )
        if not chat.live:
            with st.expander("More (fake mode)"):
                st.button(
                    "Cut off the next answer (escalation)",
                    on_click=_on_degrade,
                    width="stretch",
                )
        if s.seed and chat.seeded:
            with st.expander("Seeded questions (SAMPLE CONTENT, local only)"):
                st.caption(
                    "Logged sample questions: shown on this computer only. Don't "
                    "share screenshots of them or paste them anywhere."
                )
                for n, question in enumerate(chat.seeded):
                    if st.button(question, key=f"seedq_{n}"):
                        _send(question)
        st.caption(f"Run {chat.run_id} · user {chat.users}")


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
    show(f"**{banner.title}.** {banner.detail}")
    if s.notice:
        level, text = s.notice
        {"info": st.toast, "error": st.error}[level](text)
        s.notice = None


def _message(i: int, message: dict) -> None:
    role, text = message["role"], message["text"]
    with st.chat_message(role):
        with st.container(key=f"{text_direction(text)}-m{i}"):
            st.markdown(text or "*(no answer)*")
        report: TurnReport | None = message.get("report")
        if report is None:
            return
        failure = friendly_failure(report)
        if failure:
            st.warning(failure)
        view = cost_view(report.parts)
        parts = [
            f"**{routing_kind(report)}**",
            f"served by {report.served_by}",
            f"`{report.model_id or '-'}`",
        ]
        if view is not None and view.paid is not None:
            saved = (
                f", {view.saved_fraction:.0%} less"
                if view.saved_fraction is not None
                else ""
            )
            parts.append(
                f"paid {money(view.paid)} vs premium est. {money(view.premium)}{saved}"
            )
        with st.container(key=f"badge-{i}"):
            st.markdown(" · ".join(parts))
        with st.expander("Details"):
            for title, rows in detail_sections(report):
                st.markdown(f"**{title}**")
                st.table(pd.DataFrame(rows, columns=["", "value"]).set_index(""))


def _chat_column() -> None:
    s = _s()
    box = st.container(height=430, border=False)
    with box:
        if not s.messages:
            st.caption(
                "Pick a SYNTHETIC preset in the sidebar (or write your own bot), "
                "then say hello. Use only your own or synthetic messages."
            )
        for i, message in enumerate(s.messages):
            _message(i, message)
    preset = next((p for p in s.presets if p.key == s.preset_key), None)
    if preset and preset.suggested:
        picked = st.pills(
            "Try (SYNTHETIC)",
            preset.suggested,
            key=f"try_{len(s.messages)}",
            label_visibility="collapsed",
        )
        if picked:
            _send(picked)
            st.rerun()
    prompt = st.chat_input("Type a message …")
    if prompt:
        _send(prompt)
        st.rerun()


def _waterfall(view: CostView) -> None:
    rows = waterfall_rows(view)
    if not rows:
        st.caption("Nothing computed yet.")
        return
    data = pd.DataFrame(rows)
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
                "kind:N",
                scale=alt.Scale(
                    domain=list(KIND_COLOURS), range=list(KIND_COLOURS.values())
                ),
                legend=alt.Legend(orient="bottom", title=None),
            ),
            tooltip=[
                alt.Tooltip("term:N", title="term"),
                alt.Tooltip("label:N", title=view.currency),
            ],
        )
    )
    st.altair_chart(bars.properties(height=alt.Step(26)), width="stretch")


def _cost_tab(view: CostView | None, scope: str) -> None:
    if view is None:
        st.caption(f"No answered message yet ({scope}).")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Actually paid", money(view.paid, ""))
    c2.metric("Premium estimate", money(view.premium, ""))
    c3.metric(
        "Saved",
        f"{view.saved_fraction:.1%}" if view.saved_fraction is not None else "-",
    )
    _waterfall(view)


def _cost_panel() -> None:
    s = _s()
    chat: ChatSession = s.chat
    st.subheader("Cost")
    last = next((m["report"] for m in reversed(s.messages) if m.get("report")), None)
    message_view = cost_view(last.parts) if last else None
    session_view = cost_view(last.session_parts) if last else None
    tab1, tab2 = st.tabs(["This message", "Session"])
    with tab1:
        _cost_tab(message_view, "this message")
    with tab2:
        _cost_tab(session_view, "this run")
        if session_view is not None:
            st.caption(
                f"{session_view.messages} answered messages in this run (all users), "
                f"{session_view.cache_hits} from the cache."
            )
    if message_view or session_view:
        rows = []
        m_terms = dict(message_view.terms) if message_view else {}
        s_terms = dict(session_view.terms) if session_view else {}
        for label, _ in (message_view or session_view).terms:
            rows.append(
                {
                    "term": label,
                    "message": money(m_terms.get(label), ""),
                    "session": money(s_terms.get(label), ""),
                }
            )
        st.dataframe(pd.DataFrame(rows).set_index("term"), width="stretch")
        st.caption(
            "Premium − routing − compression − cache − provider cache + extra cost "
            "= actually paid (USD; savings shown negative). It always adds up."
        )
    st.caption(f"⚠️ {PREMIUM_CAVEATS} {DEMO_CAVEAT}")

    st.subheader("Budget")
    budget = budget_view(chat)
    if budget is None:
        st.caption("No budget configured.")
        return
    st.progress(
        min(budget.lifetime_fraction, 1.0),
        text=f"Lifetime: {budget.lifetime_spent:.6f} of {budget.lifetime_cap} "
        f"{budget.currency} ({budget.lifetime_fraction:.2%})",
    )
    if budget.run_cap is not None:
        st.progress(
            min(budget.run_fraction or 0.0, 1.0),
            text=f"This run: {budget.run_spent:.6f} of {budget.run_cap} "
            f"{budget.currency}",
        )
    marks = " and ".join(f"{w:.0%}" for w in budget.warn_at)
    if budget.crossed is not None and budget.crossed >= max(budget.warn_at):
        st.error(f"Over {budget.crossed:.0%} of the lifetime budget: tell the owner.")
    elif budget.crossed is not None:
        st.warning(f"Over {budget.crossed:.0%} of the lifetime budget.")
    st.caption(
        f"Warnings at {marks} of the lifetime cap. The ledger is per computer. "
        + (
            "Fake mode charges nothing."
            if not chat.live
            else "Every live call is charged here."
        )
    )


def main() -> None:
    st.set_page_config(page_title="Metis-Auto demo", page_icon="💸", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)  # static CSS only, no content
    _init()
    _sidebar()
    st.title("Metis-Auto demo")
    st.caption(
        "Cost-reducing middleware between a chat app and LLM providers: routing, "
        "caching, and compression, with every cent accounted for."
    )
    _banner()
    left, right = st.columns([3, 2], gap="large")
    with left:
        _chat_column()
    with right:
        _cost_panel()


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
