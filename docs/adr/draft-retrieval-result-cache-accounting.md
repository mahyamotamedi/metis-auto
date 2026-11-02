# ADR-XXXX (retrieval-result-cache-accounting): Retrieval-result cache accounting: fee block only, B-owned columns, declared agreement and freshness rules

- Status: **provisional** (Pipeline B, task R-B1, 2026-11-02). Items 1 and 2 touch the shared S-1 contract (`analysis/levers.py`, owner A) and need the owner's confirmation. Items 3 to 6 are B's own experiment rules.
- Date: 2026-11-02
- Relates to: [ADR-0034](0034-cache-guard-key-encoding-and-check-order.md) (guard), [ADR-0031](0031-full-data-lever-replay.md) and [ADR-0032](0032-lever-result-and-manifest-format.md) (on `main`); sprint plan R-B1, "Shared interfaces", Review Focus 1 and 4; FR-XCACHE-01, FR-XCACHE-04, H-3, QA-REPRO, QA-PRIV.

## Context
The shared contract says a cache version sets `served_from_cache = True` and zeroes every cost block on hit rows, and `combine` then skips context and routing for those rows. That is right for an answer cache. For a retrieval-result cache it is wrong: reusing chunks avoids only the lookup's fee. Answer generation still runs and still costs input, output and cached tokens. The log also has no corpus-version evidence, retrieval settings are a configuration snapshot, and billing items are not linked to the query they paid for.

## Decision
1. **Fee block only.** R-B1 lowers only `block_fees` on rows where a lookup is reused. It never sets `served_from_cache` and never touches `block_token_cost`, so context and routing still apply. It adds B-owned columns `retrieval_reused`, `retrieval_lookups_skipped` and `retrieval_fee_avoided`, which `combine` already carries ("any column a version adds"). Checked against the real `combine` (borrowed `levers.py`, blob `896092d`).
2. **Recorded fee block.** For R-B1 runs, `block_fees` is the message's recorded `costBreakdown.per_call` sum and `block_token_cost` is the recorded total minus that. This replaces the `with_blocks` proxy (0.002 per per-call item), so fee avoided and fee block share one source. Proposal to A: let `with_blocks` take recorded per-call sums when available.
3. **Fee attribution.** A lookup's fee is the recorded per-call amount only when the message has one per-call item per logged query and all its amounts are equal. Otherwise the fee is unknown and the lookup is not skippable. Each skipped lookup counts once.
4. **Freshness.** `ttl=None` means "no backstop expiry" and is allowed only with a known corpus version. With no version evidence (the whole dataset today), `ttl=None` gives no hits, and every hit under a TTL is labelled `ttl_only`. Versions and hashes are never invented.
5. **Agreement metric** (declared before running): Jaccard over `(chunk_id, content_hash)` pairs. A changed hash for the same ID counts as disagreement. Any unknown hash, or both sets empty, makes the result unknown. Decision rule: mean over evaluable hits ≥ 0.9.
6. **TTL rule** (tune data only): the largest TTL in {1, 7, 30, 90} days that passes item 5 with at least half the hits evaluable. On 2026-11-02 that is **1 day**.

## Alternatives considered
- **Set `served_from_cache` and zero the blocks** (the docstring rule): counts the whole answer as saved. Rejected (overstates savings; Review Focus 1).
- **A private `combine`** that understands partial savings: duplicates the shared contract. Rejected.
- **Average fee per lookup** (message fee ÷ queries) when counts differ: invents an attribution. Rejected.
- **Recall instead of Jaccard** (share of the real chunks present in the cache): ignores extra stale chunks the cache would add. Rejected.
- **`ttl=None` = never expire**: unbounded staleness with no version evidence. Rejected.

## Consequences
- Tests: `tests/unit/experiments/test_retrieval_result_cache.py` (the plan's six tests plus the guard, workflow, attribution, freshness and contract tests) and `test_retrieval_cache_run.py` (synthetic smoke run, real `LeverResult`).
- The combined waterfall shows R-B1's saving in the fee block only. If the owner rejects item 1, the combined run is blocked for R-B1, and its standalone fee accounting stays valid.
- Results are *simulation* with "measured potential, conditional on Metis-Auto being able to intercept retrieval" in `assumptions`, because the `LeverResult` evidence list has no "measured potential" (Q-B4).
