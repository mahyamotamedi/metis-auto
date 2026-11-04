"""The sprint winners in the Demo B page under Streamlit's offline test runner
(ADR-0066): the decision router is a routing choice that
offers no backend, the dedup toggle reaches the backend, and the cost panel
shows the dedup next to the other savings with the provisional label. Fake
mode only; no browser, no network, no key, no spend. Reuses the helpers of
``test_demo_ui_app``. Skipped unless the extra ``ui`` is installed."""

import pytest

pytest.importorskip("streamlit")

from test_demo_ui_app import _chat, _messages, _texts, chatbot, direct, send  # noqa: E402

from metis_auto.wiring.chat import RoutingMode  # noqa: E402
from metis_auto.wiring.demo_ui import load_presets  # noqa: E402


def test_the_decision_router_offers_no_backend_choice(tmp_path):
    at = direct(tmp_path)
    at.radio(key="routing_method").set_value(RoutingMode.DECISION_ROUTER.value).run()
    chat = _chat(at)
    assert chat.routing == RoutingMode.DECISION_ROUTER
    assert chat.router_mode == "off"
    assert not any(s.key == "router_mode" for s in at.selectbox)
    assert any("rules only" in c.value for c in at.caption)
    at = send(at, "hi")
    assert not at.exception
    report = _messages(at)[-1]["report"]
    assert report.routing["reason_code"] == "decision.gate.greeting"
    assert report.routing["tier"] == "0"
    assert "provisional: cost only" in report.routing["decision"]
    assert report.model_id not in {"gpt-4.1-nano", "mimo-v2.5"}


def test_sticky_inner_router_is_a_choice(tmp_path):
    at = direct(tmp_path)
    assert _chat(at).sticky_inner == "rule_based"
    at.radio(key="sticky_inner").set_value("decision_router").run()
    assert _chat(at).sticky_inner == "decision_router"


def test_the_dedup_toggle_reaches_the_backend_and_the_panel(tmp_path):
    keys = {p.key for p in load_presets()}
    assert {"fa_shop_dupes", "en_faq_dupes"} <= keys
    at = chatbot(tmp_path, bot="fa_shop_dupes")
    chat = _chat(at)
    assert chat.dedup is False
    at.toggle(key="dedup").set_value(True).run()
    assert chat.dedup is True
    at = send(at, "سفارشم کی می‌رسه؟")
    assert not at.exception
    report = _messages(at)[-1]["report"]
    assert report.dedup["items_total"] == "6"
    assert report.dedup["items_removed"] == "3"
    text = _texts(at)
    assert "Duplicate chunks removed (DEMO)" in text
    captions = " ".join(str(c.value) for c in at.caption)
    assert "Provisional: cost only, pending quality." in captions
    assert "mechanism demo" in captions
