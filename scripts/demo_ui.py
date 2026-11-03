"""The Metis-Auto demo UI in the browser (Demo milestone B; brief §10).

    .venv/bin/python scripts/demo_ui.py            # opens http://localhost:8501

A thin Streamlit page over ``metis_auto.wiring.chat.ChatSession`` (the same
backend as ``scripts/chat.py``) and ``metis_auto.wiring.demo_ui`` (the view
model). No routing, caching, or accounting logic here: the page holds the
history and sends it every turn (P-8), shows each ``TurnReport``, and maps the
widgets to the session's toggles.

- Header (UI spec Stage 2, UI-H01..H05): the text wordmark (متیس‌اتو /
  Metis-Auto, Stage 2b), the language switch (فا / EN), the Fake/Live chip, the
  real budget in both modes, the theme toggle and a "Local demo" chip; below,
  the Chat and Results tabs. Built here, not with Streamlit's top navigation,
  which cannot hold these controls (ADR-0052).
- Chat page: the screen the session's ``DemoWorkspace`` is on (UI spec Stage 3):
  the entry screen, the optimisation settings, or a chat workspace with the
  savings panel beside it. Drawn by ``scripts/demo_pages/workspace.py`` over
  ``wiring.demo_workspace`` and ``wiring.savings_panel``. The brand returns to
  the entry screen (an invisible page link with ``?screen=entry``).
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

import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

_PAGES = Path(__file__).resolve().parent
if str(_PAGES) not in sys.path:  # `demo_pages` next to this file (AppTest, plain run)
    sys.path.insert(0, str(_PAGES))

from demo_pages import workspace as workspace_page  # noqa: E402

from metis_auto.wiring.demo_ui import header_budget, load_presets  # noqa: E402
from metis_auto.wiring.demo_workspace import (  # noqa: E402
    DemoWorkspace,
    make_session_factory,
    synthetic_bots,
)
from metis_auto.wiring.ui_config import (  # noqa: E402
    DEFAULT_LANGUAGE,
    LANGUAGE_SHORT,
    LANGUAGES,
    load_strings,
    load_theme,
    translator,
    ui_state,
)
from metis_auto.wiring.ui_style import (  # noqa: E402
    budget_html,
    chip_html,
    header_brand_html,
    page_css,
)

STREAMLIT_OPTIONS = (
    "--browser.gatherUsageStats=false",
    "--server.address=localhost",
    "--client.toolbarMode=minimal",
    "--server.fileWatcherType=none",
)
RESULTS_PAGE = "demo_pages/results.py"  # D-2 Results page, relative to this file

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
    """One ``DemoWorkspace`` per browser session: the router, one ChatSession per
    journey and bot, the settings (wiring, spec Stage 3)."""
    s = _s()
    if "workspace" in s:
        return
    s.notice = None
    s.blocked = None
    s.workspace = DemoWorkspace(
        synthetic_bots(load_presets(_injected("presets_path"))),
        session_factory=make_session_factory(
            settings_loader=_injected("settings_loader"),
            client_factory=_injected("client_factory"),
            compressor_factory=_injected("compressor_factory"),
            seed_path=_injected("seed_path"),
        ),
    )


def _chat_page() -> None:
    _init()
    workspace_page.render()


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
    _init()  # the budget is read from the session's ledger, on every page
    chat = s.workspace.header_session()
    live = chat.live
    with st.container(key="mx-header", gap=None):
        with st.container(
            key="mx-header-row1",
            horizontal=True,
            horizontal_alignment="distribute",
            vertical_alignment="center",
        ):
            with st.container(key="mx-brand-wrap", width="content"):
                st.html(header_brand_html(s.ui_text), width="content")
                # an invisible link over the wordmark: back to the entry screen
                # (UI-H02) without losing the session (a plain href would reload)
                st.page_link(
                    pages[0][1],
                    label=S("brand_home"),
                    query_params={
                        "theme": s.ui_theme,
                        "lang": s.ui_lang,
                        "screen": "entry",
                    },
                )
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
                    budget_html(s.ui_text, budget=header_budget(chat)), width="content"
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
