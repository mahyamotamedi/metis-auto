"""The Gemini live check's plan (no call): refusals and the cost estimate.

The real configuration has no Gemini model and a deferred endpoint, so the
plan refuses. The other tests use SYNTHETIC copies under ``tmp_path`` (an
enabled endpoint, one Gemini row with SYNTHETIC prices). No network, no key.
"""

from decimal import Decimal

import pytest

from metis_auto.settings import load_settings, repo_root
from metis_auto.wiring import gemini_check

REFERENCE = repo_root() / "config" / "reference"
GEMINI_ROW = """
[[models]]
# SYNTHETIC test row: not a real catalogue entry.
model_id = "gem-synth"
provider = "gemini"
provider_model_name = "gem-synth-wire"
tier = 0
equivalence_group = "synthetic"
context_window = {}
max_output_tokens = {}
tokenizer_ref = "approx-chars-div-4"
price_ref = "synthetic-gem"
enabled = true
"""
PRICE_ROW = """
[[prices]]
# SYNTHETIC test price.
price_ref = "synthetic-gem"
input = "1"
output = "2"
"""


@pytest.fixture
def reference(tmp_path):
    endpoints = (REFERENCE / "endpoints-metis.toml").read_text(encoding="utf-8")
    (tmp_path / "endpoints.toml").write_text(
        endpoints.replace('status = "deferred"', 'status = "enabled"')
    )
    catalogue = (REFERENCE / "catalogue-metis-test.toml").read_text(encoding="utf-8")
    (tmp_path / "catalogue.toml").write_text(catalogue + GEMINI_ROW)
    prices = (REFERENCE / "prices-metis-2026-10-18-g55.toml").read_text(
        encoding="utf-8"
    )
    (tmp_path / "prices.toml").write_text(prices + PRICE_ROW)
    return {
        "reference.endpoints": str(tmp_path / "endpoints.toml"),
        "reference.catalogue": str(tmp_path / "catalogue.toml"),
        "reference.prices": str(tmp_path / "prices.toml"),
    }


def _load(model_id, budget, extra=None):
    return load_settings(
        overrides={**gemini_check.overrides(model_id, budget), **(extra or {})},
        environ={},
        dotenv=None,
        runtime=None,
    )


def test_overrides_fix_one_model_one_attempt_a_small_cap_and_the_run_cap():
    o = gemini_check.overrides("gem-synth", 0)
    assert o["pipeline.routing.fixed_model.model_id"] == "gem-synth"
    assert o["pipeline.attempts.max_attempts"] == 1
    assert o["pipeline.context.max_output_tokens_cap"] == gemini_check.OUTPUT_CAP
    assert o["budget.run_cap"] == str(gemini_check.MAX_TOTAL_ESTIMATE)
    assert o["model_options.gem-synth.thinking_budget"] == 0


def test_the_real_configuration_is_refused():
    loaded = load_settings(environ={}, dotenv=None, runtime=None)
    result = gemini_check.plan(loaded, gemini_check.DEFAULT_MODEL)
    assert result.estimate is None
    assert any("no catalogue row" in r for r in result.reasons)


def test_a_deferred_endpoint_and_a_missing_budget_are_refused(reference):
    deferred = {
        **reference,
        "reference.endpoints": str(REFERENCE / "endpoints-metis.toml"),
    }
    loaded = _load("gem-synth", None, deferred)
    reasons = gemini_check.plan(loaded, "gem-synth").reasons
    assert any("deferred" in r for r in reasons)
    assert any("thinking budget" in r for r in reasons)


def test_the_estimate_counts_the_thinking_budget_as_output(reference):
    zero = gemini_check.plan(_load("gem-synth", 0, reference), "gem-synth")
    more = gemini_check.plan(_load("gem-synth", 512, reference), "gem-synth")
    assert zero.reasons == [] and more.reasons == []
    assert zero.output_limit == gemini_check.OUTPUT_CAP
    assert more.estimate - zero.estimate == Decimal(512 * 2) / Decimal(1_000_000)


def test_an_estimate_at_or_over_the_cap_is_refused(reference, monkeypatch):
    monkeypatch.setattr(gemini_check, "MAX_TOTAL_ESTIMATE", Decimal("0.000001"))
    result = gemini_check.plan(_load("gem-synth", 0, reference), "gem-synth")
    assert any("estimate" in r for r in result.reasons)
