# ADR-0011: Cache key and lookup design — fingerprinted components, partition key plus similarity, unknown never matches

- Status: **decided** (structure). Validity rules, TTLs, and thresholds are **provisional**. The final sharing policy stays **open** (Q-16).
- Date: 2026-10-14
- Relates to: FR-XCACHE-01…09, FR-SCACHE-01…06, ADR-0007, ADR-0008, F-6, F-7
- Detail: [caching.md](../architecture/caching.md)

## Context
The sample signals that repeated requests are common, but that repeats usually differ in instructions, model, retrieved context, or history (F-6, F-7). These are provisional signals (ADR-0008); the design must not depend on their values. FR-XCACHE-02 already requires a configurable key whose serving default is the full composition. Stage 3 has to say how the key is built, how exact and semantic tiers relate, and what happens with components whose state is unknown.

## Decision
1. **A key is a keyed fingerprint ([ADR-0015](0015-keyed-content-fingerprints.md)) over ordered components:** key schema version, normalised message, instructions, history (full or windowed), retrieved context, structured-input config, the target's **equivalence group**, and the sharing scope. Attachments make a request ineligible by default.
2. **Unknown never matches.** A request with an unknown component in the serving key is ineligible. Offline variants may treat unknown as a wildcard, and say so.
3. **Two tiers, one partition key.** The partition key is every component except the message. The exact tier matches the whole key. The semantic tier matches the partition key exactly and the message by similarity, partitioned by embedder version.
4. **Narrow key variants are for measurement only**, unless marked `serving_allowed`, which needs a decision record with measured false-hit rates.
5. **Validity is checked at lookup and at store** by the cache policy (domain). Stores (`CacheStore`, `VectorIndex`) hold data and have no rules.
6. **Invalidation** by TTL and retention, by explicit operations (entry, scope, instruction group), and by construction (a key schema or embedder version change).

## Alternatives considered
- **Key on the message alone, with validity checks after the match.** This finds more candidates, but the sample signal suggests most would be unsafe. Kept as a measurement variant only.
- **Model ID in the key instead of the equivalence group.** Failover between equivalent models would split the cache for no quality reason. Rejected.
- **Semantic similarity over the whole prompt** (instructions, history, retrieval). That would hide the differences that make an answer invalid. Rejected (FR-SCACHE-02).
- **Treat unknown as absent.** This contradicts FR-REQ-04, and would turn logging gaps into false hits. Rejected.
- **Plain (unkeyed) hashes in keys.** See ADR-0015.

## Consequences
- The Stage 4 cache contracts need: component states, key variant, partition key, scope, embedder version, and a `serving_allowed` flag in the configuration schema.
- The Stage 8 exact-cache baseline computes candidates for several variants and scopes per request, outside the serving path.
- Changing the key composition is a key-schema version bump.
