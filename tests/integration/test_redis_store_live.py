"""Redis ``CacheStore`` against a real server (plan T-1). Opt-in by
availability: skipped unless the ``redis`` package is importable **and** the
configured server (``[cache] redis_host`` / ``redis_port``) answers a ping. No
new pytest marker: the plan's ``services`` marker and extra belong to T-0
(Parham) and do not exist yet; the patch is in
``docs/experiments/pipeline_b_interim_contracts_day3.md`` (Day 3). The password, if
any, comes only from ``METIS_REDIS_PASSWORD`` in the process environment.
SYNTHETIC entries; every key written is deleted afterwards."""

import uuid

import pytest
from fixtures.synthetic import contract_examples as ex

pytest.importorskip("redis")


@pytest.fixture
def client():
    from metis_auto.adapters.stores.redis_store import redis_client
    from metis_auto.settings import load_settings

    cfg = load_settings(runtime=None, dotenv=None).settings.cache
    try:
        c = redis_client(host=cfg.redis_host, port=cfg.redis_port, db=cfg.redis_db)
        c.ping()
    except Exception:
        pytest.skip("no Redis server answers at the configured host and port")
    yield c


def test_round_trip_on_a_real_server(client):
    from metis_auto.adapters.stores.redis_store import RedisCacheStore, redis_namespace

    namespace = redis_namespace(f"metis-live-test-{uuid.uuid4().hex[:8]}", "ks-1")
    store = RedisCacheStore(client, namespace=namespace)
    e = ex.cache_entry()
    try:
        assert store.get(e.key.key) is None
        store.put(e)
        assert store.get(e.key.key) == e
        assert client.ttl(f"{namespace}|{e.key.key}") == -1  # no expiry set
    finally:
        client.delete(f"{namespace}|{e.key.key}")
