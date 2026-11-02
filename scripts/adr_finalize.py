"""Give draft ADRs their numbers, and keep the ADR table in docs/README.md current.

    python scripts/adr_finalize.py --dry-run   # print what would change
    python scripts/adr_finalize.py             # do it
    python scripts/adr_finalize.py --check     # exit 1 if the tree is not finalized

A new ADR on a branch is a draft named docs/adr/draft-<slug>.md. Its title line is
"# ADR-XXXX (<slug>): Title", and every reference to it is written "ADR-XXXX
(<slug>)" or links to the draft file. The merger runs this script before merging:

1. the highest ADR number is read from origin/main (else the local main, else the
   working tree) and from the working tree, and the larger one counts;
2. each draft is renamed to the next free number, in alphabetical order of slug;
3. "ADR-XXXX (<slug>)" becomes "ADR-NNNN" and links to the draft file point to the
   numbered file, across the repository's text files;
4. the ADR table in docs/README.md, between the two marker comments, is rebuilt from
   each ADR's title line and Status line (the rest of the README is hand-written).

--check fails if a draft or an "ADR-XXXX (<slug>)" remains, a number is used twice,
a file's number differs from its title, or the table is stale. Gaps in the numbers
are reported as notes. Standard library only.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NUMBERED = re.compile(r"^(\d{4})-([a-z0-9][a-z0-9-]*)\.md$")
DRAFT = re.compile(r"^draft-([a-z0-9][a-z0-9-]*)\.md$")
PLACEHOLDER = re.compile(r"ADR-XXXX \(([a-z0-9][a-z0-9-]*)\)")
TITLE = re.compile(r"^# ADR-(\d{4}|XXXX)(?: \([^)]*\))?:\s*(.+?)\s*$")
TABLE_START = "<!-- adr-table:start -->"
TABLE_END = "<!-- adr-table:end -->"
TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yml",
    ".yaml",
    ".json",
    ".cfg",
    ".ini",
}
SKIP_DIRS = {".git", ".venv", "node_modules", "data", "runs", "__pycache__", ".scratch"}
STATUS_CHARS = 150


# --- reading the tree -------------------------------------------------------


def git(root: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    return done.stdout if done.returncode == 0 else None


def adr_names(root: Path) -> list[str]:
    folder = root / "docs" / "adr"
    return sorted(p.name for p in folder.glob("*.md")) if folder.is_dir() else []


def tree_numbers(root: Path) -> set[int]:
    return {int(m.group(1)) for n in adr_names(root) if (m := NUMBERED.match(n))}


def main_numbers(root: Path) -> tuple[str, set[int]]:
    """(where the numbers came from, ADR numbers on main)."""
    for ref in ("origin/main", "main"):
        out = git(root, "ls-tree", "--name-only", ref, "docs/adr/")
        if out is not None:
            names = [Path(line).name for line in out.splitlines()]
            return ref, {int(m.group(1)) for n in names if (m := NUMBERED.match(n))}
    return "the working tree", tree_numbers(root)


def repo_files(root: Path) -> list[Path]:
    """Text files of the repository: tracked and untracked-but-not-ignored when git
    answers, otherwise a walk that skips build and data folders."""
    out = git(root, "ls-files", "--cached", "--others", "--exclude-standard")
    if out is not None:
        paths = [root / line for line in out.splitlines() if line]
    else:
        paths = []
        for base, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            paths += [Path(base) / f for f in files]
    return [p for p in paths if p.suffix in TEXT_SUFFIXES and p.is_file()]


def read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


# --- the plan ---------------------------------------------------------------


def drafts(root: Path) -> list[str]:
    """Slugs of the drafts, alphabetical."""
    return sorted(m.group(1) for n in adr_names(root) if (m := DRAFT.match(n)))


def plan(root: Path) -> dict:
    source, on_main = main_numbers(root)
    highest = max(on_main | tree_numbers(root), default=0)
    slugs = drafts(root)
    return {
        "source": source,
        "highest": highest,
        "renames": {s: highest + 1 + i for i, s in enumerate(slugs)},
    }


def rewrite(text: str, renames: dict[str, int]) -> tuple[str, int]:
    """``text`` with placeholders and draft links replaced; and how many were."""
    count = 0

    def placeholder(m: re.Match) -> str:
        nonlocal count
        if m.group(1) in renames:
            count += 1
            return f"ADR-{renames[m.group(1)]:04d}"
        return m.group(0)

    text = PLACEHOLDER.sub(placeholder, text)
    for slug, number in renames.items():
        pattern = re.compile(rf"(?<![A-Za-z0-9-])draft-{re.escape(slug)}\.md")
        text, n = pattern.subn(f"{number:04d}-{slug}.md", text)
        count += n
    return text, count


# --- the README table -------------------------------------------------------


def plain(text: str) -> str:
    """Markdown links reduced to their text, so a table row has no broken paths."""
    return re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)


def short(text: str, limit: int = STATUS_CHARS) -> str:
    text = plain(text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:(") + "…"


def entry(root: Path, name: str) -> tuple[str, str, str]:
    """(number, title, status) of a numbered ADR."""
    lines = (root / "docs" / "adr" / name).read_text(encoding="utf-8").splitlines()
    title = name
    if lines and (m := TITLE.match(lines[0])):
        title = m.group(2)
    status = next(
        (
            line.split(":", 1)[1].strip()
            for line in lines[:12]
            if line.startswith("- Status:")
        ),
        "",
    )
    return name[:4], title, status


def table(root: Path) -> str:
    rows = ["| ADR | Title | Status |", "|---|---|---|"]
    for name in adr_names(root):
        if NUMBERED.match(name):
            number, title, status = entry(root, name)
            cells = [f"[{number}](adr/{name})", plain(title), short(status)]
            rows.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    return "\n".join(rows)


def replace_table(text: str, new: str) -> str:
    if text.count(TABLE_START) != 1 or text.count(TABLE_END) != 1:
        raise ValueError(
            f"docs/README.md needs exactly one {TABLE_START} and one {TABLE_END}"
        )
    head, rest = text.split(TABLE_START, 1)
    _old, tail = rest.split(TABLE_END, 1)
    return f"{head}{TABLE_START}\n{new}\n{TABLE_END}{tail}"


# --- checking ---------------------------------------------------------------


def check(root: Path) -> tuple[list[str], list[str]]:
    """(errors, notes)."""
    errors, notes = [], []
    seen: dict[str, list[str]] = {}
    for name in adr_names(root):
        if NUMBERED.match(name):
            seen.setdefault(name[:4], []).append(name)
        elif DRAFT.match(name):
            errors.append(f"draft not finalized: docs/adr/{name}")
    for number, names in sorted(seen.items()):
        if len(names) > 1:
            errors.append(f"ADR number {number} is used twice: {', '.join(names)}")
    for name in adr_names(root):
        if NUMBERED.match(name):
            first = (
                (root / "docs/adr" / name).read_text(encoding="utf-8").split("\n")[0]
            )
            m = TITLE.match(first)
            if not m or m.group(1) != name[:4]:
                errors.append(
                    f"docs/adr/{name}: the title line must say ADR-{name[:4]}"
                )
    for path in repo_files(root):
        text = read(path)
        for m in PLACEHOLDER.finditer(text or ""):
            errors.append(f"{path.relative_to(root)}: unresolved {m.group(0)}")
    numbers = sorted(int(n) for n in seen)
    gaps = sorted(set(range(1, numbers[-1] + 1)) - set(numbers)) if numbers else []
    if gaps:
        notes.append("gaps in the ADR numbers: " + ", ".join(f"{g:04d}" for g in gaps))
    readme = root / "docs" / "README.md"
    try:
        current = readme.read_text(encoding="utf-8")
        if replace_table(current, table(root)) != current:
            errors.append("the ADR table in docs/README.md is stale")
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    return errors, notes


# --- doing it ---------------------------------------------------------------


def finalize(root: Path, *, dry_run: bool, out=print) -> int:
    info = plan(root)
    top = f"{info['highest']:04d}"
    out(f"Highest ADR number: {top} (from {info['source']} and the tree).")
    if not info["renames"]:
        out("No drafts.")
    for slug, number in info["renames"].items():
        out(f"  docs/adr/draft-{slug}.md -> docs/adr/{number:04d}-{slug}.md")
    touched = {}
    if info["renames"]:
        for path in repo_files(root):
            text = read(path)
            if text is None:
                continue
            new, count = rewrite(text, info["renames"])
            if count:
                touched[path] = (new, count)
        for path, (_new, count) in sorted(touched.items()):
            out(f"  {count} reference(s) updated in {path.relative_to(root)}")
    if not dry_run:
        for slug, number in info["renames"].items():
            (root / "docs/adr" / f"draft-{slug}.md").rename(
                root / "docs/adr" / f"{number:04d}-{slug}.md"
            )
        for path, (new, _count) in touched.items():
            target = path
            m = DRAFT.match(path.name)
            if m and m.group(1) in info["renames"]:
                target = path.with_name(
                    f"{info['renames'][m.group(1)]:04d}-{m.group(1)}.md"
                )
            target.write_text(new, encoding="utf-8")
    readme = root / "docs" / "README.md"
    try:
        current = readme.read_text(encoding="utf-8")
        if dry_run and info["renames"]:
            # the table of the tree as it will be after the renames
            out("  the ADR table in docs/README.md will list the new ADRs")
        else:
            updated = replace_table(current, table(root))
            if updated != current:
                out(
                    "  the ADR table in docs/README.md "
                    + ("would change" if dry_run else "updated")
                )
                if not dry_run:
                    readme.write_text(updated, encoding="utf-8")
            else:
                out("  the ADR table in docs/README.md is current")
    except (OSError, ValueError) as exc:
        out(f"PROBLEM: {exc}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print, change nothing")
    ap.add_argument("--check", action="store_true", help="exit 1 if not finalized")
    args = ap.parse_args(argv)
    if args.check:
        errors, notes = check(ROOT)
        for note in notes:
            print(f"note: {note}")
        for error in errors:
            print(f"ERROR: {error}")
        if errors:
            print("Run: python scripts/adr_finalize.py")
            return 1
        print("OK: no drafts, no duplicate numbers, the ADR table is current.")
        return 0
    return finalize(ROOT, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
