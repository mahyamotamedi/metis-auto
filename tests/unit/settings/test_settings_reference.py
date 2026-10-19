"""Reference data: the Metis catalogue, prices, endpoints, baselines; the
cross-file checks; and every configured price checked against the committed
price source (docs/references/metis_pricing_2026-10-18.csv, ``raw`` column)."""

import csv
import re
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from metis_auto.contracts import TokenType
from metis_auto.settings import ReferenceDataError, load_settings, repo_root
from metis_auto.settings.reference import read_prices

CONFIG = repo_root() / "config"
PRICE_SOURCE = repo_root() / "docs/references/metis_pricing_2026-10-18.csv"
TEST_MODELS = {
    "gpt-5-nano",
    "gpt-4.1-nano",
    "gpt-4o-mini",
    "deepseek-v4-flash",
    "mimo-v2.5",
}
# Replaced as a test model by mimo-v2.5 (Q-32, 2026-10-18); kept disabled.
RETIRED = {"grok-4-1-fast"}
RAW_PATTERNS = {
    "input": r"(?<!Cached )Input Token: \$([0-9.]+) / 1M tokens",
    "output": r"Output Token: \$([0-9.]+) / 1M tokens",
    "cached_input": r"Cached Input Token: \$([0-9.]+) / 1M tokens",
}


@pytest.fixture(scope="module")
def reference():
    loaded = load_settings(config_dir=CONFIG, environ={}, dotenv=None, runtime=None)
    return loaded.reference


def raw_prices(model: str) -> list[dict[str, Decimal]]:
    """Prices parsed from the CSV's ``raw`` text, one dict per context tier
    (one tier for untiered models). Independent of the structured columns,
    which are wrong for tiered models."""
    with PRICE_SOURCE.open(encoding="utf-8") as handle:
        rows = [r for r in csv.DictReader(handle) if r["model"] == model]
    assert len(rows) == 1, model
    raw = rows[0]["raw"]
    found = []
    for text in raw.split("Long context"):
        matches = {k: re.search(p, text) for k, p in RAW_PATTERNS.items()}
        found.append({k: Decimal(m.group(1)) for k, m in matches.items() if m})
    return found


def test_catalogue_has_the_five_test_models_and_the_disabled_premium(reference):
    entries = {e.model_id: e for e in reference.catalogue.entries}
    assert set(entries) == TEST_MODELS | RETIRED | {"gpt-5.4"}
    assert all(entries[m].enabled for m in TEST_MODELS)
    assert not any(entries[m].enabled for m in RETIRED)
    assert entries["gpt-5.4"].enabled is False  # never called
    # deepseek-v4-flash: verified by the live wrapper check (Stage 7.5).
    reasoning = {"gpt-5-nano", "gpt-5.4", "deepseek-v4-flash", "mimo-v2.5"}
    for entry in entries.values():
        # Sourced in Stage 7.5 (TODO-10), except Grok's: unknown, never invented
        # (test_settings_live_reference.py checks the values).
        if entry.model_id == "grok-4-1-fast":
            assert entry.context_window.value is None
        else:
            assert entry.context_window.evidence is not None
        names = {c.name for c in entry.capabilities if c.verified}
        billed = {"hidden_reasoning_billed_as_output"}
        expected = billed if entry.model_id in reasoning else set()
        assert names == expected
        assert all(c.evidence is not None for c in entry.capabilities)


def test_every_family_has_an_endpoint_and_gemini_is_deferred(reference):
    families = {e.provider for e in reference.catalogue.entries}
    assert families == {"openai", "deepseek", "grok", "mimo"}
    for family in families:
        assert reference.endpoints.get(family).status == "enabled"
    assert reference.endpoints.get("gemini").status == "deferred"


def test_premium_baseline_is_gpt_5_4(reference):
    premium = {b.name: b for b in reference.baselines.baselines}["premium"]
    assert premium.model_id == "gpt-5.4"
    assert premium.method == "estimate_only"


@pytest.mark.parametrize("model", sorted(TEST_MODELS | RETIRED))
def test_test_model_prices_match_the_source(reference, model):
    entry = next(e for e in reference.catalogue.entries if e.model_id == model)
    configured = {
        p.token_type.value: p.amount
        for p in reference.prices.entries
        if p.price_ref == entry.price_ref
    }
    (source,) = raw_prices(model)
    assert configured == source
    assert set(configured) == {"input", "output", "cached_input"}


def test_tiered_premium_prices_match_the_source(reference):
    rows = [p for p in reference.prices.entries if p.price_ref == "metis-gpt-5.4"]
    standard, long = raw_prices("gpt-5.4")
    by_tier: dict[str, dict[str, Decimal]] = {}
    for row in rows:
        by_tier.setdefault(row.tier, {})[row.token_type.value] = row.amount
    assert by_tier == {"standard": standard, "long": long}
    # Conservative reading of "≤ 270K" (ADR-0020): 270,000, with the 1,024
    # reading flagged as uncertain; the long tier starts right after.
    for row in rows:
        if row.tier == "standard":
            assert (row.min_input_tokens, row.max_input_tokens) == (None, 270_000)
            assert row.max_input_tokens_uncertain_up_to == 276_480
        else:
            assert (row.min_input_tokens, row.max_input_tokens) == (270_001, None)


def test_cache_write_variants_and_unknown_keys(tmp_path):
    head = (
        'version = "x"\ncurrency = "USD"\nper_tokens = 1000000\n'
        '[evidence]\nsource = "SYNTHETIC"\nchecked_on = 2026-10-18\n'
    )
    path = tmp_path / "p.toml"
    path.write_text(
        head + '[[prices]]\nprice_ref = "a"\ninput = "1"\noutput = "2"\n'
        'cache_write = { "ttl-5m" = "1.25", "ttl-1h" = "2" }\n'
    )
    writes = {
        p.cache_ttl: p.amount
        for p in read_prices(path).entries
        if p.token_type == TokenType.CACHE_WRITE
    }
    assert writes == {"ttl-5m": Decimal("1.25"), "ttl-1h": Decimal("2")}
    path.write_text(head + '[[prices]]\nprice_ref = "a"\nsearch_query = "1"\n')
    with pytest.raises(ReferenceDataError, match="unknown keys"):
        read_prices(path)


def test_overlapping_tiers_are_refused(tmp_path):
    path = tmp_path / "p.toml"
    path.write_text(
        'version = "x"\ncurrency = "USD"\nper_tokens = 1000000\n'
        '[evidence]\nsource = "SYNTHETIC"\nchecked_on = 2026-10-18\n'
        '[[prices]]\nprice_ref = "a"\ntier = "s"\nmax_input_tokens = 100\n'
        'input = "1"\noutput = "2"\n'
        '[[prices]]\nprice_ref = "a"\ntier = "l"\nmin_input_tokens = 100\n'
        'input = "2"\noutput = "3"\n'
    )
    with pytest.raises(ReferenceDataError, match="overlapping"):
        read_prices(path)


def test_tokenizer_table_covers_the_catalogue(reference):
    table = reference.tokenizers
    for entry in reference.catalogue.entries:
        spec = table.get(entry.tokenizer_ref)
        assert spec is not None, entry.model_id
        assert spec.evidence.checked_on.isoformat() == "2026-10-18"
    exact = {t.ref for t in table.tokenizers if t.fidelity == "exact_local"}
    assert exact == {"openai-o200k-base", "deepseek-v4", "mimo-v2"}
    # Templates are never claimed exact before a provider-reported check.
    assert all(
        t.template.fidelity == "approximation" for t in table.tokenizers if t.template
    )


def test_unknown_tokenizer_ref_is_refused(tmp_path):
    cfg = copy_config(tmp_path)
    cat = cfg / "reference/catalogue-metis-test.toml"
    cat.write_text(cat.read_text().replace('"grok-approx"', '"no-such-tokenizer"'))
    with pytest.raises(ReferenceDataError, match="no-such-tokenizer"):
        load_settings(config_dir=cfg, environ={}, dotenv=None, runtime=None)


def test_prices_carry_evidence(reference):
    for price in reference.prices.entries:
        assert price.evidence is not None
        assert "metisai.ir/pricing" in price.evidence.source
        assert price.currency == "USD" and price.per_tokens == 1_000_000


def copy_config(tmp_path: Path) -> Path:
    target = tmp_path / "config"
    shutil.copytree(CONFIG, target, ignore=shutil.ignore_patterns("local.toml"))
    return target


def test_float_prices_are_refused(tmp_path):
    path = tmp_path / "p.toml"
    path.write_text(
        'version = "x"\ncurrency = "USD"\nper_tokens = 1000000\n'
        '[evidence]\nsource = "s"\nchecked_on = 2026-10-18\n'
        '[[prices]]\nprice_ref = "a"\ninput = 0.1\noutput = "0.2"\n'
    )
    with pytest.raises(ReferenceDataError, match="decimal string"):
        read_prices(path)


def test_a_price_ref_without_prices_is_refused(tmp_path):
    cfg = copy_config(tmp_path)
    prices = cfg / "reference/prices-metis-2026-10-18.toml"
    text = prices.read_text().replace(
        'price_ref = "metis-gpt-4o-mini"', 'price_ref = "x"'
    )
    prices.write_text(text)
    with pytest.raises(ReferenceDataError, match="gpt-4o-mini"):
        load_settings(config_dir=cfg, environ={}, dotenv=None, runtime=None)


def test_a_baseline_outside_the_catalogue_is_refused(tmp_path):
    cfg = copy_config(tmp_path)
    path = cfg / "reference/baselines.toml"
    path.write_text(path.read_text().replace('"gpt-5.4"', '"not-in-catalogue"'))
    with pytest.raises(ReferenceDataError, match="not in the catalogue"):
        load_settings(config_dir=cfg, environ={}, dotenv=None, runtime=None)


def test_input_token_type_names_match_the_contract():
    assert {"input", "output", "cached_input"} <= {t.value for t in TokenType}


def test_label_mapping_loads_and_checks_the_catalogue(tmp_path):
    from metis_auto.settings import LabelFidelity, load_settings
    from metis_auto.settings.reference import ReferenceDataError, read_label_mapping

    loaded = load_settings(environ={}, dotenv=None, runtime=None)
    mapping = loaded.reference.label_mapping
    assert mapping is not None and mapping.dataset == "sample_v1"
    assert mapping.get("gpt-4o-mini").fidelity == LabelFidelity.EXACT_ID
    assert mapping.get("default").model_id is None
    assert mapping.model_ids()["deepseek-chat"] == "deepseek-v4-flash"
    bad = tmp_path / "m.toml"
    bad.write_text(
        'version = "v"\ndataset = "d"\n[[labels]]\nlabel = "x"\nmodel_id = "x"\n'
    )
    with pytest.raises(ReferenceDataError, match="fidelity"):
        read_label_mapping(bad)
    bad.write_text(
        'version = "v"\ndataset = "d"\n[[labels]]\nlabel = "x"\n'
        'model_id = "x"\nfidelity = "alias"\n'
    )
    with pytest.raises(ReferenceDataError, match="evidence"):
        read_label_mapping(bad)
