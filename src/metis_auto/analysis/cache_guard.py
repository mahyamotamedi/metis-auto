"""Cache guard: approval, blocklist, per-bot off switch, key versions and a seeded
shadow sample (S-5; FR-XCACHE-01, FR-XCACHE-04, FR-XCACHE-07, FR-XCACHE-09, H-3,
QA-PRIV; ADR-0034).

Every offline cache version calls ``allows`` before it counts a hit (final plan,
"Shared interfaces"). The guard decides from key strings and bot labels only. It
never sees text: callers build the key body from text normalised with
``analysis.text_features.normalize_safe`` (the one Persian normaliser) and pass
only the resulting string.

**Key encoding.** A guarded key is ``"<key_version>|<body>"``, built with
``versioned_key``. ``key_version`` is non-empty and has no ``|``, and the body is
non-empty. ``allows`` accepts a key only if it starts with this guard's own
``key_version`` followed by ``|``. A key built under another version (``v0|...``,
or ``v10|...`` for a ``v1`` guard), an unversioned key and an empty body are never
allowed. ``approved`` and ``blocked`` hold whole versioned keys, so a version
change also retires the old approvals.

**Check order** (``refusal`` returns the first that fails; ``allows`` is
``refusal(...) is None``):

1. ``disabled_bot``: the bot is in ``disabled_bots`` (the per-bot off switch);
2. ``blocked``: the key is in ``blocked``;
3. ``not_approved``: an approval gate is on (``approved`` is not ``None``) and the
   key is not in it. An empty set approves nothing; ``None`` means no approval step;
4. ``key_version``: the key was not built under this guard's ``key_version``.

**Shadow sample.** ``shadow_sample`` only *selects* the rows whose cached result is
to be checked against the later real lookup. Selection is not a completed check,
and this module reports no check result: the comparison belongs to the cache
version (R-B1, Day 2). For a selected row, missing lookup evidence is "unknown",
never "agrees". The rate has no default here. The plan's 1% lives in shared
configuration (``config/evaluation/sprint.toml``, S-3; interim until it exists:
docs/experiments/pipeline_b_interim_contracts.md), and callers pass it.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from numbers import Real
from typing import Literal

import pandas as pd

SEPARATOR = "|"
Refusal = Literal["disabled_bot", "blocked", "not_approved", "key_version"]


def versioned_key(key_version: str, body: str) -> str:
    """The guarded key for ``body`` under ``key_version``."""
    _check_version(key_version)
    if not isinstance(body, str) or not body:
        raise ValueError("key body must be a non-empty string")
    return f"{key_version}{SEPARATOR}{body}"


@dataclass(frozen=True)
class CacheGuard:
    approved: frozenset[str] | None
    blocked: frozenset[str]
    disabled_bots: frozenset[str]
    key_version: str

    def __post_init__(self) -> None:
        if self.approved is not None and not isinstance(self.approved, frozenset):
            raise TypeError("approved must be a frozenset or None")
        for name in ("blocked", "disabled_bots"):
            if not isinstance(getattr(self, name), frozenset):
                raise TypeError(f"{name} must be a frozenset")
        _check_version(self.key_version)

    def allows(self, key: str, bot: str) -> bool:
        """True only if every check passes (see the module docstring)."""
        return self.refusal(key, bot) is None

    def refusal(self, key: str, bot: str) -> Refusal | None:
        """The first check that refuses ``key`` for ``bot``, in the documented
        order; ``None`` if the key may be served."""
        if bot in self.disabled_bots:
            return "disabled_bot"
        if key in self.blocked:
            return "blocked"
        if self.approved is not None and key not in self.approved:
            return "not_approved"
        prefix = f"{self.key_version}{SEPARATOR}"
        if not (key.startswith(prefix) and len(key) > len(prefix)):
            return "key_version"
        return None

    def shadow_sample(self, keys: pd.Series, rate: float, seed: int) -> pd.Series:
        """Boolean series aligned with ``keys.index``: True for rows to shadow-check.

        Each key is selected when a seeded hash of (seed, key) falls below
        ``rate``, so the result is deterministic for a seed, independent of row
        order, about ``rate`` of distinct keys, and per key (every row of a
        selected key is selected). Missing keys are never selected.

        There is no default rate: callers pass ``[cache_guard] shadow_rate`` from
        ``config/evaluation/sprint.toml`` (0.01, plan S-5).
        """
        _check_rate(rate)
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("seed must be an int")
        threshold = float(rate)

        def pick(key: object) -> bool:
            if key is None or (isinstance(key, float) and math.isnan(key)):
                return False
            if not isinstance(key, str):
                raise TypeError("each key must be a string or missing")
            return _unit(seed, key) < threshold

        return keys.map(pick).astype(bool).rename("shadow")


def _check_version(key_version: object) -> None:
    if not isinstance(key_version, str) or not key_version:
        raise ValueError("key_version must be a non-empty string")
    if SEPARATOR in key_version:
        raise ValueError(f"key_version must not contain {SEPARATOR!r}")


def _check_rate(rate: object) -> None:
    if isinstance(rate, bool) or not isinstance(rate, Real):
        raise TypeError("rate must be a real number")
    if math.isnan(rate) or not 0.0 <= rate <= 1.0:
        raise ValueError("rate must be within [0, 1] (NaN is refused)")


def _unit(seed: int, key: str) -> float:
    """A uniform number in [0, 1) from (seed, key); stable across runs."""
    digest = hashlib.blake2b(f"{seed}\x1f{key}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2**64
