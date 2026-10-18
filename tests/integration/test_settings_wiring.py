"""Settings → pipeline (ADR-0018, ADR-0019): the real Metis config builds a
valid ``PipelineConfig``; the walking skeleton runs from its config profile
with the config hash in every event; live calls need every key. Offline,
synthetic secrets, no calls."""

import json
import shutil

import pytest

from metis_auto.adapters.providers import FakeModelClient
from metis_auto.adapters.sinks import InMemoryEventSink
from metis_auto.adapters.stores import InMemoryCacheStore
from metis_auto.contracts import AnswerSource, RunMode
from metis_auto.settings import SettingsError, load_settings, repo_root
from metis_auto.wiring.from_settings import (
    build_pipeline_from_settings,
    fingerprint_key,
    live_permission,
    pipeline_config,
    spend_ledger,
)
from metis_auto.wiring.walking_skeleton import demo_requests, skeleton_settings

SYNTHETIC_API_KEY = "SYNTHETIC-not-a-real-metis-key-0002"
SYNTHETIC_FP_HEX = "ab" * 32


def load(**kwargs):
    kwargs.setdefault("environ", {})
    return load_settings(dotenv=None, runtime=None, **kwargs)


def live_env() -> dict[str, str]:
    return {
        "METIS_API_KEY": SYNTHETIC_API_KEY,
        "METIS__LIVE__ENABLED": "true",
        "METIS__EXPERIMENT__COUNTERFACTUAL_SOURCE": "live",
    }


class LiveLookingClient(FakeModelClient):
    """A fake that claims to be live, to exercise the refusal paths only."""

    @property
    def source(self) -> AnswerSource:
        return AnswerSource.LIVE


def test_default_metis_config_builds_a_valid_pipeline_config():
    config = pipeline_config(load())
    assert config.routing.policy == "fixed_model"
    assert config.routing.fixed_model.model_id == "gpt-4o-mini"
    assert config.catalogue.version == "cat-metis-test-2026-10-18-s75"
    assert config.prices.version == "prices-metis-2026-10-18-s75"


def test_unknown_pipeline_keys_are_caught_by_the_policy_types():
    loaded = load(overrides={"pipeline.cache.ttl_secs": 60})
    with pytest.raises(SettingsError, match="pipeline"):
        pipeline_config(loaded)


def test_walking_skeleton_runs_from_its_profile_with_the_config_hash():
    loaded = skeleton_settings()
    assert loaded.reference.catalogue.version == "cat-synthetic-skeleton-1"
    assert loaded.reference.endpoints is None
    sink = InMemoryEventSink()
    pipeline = build_pipeline_from_settings(
        loaded,
        model_client=FakeModelClient(),
        cache_store=InMemoryCacheStore(),
        sink=sink,
        run_id="run-settings-test",
        run_mode=RunMode.SIMULATED,
    )
    statuses = [pipeline.handle(r).status for r in demo_requests()]
    assert statuses == ["ok", "ok", "ok"]
    assert sink.events
    assert {e.versions.config_hash for e in sink.events} == {loaded.config_hash}


def test_live_permission_lists_every_missing_key():
    permission = live_permission(load())
    assert not permission.allowed
    assert len(permission.reasons) == 3  # source, live.enabled, API key
    assert live_permission(load(environ=live_env())).allowed


def test_live_client_refused_without_permission():
    with pytest.raises(SettingsError, match="live calls refused"):
        build_pipeline_from_settings(
            skeleton_settings(),
            model_client=LiveLookingClient(),
            cache_store=InMemoryCacheStore(),
            sink=InMemoryEventSink(),
            run_id="run-refused",
            run_mode=RunMode.LIVE,
        )


def test_permitted_live_client_gets_the_persistent_ledger(tmp_path):
    env = live_env() | {"METIS__PATHS__SPEND_LEDGER": str(tmp_path / "l.jsonl")}
    loaded = load(environ=env)
    book = spend_ledger(loaded, "run-x")
    assert book.path == tmp_path / "l.jsonl"
    assert str(book.remaining().amount) == "1"  # the run cap binds first


def test_relative_ledger_path_resolves_against_the_config_root(tmp_path):
    cfg = tmp_path / "config"
    shutil.copytree(
        repo_root() / "config", cfg, ignore=shutil.ignore_patterns("local.toml")
    )
    loaded = load_settings(config_dir=cfg, environ={}, dotenv=None, runtime=None)
    assert spend_ledger(loaded, "r").path == tmp_path / "data/spend/ledger.jsonl"


def test_fingerprint_key_from_env_or_ephemeral_or_refused():
    keyed = load(environ={"METIS_FINGERPRINT_KEY": SYNTHETIC_FP_HEX})
    assert fingerprint_key(keyed) == bytes.fromhex(SYNTHETIC_FP_HEX)
    assert len(fingerprint_key(load())) == 32
    strict = load(overrides={"dev.ephemeral_fingerprint_key": False})
    with pytest.raises(SettingsError, match="METIS_FINGERPRINT_KEY"):
        fingerprint_key(strict)


def test_events_never_carry_secrets():
    profile = repo_root() / "config/profiles/walking_skeleton.toml"
    env = {
        "METIS_FINGERPRINT_KEY": SYNTHETIC_FP_HEX,
        "METIS_API_KEY": SYNTHETIC_API_KEY,
    }
    loaded = load(experiment=profile, environ=env)
    sink = InMemoryEventSink()
    pipeline = build_pipeline_from_settings(
        loaded,
        model_client=FakeModelClient(),
        cache_store=InMemoryCacheStore(),
        sink=sink,
        run_id="run-secret-check",
        run_mode=RunMode.SIMULATED,
    )
    for request in demo_requests():
        pipeline.handle(request)
    dumped = json.dumps([e.model_dump(mode="json") for e in sink.events])
    assert SYNTHETIC_FP_HEX not in dumped
    assert SYNTHETIC_API_KEY not in dumped
    assert loaded.config_hash in dumped
