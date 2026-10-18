"""The production fingerprinter (ADR-0015 amendment 1) reproduces the Stage 4
reference implementation and its OpenSSL test vectors."""

import pytest
from fixtures.synthetic import contract_examples as ex

from metis_auto.application.measurement import Fingerprinter
from metis_auto.contracts import CacheKeyDraft, ComponentName

FP = Fingerprinter(ex.SYNTHETIC_TEST_KEY)


def test_test_vectors():
    assert FP.fingerprint("message", "abc") == (
        "fp1:4555ea2516fbbfc1cced93f7251c26bc1199885c6496f2758470d894a4c7b988"
    )
    assert FP.key_id == "kid1:518d160a5f289cf5"


@pytest.mark.parametrize(
    "purpose, payload",
    [
        ("message", ex.MESSAGE),
        ("history", [t.model_dump(mode="json") for t in ex.HISTORY]),
        ("structured_input", {"b": 1, "a": "سلام"}),
    ],
)
def test_matches_the_reference_implementation(purpose, payload):
    assert FP.fingerprint(purpose, payload) == ex.fingerprint(purpose, payload)


def test_short_keys_are_refused_and_the_key_is_never_shown():
    with pytest.raises(ValueError):
        Fingerprinter(b"too-short")
    assert ex.SYNTHETIC_TEST_KEY.decode() not in repr(FP)


def test_sealed_key_partition_ignores_the_message():
    key = ex.cache_key()
    draft = CacheKeyDraft(**key.model_dump(exclude={"key", "partition_key"}))
    other = draft.model_copy(
        update={
            "components": tuple(
                c.model_copy(update={"fingerprint": ex.fingerprint("message", "x")})
                if c.component == ComponentName.MESSAGE
                else c
                for c in draft.components
            )
        }
    )
    a, b = FP.seal(draft), FP.seal(other)
    assert a.key != b.key
    assert a.partition_key == b.partition_key
