"""R9 privacy audit of the decision router's committed outputs: nothing under
reports/routing/ holds Arabic-script text (Persian message content would be
the only source; QA-PRIV, dataset licence), and the slice's committed ID file
holds opaque slice IDs and stratum codes only. Static: reads committed files."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTING = ROOT / "reports" / "routing"
ARABIC_SCRIPT = re.compile("[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
TEXT_SUFFIXES = {".md", ".csv", ".json", ".txt"}


def test_no_arabic_script_under_reports_routing():
    offenders = [
        p.relative_to(ROOT).as_posix()
        for p in ROUTING.rglob("*")
        if p.is_file()
        and p.suffix in TEXT_SUFFIXES
        and ARABIC_SCRIPT.search(p.read_text(encoding="utf-8", errors="replace"))
    ]
    assert offenders == []


def test_the_slice_ids_are_opaque():
    ids = (ROUTING / "dev_slice_v1" / "ids.csv").read_text(encoding="utf-8")
    rows = [line.split(",")[0] for line in ids.splitlines()[1:] if line]
    assert rows and all(re.fullmatch(r"rs1-m_\d{6}", r) for r in rows)
