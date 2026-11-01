"""Dataset validation checks V-01…V-12 (pure over evidence) and the fingerprint.

``pending`` means a human step has not happened; it is never reported as passing.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from metis_auto.evaluation.golden.annotations import HUMAN_REQUIRED, RUBRIC
from metis_auto.evaluation.golden.records import leakage_errors

_PERSIAN_RUN = re.compile(r"[؀-ۿ‌ ]{60,}")


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    title: str
    status: str
    """``pass``, ``fail``, ``pending`` or ``info``."""
    count: int
    detail: str = ""


def fingerprint(record_ids: Iterable[str], version: str, config_sha256: str) -> str:
    payload = json.dumps(
        {
            "record_ids": sorted(record_ids),
            "version": version,
            "config_sha256": config_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def fingerprint_diff(
    expected: Mapping[str, Any], actual: Mapping[str, Any]
) -> str | None:
    """The first difference in plain words, or ``None`` for a match."""
    for key, name in (
        ("dataset_revision", "dataset revision"),
        ("config_sha256", "config"),
        ("record_count", "record count"),
    ):
        if expected.get(key) != actual.get(key):
            return f"{name}: expected {expected.get(key)}, got {actual.get(key)}"
    want, got = expected.get("record_ids", []), actual.get("record_ids", [])
    for a, b in zip(want, got, strict=False):
        if a != b:
            return f"record ids: first difference expected {a}, got {b}"
    if expected.get("fingerprint") != actual.get("fingerprint"):
        return "fingerprint differs"
    return None


def _result(check_id, title, bad, detail="") -> CheckResult:
    return CheckResult(check_id, title, "fail" if bad else "pass", bad, detail)


def run_checks(e: Mapping[str, Any], total: int) -> list[CheckResult]:
    """``e`` holds records, targets, answers, components, sessions, margins, labels."""
    records: Sequence[Mapping] = e["records"]
    ids = [r["record_id"] for r in records]
    requests = [r["request_id"] for r in records]
    sessions = [r["session_id"] for r in records]
    reserves = set(e["reserve_request_ids"])
    out = [
        _result(
            "V-01",
            f"exactly {total} primary records, none duplicated, reserves excluded",
            abs(len(records) - total)
            + (len(requests) - len(set(requests)))
            + len(reserves & set(requests)),
            f"records={len(records)}, reserves={len(reserves)}",
        ),
        _result(
            "V-02",
            "record ids and sessions are unique",
            (len(ids) - len(set(ids))) + (len(sessions) - len(set(sessions))),
        ),
        _result(
            "V-03",
            "every target is a USER message with non-empty content",
            sum(
                not (r["target_type"] == "USER" and r["target_nonblank"])
                for r in records
            ),
        ),
        _result(
            "V-04",
            "every reference is the paired AI message and pair_flag is clean",
            sum(
                not (
                    r["pair_flag"] == "clean"
                    and r["answer_type"] == "AI"
                    and r["answer_nonblank"]
                    and r["answer_id_matches"]
                )
                for r in records
            ),
        ),
    ]
    leak = 0
    ties = 0
    null_ts = 0
    for r in records:
        session = e["sessions"][r["session_id"]]
        leak += bool(
            leakage_errors(
                e["components"][r["record_id"]],
                target_id=r["request_id"],
                answer_id=r["answer_message_id"],
                session=session,
            )
        )
        stamps = [m["timestamp"] for m in session if m["timestamp"] is not None]
        ties += len(stamps) != len(set(stamps))
        null_ts += len(stamps) != len(session)
    out.append(
        _result(
            "V-05",
            "all history precedes the target by (timestamp, source_ordinal)",
            leak,
            f"sessions with tied timestamps={ties}, with null timestamps={null_ts}",
        )
    )
    out.append(
        _result(
            "V-06",
            "no routing-input view holds the answer, a later turn or post-generation",
            e["view_leaks"],
            f"checked {e['view_rows']} view rows across both profiles",
        )
    )
    out.append(
        _result(
            "V-07",
            "instructions and RAG belong to the session's bot; owner is its user",
            e["ownership_errors"],
        )
    )
    unmet = [m for m in e["margins"] if m["mandatory_unmet"]]
    short = [m for m in e["margins"] if m["shortfall"] > 0]
    undocumented = [m for m in short if not m.get("note")]
    out.append(
        CheckResult(
            "V-08",
            "quotas met or shortfalls documented with cause",
            "fail" if undocumented or unmet else "pass",
            len(short),
            f"margins short={len(short)}, undocumented={len(undocumented)}, "
            f"mandatory minimums unmet={[m['key'] for m in unmet]}",
        )
    )
    out.append(
        _result(
            "V-09",
            "no exact or near-duplicate families inside the set",
            e["duplicate_pairs"],
            f"overlap with the EDA proposal: {e['eda_overlap']} records",
        )
    )
    bad_values = sum(
        lab["value"] not in RUBRIC.get(lab["dimension"], ()) for lab in e["labels"]
    )
    reviewed = {
        (lab["record_id"], lab["dimension"])
        for lab in e["labels"]
        if lab["method"] == "human" and lab["review_status"] == "accepted"
    }
    missing = sum((rid, dim) not in reviewed for rid in ids for dim in HUMAN_REQUIRED)
    out.append(
        CheckResult(
            "V-10",
            "label values exist in the rubric; required dimensions are reviewed",
            "fail" if bad_values else ("pending" if missing else "pass"),
            bad_values,
            f"human labels still needed: {missing} of {len(ids) * len(HUMAN_REQUIRED)}",
        )
    )
    out.append(
        _result(
            "V-11",
            "no content in committed outputs",
            len(e["content_hits"]),
            f"scanned {e['files_scanned']} files",
        )
    )
    if e.get("rebuild_ids") is None:
        out.append(
            CheckResult(
                "V-12",
                "same seed and inputs rebuild the same",
                "pending",
                0,
                "rebuild not requested",
            )
        )
    else:
        out.append(
            _result(
                "V-12",
                "same seed and inputs rebuild the same record ids and strata",
                int(e["rebuild_ids"] != sorted(requests)),
            )
        )
    return out


def scan_for_content(
    files: Mapping[str, str], secrets: Iterable[str]
) -> list[tuple[str, str]]:
    """(file, reason) hits: an exact record text, or a long run of Arabic script.

    Reasons never quote the text.
    """
    texts = [t for t in secrets if len(t) >= 12]
    hits = []
    for name, body in files.items():
        if _PERSIAN_RUN.search(body):
            hits.append((name, "long Arabic-script run"))
        for text in texts:
            if text in body:
                hits.append((name, "exact dataset text"))
                break
    return hits


def markdown(results: Sequence[CheckResult]) -> str:
    lines = [
        "| Check | Result | Count | What it checks | Detail |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.check_id} | **{r.status}** | {r.count} | {r.title} | {r.detail} |"
        )
    return "\n".join(lines) + "\n"
