"""The routing dev slice end to end on a SYNTHETIC Parquet miniature with the
real schema (ADR-XXXX (system-one-decision-router)): plan reads no text, build is
deterministic and obeys exclusions and caps, committable outputs carry no content,
verify catches a changed config or a different build, labels import as ID + label
only."""

from __future__ import annotations

import csv
import io
import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")

from fixtures.synthetic.full_dataset import (  # noqa: E402
    MARKER,
    REPO,
    REVISION,
    write_dataset,
    write_source_config,
)

from metis_auto.data_access.full import reader  # noqa: E402
from metis_auto.wiring.router_slice import RouterSlice, SliceRefused  # noqa: E402

SLICE_TOML = """
[slice]
slice_id = "router-dev-slice-test"
record_prefix = "rst"
size = {size}
seed = {seed}
revision = "{revision}"
candidate_pool = 200

[inputs]
source_config = "config/evaluation/source_synthetic.toml"
features_config = "config/evaluation/golden_v1.toml"
label_mapping = "config/reference/label-mapping-full-v1.toml"
golden_exports = ["reports/evaluation/golden_v1/golden_v1_shareable.jsonl"]

[caps]
per_session = 1
per_bot = 10
per_family = 1

[quotas.language_group]
persian = 0.6
english = 0.1

[quotas.position]
first = 0.35
follow_up = 0.65

[quotas.cohort]
"Remaining accounts" = 0.2

[ceilings.cohort]
"Remaining accounts" = 0.3

[minimums]
attachments = 2
high_input = 5
rag_on_answer = 10
"""


COHORTS_TOML = """
[cohorts]
targets = {{ "Remaining accounts" = 30, "User A" = 15, "User B" = 15, "User C" = 15, \
"User D" = 15, "User E" = 10 }}
tolerance = 2
pool_min_multiple = 1.0
waive_per_bot_if_cohort_bots_at_most = 2
"""


def make_repo(
    tmp: Path, *, size: int = 100, seed: int = 11, cohorts: bool = False
) -> tuple[Path, Path, dict]:
    repo = tmp / "repo"
    data = tmp / "dataset"
    facts = write_dataset(data)
    (repo / "config" / "evaluation").mkdir(parents=True)
    (repo / "config" / "reference").mkdir(parents=True)
    shutil.copy(REPO / "config/evaluation/golden_v1.toml", repo / "config/evaluation/")
    shutil.copy(
        REPO / "config/reference/label-mapping-full-v1.toml", repo / "config/reference/"
    )
    write_source_config(repo / "config/evaluation/source_synthetic.toml", facts)
    text = SLICE_TOML.format(size=size, seed=seed, revision=REVISION)
    if cohorts:
        text = text.replace('[quotas.cohort]\n"Remaining accounts" = 0.2\n', "")
        text += COHORTS_TOML.format().replace("\\\n", "")
    (repo / "config/evaluation/router_dev_slice_test.toml").write_text(
        text, encoding="utf-8"
    )
    golden = repo / "reports/evaluation/golden_v1"
    golden.mkdir(parents=True)
    (golden / "golden_v1_shareable.jsonl").write_text(
        json.dumps(
            {
                "record_id": f"gv1-{facts['golden']}",
                "session_id": f"s-{50:05d}",
                "bot_id": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return repo, data, facts


def make_slice(repo: Path, data: Path) -> RouterSlice:
    return RouterSlice(
        repo,
        str(data),
        repo / "config/evaluation/router_dev_slice_test.toml",
        log=lambda _: None,
    )


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("slice")
    repo, data, facts = make_repo(tmp)
    sl = make_slice(repo, data)
    summary = sl.build()
    return sl, summary, facts


def records_of(sl: RouterSlice) -> list[dict]:
    from metis_auto.data_access.full.records import read_records

    return read_records(sl.paths.records)


def test_plan_reads_no_text(tmp_path, monkeypatch):
    repo, data, _ = make_repo(tmp_path)
    seen: list[list[str]] = []
    original = reader._read

    def spy(path, columns):
        seen.append(list(columns))
        return original(path, columns)

    monkeypatch.setattr(reader, "_read", spy)
    plan = make_slice(repo, data).plan()
    read_columns = {c for cols in seen for c in cols}
    assert not read_columns & {
        "content",
        "instructions",
        "attachments",
        "input",
        "headline",
        "query",
    }
    assert plan["eligible_targets"] > 100
    assert plan["exclusions"]["workflow_bot"] > 0
    assert "golden_record" in plan["exclusions"]


def test_build_writes_the_configured_size_with_splits(built):
    sl, summary, _ = built
    assert summary["records"] == 100
    assert summary["splits"] == {"check": 30, "tune": 70}
    assert summary["peak_rss_mb"] is None or summary["peak_rss_mb"] > 0
    records = records_of(sl)
    assert len({r["slice_record_id"] for r in records}) == 100
    assert all(r["slice_record_id"].startswith("rst-") for r in records)


def test_exclusions_and_caps_hold(built):
    sl, _, facts = built
    records = records_of(sl)
    ids = {r["message_id"] for r in records}
    assert not ids & facts["workflow_targets"]
    assert not ids & facts["consecutive_user"]
    assert not ids & facts["not_stop"]
    assert not ids & facts["null_ts"]
    assert facts["golden"] not in ids
    golden_session = f"s-{50:05d}"
    assert all(r["session_id"] != golden_session for r in records)
    sessions = [r["session_id"] for r in records]
    assert len(sessions) == len(set(sessions))  # one per session
    per_bot: dict[str, int] = {}
    for r in records:
        per_bot[r["bot_id"]] = per_bot.get(r["bot_id"], 0) + 1
    assert max(per_bot.values()) <= 10
    assert all(r["bot_class"] != "workflow_unknown_config" for r in records)
    # one record per duplicate family: the repeated short greeting appears once at most
    greetings = [r for r in records if r["message"] == f"{MARKER} سلام"]
    assert len(greetings) <= 1
    splits = {}
    for r in records:
        splits.setdefault(r["session_id"], set()).add(r["split"])
    assert all(len(v) == 1 for v in splits.values())


def test_quotas_drive_the_draw_and_shortfalls_are_reported(built):
    sl, _, _ = built
    manifest = json.loads(sl.paths.manifest.read_text(encoding="utf-8"))
    stats = manifest["stats"]
    assert stats["achieved"]["position"]["first"] >= 30
    assert stats["flag_counts"].get("attachments", 0) >= 1
    assert stats["flag_counts"].get("rag_on_answer", 0) >= 10
    composition = (sl.paths.reports / "composition.md").read_text(encoding="utf-8")
    assert "## Shortfalls" in composition and "## Exclusions" in composition


def test_committable_outputs_hold_no_content(built):
    sl, _, _ = built
    files = list(sl.paths.reports.iterdir())
    assert {f.name for f in files} >= {
        "ids.csv",
        "composition.md",
        "fingerprint.json",
        "review_template.csv",
    }
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert MARKER not in text, f.name
        assert "sha256:" not in text or f.name in ("fingerprint.json", "composition.md")
    header = next(csv.reader(io.StringIO((sl.paths.reports / "ids.csv").read_text())))
    assert header == [
        "slice_record_id",
        "split",
        "language_group",
        "position",
        "bot_class",
        "cohort",
        "rule_intent",
        "flags",
        "traffic_weight",
    ]


def test_the_local_review_sheet_has_text_and_double_annotation(built):
    sl, _, _ = built
    raw = sl.paths.review_local.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM for Excel
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    assert any(MARKER in r["message"] for r in rows)
    per_record: dict[str, int] = {}
    for r in rows:
        per_record[r["slice_record_id"]] = per_record.get(r["slice_record_id"], 0) + 1
    assert len(per_record) == 100
    assert sum(v == 2 for v in per_record.values()) >= 20
    assert {r["reviewer"] for r in rows} == {"R1", "R2"}


def test_build_is_deterministic_and_seed_sensitive(built, tmp_path):
    sl, _, _ = built
    repo, data, _ = make_repo(tmp_path / "a")
    again = make_slice(repo, data)
    again.build()
    assert (again.paths.reports / "ids.csv").read_bytes() == (
        sl.paths.reports / "ids.csv"
    ).read_bytes()
    first = json.loads((sl.paths.reports / "fingerprint.json").read_text())
    second = json.loads((again.paths.reports / "fingerprint.json").read_text())
    assert first == second
    repo2, data2, _ = make_repo(tmp_path / "b", seed=12)
    other = make_slice(repo2, data2)
    other.build()
    assert (other.paths.reports / "ids.csv").read_bytes() != (
        sl.paths.reports / "ids.csv"
    ).read_bytes()


def test_verify_passes_then_catches_changes(built):
    sl, _, _ = built
    assert sl.verify() == []
    assert sl.last_audit["golden_records"] == 1
    assert sl.last_audit["golden_records_in_slice"] == 0
    assert sl.last_audit["slice_records_from_golden_sessions"] == 0
    cfg = sl.config_path
    original = cfg.read_text(encoding="utf-8")
    cfg.write_text(original.replace("tune_share", "tune_share"), encoding="utf-8")
    cfg.write_text(original.replace("seed = 11", "seed = 99"), encoding="utf-8")
    try:
        changed = make_slice(sl.repo, sl.data_root)
        problems = changed.verify(hash_files=False)
        assert any("config changed" in p for p in problems)
    finally:
        cfg.write_text(original, encoding="utf-8")
    ids = sl.paths.reports / "ids.csv"
    saved = ids.read_bytes()
    ids.write_bytes(saved.replace(b"tune", b"check", 1))
    try:
        assert any("ids.csv" in p for p in sl.verify(hash_files=False))
    finally:
        ids.write_bytes(saved)


def test_report_refuses_a_changed_config(built):
    sl, _, _ = built
    assert sl.report()["records"] == 100
    cfg = sl.config_path
    original = cfg.read_text(encoding="utf-8")
    cfg.write_text(original.replace("per_bot = 10", "per_bot = 9"), encoding="utf-8")
    try:
        with pytest.raises(SliceRefused, match="config changed"):
            make_slice(sl.repo, sl.data_root).report()
    finally:
        cfg.write_text(original, encoding="utf-8")


def test_a_changed_dataset_file_is_refused(tmp_path):
    repo, data, _ = make_repo(tmp_path)
    shard = data / "data" / "chat_session.parquet"
    shard.write_bytes(shard.read_bytes() + b"x")
    with pytest.raises(SliceRefused, match="source problem"):
        make_slice(repo, data).build()


def test_labels_import_as_id_and_label_only(built, tmp_path):
    sl, _, _ = built
    template = (sl.paths.reports / "review_template.csv").read_text(encoding="utf-8")
    rows = list(csv.DictReader(io.StringIO(template)))
    for i, r in enumerate(rows):
        r["tier_needed"] = "1" if i % 3 == 0 else "0"
        r["small_model_ok"] = "no" if i % 3 == 0 else "yes"
        r["notes"] = f"{MARKER} reviewer note"  # extra columns are dropped
    path = tmp_path / "done.csv"
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=[*rows[0].keys()])
        w.writeheader()
        w.writerows(rows)
    agreement = sl.import_labels(path)
    assert agreement["records_labelled"] == 100 and agreement["double_annotated"] >= 20
    out = (sl.paths.reports / "labels_l3.csv").read_text(encoding="utf-8")
    assert MARKER not in out
    rows[0]["slice_record_id"] = "rst-unknown"
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=[*rows[0].keys()])
        w.writeheader()
        w.writerows(rows)
    with pytest.raises(SliceRefused, match="unknown slice_record_id"):
        sl.import_labels(path)


def test_targeted_reads_return_only_the_requested_sessions(built):
    sl, _, _ = built
    wanted = {"s-00010", "s-00011"}
    rows = reader.session_messages(sl.data_root, wanted)
    assert {r["session_id"] for r in rows} == wanted
    assert all("attachments" not in r and "input" not in r for r in rows)


def test_the_golden_audit_catches_a_golden_record_in_the_slice(built):
    sl, _, facts = built
    records = records_of(sl)
    fake = dict(records[0])
    fake["message_id"] = facts["golden"]
    fake["session_id"] = "s-00050"
    audit = sl.golden_audit([fake, *records[1:]])
    assert audit["golden_records_in_slice"] == 1
    assert audit["slice_records_from_golden_sessions"] == 1
    assert len(audit["problems"]) == 2


def test_the_cohort_ceiling_is_hard_and_reported(built):
    sl, _, _ = built
    records = records_of(sl)
    remaining = sum(r["cohort"] == "Remaining accounts" for r in records)
    assert 20 <= remaining <= 30
    stats = json.loads(sl.paths.manifest.read_text(encoding="utf-8"))["stats"]
    assert stats["targets"]["ceilings"] == {"cohort": {"Remaining accounts": 30}}
    assert stats["skipped_by_cap"].get("ceiling:cohort=Remaining accounts", 0) > 0
    composition = (sl.paths.reports / "composition.md").read_text(encoding="utf-8")
    assert "| Ceiling |" in composition and "final draw, ceiling" in composition


def test_records_carry_traffic_weights_that_reweight_to_traffic(built):
    sl, _, _ = built
    records = records_of(sl)
    stats = json.loads(sl.paths.manifest.read_text(encoding="utf-8"))["stats"]
    traffic = stats["traffic"]
    assert traffic["basis"] == "eligible_targets"
    by_value = traffic["by_value"]
    n = len(records)
    for r in records:
        row = by_value[r["cohort"]]
        slice_share = sum(x["cohort"] == r["cohort"] for x in records) / n
        assert r["traffic_weight"] == pytest.approx(
            row["traffic_share"] / slice_share, abs=1e-5
        )
        assert r["cohort_traffic_share"] == pytest.approx(row["traffic_share"])
    # Weighted cohort shares equal the traffic shares (covered cohorts).
    total = sum(r["traffic_weight"] for r in records)
    covered = 1 - traffic["uncovered_share"]
    for value, row in by_value.items():
        if not row["records"]:
            continue
        weighted = sum(r["traffic_weight"] for r in records if r["cohort"] == value)
        assert weighted / total == pytest.approx(
            row["traffic_share"] / covered, abs=1e-5
        )
    ids = list(csv.DictReader(io.StringIO((sl.paths.reports / "ids.csv").read_text())))
    assert all(float(r["traffic_weight"]) > 0 for r in ids)
    composition = (sl.paths.reports / "composition.md").read_text(encoding="utf-8")
    assert "## Traffic weights (by cohort)" in composition


# --- per-cohort targets and the cohort-stratified pool (owner, 2026-11-02) ----------


@pytest.fixture(scope="module")
def built_cohorts(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("slice_cohorts")
    repo, data, facts = make_repo(tmp, cohorts=True)
    sl = make_slice(repo, data)
    summary = sl.build()
    return sl, summary, facts


def test_the_pool_is_drawn_per_cohort_in_proportion_to_the_targets(built_cohorts):
    sl, _, _ = built_cohorts
    stats = json.loads(sl.paths.manifest.read_text(encoding="utf-8"))["stats"]
    plan = stats["pool_by_cohort"]
    assert set(plan) == {"Remaining accounts", *(f"User {c}" for c in "ABCDE")}
    assert sum(r["pool_planned"] for r in plan.values()) == 200
    for row in plan.values():
        # Capped by eligible sessions; the small cohorts are taken whole.
        assert row["pool_planned"] <= row["eligible_sessions"]
        assert row["pool_drawn"] >= row["pool_minimum"]
        assert row["pool_below_minimum"] is False
    small = [r for c, r in plan.items() if c != "Remaining accounts"]
    assert all(r["pool_planned"] == r["eligible_sessions"] for r in small)
    # The five-account cohort with two bots has no per-bot cap.
    assert plan["User E"]["eligible_bots"] <= 2
    assert plan["User E"]["per_bot_cap_waived"] is True
    composition = (sl.paths.reports / "composition.md").read_text(encoding="utf-8")
    assert "## Candidate pool by cohort" in composition


def test_cohort_targets_are_floors_with_a_hard_ceiling(built_cohorts):
    sl, summary, _ = built_cohorts
    records = records_of(sl)
    counts: dict[str, int] = {}
    for r in records:
        counts[r["cohort"]] = counts.get(r["cohort"], 0) + 1
    stats = json.loads(sl.paths.manifest.read_text(encoding="utf-8"))["stats"]
    ceilings = stats["targets"]["ceilings"]["cohort"]
    targets = stats["targets"]["shares"]["cohort"]
    assert ceilings["Remaining accounts"] == 30  # 0.3 × 100 beats 30 + 2
    assert ceilings["User A"] == 17
    for cohort, n in counts.items():
        assert n <= ceilings[cohort]
    shortfalls = {(d, v) for d, v, _, _ in stats["shortfalls"]}
    for cohort, target in targets.items():
        # Met, or reported as a shortfall (never silently missed).
        assert counts.get(cohort, 0) >= target or ("cohort", cohort) in shortfalls
    assert summary["records"] == len(records)


def test_the_cohort_build_is_deterministic(built_cohorts, tmp_path):
    sl, _, _ = built_cohorts
    repo, data, _ = make_repo(tmp_path, cohorts=True)
    again = make_slice(repo, data)
    again.build()
    a = (sl.paths.reports / "ids.csv").read_text(encoding="utf-8")
    b = (again.paths.reports / "ids.csv").read_text(encoding="utf-8")
    assert a == b
