"""SQL for the golden-answer table and for reading a dataset's request inputs
(ADR-0030). No decisions here (P-1). Text ordering uses ``COLLATE "C"``.

``request_inputs`` returns message text and ``answers_for`` returns answer text:
callers keep both in memory or in git-ignored files, never in logs or reports.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import Connection, text


def request_inputs(conn: Connection, dataset_id: str) -> list[dict[str, Any]]:
    """Per record in selection order: the post-retrieval view rows, every
    component kind, the stratum (labels) and nothing else."""
    records = conn.execute(
        text(
            """SELECT record_id, stratum FROM eval.dataset_record
               WHERE dataset_id = :d ORDER BY selection_rank, record_id COLLATE "C" """
        ),
        {"d": dataset_id},
    ).all()
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in conn.execute(
        text(
            """SELECT v.record_id, v.position, v.kind, v.role, v.content, v.metadata
               FROM eval.routing_input_post_retrieval_v1 v
               JOIN eval.dataset_record d USING (record_id)
               WHERE d.dataset_id = :d ORDER BY v.record_id COLLATE "C", v.position"""
        ),
        {"d": dataset_id},
    ):
        rows[r.record_id].append(dict(r._mapping))
    kinds: dict[str, set[str]] = defaultdict(set)
    for r in conn.execute(
        text(
            """SELECT c.record_id, c.kind FROM eval.record_input_component c
               JOIN eval.dataset_record d USING (record_id) WHERE d.dataset_id = :d
               GROUP BY 1, 2"""
        ),
        {"d": dataset_id},
    ):
        kinds[r.record_id].add(r.kind)
    return [
        {
            "record_id": rec.record_id,
            "stratum": rec.stratum,
            "rows": rows[rec.record_id],
            "kinds": sorted(kinds[rec.record_id]),
        }
        for rec in records
    ]


def stored_status(conn: Connection, run_id: str) -> dict[str, tuple[str, str | None]]:
    rows = conn.execute(
        text(
            "SELECT record_id, status, error_class FROM eval.golden_answer "
            "WHERE run_id = :r"
        ),
        {"r": run_id},
    )
    return {r.record_id: (r.status, r.error_class) for r in rows}


_COLUMNS = (
    "run_id, record_id, model_id, effort, max_output_tokens, settings_hash, "
    "prompt_fingerprint, status, answer, answer_chars, answer_language_group, "
    "finish_reason, error_class, attempts, provider_model_version, input_tokens, "
    "cached_input_tokens, output_tokens, reasoning_tokens, cost_usd, cost_state, "
    "latency_ms, caveats"
)


def save_answer(conn: Connection, row: Mapping[str, Any]) -> None:
    """Insert, or replace a stored failure of the same run and record (a retry
    after a retryable error). An answered row is never overwritten."""
    names = [c.strip() for c in _COLUMNS.split(",")]
    values = {**row, "caveats": json.dumps(list(row["caveats"]))}
    updates = ", ".join(
        f"{n} = EXCLUDED.{n}" for n in names if n not in ("run_id", "record_id")
    )
    conn.execute(
        text(
            f"""INSERT INTO eval.golden_answer ({_COLUMNS})
                VALUES ({", ".join(f":{n}" for n in names)})
                ON CONFLICT (run_id, record_id) DO UPDATE SET {updates}
                WHERE eval.golden_answer.status <> 'answered'"""
        ),
        {n: values[n] for n in names},
    )


def summary_rows(conn: Connection, run_id: str) -> list[dict[str, Any]]:
    """Content-free rows of a run, each with its dataset record's stratum."""
    rows = conn.execute(
        text(
            """SELECT g.record_id, g.status, g.error_class, g.finish_reason,
                      g.answer_language_group, g.latency_ms, g.input_tokens,
                      g.cached_input_tokens, g.output_tokens, g.reasoning_tokens,
                      g.cost_usd, g.cost_state, g.caveats, d.stratum
               FROM eval.golden_answer g JOIN eval.dataset_record d USING (record_id)
               WHERE g.run_id = :r ORDER BY g.record_id COLLATE "C" """
        ),
        {"r": run_id},
    )
    out = []
    for r in rows:
        row = dict(r._mapping)
        stratum = row.pop("stratum")
        row["strata"] = {k: str(v) for k, v in stratum.items() if isinstance(v, str)}
        row["caveats"] = tuple(
            dict.fromkeys((*row["caveats"], *stratum.get("caveats", ())))
        )
        out.append(row)
    return out


def answered_count(conn: Connection, run_id: str) -> int:
    return conn.execute(
        text(
            "SELECT count(*) FROM eval.golden_answer "
            "WHERE run_id=:r AND status='answered'"
        ),
        {"r": run_id},
    ).scalar_one()


def runs(conn: Connection) -> list[tuple[str, int]]:
    rows = conn.execute(
        text("SELECT run_id, count(*) FROM eval.golden_answer GROUP BY 1 ORDER BY 1")
    )
    return [(r[0], r[1]) for r in rows]


def answers_for(
    conn: Connection, run_id: str, record_ids: Iterable[str]
) -> dict[str, str]:
    """LOCAL USE ONLY: returns answer text."""
    rows = conn.execute(
        text(
            "SELECT record_id, answer FROM eval.golden_answer "
            "WHERE run_id = :r AND status = 'answered' AND record_id = ANY(:ids)"
        ),
        {"r": run_id, "ids": list(record_ids)},
    )
    return {r.record_id: r.answer for r in rows}
