"""Replay pricing for the logged models:
ADR-0041; FR-ACCT-02, FR-ACCT-07;
ADR-0002, ADR-0026, ADR-0036.

``prices-metis-2026-10-18-logged.toml`` and ``catalogue-metis-replay.toml`` are
copies of the current price file and test catalogue plus one row per logged
label that is a real text model with a pricing-page row of exactly the same
name. Every new amount is checked against the ``raw`` text of
docs/references/metis_pricing_2026-10-18.csv. Request frames here are
[SYNTHETIC]: invented token counts, no dataset content.
"""

from __future__ import annotations

import csv
import hashlib
import re
import tomllib
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from metis_auto.analysis.baselines_full import baseline_costs, best_single_cheap_model
from metis_auto.analysis.levers import ReplayContext
from metis_auto.settings import load_settings, repo_root
from metis_auto.settings.model import ReferenceData
from metis_auto.settings.reference import (
    check_consistency,
    read_catalogue,
    read_label_mapping,
    read_prices,
    read_tokenizers,
)

ROOT = repo_root()
REF = ROOT / "config" / "reference"
OLD_PRICES = REF / "prices-metis-2026-10-18-g55.toml"
OLD_CATALOGUE = REF / "catalogue-metis-test.toml"
NEW_PRICES = REF / "prices-metis-2026-10-18-logged.toml"
NEW_CATALOGUE = REF / "catalogue-metis-replay.toml"
SPRINT = ROOT / "config" / "evaluation" / "sprint.toml"
PRICE_SOURCE = ROOT / "docs" / "references" / "metis_pricing_2026-10-18.csv"
LABELS = REF / "label-mapping-full-v1.toml"

# sha256 of both files on main (cbec265, checked 2026-11-02). A new price is a
# new file (ADR-0026), so these never change.
KEPT = {
    OLD_PRICES: "13df22bdaf322d5641b6627927d5de1f717c368189526c66a9e83e2d6bc68579",
    OLD_CATALOGUE: "889618a8d0d9b3790242028ebe86c1e29204b3e502903a65d8494d1b60d7cd50",
}
# Decision (2): the page lists no cached-input price for these labels.
NO_CACHED_PRICE = {
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-3.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-3.1-flash-lite-preview",
    "gemini-3-pro-preview",
    "command-r",
}
NO_CACHED_NOTE = (
    "page lists no cached price; no discount assumed (upper bound); "
    "EDA: Google cached input ~0.03%"
)
GEMINI_25_NOTE = (
    "price page saved 2026-10-18; availability to re-check "
    "(Vertex retired 2.5 on 2026-10-20 per project research)"
)
# Same rule as the contracts' ``Name``: a model_id outside it cannot be listed.
NAME = re.compile(r"^[a-z0-9][a-z0-9_.:\-]*$")
NOT_TEXT = {"not_a_model", "not_a_text_model"}
RAW_PATTERNS = {
    "input": r"(?<!Cached )Input Token: \$([0-9.]+) / 1M tokens",
    "output": r"Output Token: \$([0-9.]+) / 1M tokens",
    "cached_input": r"Cached Input Token: \$([0-9.]+) / 1M tokens",
    "cache_write": r"Cache Write Token: \$([0-9.]+) / 1M tokens",
    "ttl-1h": r"Cache Write \(1h\): \$([0-9.]+) / 1M tokens",
    "ttl-5m": r"Cache Write \(5m\): \$([0-9.]+) / 1M tokens",
}


def _toml(path):
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _csv_rows() -> dict[str, dict[str, str]]:
    with PRICE_SOURCE.open(encoding="utf-8") as handle:
        return {r["model"]: r for r in csv.DictReader(handle)}


def _raw_tiers(model: str) -> list[dict[str, Decimal]]:
    """Token prices parsed from the ``raw`` text, one dict per context tier."""
    found = []
    for text in _csv_rows()[model]["raw"].split("Long context"):
        matches = {k: re.search(p, text) for k, p in RAW_PATTERNS.items()}
        found.append({k: Decimal(m.group(1)) for k, m in matches.items() if m})
    return found


def _new_models() -> list[dict]:
    old = {m["model_id"] for m in _toml(OLD_CATALOGUE)["models"]}
    return [m for m in _toml(NEW_CATALOGUE)["models"] if m["model_id"] not in old]


def _new_price_rows(price_ref: str) -> list[dict]:
    rows = [p for p in _toml(NEW_PRICES)["prices"] if p["price_ref"] == price_ref]
    return sorted(rows, key=lambda p: p.get("min_input_tokens", 0))


def _block(text: str, price_ref: str) -> str:
    """The ``[[prices]]`` block(s) of one price_ref, comments included."""
    return "".join(b for b in text.split("[[prices]]") if f'"{price_ref}"' in b)


def _ctx(price_path, catalogue_path) -> ReplayContext:
    return ReplayContext(
        period_bounds={},
        price_table=_toml(price_path),
        catalogue=_toml(catalogue_path),
        seed=7,
    )


def _frame(labels: list[str]) -> pd.DataFrame:
    """[SYNTHETIC] One LLM row per label, invented token counts."""
    n = len(labels)
    return pd.DataFrame(
        {
            "llm_request": [True] * n,
            "bot_provider_model": labels,
            "a_bill_inputTokens": [1_000.0 * (i + 1) for i in range(n)],
            "a_bill_cachedInputTokens": [0.0] * n,
            "a_bill_outputTokens": [200.0] * n,
            "a_bill_totalCost": [0.01] * n,
            "a_n_per_call_only_items": [0] * n,
            "a_billing_state": ["items"] * n,
        }
    )


@pytest.mark.parametrize("path", sorted(KEPT), ids=lambda p: p.name)
def test_the_old_price_file_and_live_catalogue_are_unchanged(path):
    # Line endings normalised: a Windows checkout (core.autocrlf) has CRLF.
    data = path.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(data).hexdigest() == KEPT[path]


def test_defaults_still_load_the_live_files():
    loaded = load_settings(
        config_dir=ROOT / "config", environ={}, dotenv=None, runtime=None
    )
    assert loaded.reference.catalogue.version == "cat-metis-test-2026-10-18-s75-g55"
    assert loaded.reference.prices.version == "prices-metis-2026-10-18-s75-g55"


def test_the_new_files_are_copies_plus_rows_with_new_versions():
    old_p, new_p = _toml(OLD_PRICES), _toml(NEW_PRICES)
    old_c, new_c = _toml(OLD_CATALOGUE), _toml(NEW_CATALOGUE)
    assert new_p["prices"][: len(old_p["prices"])] == old_p["prices"]
    assert new_c["models"][: len(old_c["models"])] == old_c["models"]
    assert new_p["version"] not in (old_p["version"], "")
    assert new_c["version"] not in (old_c["version"], "")
    assert {k: new_p[k] for k in ("currency", "per_tokens")} == {
        "currency": "USD",
        "per_tokens": 1_000_000,
    }
    assert str(new_p["evidence"]["checked_on"]) == "2026-10-18"
    assert "metis_pricing_2026-10-18.csv" in new_p["evidence"]["source"]


def test_new_rows_are_exactly_the_logged_text_models_with_a_same_name_page_row():
    csv_rows = _csv_rows()
    old = {m["model_id"] for m in _toml(OLD_CATALOGUE)["models"]}
    expected = {
        row["label"]
        for row in _toml(LABELS)["labels"]
        if row.get("unmapped") not in NOT_TEXT
        and row["label"] in csv_rows
        and row["label"] not in old
        and NAME.match(row["label"])
    }
    assert {m["model_id"] for m in _new_models()} == expected
    assert len(expected) == 43
    # Unpriced on purpose: no same-name page row (decision 3), or not a text
    # model, or a name the catalogue schema refuses.
    for label in ("deepseek-chat", "deepseek-reasoner", "gpt-image-1", "dalle"):
        assert label not in expected
    assert "google/gemma3-27b" in csv_rows and "google/gemma3-27b" not in expected


def test_every_new_catalogue_row_is_disabled_replay_only_and_priced():
    csv_rows = _csv_rows()
    priced = {p["price_ref"] for p in _toml(NEW_PRICES)["prices"]}
    for model in _new_models():
        label = model["model_id"]
        assert model["enabled"] is False, label
        assert model["price_ref"] in priced, label
        assert model["provider_model_name"] == label
        assert model["provider"] == csv_rows[label]["provider"]
        assert model["equivalence_group"] == "replay-only"
        # Limits and tokenizer: unknown, never invented.
        for key in ("context_window", "max_output_tokens", "tokenizer_ref"):
            assert key not in model, (label, key)


def test_every_new_amount_matches_the_raw_text():
    for model in _new_models():
        label = model["model_id"]
        rows, tiers = _new_price_rows(model["price_ref"]), _raw_tiers(label)
        assert len(rows) == len(tiers), label
        for row, raw in zip(rows, tiers, strict=True):
            for key in ("input", "output"):
                assert Decimal(row[key]) == raw[key], (label, key)
            if "cached_input" in raw:
                assert Decimal(row["cached_input"]) == raw["cached_input"], label
            writes = row.get("cache_write")
            if "cache_write" in raw:
                assert Decimal(writes) == raw["cache_write"], label
            elif "ttl-1h" in raw:
                assert {k: Decimal(v) for k, v in writes.items()} == {
                    k: raw[k] for k in ("ttl-1h", "ttl-5m")
                }, label
            else:
                assert writes is None, label
            amounts = [row[k] for k in ("input", "output", "cached_input")]
            assert all(isinstance(a, str) and Decimal(a) > 0 for a in amounts)


def test_tiered_rows_follow_the_page_context_tiers():
    for model in _new_models():
        rows = _new_price_rows(model["price_ref"])
        if len(rows) == 1:
            assert not {"tier", "min_input_tokens", "max_input_tokens"} & set(rows[0])
            continue
        assert "≤ 270K context" in _csv_rows()[model["model_id"]]["raw"]
        standard, long = rows
        assert (standard["tier"], standard["max_input_tokens"]) == ("standard", 270000)
        assert standard["max_input_tokens_uncertain_up_to"] == 276480
        assert (long["tier"], long["min_input_tokens"]) == ("long", 270001)


def test_rows_without_a_cached_price_use_the_input_price_with_a_note():
    text = NEW_PRICES.read_text(encoding="utf-8")
    without = {
        m["model_id"]
        for m in _new_models()
        if "Cached Input Token" not in _csv_rows()[m["model_id"]]["raw"]
    }
    assert without == NO_CACHED_PRICE
    for model in _new_models():
        if model["model_id"] not in NO_CACHED_PRICE:
            continue
        for row in _new_price_rows(model["price_ref"]):
            assert row["cached_input"] == row["input"], model["model_id"]
        assert NO_CACHED_NOTE in _block(text, model["price_ref"]), model["model_id"]


def test_gemini_2_5_rows_carry_the_availability_note():
    text = NEW_PRICES.read_text(encoding="utf-8")
    gemini_25 = [m for m in _new_models() if m["model_id"].startswith("gemini-2.5")]
    assert {m["model_id"] for m in gemini_25} == {
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
    }
    for model in gemini_25:
        assert GEMINI_25_NOTE in _block(text, model["price_ref"]), model["model_id"]


def test_best_single_cheap_is_unchanged_and_still_enabled():
    labels = ["gpt-4o-mini", "gemini-2.5-flash-lite", "gemini-2.0-flash", "o3-mini"]
    req = _frame(labels)
    old = best_single_cheap_model(req, _ctx(OLD_PRICES, OLD_CATALOGUE))
    new = best_single_cheap_model(req, _ctx(NEW_PRICES, NEW_CATALOGUE))
    assert new == old
    enabled = {
        m["model_id"] for m in _toml(NEW_CATALOGUE)["models"] if m.get("enabled")
    }
    assert new in enabled
    assert enabled == {
        m["model_id"] for m in _toml(OLD_CATALOGUE)["models"] if m.get("enabled")
    }


def test_sprint_points_at_the_replay_files_and_they_load():
    base = _toml(SPRINT)["baselines"]
    assert base["catalogue"] == "config/reference/catalogue-metis-replay.toml"
    assert base["price_table"] == "config/reference/prices-metis-2026-10-18-logged.toml"
    data = ReferenceData(
        catalogue=read_catalogue(ROOT / base["catalogue"]),
        prices=read_prices(ROOT / base["price_table"]),
        tokenizers=read_tokenizers(REF / "tokenizers.toml"),
        # The defaults' mapping: label-mapping-full-v1.toml is a reference list
        # (its `requests` counts are not schema fields), read here as plain TOML.
        label_mapping=read_label_mapping(REF / "label-mapping-sample-v1.toml"),
    )
    check_consistency(data)
    req = _frame(["gemini-2.5-flash", "gpt-4o-mini", "gpt-6-luna", "dalle"])
    out = baseline_costs(
        req,
        _ctx(ROOT / base["price_table"], ROOT / base["catalogue"]),
        premium_model=str(base["premium_model"]),
    )
    today = out["todays_models"]
    # dalle is an image model: unknown, never zero.
    assert (today["n_known"], today["n_unknown"]) == (Decimal(3), Decimal(1))
    assert today["token_cost"] > 0
    assert not np.isnan(float(out["premium_gpt_5_5"]["token_cost"]))
