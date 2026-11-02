"""Redis ``CacheStore`` adapter and the ``[cache] store`` switch (plan T-1;
FR-XCACHE-08, ADR-0011 point 5, QA-REPL). Fake client only; no server, no
``redis`` package needed. SYNTHETIC entries from the contract examples."""

from __future__ import annotations

import ast
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fake_redis import FakeRedis
from fixtures.synthetic import contract_examples as ex

from metis_auto.adapters.stores import InMemoryCacheStore, redis_store
from metis_auto.adapters.stores.redis_store import RedisCacheStore, redis_namespace
from metis_auto.analysis.cache_guard import versioned_key
from metis_auto.contracts import CacheEntry
from metis_auto.ports import CacheStore
from metis_auto.settings import SettingsError, load_settings
from metis_auto.wiring.from_settings import cache_store

NS = redis_namespace("metis-test", "ks-1")


def entry(answer: str = "[SYNTHETIC] answer", key: str | None = None) -> CacheEntry:
    base = ex.cache_entry()
    update: dict = {"answer": answer}
    if key is not None:
        update["key"] = base.key.model_copy(update={"key": key})
    return base.model_copy(update=update)


def load(**overrides):
    return load_settings(environ={}, dotenv=None, runtime=None, overrides=overrides)


def test_put_then_get_round_trips_a_cache_entry():
    store = RedisCacheStore(FakeRedis(), namespace=NS)
    e = entry()
    store.put(e)
    assert store.get(e.key.key) == e
    assert isinstance(store, CacheStore)


def test_missing_key_returns_none():
    assert RedisCacheStore(FakeRedis(), namespace=NS).get(entry().key.key) is None


def test_put_replaces_previous_entry():
    client = FakeRedis()
    store = RedisCacheStore(client, namespace=NS)
    store.put(entry("[SYNTHETIC] first"))
    store.put(entry("[SYNTHETIC] second"))
    assert store.get(entry().key.key).answer == "[SYNTHETIC] second"
    assert len(client.data) == 1


def test_store_applies_no_ttl_or_validity_rules():
    from metis_auto.contracts.caching import EntryStatus

    client = FakeRedis()
    store = RedisCacheStore(client, namespace=NS)
    old = entry().model_copy(
        update={
            "status": EntryStatus.INVALIDATED,
            "created_at": datetime(2000, 1, 1, tzinfo=UTC),
        }
    )
    store.put(old)
    assert store.get(old.key.key) == old  # status and age are the policy's job
    assert [c[0] for c in client.calls] == ["set", "get"]
    assert all(kwargs == {} for _, _, kwargs in client.calls)  # no ex/px/keepttl


def test_keys_are_namespaced_by_key_version():
    client = FakeRedis()
    v1 = RedisCacheStore(client, namespace=redis_namespace("metis-test", "ks-1"))
    v2 = RedisCacheStore(client, namespace=redis_namespace("metis-test", "ks-2"))
    e = entry()
    v1.put(e)
    assert v2.get(e.key.key) is None  # a key-version bump starts empty
    (stored,) = client.data
    assert stored == f"{versioned_key('ks-1', 'metis-test')}|{e.key.key}"
    assert stored.startswith("ks-1|")
    for bad in ("", "ks|1"):
        with pytest.raises(ValueError):
            redis_namespace("metis-test", bad)


def test_store_module_imports_no_redis_library():
    tree = ast.parse(Path(redis_store.__file__).read_text(encoding="utf-8"))
    top = [n for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)]
    names = {a.name for n in top for a in n.names} | {
        n.module for n in top if isinstance(n, ast.ImportFrom)
    }
    assert not any(str(x).startswith("redis") for x in names)


def test_redis_factory_raises_clear_error_when_package_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "redis", None)
    with pytest.raises(RuntimeError, match="redis package is not installed"):
        redis_store.redis_client(host="localhost", port=6379, db=0, environ={})


def fake_redis_module(record: dict, fail_with: str | None = None):
    module = types.ModuleType("redis")

    class Redis:
        def __init__(self, **kwargs):
            record.update(kwargs)
            if fail_with is not None:
                raise ConnectionError(fail_with)

    module.Redis = Redis
    return module


def test_password_comes_only_from_the_environment_and_never_in_errors(monkeypatch):
    record: dict = {}
    monkeypatch.setitem(sys.modules, "redis", fake_redis_module(record))
    redis_store.redis_client(host="h", port=1, db=2, environ={})
    assert record["password"] is None
    redis_store.redis_client(
        host="h", port=1, db=2, environ={"METIS_REDIS_PASSWORD": "s3cret-synthetic"}
    )
    assert record["password"] == "s3cret-synthetic"
    assert (record["host"], record["port"], record["db"]) == ("h", 1, 2)
    failing = fake_redis_module({}, fail_with="auth failed for s3cret-synthetic")
    monkeypatch.setitem(sys.modules, "redis", failing)
    with pytest.raises(RuntimeError) as info:
        redis_store.redis_client(
            host="h", port=1, db=2, environ={"METIS_REDIS_PASSWORD": "s3cret-synthetic"}
        )
    assert "s3cret-synthetic" not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


# --- the [cache] store switch ---


def test_default_cache_store_is_memory_and_changes_nothing_else():
    loaded = load()
    assert loaded.settings.cache.store == "memory"
    assert isinstance(cache_store(loaded), InMemoryCacheStore)
    switched = load(**{"cache.store": "redis"})
    assert switched.config_hash == loaded.config_hash
    assert switched.settings.model_dump(
        exclude={"cache"}
    ) == loaded.settings.model_dump(exclude={"cache"})
    with pytest.raises(SettingsError):
        load(**{"cache.store": "memcached"})
    with pytest.raises(SettingsError):
        load(**{"cache.redis_password": "x"})  # no secret field in config


def test_redis_switch_builds_a_redis_store_namespaced_by_the_key_version(monkeypatch):
    client = FakeRedis()
    seen = {}

    def factory(**kw):
        seen.update(kw)
        return client

    monkeypatch.setattr(redis_store, "redis_client", factory)
    loaded = load(**{"cache.store": "redis", "cache.redis_namespace": "demo"})
    store = cache_store(loaded)
    assert isinstance(store, RedisCacheStore)
    assert seen == {"host": "localhost", "port": 6379, "db": 0}
    store.put(entry())
    (key,) = client.data
    assert key.startswith("ks-1|demo|")


def test_chat_session_uses_the_configured_store(tmp_path, monkeypatch):
    from metis_auto.adapters.providers import FakeModelClient
    from metis_auto.wiring.chat import ChatSession

    client = FakeRedis()
    monkeypatch.setattr(redis_store, "redis_client", lambda **kw: client)

    def loader(store):
        def load_(overrides):
            return load_settings(
                overrides={
                    **overrides,
                    "cache.store": store,
                    "paths.spend_ledger": str(tmp_path / "spend" / "ledger.jsonl"),
                    "paths.recorded_dir": str(tmp_path / "recorded"),
                },
                runtime=None,
                dotenv=None,
                environ={},
            )

        return load_

    def chat(store):
        return ChatSession(
            live=False,
            instructions="[SYNTHETIC] demo bot",
            settings_loader=loader(store),
            client_factory=lambda _l, _r: FakeModelClient(),
        )

    plain = chat("memory")
    assert isinstance(plain._store, InMemoryCacheStore)
    redis_chat = chat("redis")
    assert isinstance(redis_chat._store, RedisCacheStore)
    store = redis_chat._store
    redis_chat._rebuild()
    assert redis_chat._store is store  # one store for the session, kept on rebuild
