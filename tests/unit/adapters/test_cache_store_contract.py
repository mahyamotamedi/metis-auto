"""One ``CacheStore`` contract, run against every store (plan T-1:
``test_same_behaviour_as_in_memory_store``; FR-XCACHE-08, QA-REPL). SYNTHETIC
entries; the Redis store runs on a fake client."""

from __future__ import annotations

import pytest
from fake_redis import FakeRedis
from fixtures.synthetic import contract_examples as ex

from metis_auto.adapters.stores import InMemoryCacheStore
from metis_auto.adapters.stores.redis_store import RedisCacheStore, redis_namespace

STORES = {
    "memory": InMemoryCacheStore,
    "redis": lambda: RedisCacheStore(
        FakeRedis(), namespace=redis_namespace("metis-test", "ks-1")
    ),
}
OTHER_KEY = "fp1:" + "b" * 64


def entry(answer: str, key: str | None = None):
    base = ex.cache_entry()
    update: dict = {"answer": answer}
    if key is not None:
        update["key"] = base.key.model_copy(update={"key": key})
    return base.model_copy(update=update)


def behaviour(store) -> list[object]:
    """What a caller can observe through the port, step by step."""
    a, b = entry("[SYNTHETIC] a"), entry("[SYNTHETIC] b", key=OTHER_KEY)
    seen: list[object] = [store.get(a.key.key)]
    store.put(a)
    seen.append(store.get(a.key.key))
    seen.append(store.get(OTHER_KEY))
    store.put(b)
    store.put(entry("[SYNTHETIC] a2"))
    seen += [store.get(a.key.key), store.get(OTHER_KEY)]
    return seen


@pytest.mark.parametrize("name", sorted(STORES))
def test_store_contract(name):
    seen = behaviour(STORES[name]())
    assert seen[0] is None and seen[2] is None
    assert seen[1].answer == "[SYNTHETIC] a"
    assert seen[3].answer == "[SYNTHETIC] a2" and seen[4].answer == "[SYNTHETIC] b"


def test_same_behaviour_as_in_memory_store():
    assert behaviour(STORES["redis"]()) == behaviour(STORES["memory"]())
