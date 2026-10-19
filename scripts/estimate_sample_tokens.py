"""Tokenizer-specific size ESTIMATES for the sample's text fields (Stage 7,
optional; MP Stage 7 last bullet).

    python scripts/estimate_sample_tokens.py [--out-dir reports/cost]

Counts the sample's user messages, answers, instructions (every occurrence,
and distinct texts once), retrieval queries, and retrieved items with each
tokenizer in the tokenizer table, and writes **aggregates only** (counts,
sums, median, p95, max, tokens per 1,000 characters, chars/4 error):
- no text, no hash, no per-message value is written or printed (CLAUDE.md);
- these are **estimates of size, not billed tokens**: no chat-template
  overhead, no knowledge of what was really sent (A-03, TODO-04);
- the sample is exploratory (ADR-0008): provisional signals, not facts;
- the writing-system bucket is a crude letter-count heuristic (share of
  Arabic-block vs Latin letters), labelled as such, not language detection.
Reads data/sample_data/raw/data.json read-only (the Stage 9 sample loader
does not exist yet); never modifies it. No network, no model call.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

from metis_auto.settings import load_settings, repo_root
from metis_auto.wiring.tokenizers import build_tokenizers

SAMPLE = Path("data/sample_data/raw/data.json")
BASELINE = "approx-chars-div-4"


def bucket(text: str) -> str:
    """Heuristic writing-system bucket (not language detection)."""
    arabic = latin = 0
    for ch in text:
        if not ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        if name.startswith(("ARABIC", "PERSIAN")):
            arabic += 1
        elif name.startswith("LATIN"):
            latin += 1
    letters = arabic + latin
    if letters == 0:
        return "no_letters"
    if arabic / letters >= 0.8:
        return "arabic_script"
    if latin / letters >= 0.8:
        return "latin_script"
    return "mixed_script"


def texts(sample: list) -> dict[str, list[str]]:
    """Field → texts, in file order. Empty strings are skipped."""
    out: dict[str, list[str]] = defaultdict(list)
    seen: set[str] = set()
    for category in sample:
        for session in category["sessions"]:
            for m in session["messages"]:
                role = m.get("role")
                if m.get("content"):
                    out["user_message" if role == "user" else "answer"].append(
                        m["content"]
                    )
                if m.get("instructions"):
                    out["instructions_all"].append(m["instructions"])
                    digest = hashlib.sha256(m["instructions"].encode()).digest()
                    if digest not in seen:  # in memory only, never written
                        seen.add(digest)
                        out["instructions_distinct"].append(m["instructions"])
                rag = m.get("rag") or {}
                if rag.get("query"):
                    out["retrieval_query"].append(rag["query"])
                for item in rag.get("context") or ():
                    if isinstance(item, str) and item:
                        out["retrieved_item"].append(item)
    return out


def p95(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, default=Path("reports/cost"))
    args = parser.parse_args()

    root = repo_root()
    with (root / SAMPLE).open(encoding="utf-8") as handle:
        sample = json.load(handle)
    built = build_tokenizers(load_settings(environ={}, dotenv=None, runtime=None))
    fallback = [s.ref for s in built.status if s.reason]
    if fallback:
        print(f"warning: approximation fallback for {fallback}", file=sys.stderr)
    refs = [s.ref for s in built.status if s.ref != "grok-approx"]  # = chars/4

    rows = []
    for field, items in texts(sample).items():
        groups = defaultdict(list)
        for text in items:
            groups["all"].append(text)
            groups[bucket(text)].append(text)
        for group, members in sorted(groups.items()):
            chars = [len(t) for t in members]
            counts = {
                ref: [built.tokenizers[ref].count(t).tokens for t in members]
                for ref in refs
            }
            row = {
                "field": field,
                "script_bucket": group,
                "texts": len(members),
                "chars_total": sum(chars),
                "chars_median": statistics.median(chars),
            }
            for ref, values in counts.items():
                total = sum(values)
                row[ref] = {
                    "tokens_total": total,
                    "tokens_median": statistics.median(values),
                    "tokens_p95": p95(values),
                    "tokens_max": max(values),
                    "tokens_per_1000_chars": round(1000 * total / sum(chars), 1),
                }
            base = sum(counts[BASELINE])
            for ref in refs:
                if ref != BASELINE:
                    exact = sum(counts[ref])
                    row[ref]["chars_div_4_error_pct"] = round(
                        100 * (base - exact) / exact, 1
                    )
            rows.append(row)

    status = [
        {"ref": s.ref, "counted_with": s.loaded, "fidelity": s.fidelity}
        for s in built.status
    ]
    result = {
        "kind": "ESTIMATE: tokenizer-specific sizes of sample text fields, "
        "not billed tokens",
        "generated_on": date.today().isoformat(),
        "sample_sha256": hashlib.sha256((root / SAMPLE).read_bytes()).hexdigest(),
        "tokenizers": status,
        "rows": rows,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "sample_token_estimates.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({"rows": len(rows), "tokenizers": status}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
