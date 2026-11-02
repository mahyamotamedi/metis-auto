"""A small in-memory stand-in for a Redis client (T-1 tests). SYNTHETIC: holds
only what a test puts in it, and records every call so tests can prove that
the store never asks for an expiry."""

from __future__ import annotations


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.calls: list[tuple[str, tuple, dict]] = []

    def get(self, name: str) -> bytes | None:
        self.calls.append(("get", (name,), {}))
        return self.data.get(name)

    def set(self, name: str, value: str | bytes, **kwargs) -> bool:
        self.calls.append(("set", (name, value), kwargs))
        self.data[name] = value.encode() if isinstance(value, str) else value
        return True

    def expire(self, name: str, seconds: int) -> bool:  # must never be called
        self.calls.append(("expire", (name, seconds), {}))
        return True
