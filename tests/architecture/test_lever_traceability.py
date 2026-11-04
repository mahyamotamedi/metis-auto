"""Traceability of the lever work (sprint plan E-3; CLAUDE.md "every design
element must cite an FR-/QA-/NG- or hypothesis/experiment ID").

1. Every experiment README cites an ID (``FR-``, ``QA-``, ``NG-``, ``H-<n>``,
   ``X<n>``).
2. Every ``lever_id`` prefix under ``reports/levers`` maps to an experiment folder.
3. Every numbered ADR is listed in ``docs/README.md``.

The checks are functions tested on planted fixtures first, then run on the repo.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ID = re.compile(r"FR-|QA-|NG-|H-\d|X\d")

# lever_id prefix -> experiment folder (the version's home, ADR-0022 naming)
PREFIX_TO_EXPERIMENT = {
    "cache.popular_question": "caching/exp-cache-003-popular-question",
    "cache.session_memo_gate": "caching/exp-cache-004-session-memo-gate",
    "context.reranker_cut": "context/exp-ctx-003-reranker-cut",
    "ctx.history_budget": "context/exp-ctx-004-history-budget",
    "ctx.within_message_dedup": "context/exp-ctx-001-within-message-dedup",
    "rb1.": "caching/exp-cache-002-retrieval-result-cache",
    "rb2.": "context/exp-ctx-002-cross-turn-chunk-policy",
    "rb3.": "routing/exp-route-011-knn-router",
    "route.per_bot": "routing/exp-route-001-per-bot-reassignment",
    "route.small_classifier": "routing/exp-route-012-small-classifier",
    "route.decision_router": "routing/exp-route-013-decision-router",
}


def readmes_without_id(readmes: dict[str, str]) -> list[str]:
    return sorted(name for name, text in readmes.items() if not ID.search(text))


def unmapped_lever_ids(lever_ids: list[str], root: Path) -> list[str]:
    bad = []
    for lid in lever_ids:
        folder = next(
            (v for k, v in PREFIX_TO_EXPERIMENT.items() if lid.startswith(k)), None
        )
        if folder is None or not (root / "experiments" / folder).is_dir():
            bad.append(lid)
    return sorted(set(bad))


def adrs_missing_from_index(adr_names: list[str], index_text: str) -> list[str]:
    return sorted(n for n in adr_names if n not in index_text)


# --- planted fixtures: each check must catch one removed ID -------------------------


def test_a_readme_without_an_id_is_caught():
    ok = {"a": "traces FR-ROUTE-01", "b": "hypothesis H-5", "c": "plan X7"}
    assert readmes_without_id(ok) == []
    assert readmes_without_id({**ok, "d": "no identifiers at all"}) == ["d"]
    assert readmes_without_id({"a": ok["a"].replace("FR-ROUTE-01", "")}) == ["a"]


def test_an_unmapped_lever_id_is_caught(tmp_path):
    (tmp_path / "experiments/routing/exp-route-001-per-bot-reassignment").mkdir(
        parents=True
    )
    assert unmapped_lever_ids(["route.per_bot.as_logged"], tmp_path) == []
    assert unmapped_lever_ids(["route.unknown.as_logged"], tmp_path) == [
        "route.unknown.as_logged"
    ]
    # a mapped prefix whose folder is gone is caught too
    assert unmapped_lever_ids(["rb3.knn-router.k-5.tune.as_logged"], tmp_path) != []


def test_an_adr_missing_from_the_index_is_caught():
    index = "| [0001](adr/0001-python-tooling.md) |"
    assert adrs_missing_from_index(["0001-python-tooling.md"], index) == []
    assert adrs_missing_from_index(["0002-x.md"], index) == ["0002-x.md"]


# --- the repository ----------------------------------------------------------------


def test_every_experiment_readme_cites_an_id():
    readmes = {}
    for pattern in (
        "experiments/*/exp-*/README.md",
        "experiments/pipelines/*/README.md",
    ):
        for p in sorted(ROOT.glob(pattern)):
            readmes[p.relative_to(ROOT).as_posix()] = p.read_text(encoding="utf-8")
    assert readmes
    assert readmes_without_id(readmes) == []


def test_every_lever_id_has_an_experiment_folder():
    ids = []
    for p in sorted((ROOT / "reports/levers").glob("*.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and "lever_id" in doc:
            ids.append(doc["lever_id"])
    assert ids
    assert unmapped_lever_ids(ids, ROOT) == []


def test_every_adr_is_listed_in_the_docs_index():
    index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    names = [
        p.name for p in sorted((ROOT / "docs/adr").glob("[0-9][0-9][0-9][0-9]-*.md"))
    ]
    assert names
    assert adrs_missing_from_index(names, index) == []
