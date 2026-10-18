# ADR-0015: Content fingerprints are keyed (HMAC), not plain hashes

- Status: **decided** (confirmed 2026-10-17, Q-20). Algorithm: HMAC-SHA-256, [amendment 1](#amendment-1-2026-10-17-stage-4-the-algorithm) (Stage 4).
- Date: 2026-10-14
- Relates to: QA-PRIV, A-09, FR-OBS-02, FR-FEAT-05, FR-XCACHE-02, ADR-0011, ADR-0012

## Context
Events, cache keys, run records, and reports use hashes in place of content (FR-OBS-02, FR-FEAT-05). The sample signal is that user messages are often very short (median about 29 characters, F-1), and many repeats are common phrases. A plain, unkeyed hash of a short, common message can be reversed by hashing a list of likely messages and comparing. Committed reports and shared run records would then leak content.

## Decision
1. Every **content fingerprint** (message, instructions, history, retrieved context, structured-input config, and any group ID derived from content) is a keyed hash (HMAC-style) using a secret **fingerprint key**.
2. The key is a **secret**: environment only, never committed, logged, or hashed into the config hash ([configuration.md](../architecture/configuration.md)). Manifests record a key **ID** (for example a short fingerprint of the key), so that runs using the same key can be compared.
3. **Opaque identifiers** that are not content (session and run IDs minted by Metis, case IDs) do not need keying.
4. Tests and the walking skeleton use a fixed, clearly synthetic test key: named as synthetic, defined only in test code or fixtures, and never used outside tests.

## Alternatives considered
- **Plain SHA-256.** Simple and reproducible everywhere, but reversible for short or common text. Rejected.
- **Random per-run IDs with no fingerprint.** Safe, but exact-match grouping across requests (cache keys, repetition analysis) becomes impossible. Rejected.
- **Salted hash with a public salt.** Only slows a dictionary attack slightly. Rejected.

## Consequences
- Fingerprints are only comparable between runs that use the same key. The team shares one key out of band for reproducible experiments. Rotating it is a deliberate, recorded event.
- Cache entries made under one key are unreachable under another, which is acceptable.
- The sample EDA's existing reports use hashed **session IDs** and numbered content groups, not content hashes, so this ADR does not require any change to them. They stay frozen (ADR-0008).

## Amendment 1 (2026-10-17, Stage 4): the algorithm

- **Decided in:** Stage 4, as this ADR required. Q-20 confirmed keyed fingerprints. Who holds and distributes the real key is still open (Q-20).
- **Algorithm:** HMAC-SHA-256 (Python standard library `hmac` and `hashlib`).
- **Key:** at least 32 bytes, from the environment only (configuration.md §3 rule 7).
- **Message:** the UTF-8 bytes of `metis-fp/1` + `0x1F` + *purpose* + `0x1F` + *canonical payload*.
  - *Purpose* is a short code naming what is fingerprinted, for example `message`, `instructions`, `history`, `retrieved`, `structured_input`, `attachment`, `session_ref`, `composition`, `cache_key`, `partition_key`. It separates domains: the same text fingerprinted as a message and as instructions gives different values, so fingerprints of different kinds can't be joined by accident.
  - *Canonical payload*: text components are hashed as given. Structured payloads (history turns, retrieved items, structured input, key material) are hashed as canonical JSON: sorted keys, no whitespace (`separators=(",", ":")`), non-ASCII kept as UTF-8 (`ensure_ascii=False`).
  - **No implicit normalisation.** Normalisation (literal, whitespace, NFKC + casefold) is a configured cache-key *treatment* applied before fingerprinting, and the key records which one was used (`KeyComponent.treatment`).
- **Output:** `fp1:` + the full 64-character lowercase hex digest. It is not truncated: a collision inside a cache key would be a false hit.
- **Key ID** (for manifests and `Versions.fingerprint_key_id`): `kid1:` + the first 16 hex characters of HMAC-SHA-256(key, `metis-fp-key-id/1`). It identifies the key without revealing it.
- **Versioning:** the `fp1` / `kid1` / `metis-fp/1` prefixes change together if the algorithm ever changes. Old and new fingerprints then never compare equal.
- **Test vectors:** with the synthetic test key `SYNTHETIC-TEST-KEY--metis-auto--not-a-secret--0001`, purpose `message`, and payload `abc`, the fingerprint is `fp1:4555ea2516fbbfc1cced93f7251c26bc1199885c6496f2758470d894a4c7b988` and the key ID is `kid1:518d160a5f289cf5`. Both were computed independently with OpenSSL 3.0.18 and are pinned in `tests/unit/contracts/test_contracts_serialization.py`. The reference implementation is in `tests/fixtures/synthetic/contract_examples.py`. Stage 5 moves it into `application/measurement` (CMP-02) and must reproduce the vectors. **Done 2026-10-18:** `application/measurement/fingerprints.py`, checked by `tests/unit/application/test_application_fingerprints.py`.
- **Alternatives considered:** keyed BLAKE2b (also in the standard library, and faster). HMAC-SHA-256 was chosen because it is the more widely implemented construction, which matters if fingerprints ever need recomputing outside Python. Speed is not a concern at these sizes. Truncated digests: rejected because of the cache-key collision risk.
