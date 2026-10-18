"""Keyed content fingerprints (ADR-0015 and its amendment 1).

Responsibility: HMAC-SHA-256 fingerprints with purpose separation and
canonical JSON; the key ID; sealing a ``CacheKeyDraft`` into a ``CacheKey``.
The key is a secret: wiring passes it in, and it is never logged, hashed into
the config hash, or put in an event (configuration §3 rule 7). This replaces
the Stage 4 reference implementation in the test fixtures and reproduces its
OpenSSL test vectors (tests/unit/application).
Called by: application.measurement.service, application.pipeline.
Status: decided.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from metis_auto.contracts import CacheKey, CacheKeyDraft, Fingerprint

MIN_KEY_BYTES = 32


def canonical(payload: object) -> str:
    """Text as given; structured payloads as canonical JSON (sorted keys, no
    whitespace, non-ASCII kept). No implicit normalisation."""
    if isinstance(payload, str):
        return payload
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


class Fingerprinter:
    def __init__(self, key: bytes) -> None:
        if len(key) < MIN_KEY_BYTES:
            raise ValueError(
                f"the fingerprint key needs at least {MIN_KEY_BYTES} bytes"
            )
        self._key = key
        digest = hmac.new(key, b"metis-fp-key-id/1", hashlib.sha256).hexdigest()
        self._key_id = "kid1:" + digest[:16]

    def __repr__(self) -> str:  # never show the key
        return f"Fingerprinter(key_id={self._key_id!r})"

    @property
    def key_id(self) -> str:
        return self._key_id

    def fingerprint(self, purpose: str, payload: object) -> Fingerprint:
        message = b"metis-fp/1\x1f" + purpose.encode() + b"\x1f"
        message += canonical(payload).encode("utf-8")
        return "fp1:" + hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def seal(self, draft: CacheKeyDraft) -> CacheKey:
        """The draft plus its key and partition-key fingerprints (ADR-0011)."""
        return CacheKey(
            **draft.model_dump(),
            key=self.fingerprint("cache_key", draft.key_material()),
            partition_key=self.fingerprint("partition_key", draft.partition_material()),
        )
