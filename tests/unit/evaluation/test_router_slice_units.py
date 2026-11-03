"""Pure parts of the routing dev slice (ADR-0047): config
bounds, the seeded selection, splits, the Request mapping, review assignment, label
agreement, and dataset-root resolution (Windows-style paths). SYNTHETIC only."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from pydantic import ValidationError

from metis_auto.contracts import ComponentState, Modality, Role
from metis_auto.evaluation.router_slice.config import HARD_MAX, SliceConfig, load_config
from metis_auto.evaluation.router_slice.records import to_request
from metis_auto.evaluation.router_slice.reports import (
    _kappa,
    import_labels,
    review_assignment,
)
from metis_auto.evaluation.router_slice.select import (
    Candidate,
    Caps,
    Targets,
    allocate,
    select,
    split_by_session,
)
from metis_auto.evaluation.router_slice.weights import (
    format_weight,
    traffic_weights,
    uncovered_share,
)
from metis_auto.settings import repo_root

MARKER = "[SYNTHETIC]"
BASE = {
    "slice": {
        "slice_id": "router-dev-slice-x",
        "record_prefix": "rsx",
        "size": 150,
        "seed": 1,
        "revision": "0" * 40,
        "candidate_pool": 300,
    },
    "inputs": {
        "source_config": "a",
        "features_config": "b",
        "label_mapping": "c",
        "golden_exports": [],
    },
}


def cfg(**slice_changes) -> SliceConfig:
    data = json.loads(json.dumps(BASE))
    data["slice"].update(slice_changes)
    return SliceConfig.model_validate(data)


# --- config -------------------------------------------------------------------------


@pytest.mark.parametrize("size", [99, HARD_MAX + 1, 10_000])
def test_size_outside_100_to_200_is_refused(size):
    with pytest.raises(ValidationError, match="100–200"):
        cfg(size=size, candidate_pool=20_000)


def test_the_committed_config_loads_and_is_150():
    loaded, digest = load_config(
        repo_root() / "config/evaluation/router_dev_slice_v1.toml"
    )
    assert loaded.slice.size == 150 and digest.startswith("sha256:")
    assert loaded.review.double_share >= 0.2
    assert loaded.caps.per_session == 1


GOLDEN_HALVED = {
    "Remaining accounts": 30,
    "User A": 31,
    "User B": 30,
    "User C": 22,
    "User D": 21,
    "User E": 16,
}


def test_the_committed_config_uses_the_golden_cohort_allocation_halved():
    loaded, _ = load_config(repo_root() / "config/evaluation/router_dev_slice_v1.toml")
    assert loaded.share_targets(150)["cohort"] == GOLDEN_HALVED
    caps = loaded.ceiling_counts(150)["cohort"]
    # target + 2, and the 30% bound (45) on Remaining accounts is not the lower one
    assert caps == {k: v + 2 for k, v in GOLDEN_HALVED.items()}
    assert loaded.cohorts.pool_min_multiple == 5.0
    assert loaded.slice.candidate_pool >= 5 * loaded.slice.size
    assert loaded.weights.traffic_basis == "eligible_targets"


def _with_cohorts(**cohorts) -> dict:
    data = json.loads(json.dumps(BASE))
    data["slice"]["candidate_pool"] = 750  # 5 × 150
    data["cohorts"] = {"targets": dict(GOLDEN_HALVED), **cohorts}
    return data


def test_cohort_targets_are_checked():
    SliceConfig.model_validate(_with_cohorts())
    bad = _with_cohorts()
    bad["cohorts"]["targets"]["User E"] = 17  # sums to 151
    with pytest.raises(ValidationError, match="not the slice size"):
        SliceConfig.model_validate(bad)
    both = _with_cohorts()
    both["quotas"] = {"cohort": {"User A": 0.2}}
    with pytest.raises(ValidationError, match="not both"):
        SliceConfig.model_validate(both)
    with pytest.raises(ValidationError, match="pool_min_multiple"):
        SliceConfig.model_validate(_with_cohorts(pool_min_multiple=6.0))  # 750 < 900
    zero = _with_cohorts()
    zero["cohorts"]["targets"]["User E"] = 0
    with pytest.raises(ValidationError, match="above 0"):
        SliceConfig.model_validate(zero)


def test_a_share_ceiling_lower_than_target_plus_tolerance_wins():
    data = _with_cohorts(tolerance=5)
    data["ceilings"] = {"cohort": {"Remaining accounts": 0.2}}  # 30 records
    caps = SliceConfig.model_validate(data).ceiling_counts(150)["cohort"]
    assert caps["Remaining accounts"] == 30 and caps["User A"] == 36


def test_a_ceiling_below_its_floor_or_on_an_unknown_dimension_is_refused():
    data = json.loads(json.dumps(BASE))
    data["quotas"] = {"cohort": {"Remaining accounts": 0.25}}
    data["ceilings"] = {"cohort": {"Remaining accounts": 0.2}}
    with pytest.raises(ValidationError, match="below the quota floor"):
        SliceConfig.model_validate(data)
    data["ceilings"] = {"weather": {"x": 0.5}}
    with pytest.raises(ValidationError, match="unknown ceiling"):
        SliceConfig.model_validate(data)
    data["ceilings"] = {"cohort": {"Remaining accounts": 0.3}}
    data["weights"] = {"traffic_basis": "page_views"}
    with pytest.raises(ValidationError, match="traffic_basis"):
        SliceConfig.model_validate(data)


def test_quota_shares_and_minimums_are_checked():
    data = json.loads(json.dumps(BASE))
    data["quotas"] = {"language_group": {"persian": 0.7, "english": 0.4}}
    with pytest.raises(ValidationError, match="sum above 1"):
        SliceConfig.model_validate(data)
    data["quotas"] = {"weather": {"x": 0.1}}
    with pytest.raises(ValidationError, match="unknown quota"):
        SliceConfig.model_validate(data)
    data["quotas"] = {}
    data["minimums"] = {"greeting": 151}
    with pytest.raises(ValidationError):
        SliceConfig.model_validate(data)


# --- selection ----------------------------------------------------------------------


def pool(n: int = 400) -> list[Candidate]:
    out = []
    for i in range(n):
        out.append(
            Candidate(
                key=f"m{i}",
                session_id=f"s{i // 2}",
                bot_id=f"b{i % 25}",
                strata={
                    "lang": "fa" if i % 10 < 8 else "en",
                    "pos": "first" if i % 3 else "follow",
                },
                flags=frozenset({"rare"}) if i % 50 == 0 else frozenset(),
                families=(f"f{i % 300}",),
            )
        )
    return out


TARGETS = Targets(
    shares={"lang": {"en": 30}, "pos": {"follow": 40}}, minimums={"rare": 5}
)


def test_quotas_are_met_when_available_and_caps_hold():
    sel = select(
        pool(),
        100,
        TARGETS,
        Caps(per_session=1, per_bot=6, per_family=1),
        seed=3,
        purpose="t",
    )
    assert len(sel.chosen) == 100
    assert sel.achieved["lang"]["en"] >= 30
    assert sel.achieved["pos"]["follow"] >= 40
    assert sel.flag_counts["rare"] >= 5
    sessions = [c.session_id for c in sel.chosen]
    assert len(set(sessions)) == len(sessions)
    bots = [c.bot_id for c in sel.chosen]
    assert max(bots.count(b) for b in set(bots)) <= 6
    families = [f for c in sel.chosen for f in c.families]
    assert len(set(families)) == len(families)
    assert sel.shortfalls(TARGETS) == []


def test_selection_is_deterministic_and_independent_of_input_order():
    items = pool()
    shuffled = items[:]
    random.Random(5).shuffle(shuffled)
    a = select(items, 80, TARGETS, Caps(), seed=9, purpose="t")
    b = select(shuffled, 80, TARGETS, Caps(), seed=9, purpose="t")
    c = select(items, 80, TARGETS, Caps(), seed=10, purpose="t")
    assert [x.key for x in a.chosen] == [x.key for x in b.chosen]
    assert [x.key for x in a.chosen] != [x.key for x in c.chosen]


def test_an_unmeetable_target_is_reported_not_forced():
    targets = Targets(shares={"lang": {"zz": 5}}, minimums={"never": 3})
    sel = select(
        pool(50), 20, targets, Caps(per_session=1, per_bot=100), seed=1, purpose="t"
    )
    shortfalls = {(d, v) for d, v, _, _ in sel.shortfalls(targets)}
    assert shortfalls == {("lang", "zz"), ("flag", "never")}
    assert len(sel.chosen) == 20


def test_a_ceiling_is_hard_even_when_its_value_dominates_the_pool():
    # 80% of the pool is "fa"; a floor pulls towards it, the ceiling stops it.
    targets = Targets(
        shares={"lang": {"fa": 20}}, ceilings={"lang": {"fa": 25}}, minimums={}
    )
    sel = select(pool(), 60, targets, Caps(per_bot=100), seed=4, purpose="t")
    assert len(sel.chosen) == 60
    assert sel.achieved["lang"]["fa"] == 25
    assert sel.achieved["lang"]["en"] == 35
    assert sel.skipped_by_cap["ceiling:lang=fa"] > 0


def test_ceilings_leave_a_draw_unchanged_when_they_do_not_bind():
    loose = Targets(
        shares=TARGETS.shares, minimums=TARGETS.minimums, ceilings={"lang": {"en": 99}}
    )
    a = select(pool(), 80, TARGETS, Caps(), seed=9, purpose="t")
    b = select(pool(), 80, loose, Caps(), seed=9, purpose="t")
    assert [x.key for x in a.chosen] == [x.key for x in b.chosen]


def test_allocate_is_proportional_capped_and_redistributes():
    weights = {"R": 30, "A": 31, "B": 30, "C": 22, "D": 21, "E": 16}
    big = dict.fromkeys(weights, 10**6)
    out = allocate(1500, weights, big)
    assert out == {"R": 300, "A": 310, "B": 300, "C": 220, "D": 210, "E": 160}
    capped = allocate(1500, weights, {**big, "E": 50})
    assert capped["E"] == 50 and sum(capped.values()) == 1500
    assert capped["A"] > 310  # E's spare went to the others in proportion
    assert allocate(10, {"x": 1, "y": 1}, {"x": 3, "y": 3}) == {"x": 3, "y": 3}
    odd = allocate(7, {"x": 1, "y": 1, "z": 1}, dict.fromkeys("xyz", 9))
    assert sum(odd.values()) == 7 and max(odd.values()) - min(odd.values()) <= 1


def test_exempt_bots_ignore_the_per_bot_cap():
    one_bot = [
        Candidate(key=f"m{i}", session_id=f"s{i}", bot_id="only", strata={})
        for i in range(30)
    ]
    capped = select(one_bot, 20, Targets(), Caps(per_bot=10), seed=1, purpose="t")
    free = select(
        one_bot,
        20,
        Targets(),
        Caps(per_bot=10, per_bot_exempt=frozenset({"only"})),
        seed=1,
        purpose="t",
    )
    assert len(capped.chosen) == 10 and len(free.chosen) == 20


def test_traffic_weights_restore_traffic_shares():
    weights = traffic_weights(
        {"A": 30, "B": 45, "R": 75}, {"A": 600, "B": 370, "R": 30}
    )
    assert weights["R"].weight == pytest.approx(0.03 / 0.5)
    assert weights["A"].weight == pytest.approx(0.6 / 0.2)
    total = sum(w.records * w.weight for w in weights.values())
    assert total == pytest.approx(150)
    assert format_weight(weights["R"].weight) == "0.060000"
    assert uncovered_share(weights) == 0


def test_a_cohort_without_records_is_uncovered_and_unweighted():
    weights = traffic_weights({"A": 10}, {"A": 90, "Z": 10})
    assert weights["Z"].weight is None and format_weight(None) == ""
    assert uncovered_share(weights) == pytest.approx(0.1)
    with pytest.raises(ValueError, match="not the traffic"):
        traffic_weights({"Q": 1}, {"A": 1})
    with pytest.raises(ValueError):
        traffic_weights({}, {"A": 1})


def test_an_exhausted_pool_stops_short():
    sel = select(pool(10), 50, Targets(), Caps(per_session=1), seed=1, purpose="t")
    assert len(sel.chosen) == 5  # ten candidates, two per session


def test_split_keeps_sessions_whole_and_follows_the_share():
    sessions = [f"s{i}" for i in range(100)] + ["s1", "s2"]
    split = split_by_session(sessions, 0.7, seed=4)
    assert len(split) == 100
    assert sum(v == "tune" for v in split.values()) == 70
    assert split == split_by_session(list(reversed(sessions)), 0.7, seed=4)


# --- the Request mapping -------------------------------------------------------------


def record(**changes) -> dict:
    base = {
        "slice_record_id": "rsx-m-1",
        "session_id": "s-1",
        "turn_index": 2,
        "message": f"{MARKER} message",
        "history_json": json.dumps(
            [
                {"role": "user", "text": f"{MARKER} earlier"},
                {"role": "assistant", "text": f"{MARKER} reply"},
            ]
        ),
        "history_turns_total": 2,
        "instructions_state": "present",
        "instructions": f"{MARKER} instructions",
        "retrieved_json": json.dumps(
            [{"chunk_id": "ch-1", "text": f"{MARKER} chunk", "relevancy": 0.4}]
        ),
        "attachment_types_json": json.dumps(["image/png"]),
        "previous_ai_input_state": "ok",
    }
    base.update(changes)
    return base


def test_post_retrieval_request_carries_every_component():
    req = to_request(record(), profile="post_retrieval")
    assert [t.role for t in req.history.value] == [Role.USER, Role.ASSISTANT]
    assert req.instructions.state == ComponentState.PRESENT
    assert req.retrieved.value.items[0].document_ref == "ch-1"
    assert req.attachments.value[0].modality == Modality.IMAGE
    assert req.structured_input.state == ComponentState.UNKNOWN
    assert req.caller_request_ref == "rsx-m-1"
    assert req.session_ref.startswith("rs1s-") and "s-1" not in req.session_ref


def test_pre_retrieval_hides_the_answers_chunks():
    req = to_request(record(), profile="pre_retrieval")
    assert req.retrieved.state == ComponentState.UNKNOWN
    assert req.retrieved.unknown_reason == "not_yet_retrieved"


def test_first_turn_blank_instructions_and_dropped_history():
    first = to_request(
        record(
            turn_index=1,
            history_json="[]",
            history_turns_total=0,
            instructions_state="absent",
            instructions=None,
            retrieved_json="[]",
            attachment_types_json="[]",
            previous_ai_input_state=None,
        ),
        profile="post_retrieval",
    )
    assert first.history.state == ComponentState.ABSENT
    assert first.instructions.state == ComponentState.ABSENT
    assert first.retrieved.state == ComponentState.ABSENT
    assert first.attachments.state == ComponentState.ABSENT
    assert first.structured_input.state == ComponentState.ABSENT
    dropped = to_request(record(history_json="[]"), profile="post_retrieval")
    assert dropped.history.state == ComponentState.UNKNOWN
    unknown = to_request(
        record(instructions_state="unknown", instructions=None),
        profile="post_retrieval",
    )
    assert unknown.instructions.state == ComponentState.UNKNOWN


def test_an_odd_chunk_id_is_not_used_as_a_reference():
    rec = record(
        retrieved_json=json.dumps(
            [{"chunk_id": "a b/c", "text": f"{MARKER} x", "relevancy": None}]
        )
    )
    req = to_request(rec, profile="post_retrieval")
    assert req.retrieved.value.items[0].document_ref is None


# --- review sheet and labels ---------------------------------------------------------


def test_review_assignment_double_annotates_at_least_the_share():
    ids = [f"r{i}" for i in range(150)]
    pairs = review_assignment(ids, ("R1", "R2"), 0.2, seed=1)
    per_record: dict[str, set[str]] = {}
    for rid, reviewer in pairs:
        per_record.setdefault(rid, set()).add(reviewer)
    assert set(per_record) == set(ids)
    assert sum(len(v) == 2 for v in per_record.values()) == 30
    load = [r for _, r in pairs]
    assert abs(load.count("R1") - load.count("R2")) <= 1


def test_kappa_and_label_validation():
    assert _kappa([("0", "0"), ("1", "1"), ("0", "1"), ("1", "0")]) == pytest.approx(
        0.0
    )
    assert _kappa([("0", "0"), ("1", "1")]) == pytest.approx(1.0)
    assert _kappa([("0", "0")]) is None  # undefined: one category only
    rows = [
        {
            "slice_record_id": "a",
            "reviewer": "R1",
            "tier_needed": "1",
            "small_model_ok": "no",
        },
        {
            "slice_record_id": "a",
            "reviewer": "R2",
            "tier_needed": "1",
            "small_model_ok": "yes",
        },
        {
            "slice_record_id": "b",
            "reviewer": "R1",
            "tier_needed": "",
            "small_model_ok": "",
        },
        {
            "slice_record_id": "c",
            "reviewer": "R3",
            "tier_needed": "0",
            "small_model_ok": "yes",
        },
        {
            "slice_record_id": "a",
            "reviewer": "R1",
            "tier_needed": "2",
            "small_model_ok": "yes",
        },
    ]
    result = import_labels(rows, {"a", "b", "c"}, ("R1", "R2"))
    assert len(result.labels) == 2
    assert result.agreement["double_annotated"] == 1
    assert result.agreement["tier_needed"]["percent_agreement"] == 1.0
    assert len(result.problems) == 2  # unknown reviewer; bad value


# --- dataset root ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "configured",
    [
        "C:\\Users\\someone\\Desktop\\metis-data",
        "C:/Users/someone/metis-data",
        "\\\\nas\\share\\metis",
    ],
)
def test_windows_style_roots_are_absolute(configured):
    from metis_auto.data_access.full.source import is_absolute_root

    assert is_absolute_root(configured)


def test_relative_roots_are_joined_to_the_repository(tmp_path):
    from metis_auto.data_access.full.source import is_absolute_root, resolve_root

    assert not is_absolute_root("data/full_data/raw")
    resolved = resolve_root("data/full_data/raw", tmp_path)
    assert resolved == (tmp_path / "data" / "full_data" / "raw").resolve()
    assert resolved.parts[-3:] == ("data", "full_data", "raw")
    assert isinstance(resolved, Path)
