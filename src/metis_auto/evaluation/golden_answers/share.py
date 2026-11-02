"""Sharing golden answers between teammates (pure, ADR-0030).

The answers are licensed to Rahnama College for educational use only and may not
be redistributed. They travel only as an export folder (a Parquet file, a manifest
and a dataset card) uploaded by the lead to the team's PRIVATE Hugging Face
dataset, never to the raw-data dataset, which has a wider audience. A teammate
imports the folder into the local database and checks it against a committed
fingerprint made of hashes and counts, never of text.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

HF_REPO = "Metis-auto/golden-answers-v2"
"""The team's private dataset for the answers (separate from the raw data)."""
EXPORT_SCHEMA = "golden-answers-export-1"
FINGERPRINT_SCHEMA = "golden-answers-fingerprint-1"
EXPORT_FILES = ("answers.parquet", "manifest.json", "README.md")
LICENCE = (
    "Licensed to Rahnama College for educational use only. No redistribution: do "
    "not copy, upload, quote or share any of it outside the project team."
)


class ShareRefused(RuntimeError):
    """An import or export that must not go ahead; the message lists why."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest(items: Iterable[Any]) -> str:
    text = json.dumps(list(items), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def answers_digest(rows: Iterable[Mapping[str, Any]]) -> str:
    """One hash over every (record ID, hash of the answer) pair, sorted. It says
    nothing about any single answer."""
    return _digest(
        sorted(
            [r["record_id"], hashlib.sha256(r["answer"].encode("utf-8")).hexdigest()]
            for r in rows
        )
    )


def prompt_digest(rows: Iterable[Mapping[str, Any]]) -> str:
    return _digest(sorted([r["record_id"], r["prompt_fingerprint"]] for r in rows))


def common_value(rows: Sequence[Mapping[str, Any]], key: str) -> Any:
    """The single value of ``key`` across ``rows``, or a refusal."""
    values = {r[key] for r in rows}
    if len(values) != 1:
        raise ShareRefused(
            f"the rows do not share one {key}: {sorted(map(str, values))}"
        )
    return values.pop()


def build_manifest(
    rows: Sequence[Mapping[str, Any]],
    *,
    dataset_id: str,
    dataset_fingerprint: str,
    parquet_sha256: str,
    parquet_bytes: int,
    created: str,
    run_settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Content-free description of an export."""
    if not rows:
        raise ShareRefused("the run has no answered records to export")
    manifest = {
        "schema": EXPORT_SCHEMA,
        "run_id": common_value(rows, "run_id"),
        "dataset_id": dataset_id,
        "dataset_fingerprint": dataset_fingerprint,
        "settings_hash": common_value(rows, "settings_hash"),
        "model_id": common_value(rows, "model_id"),
        "provider_model_versions": sorted(
            {r["provider_model_version"] or "" for r in rows}
        ),
        "reasoning_effort": common_value(rows, "effort"),
        "max_output_tokens": common_value(rows, "max_output_tokens"),
        "record_count": len(rows),
        "answers_parquet": {
            "file": "answers.parquet",
            "sha256": parquet_sha256,
            "bytes": parquet_bytes,
        },
        "created": created,
        "licence": LICENCE,
    }
    if run_settings is not None:
        manifest["run_settings"] = dict(run_settings)
    return manifest


def readme_text(manifest: Mapping[str, Any]) -> str:
    """The dataset card: what it is, the licence, how to import."""
    m = manifest
    run, dataset = m["run_id"], m["dataset_id"]
    folder = f"runs/golden_answers/{run}/export"
    lines = [
        "---",
        "license: other",
        "pretty_name: Metis golden answers v2 (team only)",
        "---",
        "",
        "# Metis golden answers v2 (team only, private)",
        "",
        f"Reference answers of `{m['model_id']}` for the {m['record_count']} records",
        f"of `{dataset}`, from run `{run}` (created {m['created']}). Each answer is a",
        "strong-model **reference**, not ground truth. The settings are in",
        f"`manifest.json` (effort `{m['reasoning_effort']}`, {m['max_output_tokens']}",
        f"output tokens, settings hash `{m['settings_hash'][:12]}...`).",
        "",
        "## Licence: read before use",
        "",
        LICENCE,
        "",
        "This dataset holds model answers to real conversations. Keep it in the",
        f"private `{HF_REPO}` repository. **Never upload it to the raw-data dataset**",
        "or anywhere else, and never paste any of it into a chat, issue or commit.",
        "",
        "## Files",
        "",
        "| File | Holds |",
        "|---|---|",
        "| `answers.parquet` | one row per record: the answer and its run data |",
        "| `manifest.json` | run, dataset, settings hash, model, count, sha256 |",
        "| `README.md` | this card |",
        "",
        "## Import",
        "",
        "In your clone of the project, with your own golden-v2 built and verified:",
        "",
        "```bash",
        f"hf download {HF_REPO} --repo-type dataset --local-dir {folder}",
        f"python scripts/golden_answers.py import {folder}",
        f"python scripts/golden_answers.py verify-answers {run}",
        "```",
        "",
        "`import` refuses if the sha256 does not match, if the dataset is not",
        f"`{dataset}`, or if a record ID is not in your verified copy.",
        "`verify-answers` must print",
        "`PASS`. Do not run the answers again against the provider: they are here.",
        "",
    ]
    return "\n".join(lines)


def fingerprint_payload(
    rows: Sequence[Mapping[str, Any]],
    *,
    dataset_id: str,
    dataset_fingerprint: str,
) -> dict[str, Any]:
    """Hashes and counts only. Over the answered rows of a run."""
    if not rows:
        raise ShareRefused("the run has no answered records")
    body = {
        "schema": FINGERPRINT_SCHEMA,
        "run_id": common_value(rows, "run_id"),
        "dataset_id": dataset_id,
        "dataset_fingerprint": dataset_fingerprint,
        "settings_hash": common_value(rows, "settings_hash"),
        "model_id": common_value(rows, "model_id"),
        "provider_model_versions": sorted(
            {r["provider_model_version"] or "" for r in rows}
        ),
        "answered_count": len(rows),
        "finish_reasons": dict(
            sorted(Counter(r["finish_reason"] for r in rows).items())
        ),
        "tokens": {
            key: sum(r[key] or 0 for r in rows)
            for key in (
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_tokens",
            )
        },
        "answers_sha256": answers_digest(rows),
        "prompt_fingerprints_sha256": prompt_digest(rows),
    }
    body["fingerprint"] = _digest(sorted(body.items()))
    return body


def fingerprint_diff(
    expected: Mapping[str, Any], actual: Mapping[str, Any]
) -> str | None:
    """The first difference in plain words, or ``None`` for a match."""
    for key in (
        "dataset_id",
        "dataset_fingerprint",
        "settings_hash",
        "model_id",
        "provider_model_versions",
        "answered_count",
        "finish_reasons",
        "tokens",
        "prompt_fingerprints_sha256",
        "answers_sha256",
        "fingerprint",
    ):
        if expected.get(key) != actual.get(key):
            want, got = _short(expected.get(key)), _short(actual.get(key))
            return f"{key}: expected {want}, got {got}"
    return None


def _short(value: Any) -> str:
    text = json.dumps(value, sort_keys=True)
    return text if len(text) <= 80 else text[:20] + "…" + text[-12:]


def import_problems(
    manifest: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    actual_parquet_sha256: str,
    expected_dataset_id: str,
    local_dataset_fingerprint: str,
    local_record_ids: set[str],
    existing_answers: Mapping[str, str],
    stray_files: Sequence[str],
) -> list[str]:
    """Every reason an import must be refused (empty = go ahead). Compares only
    hashes, IDs and counts; ``existing_answers`` is record ID → answer already
    stored locally for the same run."""
    problems = []
    if manifest.get("schema") != EXPORT_SCHEMA:
        problems.append(f"unknown manifest schema {manifest.get('schema')!r}")
    if stray_files:
        problems.append(
            "the folder holds files that are not part of an export: "
            f"{sorted(stray_files)}"
        )
    want = manifest.get("answers_parquet", {}).get("sha256")
    if want != actual_parquet_sha256:
        problems.append("the sha256 of answers.parquet does not match the manifest")
    if manifest.get("dataset_id") != expected_dataset_id:
        problems.append(
            f"the export is for dataset {manifest.get('dataset_id')!r}, "
            f"not {expected_dataset_id!r}"
        )
    if manifest.get("dataset_fingerprint") != local_dataset_fingerprint:
        problems.append(
            "the dataset fingerprint of the export differs from the one committed "
            "in this checkout (update the repository or ask the lead)"
        )
    if manifest.get("record_count") != len(rows):
        problems.append(
            f"the manifest says {manifest.get('record_count')} records, "
            f"the file holds {len(rows)}"
        )
    ids = [r["record_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("the file holds a record ID more than once")
    unknown = sorted(set(ids) - local_record_ids)
    if unknown:
        problems.append(
            f"{len(unknown)} record IDs are not in your verified "
            f"{expected_dataset_id}, for example {unknown[:3]}"
        )
    for key in ("run_id", "settings_hash", "model_id"):
        if {r[key] for r in rows} != {manifest.get(key)}:
            problems.append(f"the rows disagree with the manifest on {key}")
    if any(r["status"] != "answered" or not r["answer"] for r in rows):
        problems.append("the file holds a row that is not an answered record")
    clash = [
        i
        for i, r in ((r["record_id"], r) for r in rows)
        if i in existing_answers and existing_answers[i] != r["answer"]
    ]
    if clash:
        problems.append(
            f"{len(clash)} records already have a different answer in the same run "
            f"locally, for example {clash[:3]}"
        )
    return problems
