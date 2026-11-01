"""Render report templates from the claims ledger and check them.

    python scripts/full_eda_render.py            # merge ledgers, render all templates
    python scripts/full_eda_render.py --check    # verify rendered files == templates + ledger,
                                                  # and that templates hold no hand-typed numbers

Template syntax: ``{{claim_id}}`` or ``{{claim_id:fmt}}`` with fmt one of
pct (12.3%), pct0 (12%), int (1,234), f1, f2, f3, g (3 significant figures),
x2 (ratio as 0.05x), usd2 (2 decimals), m1 (millions, 1 decimal), n (numerator),
d (denominator).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

T = Path("reports/full_eda/tables")
PAIRS = [
    (
        Path("docs/full_eda/templates/full_eda_report.tmpl.md"),
        Path("docs/full_eda/full_eda_report.md"),
    ),
    (
        Path("docs/full_eda/templates/eda_findings.tmpl.md"),
        Path("docs/full_eda/eda_findings.md"),
    ),
]
PH = re.compile(r"\{\{([\w.+\-]+)(?::(\w+))?\}\}")
# Literals that may appear in templates because they are cited constants, not results.
ALLOWED = [
    r"F-\d",
    r"H-\d",
    r"U-\d+",
    r"Q-\d+",
    r"A-\d+",
    r"C-\d+",
    r"ADR-\d+",
    r"FR-[A-Z]+-?\d*",
    r"NG-\d+",
    r"QA-\d+",
    r"CMP-\d+",
    r"§\d+(\.\d+)?",
    r"\b20\d\d(-\d\d(-\d\d)?)?\b",
    r"\b\d+\.\d+\.\d+\b",
    r"gpt-[\d.]+\w*",
    r"gemini-[\d.]+\w*",
    r"deepseek-v\d+\w*",
    r"claude-\d+\w*",
    r"grok-[\d\-]+\w*",
    r"\bTier \d\b",
    r"\bP[012]\b",
    r"\b30f578f2\w*",
    r"\bfig\d_\w+\b",
    r"Q\d",
    r"\b100 ms\b",
    r"\b3%",
    r"\b5%",
    r"\b4,019\b",
    r"\bSHA\b",
    r"\bkpi\b",
    r"\b0\.002\b",
    r"\b16 MB\b",
    r"\bturns? (0|1|3-4|20\+)",
    r"\bturn-0\b",
    r"\b100k\b",
    r"\b40-per-label",
    r"\bat most 100 characters",
    r"\b32,000\b",
    r"\b100 most\b",
    r"\bfrom 5\b",
    r"n−1",
    r"\b100 sessions",
    r"\b0\.8\b",
    r"\b1,500\b",
    r"\b8,000\b",
    r"\b82\.6%",
    r"\b16\.3%",
    r"\b7\.5%",
    r"\b91%",
    r"\b1%",
    r"\b(5|10|100) (largest|bots|keys)",
    r"\btop (10|100)\b",
    r"\b25 sessions",
    r"\(\d\)",
    r"\b2 s\b",
    r"\bp\d\d\b",
    r"top-?\d+",
    r"\bphase \d\b",
    r"\b\d+-\d+ words\b",
    r"\bchars/4\b",
    r"\b2,500\b",
    r"\b10 minutes\b",
]


def load_ledger() -> pd.DataFrame:
    parts = [pd.read_csv(p) for p in sorted(T.glob("claims_ledger_[a-z].csv"))]
    led = pd.concat(parts, ignore_index=True)
    if led["claim_id"].duplicated().any():
        raise SystemExit(
            f"duplicate claim ids: {led.loc[led['claim_id'].duplicated(), 'claim_id'].tolist()[:5]}"
        )
    return led


def fmt(row: pd.Series, f: str | None) -> str:
    v = row["value"]
    if f == "n":
        v = row["numerator"]
        return f"{v:,.0f}"
    if f == "d":
        v = row["denominator"]
        return f"{v:,.0f}"
    return {
        None: f"{v:,.4g}",
        "g": f"{v:.3g}",
        "pct": f"{v * 100:.1f}%",
        "pct0": f"{v * 100:.0f}%",
        "int": f"{v:,.0f}",
        "f1": f"{v:.1f}",
        "f2": f"{v:.2f}",
        "f3": f"{v:.3f}",
        "x2": f"{v:.2f}x",
        "usd2": f"{v:,.2f}",
        "m1": f"{v / 1e6:,.1f} million",
        "ym": f"{int(v) // 100}-{int(v) % 100:02d}",
    }[f]


def render(text: str, led: pd.DataFrame) -> str:
    idx = led.set_index("claim_id")

    def sub(m: re.Match) -> str:
        cid, f = m.group(1), m.group(2)
        if cid not in idx.index:
            raise SystemExit(f"unknown claim id in template: {cid}")
        return fmt(idx.loc[cid], f)

    return PH.sub(sub, text)


def hand_typed_numbers(tmpl: str) -> list[str]:
    t = PH.sub("", tmpl)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)  # image refs
    t = re.sub(r"\]\([^)]*\)", "]", t)  # link targets
    t = re.sub(r"`[^`]*`", "", t)  # code spans
    t = re.sub(r"^#+ [\d.]+", "", t, flags=re.M)  # numbered headings
    t = re.sub(r"^\s*\d+\.\s", "", t, flags=re.M)  # list numbering
    for pat in sorted(ALLOWED, key=len, reverse=True):
        t = re.sub(pat, "", t)
    return [
        t[max(0, m.start() - 25) : m.end() + 10].replace("\n", " ")
        for m in re.finditer(r"(?<![\w.])\d[\d,.]*%?", t)
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    led = load_ledger()
    led.to_csv(T / "claims_ledger.csv", index=False)
    bad = 0
    for tmpl, out in PAIRS:
        if not tmpl.exists():
            continue
        text = tmpl.read_text()
        rendered = render(text, led)
        if a.check:
            if not out.exists() or out.read_text() != rendered:
                print(f"STALE: {out} differs from template + ledger")
                bad += 1
            ht = hand_typed_numbers(text)
            if ht:
                print(f"HAND-TYPED numbers in {tmpl}: {sorted(set(ht))[:30]}")
                bad += 1
        else:
            out.write_text(rendered)
            print("rendered", out, len(rendered.split()), "words")
    if a.check:
        print("check:", "FAILED" if bad else "ok", f"({len(led)} claims)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
