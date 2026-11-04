"""Self-preference handling and the 2026-11-04 benchmark reference files
(ADR-0053 amendment 5). [SYNTHETIC] rows only; no file outside the repository.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from metis_auto.evaluation.benchmark.framework_report import split_by_family

ROOT = Path(__file__).resolve().parents[3]
REF = ROOT / "config" / "reference"
FAMILIES = {
    "gpt-4o-mini": "openai",
    "gpt-5-nano": "openai",
    "deepseek-v4-flash": "deepseek",
    "deepseek-v4.1-flash": "deepseek",
}


def _table(*models: str) -> dict:
    return {
        "rows": [
            {"language": "fa", "model_id": m, "quality": {"value": 0.5}} for m in models
        ]
    }


def test_each_arm_is_headlined_without_its_own_familys_judge():
    tables = {
        "gpt-4o-mini": _table("gpt-5-nano", "gpt-4o-mini", "deepseek-v4-flash"),
        "deepseek-v4.1-flash": _table("gpt-5-nano", "gpt-4o-mini", "deepseek-v4-flash"),
    }
    out = split_by_family(tables, FAMILIES, ["gpt-4o-mini", "deepseek-v4.1-flash"])
    head = {(r["model_id"], r["judge"]) for r in out["headline"]}
    same = {(r["model_id"], r["judge"]) for r in out["same_family"]}
    assert head == {
        ("gpt-5-nano", "deepseek-v4.1-flash"),
        ("gpt-4o-mini", "deepseek-v4.1-flash"),
        ("deepseek-v4-flash", "gpt-4o-mini"),
    }
    assert same == {
        ("gpt-5-nano", "gpt-4o-mini"),
        ("gpt-4o-mini", "gpt-4o-mini"),
        ("deepseek-v4-flash", "deepseek-v4.1-flash"),
    }
    assert out["unknown_family"] == []


def test_an_earlier_judge_version_is_in_neither_part():
    tables = {
        "deepseek-v4-flash": _table("gpt-5-nano"),
        "deepseek-v4.1-flash": _table("gpt-5-nano"),
    }
    out = split_by_family(tables, FAMILIES, ["deepseek-v4.1-flash"])
    assert {r["judge"] for r in out["headline"] + out["same_family"]} == {
        "deepseek-v4.1-flash"
    }


def test_an_unknown_family_is_reported_and_not_called_the_same():
    out = split_by_family({"j": _table("m")}, {"j": "x"}, ["j"])
    assert out["same_family"] == [] and len(out["headline"]) == 1
    assert out["unknown_family"] == ["m"]


def _models(name: str) -> dict:
    raw = tomllib.loads((REF / name).read_text(encoding="utf-8"))
    return {m["model_id"]: m for m in raw["models"]}


def test_the_benchmark_catalogue_matches_what_the_wrapper_serves():
    models = _models("catalogue-metis-test-2026-11-04-v41.toml")
    assert models["gpt-4.1-nano"]["enabled"] is False
    assert models["mimo-v2.5"]["enabled"] is False
    v41 = models["deepseek-v4.1-flash"]
    assert v41["enabled"] is True and v41["price_ref"] == "metis-deepseek-v4.1-flash"
    for key in ("context_window", "max_output_tokens"):
        assert v41[key]["evidence"]["source"] and v41[key]["evidence"]["checked_on"]
    # the locked live catalogue is untouched: it still has the old flags
    assert _models("catalogue-metis-test.toml")["gpt-4.1-nano"]["enabled"] is True


def test_the_new_price_equals_the_saved_pricing_page_row():
    csv = (ROOT / "docs/references/metis_pricing_2026-10-18.csv").read_text("utf-8")
    row = next(
        ln for ln in csv.splitlines() if ln.startswith("deepseek,deepseek-v4.1-flash,")
    )
    prices = tomllib.loads(
        (REF / "prices-metis-2026-11-04-v41.toml").read_text("utf-8")
    )
    p = next(
        x for x in prices["prices"] if x["price_ref"] == "metis-deepseek-v4.1-flash"
    )
    assert f"Input Token: ${float(p['input']):.4f} / 1M" in row
    assert f"Output Token: ${float(p['output']):.4f} / 1M" in row
    assert f"Cached Input Token: ${float(p['cached_input']):.4f} / 1M" in row
