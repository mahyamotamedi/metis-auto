# ADR-0034: Cache guard: versioned key encoding, fixed check order, per-key shadow sample

- Status: **decided** for the sprint's offline cache versions, 2026-11-02 (Pipeline B, task S-5). The `refusal` method is an **addition** to the plan's frozen `CacheGuard` contract and needs the team's OK. The default shadow rate stays in shared configuration (`sprint.toml`, S-3), which does not exist yet.
- Date: 2026-11-02
- Relates to: [ADR-0011](0011-cache-key-and-lookup-design.md), [ADR-0015](0015-keyed-content-fingerprints.md), [ADR-0016](0016-curated-cache-and-traffic-source-scope.md); sprint plan S-5 and "Shared interfaces"; FR-XCACHE-01, FR-XCACHE-04, FR-XCACHE-07, FR-XCACHE-09, H-3, QA-PRIV.

## Context
The plan freezes `CacheGuard(approved: frozenset[str] | None, blocked: frozenset[str], disabled_bots: frozenset[str], key_version: str)` with `allows(key, bot) -> bool` and `shadow_sample(keys, rate, seed) -> pd.Series`. Every cache version (R-A1, R-B1, R-C1) calls `allows` before counting a hit. The plan does not say how a key carries its version, in which order the checks apply, or how the shadow sample is drawn.

## Decision
1. **Key encoding:** `"<key_version>|<body>"`, built by `analysis.cache_guard.versioned_key`. `key_version` is non-empty with no `|`, and the body is non-empty. A guard accepts only keys with exactly its own version prefix (`v10|...` is not a `v1` key). `approved` and `blocked` hold whole versioned keys, so changing `key_version` retires every old key and approval at once. Bodies come from text normalised by `analysis.text_features.normalize_safe` (the caller's job). The guard sees strings only.
2. **Check order:** disabled bot, then blocked, then approval (`None` = no gate; an empty set approves nothing), then key version. `refusal(key, bot)` returns the first failing check's name (`disabled_bot`, `blocked`, `not_approved`, `key_version`) or `None`. `allows` is `refusal(...) is None`. The reason makes the order testable, and the D-2 cache monitor can count guard blocks by reason.
3. **Shadow sample:** a row is selected when `blake2b(seed, key)` mapped to [0, 1) falls below `rate`. The result is deterministic for a seed, independent of row order, aligned with the input index, and **per key** (all rows of a key are selected together). Missing keys are never selected. `rate` is validated (0 ≤ rate ≤ 1, finite, not boolean) and **has no default**. Selection is not a check result: comparing the cached result with the later real lookup is the cache version's job (R-B1, Day 2), and missing lookup evidence is "unknown".

## Alternatives considered
- **A separate `key_version` argument to `allows`**: changes the frozen signature. Rejected.
- **Row-wise random sampling** (`numpy` draw per row): depends on row order and samples the same key inconsistently. Rejected.
- **A hidden 1% default**: the plan puts the default in shared configuration. A code default would drift from it. Rejected.

## Consequences
- Guarding tests: `tests/unit/analysis/test_cache_guard.py` (the plan's five tests, plus check order, rate validation without a default, missing keys, and field validation).
- Every cache version must build its keys with `versioned_key` under the guard's version. A key built any other way is refused (`key_version`).
- When keys are mostly repeated, the shadow rate applies to distinct keys rather than to rows. Reports must say which.
