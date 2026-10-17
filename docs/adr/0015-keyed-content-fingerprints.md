# ADR-0015: Content fingerprints are keyed (HMAC), not plain hashes

- Status: **provisional** (needs your confirmation, Q-20). The algorithm choice is made in Stage 4.
- Date: 2026-10-14
- Relates to: QA-PRIV, A-09, FR-OBS-02, FR-FEAT-05, FR-XCACHE-02, ADR-0011, ADR-0012

## Context
Events, cache keys, run records, and reports use hashes in place of content (FR-OBS-02, FR-FEAT-05). The sample signal is that user messages are often very short (median about 29 characters, F-1), and many repeats are common phrases. A plain, unkeyed hash of a short, common message can be reversed by hashing a list of likely messages and comparing. Committed reports and shared run records would then leak content.

## Decision
1. Every **content fingerprint** (message, instructions, history, retrieved context, structured-input config, and any group ID derived from content) is a keyed hash (HMAC-style) using a secret **fingerprint key**.
2. The key is a **secret**: environment only, never committed, logged, or hashed into the config hash ([configuration.md](../architecture/configuration.md)). Manifests record a key **ID** (for example a short fingerprint of the key), so that runs using the same key can be compared.
3. **Opaque identifiers** that are not content (session and run IDs minted by Metis, case IDs) do not need keying.
4. Tests and the walking skeleton use a fixed, clearly synthetic test key.

## Alternatives considered
- **Plain SHA-256.** Simple and reproducible everywhere, but reversible for short or common text. Rejected.
- **Random per-run IDs with no fingerprint.** Safe, but exact-match grouping across requests (cache keys, repetition analysis) becomes impossible. Rejected.
- **Salted hash with a public salt.** Only slows a dictionary attack slightly. Rejected.

## Consequences
- Fingerprints are only comparable between runs that use the same key. The team shares one key out of band for reproducible experiments. Rotating it is a deliberate, recorded event.
- Cache entries made under one key are unreachable under another, which is acceptable.
- The sample EDA's existing reports use hashed **session IDs** and numbered content groups, not content hashes, so this ADR does not require any change to them. They stay frozen (ADR-0008).
