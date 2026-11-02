"""Cache guard (S-5). Keys and bot labels are SYNTHETIC (``v1|synthetic-key-001``,
``bot-07``); no real key, ID or hash appears here."""

from __future__ import annotations

import dataclasses
import inspect

import numpy as np
import pandas as pd
import pytest

from metis_auto.analysis.cache_guard import CacheGuard, versioned_key

BOT = "bot-07"
OTHER_BOT = "bot-12"


def _guard(**overrides: object) -> CacheGuard:
    fields: dict[str, object] = {
        "approved": None,
        "blocked": frozenset(),
        "disabled_bots": frozenset(),
        "key_version": "v1",
    }
    return CacheGuard(**(fields | overrides))


def _key(body: str, version: str = "v1") -> str:
    return versioned_key(version, body)


def test_unapproved_key_is_never_served_when_approval_is_on():
    good, other = _key("synthetic-key-001"), _key("synthetic-key-002")

    gated = _guard(approved=frozenset({good}))
    assert gated.allows(good, BOT)
    assert not gated.allows(other, BOT)

    # An empty approved set approves nothing; None means no approval step.
    assert not _guard(approved=frozenset()).allows(good, BOT)
    assert _guard(approved=None).allows(other, BOT)


def test_blocked_key_is_never_served():
    key = _key("synthetic-key-001")
    for approved in (None, frozenset({key})):
        guard = _guard(approved=approved, blocked=frozenset({key}))
        assert not guard.allows(key, BOT)
        assert not guard.allows(key, OTHER_BOT)
    assert _guard(blocked=frozenset({key})).allows(_key("synthetic-key-002"), BOT)


def test_disabled_bot_is_never_served():
    key = _key("synthetic-key-001")
    guard = _guard(approved=frozenset({key}), disabled_bots=frozenset({BOT}))
    assert not guard.allows(key, BOT)
    assert guard.allows(key, OTHER_BOT)


def test_key_version_change_invalidates_old_keys():
    old = _key("synthetic-key-001", "v1")
    new = _key("synthetic-key-001", "v2")

    assert _guard(key_version="v1").allows(old, BOT)
    v2 = _guard(key_version="v2")
    assert not v2.allows(old, BOT)
    assert v2.allows(new, BOT)
    # Approvals made under v1 do not carry over to v2 keys.
    assert not _guard(key_version="v2", approved=frozenset({old})).allows(new, BOT)

    # The version is a whole prefix: "v10|..." is not a "v1" key.
    assert not _guard(key_version="v1").allows(_key("synthetic-key-001", "v10"), BOT)
    # Unversioned and empty-bodied keys are never allowed.
    assert not _guard().allows("synthetic-key-001", BOT)
    assert not _guard().allows("v1|", BOT)


def test_shadow_sample_is_seeded_and_about_the_given_rate():
    n = 100_000
    keys = pd.Series(
        [_key(f"synthetic-key-{i:06d}") for i in range(n)],
        index=pd.RangeIndex(10, 10 + n),  # not a default index: alignment matters
    )
    guard = _guard()

    first = guard.shadow_sample(keys, 0.01, seed=7)
    assert first.dtype == bool
    assert first.index.equals(keys.index)
    # About the rate: the binomial sd is ~0.0003 at n=100,000; allow ~6 sd.
    assert abs(first.mean() - 0.01) < 0.002
    # Seeded: the same seed gives the same rows, another seed other rows.
    assert first.equals(guard.shadow_sample(keys, 0.01, seed=7))
    assert not first.equals(guard.shadow_sample(keys, 0.01, seed=8))
    # Independent of row order: shuffling the input selects the same rows.
    order = np.random.default_rng(0).permutation(n)
    shuffled = guard.shadow_sample(keys.iloc[order], 0.01, seed=7)
    assert shuffled.sort_index().equals(first)
    # The edges.
    assert not guard.shadow_sample(keys, 0.0, seed=7).any()
    assert guard.shadow_sample(keys, 1.0, seed=7).all()


# --- Further behaviour from the S-5 spec ---


def test_checks_apply_in_order_disabled_bot_blocked_approval_version():
    stale = _key("synthetic-key-001", "v0")
    everything_wrong = _guard(
        approved=frozenset(),
        blocked=frozenset({stale}),
        disabled_bots=frozenset({BOT}),
    )
    assert everything_wrong.refusal(stale, BOT) == "disabled_bot"
    assert everything_wrong.refusal(stale, OTHER_BOT) == "blocked"
    assert _guard(approved=frozenset()).refusal(stale, BOT) == "not_approved"
    assert _guard(approved=frozenset({stale})).refusal(stale, BOT) == "key_version"
    assert _guard().refusal(_key("synthetic-key-001"), BOT) is None


def test_shadow_rate_is_validated_and_has_no_default():
    keys = pd.Series([_key("synthetic-key-001")])
    guard = _guard()
    for bad in (float("nan"), -0.01, 1.01, float("inf")):
        with pytest.raises(ValueError, match="rate"):
            guard.shadow_sample(keys, bad, seed=1)
    for bad in (True, "0.01", None):
        with pytest.raises(TypeError, match="rate"):
            guard.shadow_sample(keys, bad, seed=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="seed"):
        guard.shadow_sample(keys, 0.5, seed=1.5)  # type: ignore[arg-type]
    # The 1% default belongs to shared configuration, not to a hidden default.
    params = inspect.signature(CacheGuard.shadow_sample).parameters
    assert params["rate"].default is inspect.Parameter.empty
    assert params["seed"].default is inspect.Parameter.empty


def test_missing_key_is_never_selected_and_selection_is_per_key():
    keys = pd.Series([None, float("nan"), _key("synthetic-key-001")] * 2)
    picked = _guard().shadow_sample(keys, 1.0, seed=3)
    assert list(picked) == [False, False, True] * 2
    same = _guard().shadow_sample(keys, 0.5, seed=3)
    assert same.iloc[2] == same.iloc[5]  # one key is checked or not, everywhere
    with pytest.raises(TypeError, match="key"):
        _guard().shadow_sample(pd.Series([123]), 0.5, seed=3)


def test_guard_is_frozen_and_validates_its_fields():
    guard = _guard()
    with pytest.raises(dataclasses.FrozenInstanceError):
        guard.key_version = "v2"  # type: ignore[misc]
    for bad_version in ("", "v|1"):
        with pytest.raises(ValueError, match="key_version"):
            _guard(key_version=bad_version)
    with pytest.raises(TypeError, match="blocked"):
        _guard(blocked={"v1|synthetic-key-001"})  # a set, not a frozenset
    with pytest.raises(TypeError, match="approved"):
        _guard(approved=["v1|synthetic-key-001"])
    with pytest.raises(ValueError, match="key_version"):
        versioned_key("", "synthetic-key-001")
    with pytest.raises(ValueError, match="body"):
        versioned_key("v1", "")
