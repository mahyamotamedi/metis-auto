"""Offline tests for the language-mismatch review (ADR-0030).

All text is [SYNTHETIC] (including the Persian-looking placeholders). No database,
no model, no dataset content.
"""

import csv
import io
import json
import random
import subprocess
from pathlib import Path

import pytest

from metis_auto.evaluation.golden_answers import review as rv
from metis_auto.evaluation.golden_answers.summary import (
    language_mismatch,
    summarise,
)
from metis_auto.wiring.golden_answers import GoldenAnswers, assert_git_ignored

ROOT = Path(__file__).resolve().parents[3]
GROUPS = ["persian", "english", "mixed", "structured", "other", "finglish", None]


def row(i, request="persian", answer="persian", status="answered", caveats=()):
    return {
        "record_id": f"gv2-m_{i:03d}",
        "status": status,
        "error_class": None if status == "answered" else "context_overflow",
        "finish_reason": "complete",
        "answer_language_group": answer if status == "answered" else None,
        "latency_ms": 10.0,
        "input_tokens": 1,
        "cached_input_tokens": 0,
        "output_tokens": 1,
        "reasoning_tokens": 0,
        "cost_usd": None,
        "cost_state": "reported",
        "caveats": tuple(caveats),
        "strata": {"language_group": request},
    }


def inputs(i, instructions="[SYNTHETIC] be brief", bot="bot-1"):
    return {
        "request_id": f"m_{i:03d}",
        "bot_id": bot,
        "cohort": "User A",
        "instructions": instructions,
        "target": f"[SYNTHETIC] question {i}",
        "answer": f"[SYNTHETIC] answer {i}",
    }


# --- selection is the summary's rule ----------------------------------------


def test_the_selection_count_equals_the_summarys_mismatch_count_on_any_mix():
    rng = random.Random(7)
    for _ in range(25):
        rows = [
            row(
                i,
                request=rng.choice(GROUPS[:-1]),
                answer=rng.choice(GROUPS),
                status=rng.choice(["answered", "answered", "answered", "failed"]),
            )
            for i in range(60)
        ]
        wanted = summarise(rows, run_id="r", manifest={}, planned=60)[
            "language_mismatch"
        ]["mismatches"]
        assert len(rv.select_mismatches(rows)) == wanted


def test_every_selected_row_is_a_mismatch_by_the_summarys_function():
    rows = [
        row(0, "persian", "english"),
        row(1, "persian", "persian"),
        row(2, "english", "persian"),
        row(3, "persian", "mixed"),  # compatible, not a mismatch
        row(4, "mixed", "english"),  # request group not evaluated
        row(5, "persian", "english", status="failed"),
    ]
    chosen = rv.select_mismatches(rows)
    assert [r["record_id"] for r in chosen] == ["gv2-m_000", "gv2-m_002"]
    for r in chosen:
        assert language_mismatch(
            r["strata"]["language_group"], r["answer_language_group"]
        )


def test_the_selection_has_no_language_rule_of_its_own():
    import inspect

    body = inspect.getsource(rv.select_mismatches)
    assert "language_mismatch(" in body
    for private in ("COMPATIBLE_LANGUAGE", '"persian"', '"english"', "allowed"):
        assert private not in body
    assert rv.language_mismatch is language_mismatch  # the summary's own function


# --- language rule flag -----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "[SYNTHETIC] Always answer in English.",
        "[SYNTHETIC] Reply in PERSIAN.",
        "[SYNTHETIC] جواب را به فارسی بده",
        "[SYNTHETIC] زبان پاسخ همیشه انگلیسی باشد",
        "[SYNTHETIC] Use the user's language.",
    ],
)
def test_instructions_that_talk_about_a_language_raise_the_flag(text):
    assert rv.mentions_language(text) is True


@pytest.mark.parametrize("text", ["", None, "[SYNTHETIC] Be brief and polite."])
def test_other_instructions_do_not(text):
    assert rv.mentions_language(text) is False


# --- local entry ------------------------------------------------------------


def test_the_local_entry_has_the_requested_fields_and_a_800_char_excerpt():
    long = "[SYNTHETIC] " + "x" * 1000 + " English"
    entry = rv.local_entry(
        row(1, "persian", "english", caveats=("config_unknown",)),
        inputs(1, instructions=long),
    )
    assert set(entry) == {
        "record_id",
        "request_id",
        "bot_id",
        "cohort",
        "request_language_group",
        "answer_language_group",
        "caveats",
        "instructions_mention_language",
        "instructions_total_chars",
        "instructions_first_800_chars",
        "target_user_message",
        "answer",
    }
    assert len(entry["instructions_first_800_chars"]) == 800
    assert entry["instructions_total_chars"] == len(long)
    # computed over the whole text, not the excerpt (the word is past char 800)
    assert entry["instructions_mention_language"] is True
    assert entry["caveats"] == ["config_unknown"]
    assert entry["answer"] == "[SYNTHETIC] answer 1"


def test_the_local_json_keeps_persian_readable(tmp_path):
    entry = {"answer": "پاسخ [SYNTHETIC]"}
    path = tmp_path / "x.json"
    path.write_text(json.dumps([entry], ensure_ascii=False, indent=2), encoding="utf-8")
    assert "پاسخ" in path.read_text(encoding="utf-8")
    assert "\\u" not in path.read_text(encoding="utf-8")


# --- committable sheet ------------------------------------------------------


def entries():
    return [
        rv.local_entry(row(2, "english", "persian"), inputs(2, bot="bot-2")),
        rv.local_entry(
            row(1, "persian", "english"),
            inputs(1, instructions="[SYNTHETIC] Answer in English", bot="bot-1"),
        ),
        rv.local_entry(row(3, "persian", "english"), inputs(3, bot="bot-1")),
    ]


def test_the_sheet_has_exactly_the_id_and_label_columns_and_no_text():
    rows = rv.sheet_rows(entries())
    assert rv.SHEET_COLUMNS == (
        "record_id",
        "bot_id",
        "request_lang",
        "answer_lang",
        "instructions_mention_language",
        "verdict",
        "notes",
    )
    assert all(tuple(r) == rv.SHEET_COLUMNS for r in rows)
    dumped = rv.render_sheet(rows)
    assert "SYNTHETIC" not in dumped  # none of the instructions, targets or answers
    assert [r["record_id"] for r in rows] == ["gv2-m_001", "gv2-m_002", "gv2-m_003"]
    assert {r["verdict"] for r in rows} == {""} and {r["notes"] for r in rows} == {""}
    parsed = list(csv.DictReader(io.StringIO(dumped)))
    assert parsed[0]["instructions_mention_language"] == "true"
    assert parsed[1]["instructions_mention_language"] == "false"


def test_a_rebuilt_sheet_keeps_the_reviewers_verdicts():
    first = rv.sheet_rows(entries())
    first[0]["verdict"], first[0]["notes"] = "ok_bot_rule", "bot asks for English"
    previous = rv.read_sheet(rv.render_sheet(first))
    again = rv.sheet_rows(entries(), previous)
    assert again[0]["verdict"] == "ok_bot_rule"
    assert again[0]["notes"] == "bot asks for English"
    assert again[1]["verdict"] == ""


def test_verdicts_outside_the_allowed_values_are_reported():
    rows = rv.sheet_rows(entries())
    rows[0]["verdict"] = "fine"
    rows[1]["verdict"] = "model_error"
    problems = rv.sheet_problems(rows)
    assert len(problems) == 1 and "fine" in problems[0]
    assert rv.VERDICTS == (
        "ok_bot_rule",
        "ok_not_really_english",
        "model_error",
        "detector_error",
        "unsure",
    )


# --- breakdown --------------------------------------------------------------


def test_the_breakdown_counts_directions_bots_and_language_flags_only():
    out = rv.breakdown(rv.sheet_rows(entries()))
    assert out["mismatches"] == 3
    assert out["by_direction"] == {"persian→english": 2, "english→persian": 1}
    assert out["by_request_language"] == {"english": 1, "persian": 2}
    assert out["top_bots"][0] == {"bot_id": "bot-1", "mismatches": 2}
    assert (
        out["bots_with_mismatches"] == 2 and out["instructions_mention_language"] == 1
    )
    assert "SYNTHETIC" not in json.dumps(out, ensure_ascii=False)


def test_the_top_bots_list_stops_at_ten():
    many = [
        rv.local_entry(row(i, "persian", "english"), inputs(i, bot=f"bot-{i:02d}"))
        for i in range(15)
    ]
    assert len(rv.breakdown(rv.sheet_rows(many))["top_bots"]) == 10


# --- where the files go -----------------------------------------------------


def test_the_local_file_path_is_under_runs_and_git_ignores_it():
    answers = GoldenAnswers(engine=object(), log=lambda _m: None)
    local, sheet = answers.review_paths("ga-v2-20261101")
    assert local.relative_to(ROOT).as_posix() == (
        "runs/golden_answers/ga-v2-20261101/review/language_mismatch_local.json"
    )
    assert sheet.relative_to(ROOT).as_posix() == (
        "reports/evaluation/golden_v2/review/language_mismatch_ga-v2-20261101.csv"
    )
    assert_git_ignored(ROOT, local)  # passes: runs/ is ignored
    with pytest.raises(RuntimeError, match="not git-ignored"):
        assert_git_ignored(ROOT, sheet)  # the sheet is meant to be committed


def test_a_path_git_would_track_is_refused(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("private/\n")
    assert_git_ignored(tmp_path, tmp_path / "private" / "x.json")
    with pytest.raises(RuntimeError, match="not git-ignored"):
        assert_git_ignored(tmp_path, tmp_path / "public" / "x.json")


def test_the_cli_command_is_registered():
    source = (ROOT / "scripts/golden_answers.py").read_text()
    assert '"review-language"' in source and "g.review_language(" in source
