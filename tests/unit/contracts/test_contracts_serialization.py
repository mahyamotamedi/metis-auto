"""Serialisation of contracts and the fingerprint reference algorithm.

Every synthetic example must survive a JSON round trip unchanged: events,
manifests, cache entries, and recorded responses are persisted as JSON.
"""

import json

import pytest
from fixtures.synthetic import contract_examples as ex
from pydantic import TypeAdapter

from metis_auto.contracts import SCHEMA_VERSION, Event, ModelResult

EXAMPLES = ex.all_examples()


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_json_round_trip(name):
    original = EXAMPLES[name]
    if name.startswith("model_result"):
        adapter = TypeAdapter(ModelResult)
        assert adapter.validate_json(adapter.dump_json(original)) == original
    else:
        assert (
            type(original).model_validate_json(original.model_dump_json()) == original
        )


def test_events_round_trip_through_json_lines():
    lines = [event.model_dump_json() for event in ex.events()]
    parsed = [Event.model_validate_json(line) for line in lines]
    assert parsed == list(ex.events())
    assert {e.payload.event_type for e in parsed} == {e.event_type for e in parsed}


def test_persisted_records_carry_the_schema_version():
    for record in (ex.events()[0], ex.run_manifest(), ex.cache_entry()):
        assert json.loads(record.model_dump_json())["schema_version"] == SCHEMA_VERSION


def test_money_serialises_as_a_decimal_string_not_a_float():
    dumped = json.loads(ex.cost_estimate().model_dump_json())
    assert dumped["cost"]["amount"] == {"amount": "0.0004", "currency": "USD"}


def test_timestamps_keep_their_kind():
    case = json.loads(ex.replay_case().model_dump_json())
    assert case["logged_timestamp"] == "2026-05-01T14:02:03"  # naive, no offset
    manifest = json.loads(ex.run_manifest().model_dump_json())
    assert manifest["started_at"].endswith("Z")


def test_persian_text_survives_unescaped():
    request = ex.request()
    assert "سلام" in request.model_dump_json()
    assert type(request).model_validate_json(request.model_dump_json()) == request


# --- Fingerprints (ADR-0015 amendment 1) ------------------------------------


def test_fingerprint_format_and_determinism():
    fp = ex.fingerprint("message", ex.MESSAGE)
    assert fp == ex.fingerprint("message", ex.MESSAGE)
    assert fp.startswith("fp1:") and len(fp) == 4 + 64


def test_fingerprint_separates_purpose_and_key():
    text = f"{ex.MARKER} same text"
    assert ex.fingerprint("message", text) != ex.fingerprint("instructions", text)
    other_key = b"SYNTHETIC-OTHER-KEY--not-a-secret--0002"
    assert ex.fingerprint("message", text) != ex.fingerprint("message", text, other_key)


def test_fingerprint_of_structured_payloads_is_canonical():
    a = {"b": 1, "a": [1, 2], "c": "سلام"}
    b = {"c": "سلام", "a": [1, 2], "b": 1}
    assert ex.fingerprint("structured_input", a) == ex.fingerprint(
        "structured_input", b
    )
    assert ex.canonical(a) == '{"a":[1,2],"b":1,"c":"سلام"}'


def test_fingerprint_does_not_normalise_text():
    # Normalisation is a configured cache-key treatment, applied before hashing.
    assert ex.fingerprint("message", "Hello") != ex.fingerprint("message", "hello")


def test_fingerprint_test_vectors():
    # Pins the algorithm. Values computed independently with OpenSSL 3.0.18:
    #   printf 'metis-fp/1\x1fmessage\x1fabc' | openssl dgst -sha256 -hmac "$KEY"
    #   printf 'metis-fp-key-id/1' | openssl dgst -sha256 -hmac "$KEY"
    # Stage 5's implementation in application/measurement must reproduce them.
    assert ex.fingerprint("message", "abc") == (
        "fp1:4555ea2516fbbfc1cced93f7251c26bc1199885c6496f2758470d894a4c7b988"
    )
    assert ex.key_id() == "kid1:518d160a5f289cf5"
