"""The Demo B UI live smoke test's plan (``wiring.demo_ui_check``), offline:
no call, no key; config/local.toml and .env are not read."""

from decimal import Decimal

from metis_auto.settings import load_settings
from metis_auto.wiring.demo_ui_check import APPROVED_TOTAL, OUTPUT_CAP, loader, plan


def hermetic(tmp_path):
    return lambda o: load_settings(
        overrides={**o, "paths.spend_ledger": str(tmp_path / "l.jsonl")},
        runtime=None,
        dotenv=None,
        environ={},
    )


def test_plan_estimates_every_call_and_stays_under_the_approval(tmp_path):
    rows, total, worst = plan(hermetic(tmp_path))
    assert [r.step for r in rows] == [
        "greeting",
        "first_substantive",
        "similar_follow_up",
        "coding_request",
        "second_user_greeting",
    ]
    assert [r.served_by for r in rows] == ["model"] * 4 + ["cache"]
    assert rows[-1].estimate == 0  # the second user's greeting is a cache hit
    assert rows[3].reason_code.startswith("sticky.reroute.coding_intent_appeared")
    assert all(r.estimate > 0 for r in rows[:4])
    assert Decimal(0) < total <= worst <= APPROVED_TOTAL


def test_loader_caps_output_and_the_run(tmp_path):
    loaded = loader(hermetic(tmp_path))({})
    assert loaded.settings.budget.run_cap == APPROVED_TOTAL
    assert loaded.settings.pipeline["context"]["max_output_tokens_cap"] == OUTPUT_CAP
