"""Nothing under ``reports/`` holds text, IDs or hashes of dataset content
(sprint plan I-2; dataset licence; QA-PRIV; CLAUDE.md "Data and privacy").

Static: reads the files on disk, committed or not. Rules:

- **Whole tree:** no Arabic-script text (Persian message content would be the only
  source) and no UUID, in any text file.
- **Sprint outputs** (``reports/levers`` and ``reports/pipelines``): no JSON key
  that names an identifier column; no hex string of 24 or more characters except
  the manifest's own reproducibility fields (``data_revision``, ``code_commit``,
  ``config_hash``), which are public pins and hashes of configuration, not of
  content; in Markdown and CSV only a pinned ``data_revision`` that appears in a
  result's manifest.

The checker is tested on planted fixtures first (a planted violation must be
caught), then run on the real tree.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
SPRINT_DIRS = ("levers", "pipelines")
TEXT_SUFFIXES = {".md", ".csv", ".json", ".jsonl", ".txt"}

ARABIC_SCRIPT = re.compile("[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
# a hash has at least one letter a-f; a long run of digits is a decimal number
LONG_HEX = re.compile(r"(?<![0-9A-Za-z.])(?=[0-9]*[a-f])[0-9a-f]{24,}(?![0-9A-Za-z])")
MANIFEST_HEX_KEYS = {"data_revision", "code_commit", "config_hash"}
ID_KEYS = {
    "session_id",
    "user_id",
    "bot_id",
    "bot_user_id",
    "message_id",
    "ai_message_id",
    "user_message_id",
    "chunk_id",
    "u_h_norm",
    "h_exact",
    "h_norm",
    "hist_hash",
    "text",
    "content",
    "message",
    "instructions",
}


def _walk(obj: object, key: str | None = None) -> Iterator[tuple[str | None, object]]:
    """Every (key, value) leaf of a JSON document, and every key as (key, None)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k), None
            yield from _walk(v, str(k))
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, key)
    else:
        yield key, obj


def violations(
    name: str, text: str, *, strict: bool, pinned: frozenset[str] = frozenset()
) -> list[str]:
    """Problems in one file. ``strict``: the sprint-output rules as well."""
    found = []
    if ARABIC_SCRIPT.search(text):
        found.append(f"{name}: Arabic-script text")
    if UUID.search(text):
        found.append(f"{name}: UUID")
    if not strict:
        return found
    if name.endswith((".json", ".jsonl")):
        docs = []
        try:
            docs = (
                [json.loads(line) for line in text.splitlines() if line.strip()]
                if name.endswith(".jsonl")
                else [json.loads(text)]
            )
        except ValueError:
            found.append(f"{name}: not valid JSON")
        for doc in docs:
            for key, value in _walk(doc):
                if value is None and key in ID_KEYS:
                    found.append(f"{name}: identifier key {key!r}")
                elif isinstance(value, str) and LONG_HEX.search(value):
                    if key not in MANIFEST_HEX_KEYS:
                        found.append(f"{name}: hex string under {key!r}")
    else:
        for m in LONG_HEX.finditer(text):
            if m.group(0) not in pinned:
                found.append(f"{name}: hex string outside the manifest fields")
                break
        if name.endswith(".csv"):
            header = {h.strip().strip('"') for h in text.splitlines()[0].split(",")}
            bad = sorted(header & ID_KEYS)
            if bad:
                found.append(f"{name}: identifier column {bad}")
    return found


def pinned_revisions(folder: Path) -> frozenset[str]:
    """The ``data_revision`` pins that appear in result manifests."""
    pins = set()
    for p in folder.glob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        rev = (
            (doc.get("manifest") or {}).get("data_revision")
            if isinstance(doc, dict)
            else None
        )
        if isinstance(rev, str):
            pins.add(rev)
    return frozenset(pins)


# --- the checker catches a planted violation ---------------------------------------


def test_planted_arabic_text_is_caught():
    assert violations("x.md", "salam سلام", strict=False)
    assert violations("x.csv", "a\nپیام", strict=False)


def test_planted_uuid_is_caught():
    text = "id 123e4567-e89b-12d3-a456-426614174000 here"
    assert violations("x.json", json.dumps({"a": text}), strict=False)


def test_planted_hash_outside_the_manifest_fields_is_caught():
    h = "a" * 32
    assert violations("x.json", json.dumps({"slice": {"label": h}}), strict=True)
    assert violations("x.md", f"row {h}", strict=True)
    assert violations("x.md", f"row {h}", strict=True, pinned=frozenset({"b" * 32}))


def test_planted_identifier_key_is_caught():
    assert violations("x.json", json.dumps({"rows": [{"session_id": 1}]}), strict=True)
    assert violations("x.csv", "bot_id,saving\n1,2\n", strict=True)
    assert violations("x.json", json.dumps({"text": "hello"}), strict=True)


def test_manifest_hashes_and_pinned_revisions_are_allowed():
    h = "0123456789abcdef" * 4
    doc = {
        "manifest": {"data_revision": h[:40], "code_commit": h[:40], "config_hash": h}
    }
    assert violations("x.json", json.dumps(doc), strict=True) == []
    assert (
        violations("x.md", f"data {h[:40]}", strict=True, pinned=frozenset({h[:40]}))
        == []
    )


def test_a_long_decimal_is_not_a_hash():
    assert (
        violations("x.md", "share 0.002575515795679189612119270567", strict=True) == []
    )
    assert (
        violations(
            "x.json", json.dumps({"a": "0.12345678901234567890123456789"}), strict=True
        )
        == []
    )


def test_aggregates_pass():
    doc = {
        "saving": {"total": "1.5"},
        "slices": {"bot_rank:1": {"n": 3}, "lang:fa": {}},
    }
    assert violations("x.json", json.dumps(doc), strict=True) == []
    assert violations("x.csv", "bot_rank,saving\n1,2\n", strict=True) == []


# --- the real tree -----------------------------------------------------------------


def _files(folder: Path) -> Iterator[Path]:
    for p in sorted(folder.rglob("*")):
        if p.is_file() and p.suffix in TEXT_SUFFIXES:
            yield p


def test_no_arabic_script_or_uuid_anywhere_under_reports():
    found = []
    for p in _files(REPORTS):
        found += violations(
            p.relative_to(ROOT).as_posix(),
            p.read_text(encoding="utf-8", errors="replace"),
            strict=False,
        )
    assert found == []


def test_sprint_outputs_hold_no_identifier_or_content_hash():
    found = []
    for sub in SPRINT_DIRS:
        folder = REPORTS / sub
        if not folder.is_dir():
            continue
        pins = pinned_revisions(REPORTS / "levers")
        for p in _files(folder):
            found += violations(
                p.relative_to(ROOT).as_posix(),
                p.read_text(encoding="utf-8", errors="replace"),
                strict=True,
                pinned=pins,
            )
    assert found == []
