"""Offline tests for golden-v1: config, selection, records, labels, validation.

All data is [SYNTHETIC]. No database, no model, no dataset content.
"""

import json
import os
import subprocess
import sys
import textwrap
import tomllib
from collections import Counter
from pathlib import Path

import pytest

from metis_auto.evaluation.golden.annotations import (
    RUBRIC,
    LabelRow,
    double_annotation_ids,
    label_errors,
    percent_agreement,
    rule_annotations,
    weighted_kappa,
)
from metis_auto.evaluation.golden.config import (
    MARGINS,
    SOFT_MARGINS,
    ConfigError,
    config_sha256,
    length_bucket,
    parse_config,
    percentile,
    position_bucket,
)
from metis_auto.evaluation.golden.records import (
    build_components,
    earlier_messages,
    leakage_errors,
)
from metis_auto.evaluation.golden.selection import (
    Candidate,
    design_weights,
    distinct_pool,
    plan_swaps,
    select,
)
from metis_auto.evaluation.golden.validation import (
    fingerprint,
    fingerprint_diff,
    scan_for_content,
)

ROOT = Path(__file__).resolve().parents[3]
RAW = (ROOT / "config/evaluation/golden_v1.toml").read_bytes()


def real_cfg():
    return parse_config(tomllib.loads(RAW.decode()), config_sha256(RAW))


def small_cfg(total=12):
    """[SYNTHETIC] config with the shape of the real one and small quotas."""
    raw = tomllib.loads(RAW.decode())
    raw["dataset"].update(total=total, reserve_max=6)
    raw["quotas"] = {
        "primary_intent": {"i1": total // 2, "i2": total - total // 2},
        "cohort": {"c1": total // 2, "Remaining accounts": total - total // 2},
        "complexity_proxy": {"simple": total // 2, "complex": total - total // 2},
        "language_group": {"persian": total // 2, "english": total - total // 2},
        "target_length": {"short": total // 2, "long": total - total // 2},
        "position": {"first": total // 2, "late": total - total // 2},
        "bot_class": {"instruction_only": total},
    }
    raw["coverage"] = {"history_recent": {"minimum": 2, "mandatory": True}}
    raw["minimums"]["primary_intent_floor"] = 1
    raw["caps"].update(per_bot=4, single_account_cohort_max=total)
    return parse_config(raw, "synthetic")


def cands(n=400):
    out = []
    for i in range(n):
        out.append(
            Candidate(
                request_id=f"m_{i}",
                session_id=f"s_{i}",
                bot_id=f"b_{i % 9}",
                intent="i1" if i % 2 else "i2",
                cohort="c1" if i % 3 else "Remaining accounts",
                strata=(
                    ("complexity_proxy", "simple" if i % 5 else "complex"),
                    ("language_group", "persian" if i % 7 else "english"),
                    ("target_length", "short" if i % 2 else "long"),
                    ("position", "first" if i % 4 else "late"),
                    ("bot_class", "instruction_only"),
                ),
                tags=frozenset({"history_recent"}) if i % 11 == 0 else frozenset(),
                family=f"f_{i}",
                near_family=f"n_{i}",
            )
        )
    return out


def test_real_config_margins_sum_to_exactly_300():
    cfg = real_cfg()
    assert cfg.total == 300
    for margin in MARGINS:
        assert sum(cfg.quotas(margin).values()) == 300, margin


def test_config_rejects_a_wrong_margin_total():
    raw = tomllib.loads(RAW.decode())
    raw["quotas"]["position"]["first"] += 1
    with pytest.raises(ConfigError):
        parse_config(raw, "x")


def test_config_hash_ignores_line_endings():
    assert config_sha256(b"a\r\nb\n") == config_sha256(b"a\nb\n")


def test_percentile_is_nearest_rank():
    assert percentile([1, 2, 3, 4], 25) == 1
    assert percentile([1, 2, 3, 4], 50) == 2
    assert percentile([1, 2, 3, 4], 99) == 4


def test_buckets():
    labels = ["a", "b", "c"]
    assert length_bucket(5, [5, 9], labels) == "a"
    assert length_bucket(6, [5, 9], labels) == "b"
    assert length_bucket(10, [5, 9], labels) == "c"
    assert [position_bucket(t, 5) for t in (1, 2, 5, 6)] == [
        "first",
        "middle",
        "middle",
        "late",
    ]


def test_selection_meets_total_and_both_cell_margins():
    cfg = small_cfg()
    sel = select(cands(), cfg)
    assert len(sel.primary) == 12
    picked = [c for c, _ in sel.primary]
    assert sum(c.intent == "i1" for c in picked) == 6
    assert sum(c.cohort == "c1" for c in picked) == 6
    assert sum(sel.joint.values()) == 12


def test_selection_limits_session_family_and_bot():
    cfg = small_cfg()
    sel = select(cands(), cfg)
    picked = [c for c, _ in sel.primary]
    assert len({c.session_id for c in picked}) == 12
    assert len({c.family for c in picked}) == 12
    assert max(Counter(c.bot_id for c in picked).values()) <= 4


def test_no_sample_in_an_empty_cell():
    cfg = small_cfg()
    sel = select([c for c in cands() if c.cell != ("i1", "c1")], cfg)
    assert ("i1", "c1") not in sel.joint


def test_one_session_cannot_supply_two_records():
    cfg = small_cfg(4)
    same = [
        Candidate(
            f"m_{i}",
            "s_same" if i < 300 else f"s_{i}",
            f"b_{i % 5}",
            "i1" if i % 2 else "i2",
            "c1" if i % 3 else "Remaining accounts",
            cands(1)[0].strata,
            frozenset(),
            f"f_{i}",
            f"n_{i}",
        )
        for i in range(400)
    ]
    picked = [c for c, _ in select(same, cfg).primary]
    assert sum(c.session_id == "s_same" for c in picked) <= 1


def test_reserves_are_outside_the_primary_set_and_ranked():
    cfg = small_cfg()
    sel = select(cands(), cfg)
    primary = {c.request_id for c, _ in sel.primary}
    reserves = [c.request_id for c, _ in sel.reserves]
    assert reserves and not primary & set(reserves)
    assert len(reserves) <= 6 and len(reserves) == len(set(reserves))


def test_selection_ignores_input_order():
    cfg = small_cfg()
    a = [c.request_id for c, _ in select(cands(), cfg).primary]
    b = [c.request_id for c, _ in select(list(reversed(cands())), cfg).primary]
    assert a == b


def test_family_control_keeps_one_per_family():
    many = [
        Candidate(
            f"m_{i}",
            f"s_{i}",
            "b",
            "i1",
            "c1",
            (),
            frozenset(),
            "same_family" if i < 5 else f"f{i}",
            f"n{i}",
        )
        for i in range(8)
    ]
    assert len(distinct_pool(many, 1)) == 4


def test_selection_does_not_depend_on_hash_randomisation(tmp_path):
    script = tmp_path / "run.py"
    script.write_text(
        textwrap.dedent(
            """
            import sys
            sys.path.insert(0, HERE)
            from test_evaluation_golden_v1 import cands, small_cfg
            from metis_auto.evaluation.golden.selection import select
            sel = select(cands(), small_cfg())
            print(",".join(c.request_id for c, _ in sel.primary + sel.reserves))
            """
        ).replace("HERE", repr(str(Path(__file__).parent)))
    )
    outs = {
        subprocess.run(
            [sys.executable, str(script)],
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for seed in ("1", "2", "4242")
    }
    assert len(outs) == 1


def test_weight_arithmetic_and_uncovered_share():
    weights, uncovered = design_weights(
        {("a", "x"): 100, ("b", "x"): 50, ("c", "x"): 50},
        {("a", "x"): 4, ("b", "x"): 5},
    )
    assert weights == {("a", "x"): 25.0, ("b", "x"): 10.0}
    assert uncovered == 0.25


def test_plan_swaps_takes_a_reserve_of_the_cell_left_behind():
    swaps = plan_swaps(
        {"r1": "coding", "r2": "translation", "r3": "coding"},
        {"r1": "translation", "r2": "translation", "r3": "translation"},
        [("x1", "translation"), ("x2", "coding")],
    )
    assert swaps == [("r1", "x1")]


# ------------------------------------------------------------------ records/leakage
def session(*rows):
    return [
        {
            "message_id": mid,
            "type": typ,
            "timestamp": ts,
            "source_ordinal": i,
            "input_state": "null",
            "content_sha256": "h",
        }
        for i, (mid, typ, ts) in enumerate(rows)
    ]


BOT = {"bot_id": "b", "instructions_sha256": "h"}


def comps(sess, target="u2", chunks=()):
    return build_components(
        target=next(m for m in sess if m["message_id"] == target),
        session=sess,
        bot=BOT,
        answer_chunks=chunks,
        earlier_chunks={},
    )


def test_history_excludes_answer_and_later_turns():
    s = session(
        ("u1", "USER", 1),
        ("a1", "AI", 2),
        ("u2", "USER", 3),
        ("a2", "AI", 4),
        ("u3", "USER", 5),
    )
    assert [m["message_id"] for m in earlier_messages(s, "u2")] == ["u1", "a1"]
    assert not leakage_errors(comps(s), target_id="u2", answer_id="a2", session=s)


def test_tied_timestamps_use_source_order():
    s = session(("u1", "USER", 1), ("a1", "AI", 1), ("u2", "USER", 1), ("a2", "AI", 1))
    assert [m["message_id"] for m in earlier_messages(s, "u2")] == ["u1", "a1"]


def test_null_timestamp_is_never_history():
    s = session(
        ("x", "AI", None), ("u1", "USER", 1), ("u2", "USER", 2), ("a2", "AI", 3)
    )
    assert [m["message_id"] for m in earlier_messages(s, "u2")] == ["u1"]


def test_consecutive_user_messages_are_history():
    s = session(("u0", "USER", 1), ("u1", "USER", 2), ("u2", "USER", 3), ("a", "AI", 4))
    assert [m["message_id"] for m in earlier_messages(s, "u2")] == ["u0", "u1"]


def test_validator_catches_an_answer_or_later_message():
    s = session(("u2", "USER", 1), ("a2", "AI", 2), ("u3", "USER", 3))
    good = comps(s)
    bad = [dict(c) for c in good]
    bad.insert(-1, {**good[-1], "source_message_id": "a2"})
    assert leakage_errors(bad, target_id="u2", answer_id="a2", session=s)
    later = [dict(c) for c in good]
    later.insert(-1, {**good[-1], "source_message_id": "u3"})
    assert leakage_errors(later, target_id="u2", answer_id="a2", session=s)


def test_chunks_are_only_in_the_post_retrieval_profile():
    s = session(("u2", "USER", 1), ("a2", "AI", 2))
    out = comps(s, chunks=[{"file_id": 1, "row": 2, "content_sha256": "h"}])
    chunk = next(c for c in out if c["source_kind"] == "rag_chunk")
    assert chunk["included_post_retrieval"] and not chunk["included_pre_retrieval"]
    assert chunk["availability_stage"] == "retrieval_order_unknown"


def test_model_labels_are_not_routing_input():
    s = session(("u2", "USER", 1), ("a2", "AI", 2))
    bot = {**BOT, "provider_model": "[SYNTHETIC]-model", "provider_name": "x"}
    out = build_components(
        target=s[0], session=s, bot=bot, answer_chunks=(), earlier_chunks={}
    )
    assert "[SYNTHETIC]-model" not in json.dumps(out, default=str)


# ------------------------------------------------------------------------- labels
def test_rule_labels_are_proposals_and_never_complexity():
    rows = rule_annotations(
        "r", {"rule_intent": "coding", "rule_tags": {"time_sensitive": True}}, "v1"
    )
    assert {r["review_status"] for r in rows} == {"proposed"}
    assert "complexity" not in {r["dimension"] for r in rows}


def test_label_validation_rejects_unknowns_and_llm_without_approval():
    good = LabelRow("r", "complexity", "simple", "p1")
    assert label_errors([good], {"r"}) == []
    assert label_errors([LabelRow("x", "complexity", "simple", "p1")], {"r"})
    assert label_errors([LabelRow("r", "complexity", "huge", "p1")], {"r"})
    assert label_errors([LabelRow("r", "nope", "simple", "p1")], {"r"})
    llm = LabelRow("r", "complexity", "simple", "p1", method="llm_assisted")
    assert label_errors([llm], {"r"})
    assert label_errors([llm], {"r"}, llm_approved=True) == []


def test_every_rubric_dimension_has_values():
    assert all(RUBRIC.values())


def test_agreement_measures():
    assert percent_agreement([("a", "a"), ("a", "b")]) == 0.5
    assert percent_agreement([]) is None
    perfect = [("simple", "simple"), ("average", "average"), ("complex", "complex")]
    assert weighted_kappa(perfect) == 1.0
    assert weighted_kappa([]) is None
    assert weighted_kappa([("simple", "simple")]) is None


def test_double_annotation_share_is_stratified():
    strata = {f"r{i}": ("a" if i < 50 else "b") for i in range(60)}
    rank = {k: k for k in strata}
    chosen = double_annotation_ids(strata, 0.2, rank)
    assert sum(int(c[1:]) < 50 for c in chosen) == 10
    assert sum(int(c[1:]) >= 50 for c in chosen) == 2


# --------------------------------------------------------------------- fingerprint
def test_fingerprint_ignores_order_and_detects_a_change():
    assert fingerprint(["a", "b"], "1", "c") == fingerprint(["b", "a"], "1", "c")
    assert fingerprint(["a"], "1", "c") != fingerprint(["b"], "1", "c")


def test_fingerprint_diff_names_the_first_difference():
    base = {
        "dataset_revision": "r",
        "config_sha256": "c",
        "record_count": 1,
        "record_ids": ["a"],
        "fingerprint": "f",
    }
    assert fingerprint_diff(base, dict(base)) is None
    assert "config" in fingerprint_diff(base, {**base, "config_sha256": "d"})
    assert "revision" in fingerprint_diff(base, {**base, "dataset_revision": "x"})
    assert "record ids" in fingerprint_diff(
        base, {**base, "record_ids": ["b"], "fingerprint": "g"}
    )


def test_content_scan_finds_text_without_quoting_it():
    secret = "[SYNTHETIC] a private sentence"
    hits = scan_for_content({"a.md": f"x {secret} y", "b.md": "clean"}, [secret])
    assert hits == [("a.md", "exact dataset text")]
    assert secret not in json.dumps(hits)
    long_run = "س" * 70
    assert scan_for_content({"c.md": long_run}, []) == [
        ("c.md", "long Arabic-script run")
    ]


def test_soft_margins_are_a_subset_of_margins():
    assert set(SOFT_MARGINS) <= set(MARGINS)
