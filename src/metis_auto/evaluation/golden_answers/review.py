"""Review of language mismatches between a request and its golden answer (pure,
ADR-0030). A mismatch is exactly what ``summary.language_mismatch`` says it is:
this module calls that function and has no rule of its own, so the count here is
the count in the run summary.

Two outputs. The local entries hold message text and must stay on this machine;
the committable sheet holds IDs, labels and a flag only.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from metis_auto.evaluation.golden_answers.summary import language_mismatch

VERDICTS = (
    "ok_bot_rule",
    "ok_not_really_english",
    "model_error",
    "detector_error",
    "unsure",
)
"""Allowed values of the sheet's ``verdict`` column (empty = not reviewed):
ok_bot_rule: the bot's instructions require that answer language.
ok_not_really_english: the request only looked English (a name, a term, a code).
model_error: the model answered in the wrong language.
detector_error: the script detector mislabelled the request or the answer.
unsure: the reviewer cannot tell."""

SHEET_COLUMNS = (
    "record_id",
    "bot_id",
    "request_lang",
    "answer_lang",
    "instructions_mention_language",
    "verdict",
    "notes",
)
INSTRUCTION_EXCERPT_CHARS = 800
LANGUAGE_WORDS = (
    "فارسی",
    "پارسی",
    "انگلیسی",
    "زبان",
    "persian",
    "farsi",
    "english",
    "language",
)
"""Words whose presence in a bot's instructions raises the flag. A flag only: it
says the instructions talk about a language, not what rule they give."""


def select_mismatches(
    rows: Iterable[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """The answered rows that ``language_mismatch`` marks as a mismatch, in record
    order. ``rows`` are the content-free summary rows (``strata`` and
    ``answer_language_group`` included)."""
    chosen = [
        r
        for r in rows
        if r["status"] == "answered"
        and language_mismatch(r["strata"]["language_group"], r["answer_language_group"])
        is True
    ]
    return sorted(chosen, key=lambda r: r["record_id"])


def mentions_language(instructions: str | None) -> bool:
    folded = (instructions or "").casefold()
    return any(word.casefold() in folded for word in LANGUAGE_WORDS)


def local_entry(row: Mapping[str, Any], inputs: Mapping[str, Any]) -> dict[str, Any]:
    """One record of the local, text-bearing file. ``inputs`` holds request_id,
    bot_id, cohort, instructions, target and answer."""
    instructions = inputs.get("instructions") or ""
    return {
        "record_id": row["record_id"],
        "request_id": inputs["request_id"],
        "bot_id": inputs["bot_id"],
        "cohort": inputs["cohort"],
        "request_language_group": row["strata"]["language_group"],
        "answer_language_group": row["answer_language_group"],
        "caveats": list(row["caveats"]),
        "instructions_mention_language": mentions_language(instructions),
        "instructions_total_chars": len(instructions),
        "instructions_first_800_chars": instructions[:INSTRUCTION_EXCERPT_CHARS],
        "target_user_message": inputs["target"],
        "answer": inputs["answer"],
    }


def sheet_rows(
    entries: Sequence[Mapping[str, Any]],
    previous: Mapping[str, Mapping[str, str]] | None = None,
) -> list[dict[str, str]]:
    """The committable rows. A reviewer's earlier verdict and notes for the same
    record are kept, so building the sheet again never erases a review."""
    previous = previous or {}
    out = []
    for e in sorted(entries, key=lambda e: e["record_id"]):
        old = previous.get(e["record_id"], {})
        out.append(
            {
                "record_id": e["record_id"],
                "bot_id": e["bot_id"],
                "request_lang": e["request_language_group"],
                "answer_lang": e["answer_language_group"],
                "instructions_mention_language": str(
                    e["instructions_mention_language"]
                ).lower(),
                "verdict": old.get("verdict", ""),
                "notes": old.get("notes", ""),
            }
        )
    return out


def render_sheet(rows: Sequence[Mapping[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=SHEET_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def read_sheet(text: str) -> dict[str, dict[str, str]]:
    return {
        r["record_id"]: {"verdict": r.get("verdict", ""), "notes": r.get("notes", "")}
        for r in csv.DictReader(io.StringIO(text))
    }


def sheet_problems(rows: Iterable[Mapping[str, str]]) -> list[str]:
    """Verdicts outside the allowed values. Notes cannot be checked for message
    text here: the reviewer must never put any in them."""
    return [
        f"{r['record_id']}: verdict {r['verdict']!r} is not one of {VERDICTS}"
        for r in rows
        if r["verdict"] and r["verdict"] not in VERDICTS
    ]


def breakdown(rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    """Content-free counts: by direction, by bot (top 10), and how many bots'
    instructions mention a language."""
    directions = Counter(f"{r['request_lang']}→{r['answer_lang']}" for r in rows)
    bots = Counter(r["bot_id"] for r in rows)
    return {
        "mismatches": len(rows),
        "by_direction": dict(
            sorted(directions.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        "by_request_language": dict(
            sorted(Counter(r["request_lang"] for r in rows).items())
        ),
        "top_bots": [
            {"bot_id": b, "mismatches": n}
            for b, n in sorted(bots.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
        ],
        "bots_with_mismatches": len(bots),
        "instructions_mention_language": sum(
            r["instructions_mention_language"] == "true" for r in rows
        ),
    }
