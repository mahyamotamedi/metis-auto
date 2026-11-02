"""Redis ``CacheStore`` (plan T-1, CMP-11; FR-XCACHE-08, QA-REPL).

Responsibility: hold answer-cache entries in a Redis server, one value per key
fingerprint, serialised with the contract's JSON (``CacheEntry`` round-trips).
Like the in-memory store it applies **no** validity rule: no TTL, no Redis
expiry, no status or scope check (ADR-0011 point 5; stores hold data, policies
decide).

Keys: ``<namespace>|<fingerprint>``, where ``redis_namespace(prefix,
key_version)`` is ``<key_version>|<prefix>``, the encoding of
``analysis.cache_guard.versioned_key``. A key-schema bump therefore starts from
an empty namespace; old entries stay in Redis until removed by an operator.

This module imports no Redis library. ``redis_client`` imports ``redis`` lazily
(the planned ``services`` extra, T-0), and the password, if any, comes only
from ``METIS_REDIS_PASSWORD`` in the process environment, never from config or
``.env``, and never appears in an error.

Built by: ``wiring.from_settings.cache_store`` (``[cache] store = "redis"``).
Called by: ``application.pipeline`` through the ``CacheStore`` port. Content
(answers) lives only in the server. Status: provisional (demo store).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Protocol

from metis_auto.contracts import CacheEntry, Fingerprint

SEPARATOR = "|"
PASSWORD_ENV = "METIS_REDIS_PASSWORD"


class RedisLike(Protocol):
    """The two client calls the store uses (``redis.Redis`` satisfies it)."""

    def get(self, name: str) -> bytes | str | None: ...

    def set(self, name: str, value: str) -> Any: ...


def redis_namespace(prefix: str, key_version: str) -> str:
    """``<key_version>|<prefix>`` (``cache_guard.versioned_key`` encoding)."""
    if not key_version or SEPARATOR in key_version:
        raise ValueError(f"key_version must be non-empty and contain no {SEPARATOR!r}")
    if not prefix:
        raise ValueError("prefix must be non-empty")
    return f"{key_version}{SEPARATOR}{prefix}"


class RedisCacheStore:
    def __init__(self, client: RedisLike, *, namespace: str) -> None:
        if not namespace:
            raise ValueError("namespace must be non-empty")
        self._client = client
        self._namespace = namespace

    def _key(self, key: str) -> str:
        return f"{self._namespace}{SEPARATOR}{key}"

    def get(self, key: Fingerprint) -> CacheEntry | None:
        raw = self._client.get(self._key(key))
        if raw is None:
            return None
        return CacheEntry.model_validate_json(raw)

    def put(self, entry: CacheEntry) -> None:
        self._client.set(self._key(entry.key.key), entry.model_dump_json())


def redis_client(
    *, host: str, port: int, db: int, environ: Mapping[str, str] | None = None
) -> RedisLike:
    """A ``redis.Redis`` client. Needs the ``redis`` package (not in the default
    install). Connection details come from settings; the password only from
    ``METIS_REDIS_PASSWORD`` in ``environ`` (default ``os.environ``)."""
    try:
        import redis
    except ImportError:
        raise RuntimeError(
            "the redis package is not installed; it belongs to the planned "
            "'services' extra (T-0). Use [cache] store = \"memory\" without it."
        ) from None
    env = os.environ if environ is None else environ
    try:
        return redis.Redis(host=host, port=port, db=db, password=env.get(PASSWORD_ENV))
    except Exception as exc:
        raise RuntimeError(
            f"could not create a Redis client for {host}:{port} db {db} "
            f"({type(exc).__name__})"
        ) from None
