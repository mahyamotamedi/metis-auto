"""Gemini through the native adapter: settings side
(ADR-0043). Reads the real config files; offline."""

import pytest
from pydantic import ValidationError

from metis_auto.settings import (
    ApiFormat,
    EndpointStatus,
    ModelRequestOptions,
    load_settings,
)


@pytest.fixture(scope="module")
def loaded():
    return load_settings(environ={}, dotenv=None, runtime=None)


def test_thinking_budget_is_a_non_negative_integer():
    assert ModelRequestOptions(thinking_budget=512).thinking_budget == 512
    assert ModelRequestOptions(thinking_budget=0).thinking_budget == 0
    with pytest.raises(ValidationError):
        ModelRequestOptions(thinking_budget=-1)  # provider-chosen ("dynamic")


def test_an_unset_thinking_budget_leaves_existing_dumps_and_hashes_unchanged():
    dumped = ModelRequestOptions(thinking="disabled").model_dump(mode="json")
    assert dumped == {"reasoning_effort": None, "thinking": "disabled"}
    assert "thinking_budget" in ModelRequestOptions(thinking_budget=8).model_dump()


def test_the_gemini_endpoint_stays_deferred(loaded):
    gemini = loaded.reference.endpoints.get("gemini")
    assert gemini.status == EndpointStatus.DEFERRED
    assert gemini.api_format == ApiFormat.GOOGLE_GENAI
    assert gemini.auth_header == "x-goog-api-key"
    assert gemini.base_url == "https://api.metisai.ir"


def test_no_gemini_model_is_enabled(loaded):
    enabled = [
        e.model_id
        for e in loaded.reference.catalogue.entries
        if e.provider == "gemini" and e.enabled
    ]
    assert enabled == []


def test_no_thinking_budget_is_set_by_default(loaded):
    assert all(
        o.thinking_budget is None for o in loaded.settings.model_options.values()
    )
