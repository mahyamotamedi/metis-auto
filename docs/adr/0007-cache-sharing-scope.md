# ADR-0007: Cache sharing scope — session by default, configurable, opportunity measured separately

- Status: **decided** (the default and configurability). The final production policy is **open** (Q-16).
- Date: 2026-10-14
- Relates to: FR-XCACHE-05, FR-SCACHE-01, Q-16, A-09

## Context
Serving a cached answer to a different session or user can leak content or personalised answers. Repeated requests appear across sessions in the sample, but the brief says the dataset does not distinguish users. Whether cross-session or cross-user reuse is acceptable is a product/privacy decision. The size of the opportunity is unknown.

## Decision
1. Every cache entry carries a **sharing scope**: `session`, `user`, or `global`. It is configuration, used by both exact and semantic caches.
2. **The default for anything serving users is `session`.**
3. Offline experiments measure reuse candidates at **each scope separately**: within-session, cross-session (same user), and cross-user. Results then quantify the opportunity before anyone decides a wider scope.
4. Cross-user measurement needs a privacy-safe user identifier. The sample has none, so it is reported as "unmeasured" until the data provides one.
5. Instruction group, model, RAG state, and history remain **key components** (FR-XCACHE-02), independent of scope.

## Alternatives considered
- **Global by default.** Rejected: it has the highest leak risk, and there is no evidence yet that it is safe.
- **No cross-session measurement until the policy is decided.** Rejected: the decision then has no evidence to rest on.
- **Instruction group as a scope level.** Rejected: it is a key component, and keeping the two separate stops the concepts from mixing.

## Consequences
- The cache contracts (Stage 4) need a scope field, and requests need an optional privacy-safe user ID.
- The Stage 8 exact-cache baseline reports candidates per scope as well as per key variant.
- Widening the serving scope later needs a new decision record citing measured false-hit rates.
