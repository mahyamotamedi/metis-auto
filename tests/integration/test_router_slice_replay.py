"""The slice replay (ADR-0047, R4) on a SYNTHETIC miniature
slice: the frozen records only, every scenario, counts and timings only, the router
cache on the second pass, and no dataset state ever reaching a hosted backend."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("pyarrow")

from integration.test_router_slice_build import make_repo, make_slice  # noqa: E402

from metis_auto.settings import load_settings  # noqa: E402
from metis_auto.wiring.router_replay import run_scenario  # noqa: E402
from metis_auto.wiring.router_slice import SliceRefused  # noqa: E402


def hermetic(overrides):
    return load_settings(environ={}, dotenv=None, runtime=None, overrides=overrides)


@pytest.fixture(scope="module")
def frozen(tmp_path_factory):
    repo, data, _ = make_repo(tmp_path_factory.mktemp("replay"))
    sl = make_slice(repo, data)
    sl.build()
    return sl, sl.frozen_records()


def test_only_the_committed_slice_is_replayed(frozen):
    sl, records = frozen
    assert len(records) == 100
    ids = sl.paths.reports / "ids.csv"
    original = ids.read_bytes()
    try:
        ids.write_bytes(original.replace(b"tune", b"check", 1))
        with pytest.raises(SliceRefused, match="frozen"):
            sl.frozen_records()
    finally:
        ids.write_bytes(original)
    assert len(sl.frozen_records()) == 100


def test_router_off_replays_without_decisions(frozen):
    _, records = frozen
    out = run_scenario(hermetic, records, "off")
    assert out["router"]["built"] is False and len(out["passes"]) == 1
    first = out["passes"][0]
    assert sum(first["responses"].values()) == 100
    assert first["decision_status"] == {}
    assert set(first["router_paths"]) <= {
        "fallback_rules",
        "fallback_safe_tier",
        "fast_rules",
        "none",
    }


def test_local_replay_decides_and_the_second_pass_hits_the_router_cache(frozen):
    _, records = frozen
    out = run_scenario(hermetic, records, "local", passes=2)
    one, two = out["passes"]
    assert sum(one["decision_status"].values()) == 100
    assert one["decision_status"].get("answered", 0) > 0
    assert one["router_cache_hits"] < two["router_cache_hits"]
    assert two["router_cache_hits"] == two["decision_status"].get("answered", 0)
    assert one["decision_step_ms"]["n"] == 100
    assert out["router"]["cache_entries"] > 0
    assert out["router"]["hosted_calls"] == 0


def test_dataset_states_never_reach_the_hosted_backend(frozen):
    _, records = frozen
    out = run_scenario(hermetic, records, "hosted_refused", passes=1)
    first = out["passes"][0]
    assert out["router"]["hosted_calls"] == 0
    refused = first["hosted_refused_not_approved"].get("fake_hosted", 0)
    asked = first["decision_status"].get("answered", 0) + first["decision_status"].get(
        "failed", 0
    )
    assert refused == asked > 0
    assert first["overhead_cost_usd"] == "0"
    assert out["router"]["spend_guard_stopped"] is False


def test_the_replay_output_holds_no_text(frozen):
    _, records = frozen
    out = run_scenario(hermetic, records, "local", passes=1)
    text = json.dumps(out, ensure_ascii=False)
    assert "[SYNTHETIC]" not in text
    for r in records[:20]:
        assert r["message"] not in text


def test_requests_without_a_target_are_broken_down_by_reason(frozen):
    _, records = frozen
    first = run_scenario(hermetic, records, "off")["passes"][0]
    breakdown = first["no_target_by_reason"]
    assert sum(breakdown.values()) == first["target_models"].get("none", 0)
    for key in breakdown:
        reason, eligible, excluded, attachments = key.split("|")
        assert reason == "no_eligible_model" and eligible.startswith("eligible=")
        assert attachments.startswith("attachments=")


def test_the_thx01_scenario_uses_the_configured_backend_and_falls_back_honestly(
    frozen, tmp_path
):
    """R5: ``thx01`` builds the real backend from settings. Here (no pinned files
    under the test's asset root) it is unavailable, so every decision that was
    asked for fails as unavailable and routing falls back: counted, not hidden."""
    _, records = frozen

    def load(overrides):
        return hermetic({**overrides, "paths.router_assets": str(tmp_path)})

    out = run_scenario(load, records, "thx01", passes=1)
    assert out["router"]["built"] is True and out["router"]["mode"] == "local"
    first = out["passes"][0]
    asked = sum(first["decision_status"].values())
    assert asked > 0 and first["decision_status"].get("answered", 0) == 0
    assert out["router"]["hosted_calls"] == 0
