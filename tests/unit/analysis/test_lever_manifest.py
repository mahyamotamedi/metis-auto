"""Reproducibility manifest on every lever result (final plan E-2, QA-REPRO).

All values are [SYNTHETIC]. ``created_at`` is passed in, so identical inputs
give byte-identical JSON; scripts pass the real UTC time.
"""

from __future__ import annotations

import getpass
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from metis_auto.analysis.lever_result import LeverResult, Manifest, build_manifest
from metis_auto.analysis.levers import ReplayContext

REVISION = "30f578f283b903cdbd06cd1b5f7f962f76452ded"
COMMIT = "1234567890abcdef1234567890abcdef12345678"
FIXED_TIME = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


def make_ctx(seed: int = 7) -> ReplayContext:
    return ReplayContext(
        period_bounds={},
        price_table={"version": "prices-synthetic-2026-10-18"},
        catalogue={},
        seed=seed,
        min_n=30,
    )


def make_manifest(config: dict, seed: int = 7) -> Manifest:
    return build_manifest(
        config,
        make_ctx(seed),
        code_commit=COMMIT,
        python_version="3.13.5",
        created_at=FIXED_TIME,
    )


def make_result(config: dict, seed: int = 7) -> LeverResult:
    slices = {
        "all": {"n_requests": Decimal(6), "saving:total": Decimal("0.1")},
        "llm_only": {"n_requests": Decimal(5), "saving:total": Decimal("0.1")},
    }
    return LeverResult(
        lever_id="synthetic.cache",
        step="cache",
        version="v0",
        n_requests=6,
        n_eligible=5,
        baseline="as_logged",
        baseline_cost={"total": Decimal("0.8")},
        saving={"total": Decimal("0.1")},
        slices=slices,
        evidence_class="simulation",
        correctness_state="unmeasured",
        manifest=make_manifest(config, seed),
    )


def test_result_records_revision_commit_config_hash_seed_price_and_python_version():
    m = make_result({"threshold": 0.5}).manifest
    assert m.data_revision == REVISION
    assert m.code_commit == COMMIT
    assert len(m.config_hash) == 64
    assert m.seed == 7
    assert m.price_version == "prices-synthetic-2026-10-18"
    assert m.python_version == "3.13.5"
    assert m.created_at == FIXED_TIME


def test_same_inputs_same_seed_give_identical_json():
    config = {"threshold": 0.5, "windows": [90, 3], "enabled": True}
    first = make_result(config).to_json()
    second = make_result(dict(reversed(list(config.items())))).to_json()
    assert first == second  # key order in the config does not matter
    assert LeverResult.from_json(first).to_json() == first
    assert json.loads(first) == json.loads(second)
    keys = list(json.loads(first))
    assert keys == sorted(keys)
    assert make_result(config, seed=8).to_json() != first


def test_changing_a_threshold_changes_the_config_hash():
    a = make_manifest({"threshold": 0.5}).config_hash
    b = make_manifest({"threshold": 0.6}).config_hash
    assert a != b
    assert a == make_manifest({"threshold": 0.5}).config_hash


def test_manifest_has_no_path_or_user_name():
    config = {"out": "C:\\Users\\someone\\reports", "home": "/home/someone"}
    text = make_result(config).to_json()
    for needle in ("\\", "someone", "Users", "/home"):
        assert needle not in text
    assert getpass.getuser() not in text
    # The fields refuse a path even when a caller passes one.
    for bad in ("C:\\Users\\someone\\repo", "/home/someone/repo", "someone@host"):
        with pytest.raises(ValidationError):
            Manifest(**{**make_manifest({}).model_dump(), "code_commit": bad})
    with pytest.raises(ValidationError):
        Manifest(**{**make_manifest({}).model_dump(), "python_version": "C:\\py"})
