"""Offline tests for sharing golden answers: manifest, dataset card, fingerprint,
import checks, the Parquet file. All text is [SYNTHETIC]."""

import json
from pathlib import Path

import pytest

from metis_auto.evaluation.golden_answers import share as sh

ROOT = Path(__file__).resolve().parents[3]


def row(i, answer=None, **kw):
    base = {
        "record_id": f"gv2-m_{i:03d}",
        "run_id": "run-1",
        "model_id": "gpt-5.5",
        "provider_model_version": "gpt-5.5-test",
        "effort": "medium",
        "max_output_tokens": 8192,
        "settings_hash": "h" * 64,
        "prompt_fingerprint": f"{i:064d}",
        "status": "answered",
        "answer": answer if answer is not None else f"[SYNTHETIC] answer {i}",
        "answer_chars": 20,
        "answer_language_group": "english",
        "finish_reason": "complete",
        "error_class": None,
        "attempts": 1,
        "input_tokens": 100,
        "cached_input_tokens": 0,
        "output_tokens": 50,
        "reasoning_tokens": 10,
        "cost_usd": "0.01000000",
        "cost_state": "reported",
        "latency_ms": 12.5,
        "caveats": ["config_unknown"],
    }
    return base | kw


def rows(n=4):
    return [row(i) for i in range(n)]


def fp(rs, dataset_fp="d" * 64):
    return sh.fingerprint_payload(
        rs, dataset_id="golden-v2", dataset_fingerprint=dataset_fp
    )


# --- digests and fingerprint ------------------------------------------------


def test_the_answers_digest_ignores_order_and_changes_with_any_answer():
    base = sh.answers_digest(rows())
    assert sh.answers_digest(list(reversed(rows()))) == base
    changed = rows()
    changed[2] = row(2, "[SYNTHETIC] a different answer")
    assert sh.answers_digest(changed) != base
    assert sh.answers_digest(rows()[:3]) != base


def test_the_fingerprint_holds_hashes_and_counts_only():
    payload = fp(rows())
    dumped = json.dumps(payload)
    assert "SYNTHETIC" not in dumped
    assert payload["answered_count"] == 4
    assert payload["tokens"]["output_tokens"] == 200
    assert len(payload["answers_sha256"]) == 64 and len(payload["fingerprint"]) == 64
    # no per-record answer hash is published: one aggregate only
    assert not any(r["record_id"] in dumped for r in rows())


def test_the_fingerprint_is_stable_and_detects_a_change():
    assert fp(rows()) == fp(list(reversed(rows())))
    other = rows()
    other[0] = row(0, "[SYNTHETIC] edited")
    diff = sh.fingerprint_diff(fp(rows()), fp(other))
    assert diff is not None and diff.startswith("answers_sha256")
    assert sh.fingerprint_diff(fp(rows()), fp(rows())) is None
    assert sh.fingerprint_diff(fp(rows()), fp(rows()[:3])).startswith("answered_count")
    assert sh.fingerprint_diff(fp(rows()), fp(rows(), "e" * 64)).startswith(
        "dataset_fingerprint"
    )


def test_rows_of_two_runs_or_settings_cannot_be_fingerprinted_together():
    mixed = rows() + [row(9, settings_hash="x" * 64)]
    with pytest.raises(sh.ShareRefused, match="settings_hash"):
        fp(mixed)
    with pytest.raises(sh.ShareRefused, match="no answered"):
        fp([])


# --- manifest and card ------------------------------------------------------


def manifest(rs=None):
    return sh.build_manifest(
        rs or rows(),
        dataset_id="golden-v2",
        dataset_fingerprint="d" * 64,
        parquet_sha256="a" * 64,
        parquet_bytes=1234,
        created="2026-11-02",
    )


def test_the_manifest_describes_the_run_without_any_answer():
    m = manifest()
    assert m["run_id"] == "run-1" and m["dataset_id"] == "golden-v2"
    assert m["settings_hash"] == "h" * 64 and m["record_count"] == 4
    assert m["model_id"] == "gpt-5.5" and m["provider_model_versions"] == [
        "gpt-5.5-test"
    ]
    assert m["answers_parquet"] == {
        "file": "answers.parquet",
        "sha256": "a" * 64,
        "bytes": 1234,
    }
    assert m["created"] == "2026-11-02" and "Rahnama" in m["licence"]
    assert "SYNTHETIC" not in json.dumps(m)


def test_the_dataset_card_names_the_private_repo_the_licence_and_the_steps():
    card = sh.readme_text(manifest())
    assert sh.HF_REPO == "Metis-auto/golden-answers-v2"
    assert "hf download Metis-auto/golden-answers-v2 --repo-type dataset" in card
    assert "--local-dir runs/golden_answers/run-1/export" in card
    assert "python scripts/golden_answers.py import" in card
    assert "verify-answers run-1" in card
    assert "Rahnama College" in card and "No redistribution" in card
    assert "raw-data dataset" in card and "metis-auto-team" not in card
    assert card.startswith("---\nlicense: other")


def test_an_export_is_exactly_three_files():
    assert sh.EXPORT_FILES == ("answers.parquet", "manifest.json", "README.md")


# --- import checks ----------------------------------------------------------


def problems(**kw):
    rs = kw.pop("rows", rows())
    given = kw.pop("manifest", None)
    args = {
        "manifest": given if given is not None else manifest(rs),
        "rows": rs,
        "actual_parquet_sha256": "a" * 64,
        "expected_dataset_id": "golden-v2",
        "local_dataset_fingerprint": "d" * 64,
        "local_record_ids": {r["record_id"] for r in rs},
        "existing_answers": {},
        "stray_files": [],
    } | kw
    return sh.import_problems(**args)


def test_a_good_export_has_no_problems():
    assert problems() == []


@pytest.mark.parametrize(
    ("change", "text"),
    [
        ({"actual_parquet_sha256": "b" * 64}, "sha256"),
        ({"expected_dataset_id": "golden-v1"}, "not 'golden-v1'"),
        ({"local_dataset_fingerprint": "e" * 64}, "fingerprint"),
        ({"stray_files": ["review.json"]}, "not part of an export"),
        ({"local_record_ids": {"gv2-m_000"}}, "not in your verified"),
    ],
)
def test_each_unsafe_import_is_refused_with_its_reason(change, text):
    found = problems(**change)
    assert found and any(text in p for p in found)


def test_row_level_problems_are_found():
    dup = rows() + [row(0)]
    assert any("more than once" in p for p in problems(rows=dup))
    bad = rows()
    bad[1] = row(1, status="failed", answer=None)
    assert any("not an answered" in p for p in problems(rows=bad))
    wrong = rows()
    wrong[2] = row(2, settings_hash="z" * 64)
    assert any("settings_hash" in p for p in problems(rows=wrong, manifest=manifest()))
    m = manifest() | {"record_count": 7}
    assert any("says 7 records" in p for p in problems(manifest=m))


def test_a_different_local_answer_blocks_the_import_but_an_equal_one_does_not():
    same = {r["record_id"]: r["answer"] for r in rows()}
    assert problems(existing_answers=same) == []
    differ = same | {"gv2-m_001": "[SYNTHETIC] another answer"}
    found = problems(existing_answers=differ)
    assert len(found) == 1 and "different answer" in found[0]


# --- parquet file -----------------------------------------------------------


def test_the_parquet_file_round_trips_and_is_sorted_and_deterministic(tmp_path):
    pytest.importorskip("pyarrow")
    from metis_auto.data_access.postgres import answer_files

    shuffled = [row(2), row(0), row(3, "پاسخ [SYNTHETIC]"), row(1)]
    a, b = tmp_path / "a.parquet", tmp_path / "b.parquet"
    answer_files.write_answers(shuffled, a)
    answer_files.write_answers(list(reversed(shuffled)), b)
    back = answer_files.read_answers(a)
    assert [r["record_id"] for r in back] == sorted(r["record_id"] for r in shuffled)
    assert next(r for r in back if r["record_id"] == "gv2-m_003")["answer"] == (
        "پاسخ [SYNTHETIC]"
    )
    assert (
        back[0]["caveats"] == ["config_unknown"] and back[0]["cost_usd"] == "0.01000000"
    )
    assert sh.sha256_file(a) == sh.sha256_file(b)


def test_a_file_with_other_columns_is_refused(tmp_path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    from metis_auto.data_access.postgres import answer_files

    path = tmp_path / "x.parquet"
    pq.write_table(pa.table({"record_id": ["r"], "prompt": ["[SYNTHETIC]"]}), path)
    with pytest.raises(ValueError, match="expected columns"):
        answer_files.read_answers(path)


def test_the_sharing_columns_carry_no_prompt_or_review_text():
    pytest.importorskip("pyarrow")
    from metis_auto.data_access.postgres import answer_files

    names = set(answer_files.COLUMNS)
    assert "answer" in names and "prompt_fingerprint" in names
    assert not names & {"prompt", "instructions", "target_user_message", "review"}


def test_the_cli_registers_the_sharing_commands():
    source = (ROOT / "scripts/golden_answers.py").read_text()
    for command in ("export", "import", "verify-answers", "fingerprint-answers"):
        assert f'"{command}"' in source
