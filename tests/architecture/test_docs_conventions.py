"""Docs conventions that stop merge conflicts: one progress entry per file with a
generated index, and ADR drafts that get their numbers at merge.

The real-tree tests run on every branch (drafts are allowed on a branch; the merger
runs `adr_finalize.py --check`, which also fails on drafts). The rest runs the two
scripts on synthetic trees. No network, no data."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PH = "ADR-" + "XXXX"  # the placeholder, built here so this file is not flagged


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pi = load("progress_index")
af = load("adr_finalize")


# --- the real tree ----------------------------------------------------------


def test_the_progress_index_matches_the_folder():
    assert pi.main(["--check"]) == 0


def test_every_progress_entry_is_well_formed():
    items, problems = pi.entries(ROOT / "docs" / "project" / "progress")
    assert problems == [] and len(items) >= 21
    names = {p.name for p in (ROOT / "docs/project/progress").glob("*.md")}
    assert names == {i[3] for i in items}  # no file the index would ignore


def test_progress_md_stays_short_and_keeps_the_lead_owned_status():
    text = (ROOT / "docs/project/progress.md").read_text(encoding="utf-8")
    assert "## Current status (lead-owned)" in text
    assert text.count(pi.START) == 1 and text.count(pi.END) == 1
    assert len(text.splitlines()) < 150


def test_gitattributes_merges_progress_md_by_union_with_a_reason():
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "docs/project/progress.md merge=union" in text
    assert "docs/references/*.csv -text" in text  # existing lines kept
    before = text.split("docs/project/progress.md merge=union")[0]
    assert before.rstrip().splitlines()[-1].startswith("#")  # a comment explains it


def test_adr_numbers_are_unique_and_the_readme_table_matches_the_files():
    errors, _notes = af.check(ROOT)
    errors = [e for e in errors if not e.startswith("draft not finalized")]
    assert errors == []


def test_the_rules_are_in_the_agent_and_team_docs():
    for name in ("CLAUDE.md", "AGENTS.md", "docs/guides/team_workflow.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "docs/project/progress/" in text, name
        assert "progress_index.py" in text and "adr_finalize.py" in text, name
        assert "draft-<slug>" in text or "draft-" in text, name
    assert "Update `progress.md`" not in (ROOT / "CLAUDE.md").read_text(
        encoding="utf-8"
    )


# --- progress_index on synthetic folders ------------------------------------


def entry(folder, name, title, body="text"):
    (folder / name).write_text(f"## {title}\n\n{body}\n", encoding="utf-8")


def test_entries_are_listed_newest_first_ties_by_name_and_titles_lose_the_date(
    tmp_path,
):
    entry(tmp_path, "2026-11-01-alpha.md", "Alpha (2026-11-01)")
    entry(tmp_path, "2026-11-02-beta.md", "Beta (2026-11-02)")
    entry(tmp_path, "2026-11-02-gamma.md", "Gamma, no date in the title")
    (tmp_path / "README.md").write_text("not an entry")
    (tmp_path / "notes.txt").write_text("not an entry")
    items, problems = pi.entries(tmp_path)
    assert problems == []
    assert [i[3] for i in items] == [
        "2026-11-02-gamma.md",
        "2026-11-02-beta.md",
        "2026-11-01-alpha.md",
    ]
    assert [i[2] for i in items] == ["Gamma, no date in the title", "Beta", "Alpha"]
    assert pi.render(items).splitlines()[1] == (
        "- 2026-11-02: [Beta](progress/2026-11-02-beta.md)"
    )


def test_malformed_entries_are_reported_not_listed(tmp_path):
    (tmp_path / "2026-11-02-no-heading.md").write_text("just text\n")
    (tmp_path / "2026-13-45-bad-date.md").write_text("## Title\n")
    entry(tmp_path, "2026-11-02-fine.md", "Fine (2026-11-02)")
    items, problems = pi.entries(tmp_path)
    assert [i[3] for i in items] == ["2026-11-02-fine.md"]
    assert len(problems) == 2 and any("not a date" in p for p in problems)


def test_the_index_replaces_only_the_lines_between_the_markers():
    text = f"top\n\n{pi.START}\nold\n{pi.END}\n\nbottom\n"
    out = pi.replace_index(text, "- new")
    assert out == f"top\n\n{pi.START}\n- new\n{pi.END}\n\nbottom\n"
    assert pi.replace_index(out, "- new") == out  # idempotent
    with pytest.raises(ValueError, match="exactly one"):
        pi.replace_index("no markers", "x")
    with pytest.raises(ValueError, match="in order"):
        pi.replace_index(f"{pi.END}\n{pi.START}", "x")


def test_check_fails_when_the_index_is_stale_and_write_fixes_it(tmp_path, monkeypatch):
    folder = tmp_path / "progress"
    folder.mkdir()
    page = tmp_path / "progress.md"
    page.write_text(f"# P\n\n{pi.START}\n{pi.END}\n", encoding="utf-8")
    entry(folder, "2026-11-02-one.md", "One (2026-11-02)")
    monkeypatch.setattr(pi, "FOLDER", folder)
    monkeypatch.setattr(pi, "PROGRESS", page)
    assert pi.main(["--check"]) == 1
    assert pi.main([]) == 0 and "One" in page.read_text(encoding="utf-8")
    assert pi.main(["--check"]) == 0
    entry(folder, "2026-11-03-two.md", "Two (2026-11-03)")
    assert pi.main(["--check"]) == 1


# --- adr_finalize on synthetic trees ----------------------------------------


def adr(root, name, number, title, status="**decided**", body=""):
    folder = root / "docs" / "adr"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(
        f"# ADR-{number}: {title}\n\n- Status: {status}\n- Date: 2026-11-02\n"
        f"\n{body}\n",
        encoding="utf-8",
    )


def readme(root):
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "README.md").write_text(
        f"# Index\n\nhand-written\n\n{af.TABLE_START}\n{af.TABLE_END}\n\nmore text\n",
        encoding="utf-8",
    )


def tree(tmp_path, last=3):
    for n in range(1, last + 1):
        adr(tmp_path, f"{n:04d}-old-{n}.md", f"{n:04d}", f"Old decision {n}")
    readme(tmp_path)
    af.finalize(tmp_path, dry_run=False, out=lambda _m: None)  # a finalized tree
    return tmp_path


def draft(root, slug, title, refs=""):
    adr(root, f"draft-{slug}.md", "XXXX", title, body=refs)
    text = (root / "docs/adr" / f"draft-{slug}.md").read_text(encoding="utf-8")
    # the title line of a draft carries the slug
    (root / "docs/adr" / f"draft-{slug}.md").write_text(
        text.replace("# ADR-XXXX:", f"# {PH} ({slug}):", 1), encoding="utf-8"
    )


def test_a_finalized_tree_checks_clean(tmp_path):
    root = tree(tmp_path)
    assert af.check(root) == ([], [])


def test_drafts_get_the_next_numbers_in_alphabetical_order_of_slug(tmp_path):
    root = tree(tmp_path, last=3)
    draft(root, "zeta-rule", "Zeta")
    draft(root, "alpha-rule", "Alpha")
    af.finalize(root, dry_run=False, out=lambda _m: None)
    names = sorted(p.name for p in (root / "docs/adr").glob("*.md"))
    assert "0004-alpha-rule.md" in names and "0005-zeta-rule.md" in names
    assert not [n for n in names if n.startswith("draft-")]
    first = (root / "docs/adr/0004-alpha-rule.md").read_text(encoding="utf-8")
    assert first.startswith("# ADR-0004: Alpha")
    table = (root / "docs/README.md").read_text(encoding="utf-8")
    assert "[0004](adr/0004-alpha-rule.md) | Alpha |" in table
    assert "hand-written" in table and "more text" in table  # the rest untouched
    assert af.check(root) == ([], [])


def test_references_and_links_to_a_draft_are_rewritten_across_the_repository(tmp_path):
    root = tree(tmp_path)
    draft(root, "my-rule", "My rule")
    (root / "docs" / "guide.md").write_text(
        f"See {PH} (my-rule) and [it](adr/draft-my-rule.md). Also {PH} (other).\n"
        "Keep draft-my-rule-extra.md alone.\n",
        encoding="utf-8",
    )
    (root / "src.py").write_text(f"# decision: {PH} (my-rule)\n", encoding="utf-8")
    af.finalize(root, dry_run=False, out=lambda _m: None)
    guide = (root / "docs/guide.md").read_text(encoding="utf-8")
    assert "See ADR-0004 and [it](adr/0004-my-rule.md)." in guide
    assert f"{PH} (other)" in guide  # not a draft here: left, and --check reports it
    assert "draft-my-rule-extra.md" in guide
    assert (root / "src.py").read_text(encoding="utf-8") == "# decision: ADR-0004\n"
    errors, _ = af.check(root)
    assert any("(other)" in e for e in errors)


def test_dry_run_prints_the_plan_and_changes_nothing(tmp_path):
    root = tree(tmp_path)
    draft(root, "my-rule", "My rule", refs=f"{PH} (my-rule)")
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    lines = []
    af.finalize(root, dry_run=True, out=lines.append)
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
    text = "\n".join(lines)
    assert "draft-my-rule.md -> docs/adr/0004-my-rule.md" in text
    assert "reference(s) updated in docs/adr/draft-my-rule.md" in text


def test_the_highest_number_comes_from_main_when_the_branch_is_behind(tmp_path):
    root = tmp_path
    adr(root, "0001-old-1.md", "0001", "Old")
    readme(root)

    def run(*args):
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=root,
            check=True,
            capture_output=True,
        )

    run("init", "-q", "-b", "main")
    adr(root, "0007-landed-on-main.md", "0007", "Landed")
    run("add", "-A")
    run("commit", "-q", "-m", "main has 0007")
    run("switch", "-q", "-c", "feature")
    (root / "docs/adr/0007-landed-on-main.md").unlink()  # the branch never saw it
    draft(root, "mine", "Mine")
    plan = af.plan(root)
    assert plan["source"] == "main" and plan["highest"] == 7
    assert plan["renames"] == {"mine": 8}


def test_check_flags_a_draft_a_duplicate_number_a_wrong_title_and_a_stale_table(
    tmp_path,
):
    root = tree(tmp_path)
    draft(root, "pending", "Pending")
    adr(root, "0002-second-claim.md", "0002", "Same number as old-2")
    adr(root, "0003-old-3.md", "0009", "Title says another number")
    errors, _ = af.check(root)
    text = "\n".join(errors)
    assert "draft not finalized: docs/adr/draft-pending.md" in text
    assert "ADR number 0002 is used twice" in text
    assert "title line must say ADR-0003" in text
    assert "table in docs/README.md is stale" in text


def test_gaps_are_notes_not_errors(tmp_path):
    root = tree(tmp_path, last=2)
    (root / "docs/adr/0002-old-2.md").rename(root / "docs/adr/0004-old-2.md")
    text = (root / "docs/adr/0004-old-2.md").read_text(encoding="utf-8")
    (root / "docs/adr/0004-old-2.md").write_text(
        text.replace("ADR-0002", "ADR-0004"), encoding="utf-8"
    )
    af.finalize(root, dry_run=False, out=lambda _m: None)
    errors, notes = af.check(root)
    assert errors == [] and any("0002, 0003" in n for n in notes)


def test_the_table_strips_links_escapes_pipes_and_shortens_long_statuses(tmp_path):
    root = tmp_path
    readme(root)
    long = "**decided**. " + "word " * 80
    adr(
        root,
        "0001-first.md",
        "0001",
        "Pipes | in a title",
        status="**decided**. Amended by [ADR-0002](0002-second.md) on 2026-11-02. "
        + long,
    )
    adr(root, "0002-second.md", "0002", "Second")
    af.finalize(root, dry_run=False, out=lambda _m: None)
    rows = (root / "docs/README.md").read_text(encoding="utf-8").splitlines()
    row = next(r for r in rows if r.startswith("| [0001]"))
    assert "Pipes \\| in a title" in row and "](0002-second.md)" not in row
    assert "Amended by ADR-0002" in row and row.rstrip(" |").endswith("…")


def test_drafts_with_the_same_slug_pattern_only_match_whole_slugs(tmp_path):
    assert af.DRAFT.match("draft-a-b.md") and not af.DRAFT.match("draft-.md")
    assert not af.DRAFT.match("draft-A.md") and not af.NUMBERED.match("12-x.md")
    assert af.PLACEHOLDER.search(f"{PH} (a-b)")
    assert not af.PLACEHOLDER.search(f"{PH} (<slug>)")  # how the docs write it


def test_without_git_the_working_tree_is_used(tmp_path, monkeypatch):
    root = tree(tmp_path)
    monkeypatch.setattr(af, "git", lambda *a, **k: None)
    assert af.main_numbers(root) == ("the working tree", {1, 2, 3})
    assert af.repo_files(root)  # the walk finds the text files without git
