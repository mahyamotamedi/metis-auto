"""Regenerate the index of progress entries in docs/project/progress.md.

    python scripts/progress_index.py            # rewrite the index
    python scripts/progress_index.py --check    # exit 1 if stale or malformed

Each piece of work is one file docs/project/progress/YYYY-MM-DD-<slug>.md that starts
with a "## Title (YYYY-MM-DD)" heading. Add a new file; never edit someone else's
entry. The index sits between the two marker comments in progress.md, newest first
(entries of one day sort by file name); everything outside the markers, including
"Current status", is written by hand and never touched here.

Standard library only; it reads and writes Markdown and calls nothing else.
Run it before committing a new entry, and again before merging.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROGRESS = ROOT / "docs" / "project" / "progress.md"
FOLDER = ROOT / "docs" / "project" / "progress"
START = "<!-- progress-index:start -->"
END = "<!-- progress-index:end -->"
NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-([a-z0-9]+(?:-[a-z0-9]+)*)\.md$")
TRAILING_DATE = re.compile(r"\s*\((\d{4}-\d{2}-\d{2})\)\s*$")


def entries(folder: Path) -> tuple[list[tuple[str, str, str, str]], list[str]]:
    """((date, slug, title, file name) newest first, problems). Files that do not
    look like entries (a README, for example) are ignored; malformed entries are
    problems."""
    found, problems = [], []
    for path in sorted(folder.glob("*.md")):
        match = NAME.match(path.name)
        if not match:
            continue
        day, slug = match.groups()
        try:
            date.fromisoformat(day)
        except ValueError:
            problems.append(f"{path.name}: {day} is not a date")
            continue
        first = path.read_text(encoding="utf-8").split("\n", 1)[0]
        if not first.startswith("## "):
            problems.append(f'{path.name}: the first line must be a "## Title" heading')
            continue
        title = TRAILING_DATE.sub("", first[3:].strip())
        found.append((day, slug, title, path.name))
    found.sort(key=lambda e: (e[0], e[1]), reverse=True)
    return found, problems


def render(items: list[tuple[str, str, str, str]]) -> str:
    return "\n".join(
        f"- {day}: [{title}](progress/{name})" for day, _slug, title, name in items
    )


def replace_index(text: str, index: str) -> str:
    """``text`` with the lines between the markers replaced by ``index``."""
    if (
        text.count(START) != 1
        or text.count(END) != 1
        or text.index(START) > text.index(END)
    ):
        raise ValueError(
            f"progress.md needs exactly one {START} and one {END}, in order"
        )
    head, rest = text.split(START, 1)
    _old, tail = rest.split(END, 1)
    return f"{head}{START}\n{index}\n{END}{tail}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--check", action="store_true", help="do not write; exit 1 if stale"
    )
    args = ap.parse_args(argv)
    items, problems = entries(FOLDER)
    for problem in problems:
        print(f"PROBLEM: {problem}")
    text = PROGRESS.read_text(encoding="utf-8")
    try:
        updated = replace_index(text, render(items))
    except ValueError as exc:
        print(f"PROBLEM: {exc}")
        return 1
    if args.check:
        if problems or updated != text:
            if updated != text:
                print(
                    "The index in docs/project/progress.md is out of date: run "
                    "python scripts/progress_index.py"
                )
            return 1
        print(
            f"OK: the index lists the {len(items)} entries in docs/project/progress/."
        )
        return 0
    state = "already current"
    if updated != text:
        PROGRESS.write_text(updated, encoding="utf-8")
        state = "updated"
    print(f"{len(items)} entries; index {state}.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
