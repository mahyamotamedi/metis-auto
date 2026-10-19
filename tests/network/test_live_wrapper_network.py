"""Real-network smoke test of the live adapter (opt-in: --run-network).

Skipped by default (ADR-0003). When opted in it still needs the runtime's
``live.enabled = true`` and METIS_API_KEY, and it spends real money through
the spend guard and the persistent ledger: one tiny SYNTHETIC message to
gpt-4.1-nano (the cheapest per output token among the test models, with no
hidden reasoning). Use only with the owner's approval (ADR-0018).
"""

import pytest

from metis_auto.settings import load_settings
from metis_auto.wiring.chat import ChatSession
from metis_auto.wiring.from_settings import live_permission
from metis_auto.wiring.live import live_overrides

pytestmark = pytest.mark.network


def test_one_tiny_live_call():
    pytest.importorskip("openai")
    loaded = load_settings(overrides=live_overrides())
    permission = live_permission(loaded)
    if not permission.allowed:
        pytest.skip("live calls not enabled: " + "; ".join(permission.reasons))
    session = ChatSession("gpt-4.1-nano", live=True, single_attempt=True)
    response, report = session.ask("[SYNTHETIC] Reply with the word OK.")
    assert response.answer
    assert "provider_reported" in report.tokens["input"]
