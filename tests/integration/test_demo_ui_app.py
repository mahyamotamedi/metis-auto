"""The Demo B page (``scripts/demo_ui.py``) under Streamlit's offline test
runner (``streamlit.testing.v1.AppTest``): it loads in fake mode, a message
round-trips, presets load, toggles reach the backend, a blocked live switch
says why, the budget guard's refusal is explained, and no message content
reaches the logs. No browser, no network, no key; config/local.toml and .env
are not read (the settings loader is injected through the page's test hooks).
Skipped unless the extra ``ui`` (requirements-ui.lock) is installed."""

import json
import logging
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from metis_auto.adapters.providers import FakeModelClient  # noqa: E402
from metis_auto.settings import load_settings  # noqa: E402
from metis_auto.wiring.chat import CompressionMode, RoutingMode  # noqa: E402
from metis_auto.wiring.demo_ui import load_presets  # noqa: E402
from metis_auto.wiring.ui_config import load_strings  # noqa: E402

PAGE = str(Path(__file__).resolve().parents[2] / "scripts" / "demo_ui.py")


class NoBots:
    """A hermetic stand-in for the local database (UI Stage 4): the page never
    reaches a real one in a test. The bot list is empty; the synthetic samples
    remain."""

    def directory_rows(self):
        return []

    def instructions(self, bot_id):
        raise AssertionError("no real bot in this test")

    def rag_texts(self, bot_id):
        raise AssertionError("no real bot in this test")


MARKER = "SYNTHETIC-CONTENT-MARKER-91c2"
SYNTHETIC_KEY = "sk-SYNTHETIC-not-a-key"
FAKE, LIVE = "Fake (free, no key)", "Live (real models, budgeted)"


def make_loader(tmp_path, *, live_enabled=False, key=None, run_cap=None):
    def load(overrides):
        extra = {"budget.run_cap": run_cap} if run_cap else {}
        return load_settings(
            overrides={
                **overrides,
                **extra,
                "paths.spend_ledger": str(tmp_path / "spend" / "ledger.jsonl"),
                "paths.recorded_dir": str(tmp_path / "recorded"),
                "live.enabled": live_enabled,
            },
            runtime=None,
            dotenv=None,
            environ={"METIS_API_KEY": key} if key else {},
        )

    return load


def page(
    tmp_path, *, loader=None, client_factory=None, compressor_factory=None, lang="en"
) -> AppTest:
    """The app on its entry screen, in English (``?lang=en``): the default is
    Persian since Stage 2 (UI-V06); the assertions below read the English
    strings."""
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["_test_bot_source"] = NoBots
    at.query_params["lang"] = lang
    at.session_state["_test_settings_loader"] = loader or make_loader(tmp_path)
    at.session_state["_test_client_factory"] = client_factory or (
        lambda _l, _r: FakeModelClient()
    )
    if compressor_factory is not None:
        at.session_state["_test_compressor_factory"] = compressor_factory
    return at.run()


def direct(tmp_path, **kwargs) -> AppTest:
    """Journey B: the entry screen's "Direct chat" card (UI-S06)."""
    at = page(tmp_path, **kwargs)
    return at.button(key="mx-cta-entry-direct").click().run()


def chatbot(tmp_path, bot: str | None = None, **kwargs) -> AppTest:
    """Journey A: entry -> (a bot) -> settings -> "Start chatting" (UI-S05)."""
    at = page(tmp_path, **kwargs)
    at = at.button(key="mx-cta-entry-chatbot").click().run()  # S02
    if bot:
        at = at.button(key=f"mx-bot-{bot}").click().run()
    at = at.button(key="mx-cta-continue").click().run()  # S02 -> S04
    return at.button(key="mx-cta-start").click().run()


def send(at: AppTest, text: str) -> AppTest:
    return at.chat_input[0].set_value(text).run()


def _texts(at: AppTest) -> str:
    return " ".join(str(m.value) for m in at.markdown)


def _chat(at: AppTest):
    """The open workspace's real ChatSession."""
    return at.session_state["workspace"].current().session


def _messages(at: AppTest) -> list[dict]:
    return at.session_state["workspace"].current().messages


def test_loads_in_fake_mode_and_a_message_round_trips(tmp_path):
    at = page(tmp_path)
    assert not at.exception
    assert at.session_state["workspace"].journey.value == "none"  # the entry screen
    assert len(at.get("page_link")) == 3  # brand overlay, Chat, Results
    at = at.button(key="mx-cta-entry-direct").click().run()
    assert not at.exception
    chat = _chat(at)
    assert not chat.live and chat.routing == RoutingMode.STICKY_V1
    assert any("Fake mode: live calls OFF" in c.value for c in at.caption)
    assert any("live.enabled is false" in c.value for c in at.caption)

    at = send(at, "سلام")
    assert not at.exception
    messages = _messages(at)
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["text"].startswith("[SYNTHETIC] fake answer")
    assert messages[1]["report"].routing["reason_code"] == "sticky.greeting"
    assert len(at.chat_message) == 2
    assert "greeting" in _texts(at)  # the badge under the answer
    assert len(chat.history) == 2  # the session holds the history (P-8)
    assert at.metric[0].label == "Actually paid (est.)"  # fake: an estimate


def test_bots_are_listed_and_their_instructions_reach_the_request(tmp_path):
    presets = {p.key: p for p in load_presets()}
    fa, en = presets["fa_shop_dupes"], presets["en_faq_dupes"]
    at = chatbot(tmp_path, bot="en_faq_dupes")
    assert not at.exception
    chat = _chat(at)
    at = send(at, "How do I export my notes to PDF?")
    assert chat.instructions == en.instructions
    assert chat.retrieved == en.documents
    report = _messages(at)[-1]["report"]
    assert report.routing["reason_code"].startswith("sticky.first_substantive")
    ws = at.session_state["workspace"]
    assert ws.bot_key == en.key and ws.bots[0].key == fa.key


def test_toggles_reach_the_backend(tmp_path):
    at = direct(tmp_path)
    chat = _chat(at)
    assert not chat.bot_cache and chat.compression == CompressionMode.OFF
    at.radio(key="routing_method").set_value(RoutingMode.PER_REQUEST.value).run()
    assert chat.routing == RoutingMode.PER_REQUEST
    at.toggle(key="sw_routing").set_value(False).run()  # routing off: fixed model
    assert chat.routing == RoutingMode.FIXED
    at.selectbox(key="preferred_model").set_value("gpt-4.1-nano").run()
    assert chat.routing == RoutingMode.FIXED and chat.model_id == "gpt-4.1-nano"
    at.toggle(key="sw_routing").set_value(True).run()
    assert chat.routing == RoutingMode.PER_REQUEST  # the chosen method is back
    at.toggle(key="sw_cache").set_value(True).run()
    at.radio(key="compression").set_value(CompressionMode.FAKE.value).run()
    at.toggle(key="thinking").set_value(False).run()
    assert chat.bot_cache and chat.compression == CompressionMode.FAKE
    assert at.toggle(key="sw_context").value is True  # the switch shows the real state
    assert not chat.deepseek_thinking
    assert _chat(at) is chat  # toggles keep the run and the cache

    at = chatbot(tmp_path, bot="fa_shop_dupes")
    chat = _chat(at)
    at.toggle(key="sw_cache").set_value(True).run()
    at = send(at, "هزینه ارسال برای شهرستان چقدر است؟")
    at.button(key="new_user").click().run()
    assert chat.users == 2 and _messages(at) == []
    at = send(at, "هزینه ارسال برای شهرستان چقدر است؟")
    assert _messages(at)[-1]["report"].served_by == "cache"  # cross-user hit
    at.button(key="reset").click().run()
    assert chat.history == [] and _messages(at) == []


def test_a_failed_toggle_is_reported_and_reverted(tmp_path):
    def broken(_loaded, _name):
        raise ValueError("compression unavailable: [SYNTHETIC] test")

    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["_test_bot_source"] = NoBots
    at.query_params["lang"] = "en"
    at.session_state["_test_settings_loader"] = make_loader(tmp_path)
    at.session_state["_test_client_factory"] = lambda _l, _r: FakeModelClient()
    at.session_state["_test_compressor_factory"] = broken
    at.run()
    at.button(key="mx-cta-entry-direct").click().run()
    at.radio(key="compression").set_value(CompressionMode.LLMLINGUA2.value).run()
    assert at.session_state["compression"] == CompressionMode.OFF.value
    assert _chat(at).compression == CompressionMode.OFF
    assert "compression unavailable" in at.error[0].value


def test_live_and_llmlingua_have_no_persistent_warning_banners(tmp_path):
    from metis_auto.adapters.compressors import FakeCompressor

    at = direct(
        tmp_path,
        loader=make_loader(tmp_path, live_enabled=True, key=SYNTHETIC_KEY),
        compressor_factory=lambda _l, _n: FakeCompressor(),
    )
    at.radio(key="mode").set_value(LIVE).run()
    assert _chat(at).live
    assert not at.warning
    at.radio(key="compression").set_value(CompressionMode.LLMLINGUA2.value).run()
    assert _chat(at).compression == CompressionMode.LLMLINGUA2
    assert not at.warning


def test_persian_dedup_sample_preserves_original_shop_knowledge():
    presets = {p.key: p for p in load_presets()}
    original, demo = presets["fa_shop"], presets["fa_shop_dupes"]
    assert demo.instructions == original.instructions
    assert tuple(dict.fromkeys(demo.documents)) == original.documents


@pytest.mark.parametrize("dedup", [False, True])
def test_persian_knowledge_reaches_the_model_unchanged(tmp_path, dedup):
    invocations = []

    class Capture(FakeModelClient):
        def invoke(self, invocation):
            invocations.append(invocation)
            return super().invoke(invocation)

    at = chatbot(
        tmp_path,
        bot="fa_shop_dupes",
        client_factory=lambda _l, _r: Capture(),
    )
    if dedup:
        at.toggle(key="dedup").set_value(True).run()
    at = send(at, "هزینه ارسال برای شهرستان چقدر است؟")
    assert not at.exception
    assert len(invocations) == 1
    parts = invocations[0].parts
    preset = next(p for p in load_presets() if p.key == "fa_shop")
    knowledge = [p.text for p in parts if p.component.value == "retrieved"]
    assert tuple(dict.fromkeys(knowledge)) == preset.documents
    assert "۶۵ هزار تومان" in "\n".join(knowledge)
    assert parts[0].text == preset.instructions
    assert parts[-1].text == "هزینه ارسال برای شهرستان چقدر است؟"


def test_live_switch_blocked_by_configuration_says_why(tmp_path):
    at = direct(tmp_path)
    at.radio(key="mode").set_value(LIVE).run()
    assert at.session_state["mode"] == FAKE
    assert not _chat(at).live
    banner = at.error[0].value
    assert "Live calls BLOCKED" in banner
    assert "live.enabled is false" in banner
    assert "METIS_API_KEY is not set" in banner
    assert SYNTHETIC_KEY not in banner


def test_no_message_content_in_logs(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    at = chatbot(tmp_path, bot="en_faq_dupes")
    at = send(at, f"{MARKER} how do I sync?")
    at = send(at, f"{MARKER} write a python function to list notes")
    assert not at.exception
    assert MARKER not in caplog.text
    assert "[SYNTHETIC]" not in caplog.text  # no bot text, no answer text


def test_live_budget_refusal_is_explained(tmp_path):
    pytest.importorskip("openai")
    import httpx2

    from metis_auto.wiring.live import build_live_client

    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(500, json={"error": {"message": "[SYNTHETIC]"}})

    def factory(loaded, run_id):
        if loaded.settings.experiment.counterfactual_source.value != "live":
            return FakeModelClient()  # the page starts in fake mode
        return build_live_client(
            loaded,
            run_id,
            http_client_factory=lambda: httpx2.Client(
                transport=httpx2.MockTransport(handler)
            ),
        )

    loader = make_loader(
        tmp_path, live_enabled=True, key=SYNTHETIC_KEY, run_cap="0.0000001"
    )
    at = direct(tmp_path, loader=loader, client_factory=factory)
    assert any("Live mode is available" in c.value for c in at.caption)
    at.radio(key="mode").set_value(LIVE).run()
    chat = _chat(at)
    assert chat.live
    assert not at.warning  # the header chip indicates live mode without a banner
    at = send(at, f"{MARKER} hello")
    report = _messages(at)[-1]["report"]
    assert report.failure == "budget_exhausted"
    assert requests == []  # refused before any HTTP request
    assert any("Nothing was charged" in w.value for w in at.warning)
    ledger = tmp_path / "spend" / "ledger.jsonl"
    assert not ledger.exists() or all(
        MARKER not in json.dumps(line) for line in ledger.read_text().splitlines()
    )


# --- Results page (D-2, spec UI-S07) -------------------------------------------

RESULTS_PAGE = "demo_pages/results.py"  # relative to scripts/demo_ui.py
REAL_LEVERS = Path(__file__).resolve().parents[2] / "reports" / "levers"


def _synthetic_levers(folder: Path) -> Path:
    from datetime import UTC, datetime
    from decimal import Decimal

    from metis_auto.analysis.lever_result import LeverResult, Manifest

    manifest = Manifest(
        data_revision="0" * 40,
        code_commit="unknown",
        config_hash="a" * 64,
        seed=7,
        price_version="prices-synthetic-1",
        python_version="3.13.5",
        created_at=datetime(2026, 11, 3, 9, 0, tzinfo=UTC),
    )
    cut = {"n_requests": Decimal(10), "n_cache_hits": Decimal(2)}
    result = LeverResult(
        lever_id="cache.synthetic.as_logged",
        step="cache",
        version="synthetic",
        n_requests=10,
        n_eligible=6,
        baseline="as_logged",
        baseline_cost={"fees": Decimal(2), "token_cost": Decimal(6)},
        saving={"fees": Decimal("0.5"), "token_cost": Decimal("1.5")},
        ci_low=0.1,
        ci_high=0.3,
        slices={"all": cut, "llm_only": cut},
        evidence_class="simulation",
        correctness_state="unmeasured",
        assumptions=("[SYNTHETIC] fixture",),
        manifest=manifest,
    )
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{result.lever_id}.json").write_text(result.to_json(), encoding="utf-8")
    return folder


def results_page(tmp_path, levers: Path) -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["_test_bot_source"] = NoBots
    at.session_state["_test_settings_loader"] = make_loader(tmp_path)
    at.session_state["_test_client_factory"] = lambda _l, _r: FakeModelClient()
    at.session_state["_test_levers_dir"] = str(levers)
    at.run()
    return at.switch_page(RESULTS_PAGE).run()


def _page_text(at: AppTest) -> str:
    parts = [
        str(e.value)
        for kind in (
            "markdown",
            "caption",
            "title",
            "header",
            "subheader",
            "info",
            "warning",
        )
        for e in getattr(at, kind)
    ]
    parts += [f"{m.label} {m.value}" for m in at.metric]
    # st.html fragments (empty states, header), not the style sheet (Stage 2)
    parts += [
        e.proto.body for e in at.get("html") if not e.proto.body.startswith("<style>")
    ]
    return " ".join(parts)


def test_results_page_renders_in_fake_mode(tmp_path):
    at = results_page(tmp_path, _synthetic_levers(tmp_path / "levers"))
    assert not at.exception
    at.segmented_control(key="ui_lang").set_value("en").run()
    assert not at.exception
    assert at.title[0].value == "Results"
    assert any(m.label == "Saving" for m in at.metric)
    at.selectbox(key="res_baseline").set_value("todays_models").run()
    assert not at.exception
    at.segmented_control(key="ui_lang").set_value("fa").run()
    assert not at.exception and at.title[0].value != "Results"


def test_results_page_empty_state(tmp_path):
    at = results_page(tmp_path, tmp_path / "no-results")
    assert not at.exception
    at.segmented_control(key="ui_lang").set_value("en").run()
    assert "No lever results yet" in _page_text(at)
    assert not at.metric


@pytest.mark.skipif(not REAL_LEVERS.is_dir(), reason="no committed lever results")
def test_results_page_on_the_committed_results_shows_no_ids(tmp_path):
    import re

    at = results_page(tmp_path, REAL_LEVERS)
    assert not at.exception
    for lang in ("en", "fa"):
        at.segmented_control(key="ui_lang").set_value(lang).run()
        for baseline in ("as_logged", "todays_models", "premium_gpt_5_5"):
            at.selectbox(key="res_baseline").set_value(baseline).run()
            assert not at.exception, (lang, baseline)
            text = _page_text(at)
            assert not re.search(r"\b[0-9a-f]{16,}\b", text)
            assert not re.search(r"\b(bot|tenant|user)_(rank|id)\b", text)


# --- Design system (UI spec Stage 2) ---------------------------------------------

LRI, PDI = "\u2066", "\u2069"
RTL_LAYOUT = '[data-testid="stAppViewContainer"] { direction: rtl; }'


def _html(at: AppTest) -> list[str]:
    """``st.html`` bodies other than the style sheet (header, states)."""
    return [
        e.proto.body for e in at.get("html") if not e.proto.body.startswith("<style>")
    ]


def _css(at: AppTest) -> str:
    """The theme style sheet. A style-only ``st.html`` goes to Streamlit's event
    container, outside the main tree, so AppTest cannot see its position; the
    page emits it before anything else (checked in the browser)."""
    sheets = [
        e.proto.body for e in at.get("html") if e.proto.body.startswith("<style>")
    ]
    assert len(sheets) == 1
    return sheets[0]


def _visible_text(at: AppTest) -> str:
    return _page_text(at) + " " + " ".join(_html(at))


def _app(tmp_path, *, theme: str, lang: str, levers: Path | None = None) -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["_test_bot_source"] = NoBots
    at.query_params["theme"] = theme
    at.query_params["lang"] = lang
    at.session_state["_test_settings_loader"] = make_loader(tmp_path)
    at.session_state["_test_client_factory"] = lambda _l, _r: FakeModelClient()
    at.session_state["_test_levers_dir"] = str(
        levers or _synthetic_levers(tmp_path / "levers")
    )
    return at.run()


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("lang", ["fa", "en"])
def test_both_pages_render_in_every_theme_and_language(tmp_path, theme, lang):
    at = _app(tmp_path, theme=theme, lang=lang)
    assert not at.exception
    assert at.session_state["ui_theme"] == theme
    assert at.session_state["ui_lang"] == lang
    css = _css(at)  # the theme CSS (UI-T04)
    assert "--bg:" in css
    assert (RTL_LAYOUT in css) == (lang == "fa")
    at = at.button(key="mx-cta-entry-direct").click().run()
    at = send(at, "سلام")
    assert not at.exception
    at = at.switch_page(RESULTS_PAGE).run()
    assert not at.exception
    assert "--bg:" in _css(at)
    assert at.title[0].value == ("Results" if lang == "en" else "نتایج")


def test_query_parameters_restore_theme_and_language(tmp_path):
    at = _app(tmp_path, theme="light", lang="en")
    assert at.toggle(key="ui_dark").value is False
    assert at.segmented_control(key="ui_lang").value == "en"
    assert at.query_params["theme"] == "light" and at.query_params["lang"] == "en"
    at.toggle(key="ui_dark").set_value(True).run()
    assert at.session_state["ui_theme"] == "dark"
    assert at.query_params["theme"] == "dark"  # a reload keeps the choice
    at.segmented_control(key="ui_lang").set_value("fa").run()
    assert at.query_params["lang"] == "fa"
    assert RTL_LAYOUT in _css(at)


def test_default_is_dark_and_persian(tmp_path):
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["_test_bot_source"] = NoBots
    at.session_state["_test_settings_loader"] = make_loader(tmp_path)
    at.session_state["_test_client_factory"] = lambda _l, _r: FakeModelClient()
    at.run()
    assert not at.exception
    assert at.session_state["ui_theme"] == "dark"
    assert at.session_state["ui_lang"] == "fa"
    assert at.toggle(key="ui_dark").value is True


def test_numbers_and_model_ids_are_ltr_isolated(tmp_path):
    """UI-V07: money, percentages, counts and model ids never reorder in RTL."""
    at = _app(tmp_path, theme="dark", lang="fa")
    at = at.button(key="mx-cta-entry-direct").click().run()
    at = send(at, "How do I export my notes to PDF?")
    assert not at.exception
    report = _messages(at)[-1]["report"]
    values = [m.value for m in at.metric]
    assert values and all(v.startswith(LRI) and v.endswith(PDI) for v in values)
    badge = _texts(at)
    assert f"{LRI}{report.model_id}{PDI}" in badge
    assert '<b><bdi dir="ltr" class="mx-ltr">$' in " ".join(_html(at))  # budget
    at = at.switch_page(RESULTS_PAGE).run()
    values = [m.value for m in at.metric]
    assert values and all(v.startswith(LRI) and v.endswith(PDI) for v in values)


def test_header_has_brand_mode_chip_budget_and_no_login(tmp_path):
    at = _app(tmp_path, theme="dark", lang="fa")
    html = " ".join(_html(at))
    assert "متیس‌اتو" in html and "نمونه‌ی آزمایشی" in html  # Stage 2b point 1
    # Stage 2b point 2: the real budget (cap 20, empty test ledger) in fake
    # mode too; the mode only in the chip, never twice
    assert '<div class="mx-budget"' in html and "بودجه:" in html
    assert '<b><bdi dir="ltr" class="mx-ltr">$92.00</bdi></b>' in html
    assert "حالت آزمایشی" not in html and html.count("آزمایشی") == 2  # chip, pill
    text = html.lower()
    for absent in ("login", "sign up", "ورود", "avatar", "+</"):
        assert absent not in text, absent
    links = at.get("page_link")
    assert len(links) == 3  # the brand (back to the entry screen), Chat, Results


def test_streamlit_chrome_is_hidden_and_colours_come_from_tokens(tmp_path):
    import re

    at = _app(tmp_path, theme="light", lang="en")
    css = _css(at)
    assert '[data-testid="stToolbar"]' in css and "display: none" in css
    body = css.split("}", 1)[1]
    assert not re.search(r"#[0-9a-fA-F]{6}\b", body.replace("#vg-tooltip-element", ""))


# --- Stage 2b polish (owner review 2026-11-03) ------------------------------------


def _specs(at: AppTest) -> list[dict]:
    return [json.loads(e.proto.spec) for e in at.get("vega_lite_chart")]


def _encodings(spec: dict) -> list[dict]:
    layers = [spec, *spec.get("layer", [])]
    return [layer.get("encoding", {}) for layer in layers]


def test_results_are_tabbed_with_names_legends_and_rtl_bars(tmp_path):
    at = _app(tmp_path, theme="dark", lang="fa", levers=REAL_LEVERS)
    at = at.switch_page(RESULTS_PAGE).run()
    assert not at.exception
    strings = load_strings()
    tabs = [t.label for t in at.tabs]
    for key in ("step_cache", "step_context", "step_routing", "tab_per_bot"):
        assert strings.text(key, "fa") in tabs, key
    specs = _specs(at)
    assert specs
    for spec in specs:  # Vega's own legend hidden: the page draws a centred one
        for enc in _encodings(spec):
            if "field" in enc.get("color", {}):
                assert enc["color"].get("legend", "absent") is None, enc["color"]
    assert any('class="mx-legend"' in h for h in _html(at))
    horizontal = [
        enc
        for spec in specs
        for enc in _encodings(spec)
        if enc.get("y", {}).get("type") == "nominal"
        and enc.get("x", {}).get("type") == "quantitative"
    ]
    assert horizontal
    for enc in horizontal:  # labels on the right, bars from right to left
        assert enc["y"]["axis"]["orient"] == "right"
        assert enc["x"]["scale"]["reverse"] is True
    # readable names; the raw id only in the muted id caption
    options = " ".join(o for sb in at.selectbox for o in sb.options)
    assert "حافظه‌ی بازیابی، ۹۰ روز (B)" in options
    assert "بودجه‌ی تاریخچه" in options
    assert "rb1.retrieval-cache" not in options and "ctx.history_budget" not in options
    assert any('class="mx-id"' in h for h in _html(at))
    # long tables are folded
    assert all(e.proto.expanded is False for e in at.expander)


def test_numbers_use_the_one_formatter(tmp_path):
    import re

    at = _app(tmp_path, theme="dark", lang="en", levers=REAL_LEVERS)
    at = at.switch_page(RESULTS_PAGE).run()
    values = [m.value.strip(LRI + PDI) for m in at.metric]
    assert values
    for value in values:
        assert not re.search(r"\.[0-9]{2}%", value), value  # 1 decimal
        assert not re.fullmatch(r"[0-9,]+\.[0-9]{3,}", value) or value.startswith(
            "0."
        ), value  # >= 1: 2 decimals


def _english_ui_strings() -> list[str]:
    """English values of the strings table that a Persian page must not show:
    longer than 3 letters, different from every Persian string (so product
    names such as "Metis-Auto" or "LLMLingua-2" inside Persian text pass)."""
    import re

    strings = load_strings()
    fa_all = " ".join(strings.text(k, "fa") for k in strings.keys())
    out = []
    for key in strings.keys():
        en = re.sub(r"\{[a-z_]+\}", "", strings.text(key, "en")).strip(" .:,")
        if len(re.sub(r"[^A-Za-z]", "", en)) > 3 and en not in fa_all:
            out.append(en)
    return out


def _persian_page_text(at: AppTest) -> str:
    """Every visible UI text: labels, values, captions, tabs, expander labels,
    select options, tables (chat details: labels only; their values are model
    ids, states and router explanations from the backend), HTML fragments.
    Message bodies are content and are left out."""
    parts = [
        str(e.value)
        for kind in ("caption", "title", "header", "subheader", "info", "warning")
        for e in getattr(at, kind)
        if "[SYNTHETIC]" not in str(e.value)  # a SYNTHETIC bot's English label
    ]
    parts += [str(m.value) for m in at.markdown if "[SYNTHETIC]" not in str(m.value)]
    parts += [f"{m.label} {m.value}" for m in at.metric]
    parts += [t.label for t in at.tabs] + [e.label for e in at.expander]
    parts += [o for sb in at.selectbox for o in sb.options]
    # preset titles are SYNTHETIC preset data (presets-synthetic.toml), English
    presets = {f"[SYNTHETIC] {p.title}" for p in load_presets()}
    parts += [
        w.label
        for kind in ("toggle", "button", "radio")
        for w in getattr(at, kind)
        if w.label not in presets
    ]
    for table in at.table:
        frame = table.value
        parts += [str(c) for c in frame.columns] + [str(i) for i in frame.index]
        if "مقدار" not in [str(c) for c in frame.columns]:
            parts += [str(v) for v in frame.to_numpy().ravel()]
    # the raw id caption (allowed, owner review point 3) and result data that
    # its writer stored in English (assumptions) are not UI strings
    parts += [
        h
        for h in _html(at)
        if 'class="mx-id"' not in h and "mx-data" not in h and "[SYNTHETIC]" not in h
    ]
    return " ".join(parts)


def test_no_english_ui_string_in_persian_on_either_page(tmp_path):
    import re

    english = _english_ui_strings()
    assert len(english) > 100
    at = _app(tmp_path, theme="dark", lang="fa", levers=REAL_LEVERS)
    pages = [_persian_page_text(at)]  # the entry screen
    at = at.button(key="mx-cta-entry-chatbot").click().run()  # S02
    at = at.button(key="mx-cta-continue").click().run()  # S04
    pages.append(_persian_page_text(at))  # settings
    at = at.button(key="mx-cta-start").click().run()
    at = send(at, "سلام")
    at = send(at, "سفارشم کی می‌رسه؟")
    assert not at.exception
    pages.append(_persian_page_text(at))
    at = at.switch_page(RESULTS_PAGE).run()
    assert not at.exception
    pages.append(_persian_page_text(at))
    for text in pages:
        found = [
            e
            for e in english
            if re.search(rf"(?<![A-Za-z]){re.escape(e)}(?![A-Za-z])", text)
        ]
        assert found == []
