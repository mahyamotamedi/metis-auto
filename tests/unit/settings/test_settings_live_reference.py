"""Stage 7.5 reference data: sourced limits (TODO-10) and endpoint
generation-limit fields. Reads the real config files; offline."""

from datetime import date

import pytest

from metis_auto.settings import (
    ApiFormat,
    EndpointStatus,
    MaxTokensParam,
    ProviderEndpoint,
    load_settings,
)

TEST_MODELS = ("gpt-5-nano", "gpt-4.1-nano", "gpt-4o-mini", "deepseek-v4-flash")


@pytest.fixture(scope="module")
def loaded():
    return load_settings(environ={}, dotenv=None, runtime=None)


def test_every_known_limit_has_a_source_and_a_check_date(loaded):
    for entry in loaded.reference.catalogue.entries:
        for limit in (entry.context_window, entry.max_output_tokens):
            if limit.value is not None:
                assert limit.evidence is not None
                assert limit.evidence.checked_on == date(2026, 10, 18)


def test_todo_10_values(loaded):
    entries = {e.model_id: e for e in loaded.reference.catalogue.entries}
    expected = {
        "gpt-5-nano": (400_000, 128_000),
        "gpt-4.1-nano": (1_047_576, 32_768),
        "gpt-4o-mini": (128_000, 16_384),
        "deepseek-v4-flash": (1_000_000, 384_000),
        "gpt-5.4": (1_050_000, 128_000),
        "mimo-v2.5": (1_000_000, 131_072),
    }
    for model_id, (window, output) in expected.items():
        e = entries[model_id]
        assert (e.context_window.value, e.max_output_tokens.value) == (window, output)
    # No first- or second-party source on 2026-10-18 (Q-32): unknown.
    gpt55 = entries["gpt-5.5"]  # premium baseline (2026-10-30): limits unsourced
    assert gpt55.context_window.value is None and gpt55.max_output_tokens.value is None
    grok = entries["grok-4-1-fast"]
    assert grok.context_window.value is None and grok.max_output_tokens.value is None
    assert grok.enabled is False  # Q-32: replaced by mimo-v2.5


def test_defaults_cap_the_generation_limit(loaded):
    assert loaded.settings.pipeline["context"]["max_output_tokens_cap"] == 4096


def test_enabled_endpoints_name_their_generation_limit_field(loaded):
    params = {
        e.family: e.max_tokens_param
        for e in loaded.reference.endpoints.endpoints
        if e.status == EndpointStatus.ENABLED
    }
    assert params == {
        "openai": MaxTokensParam.MAX_COMPLETION_TOKENS,
        "deepseek": MaxTokensParam.MAX_TOKENS,
        "grok": MaxTokensParam.MAX_TOKENS,
        "mimo": MaxTokensParam.MAX_COMPLETION_TOKENS,
    }


def test_an_enabled_chat_endpoint_without_the_field_is_rejected(loaded):
    row = loaded.reference.endpoints.get("openai").model_dump()
    row["max_tokens_param"] = None
    with pytest.raises(ValueError, match="max_tokens_param"):
        ProviderEndpoint.model_validate(row)
    row |= {"status": EndpointStatus.DEFERRED, "api_format": ApiFormat.GOOGLE_GENAI}
    ProviderEndpoint.model_validate(row)  # deferred rows need none


def test_request_options_are_allowed_only_where_documented(loaded):
    allowed = {
        e.family: e.request_options for e in loaded.reference.endpoints.endpoints
    }
    assert allowed["deepseek"] == ("thinking",) and allowed["mimo"] == ("thinking",)
    assert allowed["openai"] == ("reasoning_effort",) and allowed["grok"] == ()


def test_no_model_option_is_set_by_default(loaded):
    # Q-34: DeepSeek keeps its default (thinking on) until Stage 8.
    assert loaded.settings.model_options == {}


def test_mimo_template_frames_the_check_layout_with_11_tokens(loaded):
    from metis_auto.domain import accounting

    template = loaded.reference.tokenizers.get("mimo-v2").template
    overhead = accounting.template_overhead(template, ["instructions", "user"])
    assert overhead.tokens == 11  # 2 × (3 + 1) + 3, from the chat_template
