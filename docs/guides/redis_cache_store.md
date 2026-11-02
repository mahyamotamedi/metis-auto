# Redis cache store (sprint task T-1)

The answer cache can keep its entries in Redis instead of process memory. Only the store changes: the cache policy, its key, its scope and its validity rules are the same code path ("added without touching the pipeline"; QA-REPL, FR-XCACHE-08, ADR-0011 point 5). Code: `src/metis_auto/adapters/stores/redis_store.py`, switch `wiring.from_settings.cache_store`, setting `[cache] store` (`settings.model.CacheStoreSettings`).

## Switch

```toml
# config/local.toml (machine-local; not in the config hash)
[cache]
store = "redis"          # default "memory": unchanged behaviour
redis_host = "localhost"
redis_port = 6379
redis_db = 0
redis_namespace = "metis-auto"
```

- **Default `memory`** changes nothing: the same `InMemoryCacheStore`, built once per chat session. `[cache]` is excluded from the config hash (tested: switching the store leaves the hash and every other setting unchanged).
- **`redis`**: needs the `redis` package and a server. The package belongs to the planned `services` extra and lock (T-0, Parham); neither exists yet, so without the package the switch fails with a clear error and `memory` keeps working.
- **Password:** only from `METIS_REDIS_PASSWORD` in the process environment. Never in `config/`, never from `.env`, never in an error message (tested).
- **Keys:** `<key_version>|<namespace>|<fingerprint>`, where the key version is `[pipeline.cache] key_schema_version` (the encoding of `analysis.cache_guard.versioned_key`). A key-schema bump starts from an empty namespace. The store sets **no expiry** and applies no TTL or status rule; the policy decides.
- Only the demo chat (`wiring.chat.ChatSession`, `scripts/chat.py`, `scripts/demo_ui.py`) uses the switch. Experiment runs and the walking skeleton keep a fresh in-memory store per run, so a replay never sees entries from another run.

## What a Redis hit shows, and what it does not

A demo hit read from Redis (for example a second synthetic user's greeting under the demo-only bot-level scope) demonstrates **the answer-cache adapter**: the same entry round-trips through a real server. It is **not evidence** of retrieval-cache savings (R-B1 is an offline replay of logged lookups and stores nothing in Redis), and it is **not evidence** that cross-user reuse is safe (hit correctness is reviewed separately, K-1; the demo bot-level scope is a placeholder, ADR-0023).

## Tests

- `tests/unit/adapters/test_redis_store.py`: fake client (`fake_redis.py`), round trip, missing key, replace, no TTL or expiry, namespacing by key version, no `redis` import in the module, clear error without the package, password handling, the switch and the chat session.
- `tests/unit/adapters/test_cache_store_contract.py`: one contract run against the in-memory and the Redis store.
- `tests/integration/test_redis_store_live.py`: skips unless `redis` is importable **and** the configured server answers a ping. No new pytest marker (the `services` marker is T-0's; patch in `docs/experiments/pipeline_b_interim_contracts_day3.md`, Day 3).

Docker: the Redis service in `compose.yaml` is T-4 (Parham) and does not exist yet. Until then, any local Redis on `127.0.0.1:6379` works for the live test.
