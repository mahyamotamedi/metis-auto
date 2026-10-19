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

PAGE = str(Path(__file__).resolve().parents[2] / "scripts" / "demo_ui.py")
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


def page(tmp_path, *, loader=None, client_factory=None) -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["_test_settings_loader"] = loader or make_loader(tmp_path)
    at.session_state["_test_client_factory"] = client_factory or (
        lambda _l, _r: FakeModelClient()
    )
    return at.run()


def send(at: AppTest, text: str) -> AppTest:
    return at.chat_input[0].set_value(text).run()


def _texts(at: AppTest) -> str:
    return " ".join(str(m.value) for m in at.markdown)


def test_loads_in_fake_mode_and_a_message_round_trips(tmp_path):
    at = page(tmp_path)
    assert not at.exception
    assert at.title[0].value == "Metis-Auto demo"
    assert "Fake mode: live calls OFF" in at.info[0].value
    assert "live.enabled is false" in at.info[0].value  # why live is blocked
    chat = at.session_state["chat"]
    assert not chat.live and chat.routing == RoutingMode.STICKY_V1

    at = send(at, "سلام")
    assert not at.exception
    messages = at.session_state["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["text"].startswith("[SYNTHETIC] fake answer")
    assert messages[1]["report"].routing["reason_code"] == "sticky.greeting"
    assert len(at.chat_message) == 2
    assert "greeting" in _texts(at)  # the badge under the answer
    assert len(chat.history) == 2  # the session holds the history (P-8)
    assert at.metric[0].label == "Actually paid"


def test_presets_load_into_the_bot_setup(tmp_path):
    at = page(tmp_path)
    fa, en = load_presets()
    at.button(key="preset_fa_shop").click().run()
    assert at.session_state["instructions"] == fa.instructions
    assert len(at.session_state["doc_ids"]) == len(fa.documents)
    assert at.text_area(key="instructions").value == fa.instructions
    at.button(key="preset_en_faq").click().run()
    docs = [at.text_area(key=f"doc_{i}").value for i in at.session_state["doc_ids"]]
    assert docs == list(en.documents)

    at = send(at, "How do I export my notes to PDF?")
    chat = at.session_state["chat"]
    assert chat.instructions == en.instructions
    assert chat.retrieved == en.documents
    report = at.session_state["messages"][-1]["report"]
    assert report.routing["reason_code"].startswith("sticky.first_substantive")

    at.button(key=f"rm_{at.session_state['doc_ids'][0]}").click().run()
    assert len(at.session_state["doc_ids"]) == len(en.documents) - 1


def test_toggles_reach_the_backend(tmp_path):
    at = page(tmp_path)
    chat = at.session_state["chat"]
    at.radio(key="routing").set_value(RoutingMode.PER_REQUEST.value).run()
    assert chat.routing == RoutingMode.PER_REQUEST
    at.radio(key="routing").set_value(RoutingMode.FIXED.value).run()
    at.selectbox(key="fixed_model").set_value("gpt-4.1-nano").run()
    assert chat.routing == RoutingMode.FIXED and chat.model_id == "gpt-4.1-nano"
    at.radio(key="routing").set_value(RoutingMode.STICKY_V1.value).run()
    at.toggle(key="bot_cache").set_value(True).run()
    at.radio(key="compression").set_value(CompressionMode.FAKE.value).run()
    at.toggle(key="thinking").set_value(False).run()
    assert chat.routing == RoutingMode.STICKY_V1
    assert chat.bot_cache and chat.compression == CompressionMode.FAKE
    assert not chat.deepseek_thinking
    assert at.session_state["chat"] is chat  # toggles keep the run and cache

    at.button(key="preset_fa_shop").click().run()
    at = send(at, "هزینه ارسال برای شهرستان چقدر است؟")
    first = at.session_state["messages"][-1]["report"]
    assert first.compression  # the fake compressor ran on the documents
    at.button(key="new_user").click().run()
    assert chat.users == 2 and at.session_state["messages"] == []
    at = send(at, "هزینه ارسال برای شهرستان چقدر است؟")
    hit = at.session_state["messages"][-1]["report"]
    assert hit.served_by == "cache"  # cross-user hit on the same bot
    at.button(key="reset").click().run()
    assert chat.history == [] and at.session_state["messages"] == []


def test_a_failed_toggle_is_reported_and_reverted(tmp_path):
    def broken(_loaded, _name):
        raise ValueError("compression unavailable: [SYNTHETIC] test")

    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["_test_settings_loader"] = make_loader(tmp_path)
    at.session_state["_test_client_factory"] = lambda _l, _r: FakeModelClient()
    at.session_state["_test_compressor_factory"] = broken
    at.run()
    at.radio(key="compression").set_value(CompressionMode.LLMLINGUA2.value).run()
    assert at.session_state["compression"] == CompressionMode.OFF.value
    assert at.session_state["chat"].compression == CompressionMode.OFF
    assert "compression unavailable" in at.error[0].value


def test_live_switch_blocked_by_configuration_says_why(tmp_path):
    at = page(tmp_path)
    at.radio(key="mode").set_value(LIVE).run()
    assert at.session_state["mode"] == FAKE
    assert not at.session_state["chat"].live
    banner = at.error[0].value
    assert "Live calls BLOCKED" in banner
    assert "live.enabled is false" in banner
    assert "METIS_API_KEY is not set" in banner
    assert SYNTHETIC_KEY not in banner


def test_no_message_content_in_logs(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    at = page(tmp_path)
    at.button(key="preset_en_faq").click().run()
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
    at = page(tmp_path, loader=loader, client_factory=factory)
    assert "Live mode is available" in at.info[0].value
    at.radio(key="mode").set_value(LIVE).run()
    chat = at.session_state["chat"]
    assert chat.live
    assert "Live calls ON" in at.warning[0].value
    at = send(at, f"{MARKER} hello")
    report = at.session_state["messages"][-1]["report"]
    assert report.failure == "budget_exhausted"
    assert requests == []  # refused before any HTTP request
    assert any("Nothing was charged" in w.value for w in at.warning)
    ledger = tmp_path / "spend" / "ledger.jsonl"
    assert not ledger.exists() or all(
        MARKER not in json.dumps(line) for line in ledger.read_text().splitlines()
    )
