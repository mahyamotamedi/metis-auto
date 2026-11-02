"""Offline tests for golden-v2: the config, the derivation, the ID mapping.

All data is [SYNTHETIC] except the committed ID-only files, which hold no text.
No database, no model, no dataset content (ADR-0029).
"""

import json
import tomllib
from collections import Counter
from pathlib import Path

import pytest

from metis_auto.evaluation.golden.config import (
    ConfigError,
    config_sha256,
    parse_config,
)
from metis_auto.evaluation.golden.mapping import build_mapping, carry_labels
from metis_auto.evaluation.golden.selection import (
    Candidate,
    derive_without,
    select,
)

ROOT = Path(__file__).resolve().parents[3]
V1 = (ROOT / "config/evaluation/golden_v1.toml").read_bytes()
V2 = (ROOT / "config/evaluation/golden_v2.toml").read_bytes()
V1_REPORTS = ROOT / "reports/evaluation/golden_v1"
V2_REPORTS = ROOT / "reports/evaluation/golden_v2"


def raw_of(data: bytes):
    return tomllib.loads(data.decode())


# --- config ------------------------------------------------------------------------


def test_v2_config_parses_and_keeps_every_design_value_of_v1():
    one, two = raw_of(V1), raw_of(V2)
    parse_config(two, config_sha256(V2))
    for section in (
        "quotas",
        "minimums",
        "caps",
        "buckets",
        "selection",
        "language_groups",
        "intent_map",
        "rules",
        "review",
        "cohorts",
    ):
        assert two[section] == one[section], section
    same = {k: v for k, v in two["dataset"].items() if k in one["dataset"]}
    differ = {k for k in same if same[k] != one["dataset"][k]}
    assert differ == {"dataset_id", "version", "record_prefix"}
    assert two["dataset"]["seed"] == one["dataset"]["seed"]
    assert two["dataset"]["total"] == 300


def test_v2_drops_only_the_attachment_coverage_minimum():
    one, two = raw_of(V1)["coverage"], raw_of(V2)["coverage"]
    assert set(one) - set(two) == {"attachment_dependent"}
    assert all(two[k] == one[k] for k in two)


def test_v2_derives_from_the_committed_v1_fingerprint():
    committed = json.loads((V1_REPORTS / "fingerprint.json").read_text())
    assert raw_of(V2)["derive"]["base_fingerprint"] == committed["fingerprint"]
    assert raw_of(V2)["derive"]["base_dataset"] == committed["dataset_id"]


def test_a_derived_config_may_not_require_attachments():
    raw = raw_of(V2)
    raw["coverage"]["attachment_dependent"] = {"minimum": 1, "mandatory": True}
    with pytest.raises(ConfigError, match="attachment_dependent"):
        parse_config(raw, "x")


def test_a_derive_section_needs_exactly_its_keys_and_a_known_rule():
    raw = raw_of(V2)
    raw["derive"]["exclude"] = "everything"
    with pytest.raises(ConfigError, match="exclude"):
        parse_config(raw, "x")
    raw = raw_of(V2)
    del raw["derive"]["base_fingerprint"]
    with pytest.raises(ConfigError, match=r"\[derive\]"):
        parse_config(raw, "x")


def test_v1_config_has_no_derive_section_and_is_untouched():
    assert "derive" not in raw_of(V1)
    assert "caveats" not in raw_of(V1)
    committed = json.loads((V1_REPORTS / "fingerprint.json").read_text())
    assert committed["config_sha256"] == config_sha256(V1)


# --- derivation --------------------------------------------------------------------


def small_cfg():
    """[SYNTHETIC] config with the real shape and tiny quotas, per-bot cap 2."""
    raw = raw_of(V2)
    raw.pop("derive")
    raw["dataset"].update(total=4, reserve_max=6)
    half = 2
    raw["quotas"] = {
        "primary_intent": {"i1": half, "i2": half},
        "cohort": {"c1": half, "Remaining accounts": half},
        "complexity_proxy": {"simple": 4},
        "language_group": {"persian": 4},
        "target_length": {"short": 4},
        "position": {"first": 4},
        "bot_class": {"instruction_only": 4},
    }
    raw["coverage"] = {}
    raw["minimums"]["primary_intent_floor"] = 1
    raw["caps"].update(per_bot=2, single_account_cohort_max=99)
    return parse_config(raw, "synthetic")


def cand(i, intent="i1", cohort="c1", bot=None):
    return Candidate(
        request_id=f"m_{i:03d}",
        session_id=f"s_{i:03d}",
        bot_id=bot or f"b_{i:03d}",
        intent=intent,
        cohort=cohort,
        strata=(
            ("complexity_proxy", "simple"),
            ("language_group", "persian"),
            ("target_length", "short"),
            ("position", "first"),
            ("bot_class", "instruction_only"),
        ),
        tags=frozenset(),
        family=f"f_{i:03d}",
        near_family=f"n_{i:03d}",
    )


def world():
    """Base: m_000,m_001 (i1|c1), m_002,m_003 (i2|Remaining). Reserves for i1|c1 in
    rank order: m_010 (bot of a kept record, cap reached), m_011, m_012."""
    pool = [
        cand(0),
        cand(1),
        cand(2, "i2", "Remaining accounts"),
        cand(3, "i2", "Remaining accounts"),
        cand(10, bot="b_001"),
        cand(11),
        cand(12),
        cand(20),
        cand(21),
    ]
    base = [
        ("m_000", "cell_quota"),
        ("m_001", "cell_quota"),
        ("m_002", "cell_quota"),
        ("m_003", "moved_same_cohort"),
    ]
    return pool, base, ["m_010", "m_011", "m_012"]


def run(pool, base, reserves, remove, exclude=frozenset()):
    return derive_without(
        pool,
        small_cfg(),
        base_primary=base,
        base_reserves=reserves,
        remove=frozenset(remove),
        exclude=frozenset(exclude),
    )


def test_a_removed_record_is_replaced_from_its_own_cell_by_the_next_reserve():
    pool, base, reserves = world()
    sel = run(pool, base, reserves, {"m_001"})
    ids = {c.request_id for c, _ in sel.primary}
    assert len(ids) == 4 and "m_001" not in ids
    replacement = ({"m_010", "m_011", "m_012"} & ids).pop()
    assert next(c for c, _ in sel.primary if c.request_id == replacement).cell == (
        "i1",
        "c1",
    )
    assert {"m_000", "m_002", "m_003"} <= ids


def test_the_per_bot_cap_skips_a_reserve_whose_bot_is_full():
    pool, base, reserves = world()
    # b_001 keeps two records (the cap is 2), so its reserve m_010 cannot come in
    pool[1] = cand(1, bot="b_001")
    pool[2] = cand(2, "i2", "Remaining accounts", bot="b_001")
    sel = run(pool, base, reserves, {"m_000"})
    ids = [c.request_id for c, _ in sel.primary]
    assert "m_010" not in ids
    assert "m_011" in ids and len(ids) == 4


def test_reserves_run_out_then_the_pool_fills_the_same_cell_in_seeded_order():
    pool, base, reserves = world()
    sel = run(pool, base, reserves, {"m_000", "m_001"}, exclude={"m_011", "m_012"})
    moves = [m for m in sel.moves if "removed" in m]
    rules = Counter(m.get("rule") for m in moves)
    assert rules == Counter({"reserve": 1, "pool": 1})
    pooled = next(m for m in moves if m.get("rule") == "pool")
    assert pooled["replacement"] in {"m_020", "m_021"}
    assert pooled["cell"] == ["i1", "c1"]
    codes = {c.request_id: code for c, code in sel.primary}
    assert codes[pooled["replacement"]] == "attachment_replacement_pool"


def test_a_cell_without_candidates_is_reported_unfilled_not_filled_elsewhere():
    pool, base, reserves = world()
    pool = [
        c
        for c in pool
        if c.request_id not in {"m_010", "m_011", "m_012", "m_020", "m_021"}
    ]
    sel = run(pool, base, [], {"m_001"})
    assert len(sel.primary) == 3
    assert any(m.get("unfilled") for m in sel.moves)
    assert {c.cell for c, _ in sel.primary if c.request_id == "m_002"} == {
        ("i2", "Remaining accounts")
    }


def test_removed_and_excluded_requests_are_never_chosen():
    pool, base, reserves = world()
    sel = run(pool, base, reserves, {"m_001", "m_011"}, exclude={"m_010"})
    chosen = {c.request_id for c, _ in sel.primary + sel.reserves}
    assert not chosen & {"m_001", "m_011", "m_010"}


def test_unchanged_records_keep_their_original_codes():
    pool, base, reserves = world()
    sel = run(pool, base, reserves, {"m_001"})
    codes = {c.request_id: code for c, code in sel.primary}
    assert codes["m_003"] == "moved_same_cohort"


def test_unused_reserves_stay_in_rank_order():
    pool, base, reserves = world()
    sel = run(pool, base, reserves, {"m_001"})
    left = [c.request_id for c, _ in sel.reserves]
    assert left == [r for r in reserves if r in left]
    assert len(left) == 2


def test_the_derivation_does_not_depend_on_input_order():
    pool, base, reserves = world()
    a = run(pool, base, reserves, {"m_000", "m_002"})
    b = run(list(reversed(pool)), base, reserves, {"m_000", "m_002"})
    assert [c.request_id for c, _ in a.primary] == [c.request_id for c, _ in b.primary]
    assert a.moves == b.moves


def test_with_nothing_to_remove_the_set_is_unchanged():
    pool, base, reserves = world()
    sel = run(pool, base, reserves, set())
    assert {c.request_id for c, _ in sel.primary} == {r for r, _ in base}
    assert [c.request_id for c, _ in sel.reserves] == reserves


def test_plain_selection_is_not_affected_by_the_new_code():
    sel = select(
        [
            cand(i, "i1" if i % 2 else "i2", "c1" if i % 3 else "Remaining accounts")
            for i in range(60)
        ],
        small_cfg(),
    )
    assert len(sel.primary) <= 4


# --- ID mapping --------------------------------------------------------------------


def test_mapping_links_unchanged_removed_and_replacement_records():
    base = {"m_1": "gv1-m_1", "m_2": "gv1-m_2", "m_3": "gv1-m_3"}
    new = {"m_1": "gv2-m_1", "m_3": "gv2-m_3", "m_9": "gv2-m_9"}
    rows = build_mapping(base, new, [{"removed": "m_2", "replacement": "m_9"}])
    by = {(r["status"], r["request_id"]): r for r in rows}
    assert by[("same", "m_1")]["record_id"] == "gv2-m_1"
    assert by[("removed", "m_2")]["replaced_by"] == "gv2-m_9"
    assert by[("replacement", "m_9")]["replaces"] == "gv1-m_2"
    assert Counter(r["status"] for r in rows) == Counter(
        {"same": 2, "removed": 1, "replacement": 1}
    )


def test_labels_carry_over_only_for_unchanged_records():
    mapping = [
        {"base_record_id": "gv1-m_1", "record_id": "gv2-m_1", "status": "same"},
        {"base_record_id": "gv1-m_2", "record_id": None, "status": "removed"},
    ]
    lines = [
        json.dumps({"record_id": "gv1-m_1", "dimension": "d", "value": "v"}),
        json.dumps({"record_id": "gv1-m_2", "dimension": "d", "value": "v"}),
        "",
    ]
    carried, dropped = carry_labels(lines, mapping)
    assert [c["record_id"] for c in carried] == ["gv2-m_1"]
    assert dropped == 1


# --- committed v2 files (IDs only) --------------------------------------------------


def test_committed_v2_fingerprint_matches_its_config_and_prefix():
    fp = json.loads((V2_REPORTS / "fingerprint.json").read_text())
    assert fp["dataset_id"] == "golden-v2" and fp["version"] == "2"
    assert fp["config_sha256"] == config_sha256(V2)
    assert fp["record_count"] == 300 == len(set(fp["record_ids"]))
    assert all(r.startswith("gv2-") for r in fp["record_ids"])


def test_committed_mapping_agrees_with_both_fingerprints():
    rows = [
        json.loads(x)
        for x in (V2_REPORTS / "golden_v1_to_golden_v2_mapping.jsonl")
        .read_text()
        .splitlines()
    ]
    v1 = set(json.loads((V1_REPORTS / "fingerprint.json").read_text())["record_ids"])
    v2 = set(json.loads((V2_REPORTS / "fingerprint.json").read_text())["record_ids"])
    assert {r["base_record_id"] for r in rows if r["base_record_id"]} == v1
    assert {r["record_id"] for r in rows if r["record_id"]} == v2
    counts = Counter(r["status"] for r in rows)
    assert counts["same"] + counts["removed"] == 300
    assert counts["same"] + counts["replacement"] == 300
    # a record id is the prefix plus the request id, so the mapping is checkable
    assert all(
        r["record_id"] == "gv2-" + r["request_id"] for r in rows if r["record_id"]
    )


def test_committed_v2_export_has_no_attachment_dependent_tag_and_marks_media():
    path = V2_REPORTS / "golden_v2_shareable.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    assert len(rows) == 300
    assert not any(r["stratum"]["tags"].get("attachment_dependent") for r in rows)
    media = [r for r in rows if r["stratum"]["primary_intent"] == "media_generation"]
    assert media and all(
        r["stratum"]["caveats"] == ["text_model_cannot_fulfil_media"] for r in media
    )
    others = [r for r in rows if r["stratum"]["primary_intent"] != "media_generation"]
    assert all(r["stratum"]["caveats"] == [] for r in others)
