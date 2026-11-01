"""Reproducible Parquet → PostgreSQL ingestion (ADR-0027).

Discover files, hash them, read footers, compare to the expected-schema config, then
stream record batches through COPY into a temporary table and INSERT … ON CONFLICT
DO NOTHING. One transaction per file, so an interrupted run leaves whole files only;
re-running skips files already loaded under the same path and sha256. Text is never
normalised. Messages and row values are never logged.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from sqlalchemy import Engine, Table, select

from metis_auto.data_access.postgres import models as m

TABLES: dict[str, Table] = {
    "users": m.users,
    "chat_bot": m.chat_bot,
    "chat_session": m.chat_session,
    "chat_message": m.chat_message,
    "rag_query": m.rag_query,
    "rag_chunk": m.rag_chunk,
    "billing_item": m.billing_item,
    "input_item": m.input_item,
    "tool_call": m.tool_call,
    "action": m.action,
}
"""Load order: parents before children."""

_SHARD_FACTOR = 1_000_000_000


class IngestError(RuntimeError):
    """A schema, revision or file-identity problem. The message holds no content."""


@dataclass(frozen=True)
class SourceFile:
    logical_table: str
    relative_path: str
    path: Path
    sha256: str
    bytes: int
    parquet_rows: int
    columns: tuple[tuple[str, str], ...]
    shard_index: int


def json_state(raw: str | None) -> str:
    """``null``, ``empty``, ``malformed`` or ``ok`` for one JSON-text value."""
    if raw is None:
        return "null"
    if not raw.strip():
        return "empty"
    try:
        parsed = json.loads(raw)
    except ValueError:
        return "malformed"
    return "empty" if parsed in ([], {}, None, "") else "ok"


def text_sha256(text: str | None) -> str | None:
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def strip_rag_chunk_text(raw: str) -> str:
    """Replace each chunk's text by its sha256; the text stays in ``src.rag_chunk``."""
    parsed = json.loads(raw)
    for query in parsed or []:
        for chunk in query.get("relevantChunks") or []:
            chunk["content_sha256"] = text_sha256(chunk.pop("content", None))
    return json.dumps(parsed, ensure_ascii=False)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def discover(
    raw_dir: Path, tables: Mapping[str, Mapping[str, Any]]
) -> list[SourceFile]:
    """Fixed order, from the config; every expected file must exist."""
    out: list[SourceFile] = []
    for name in TABLES:
        spec = tables.get(name)
        if spec is None:
            continue
        found = sorted(p for p in raw_dir.glob(spec["pattern"]))
        listed = [f["path"] for f in spec.get("files", [])]
        relative = [p.relative_to(raw_dir).as_posix() for p in found]
        if listed and relative != listed:
            raise IngestError(
                f"{name}: expected {len(listed)} files, found {len(relative)}; "
                "the raw directory does not match the pinned file list"
            )
        if not found:
            raise IngestError(f"{name}: no file matches {spec['pattern']}")
        for shard, path in enumerate(found):
            pf = pq.ParquetFile(path)
            out.append(
                SourceFile(
                    logical_table=name,
                    relative_path=path.relative_to(raw_dir).as_posix(),
                    path=path,
                    sha256=file_sha256(path),
                    bytes=path.stat().st_size,
                    parquet_rows=pf.metadata.num_rows,
                    columns=tuple((c.name, str(c.type)) for c in pf.schema_arrow),
                    shard_index=shard,
                )
            )
    return out


def schema_problems(
    sources: Iterable[SourceFile], tables: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    """Column differences and pinned-hash differences, in plain words."""
    problems = []
    for source in sources:
        spec = tables[source.logical_table]
        expected = [tuple(c) for c in spec["columns"]]
        actual = list(source.columns)
        missing = [c[0] for c in expected if c not in actual]
        unknown = [c[0] for c in actual if c not in expected]
        if missing:
            problems.append(f"{source.relative_path}: missing columns {missing}")
        if unknown:
            problems.append(f"{source.relative_path}: unknown columns {unknown}")
    return problems


def hash_problems(
    sources: Iterable[SourceFile], tables: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    pinned = {
        f["path"]: f["sha256"]
        for spec in tables.values()
        for f in spec.get("files", [])
    }
    return [
        f"{s.relative_path}: sha256 differs from the pinned value"
        for s in sources
        if s.relative_path in pinned and pinned[s.relative_path] != s.sha256
    ]


def _stg_row(table: Table, source: SourceFile, row: dict, index: int) -> dict:
    """One Parquet row → column values for ``table``."""
    out: dict[str, Any] = {}
    mapped: set[str] = set()
    for column in table.columns:
        name = column.info.get("source")
        if name is None:
            continue
        mapped.add(name)
        value = row.get(name)
        state_col = f"{column.name}_state"
        if state_col in table.columns:
            state = json_state(value)
            out[state_col] = state
            if state in ("null", "malformed") or not (value or "").strip():
                value = None
            elif column.name == "rag" and table.name == "chat_message":
                value = strip_rag_chunk_text(value)
        out[column.name] = value
    if table.name == "chat_message":
        out["source_ordinal"] = source.shard_index * _SHARD_FACTOR + index
    elif table.name == "chat_bot":
        out["instructions_sha256"] = text_sha256(row.get("instructions"))
    elif table.name == "rag_chunk":
        out["content_sha256"] = text_sha256(row.get("content"))
    elif table.name == "tool_call":
        out["row_data"] = json.dumps(
            {k: v for k, v in row.items() if k not in mapped and v is not None},
            ensure_ascii=False,
            sort_keys=True,
        )
    return out


def iter_rows(path: Path, batch_rows: int, limit: int | None) -> Iterator[list[dict]]:
    pf = pq.ParquetFile(path)
    seen = 0
    for batch in pf.iter_batches(batch_size=batch_rows):
        rows = batch.to_pylist()
        if limit is not None:
            rows = rows[: max(0, limit - seen)]
        seen += len(rows)
        if rows:
            yield rows
        if limit is not None and seen >= limit:
            return


def load_file(
    engine: Engine,
    source: SourceFile,
    run_id: int,
    *,
    batch_rows: int,
    limit_rows: int | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, int]:
    """Load one file in one transaction; a loaded file is a no-op."""
    table = TABLES[source.logical_table]
    target_cols = [c.name for c in table.columns]
    qualified = f'{table.schema}."{table.name}"'
    raw = engine.raw_connection()
    try:
        conn = raw.driver_connection
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_file_id, status FROM meta.source_file "
                "WHERE relative_path=%s AND sha256=%s",
                (source.relative_path, source.sha256),
            )
            existing = cur.fetchone()
            if existing and existing[1] == "loaded":
                log(f"  skip {source.relative_path}: already loaded, 0 rows inserted")
                raw.rollback()
                return {"inserted": 0, "seen": 0, "skipped_file": 1}
            schema_json = json.dumps(list(source.columns))
            cur.execute(
                "INSERT INTO meta.source_file (run_id, logical_table, relative_path,"
                " sha256, bytes, parquet_rows, loaded_rows, schema_json, status) "
                "VALUES (%s,%s,%s,%s,%s,%s,0,%s,'loading') RETURNING source_file_id",
                (
                    run_id,
                    source.logical_table,
                    source.relative_path,
                    source.sha256,
                    source.bytes,
                    source.parquet_rows,
                    schema_json,
                ),
            )
            file_id = cur.fetchone()[0]
            cur.execute(
                f'CREATE TEMP TABLE "_stg" (LIKE {qualified} INCLUDING DEFAULTS) '
                "ON COMMIT DROP"
            )
            quoted = ", ".join(f'"{c}"' for c in target_cols)
            seen = 0
            with cur.copy(f'COPY "_stg" ({quoted}) FROM STDIN') as copy:
                for rows in iter_rows(source.path, batch_rows, limit_rows):
                    for row in rows:
                        values = _stg_row(table, source, row, seen)
                        values["_source_file_id"] = file_id
                        values["_source_row"] = seen
                        copy.write_row([values.get(c) for c in target_cols])
                        seen += 1
            cur.execute(
                f'INSERT INTO {qualified} ({quoted}) SELECT {quoted} FROM "_stg" '
                "ON CONFLICT DO NOTHING"
            )
            inserted = cur.rowcount
            status = "loaded" if limit_rows is None else "loaded_partial"
            cur.execute(
                "UPDATE meta.source_file SET loaded_rows=%s, status=%s "
                "WHERE source_file_id=%s",
                (inserted, status, file_id),
            )
        raw.commit()
    except BaseException:
        raw.rollback()
        raise
    finally:
        raw.close()
    log(f"  {source.relative_path}: {inserted}/{seen} rows inserted")
    return {"inserted": inserted, "seen": seen, "skipped_file": 0}


def changed_files(engine: Engine, sources: Iterable[SourceFile]) -> list[str]:
    """Files already loaded under the same path with a different sha256."""
    sf = m.source_file
    with engine.connect() as conn:
        loaded = {
            (r.relative_path, r.sha256)
            for r in conn.execute(select(sf.c.relative_path, sf.c.sha256))
        }
    paths = {p for p, _ in loaded}
    return [
        s.relative_path
        for s in sources
        if s.relative_path in paths and (s.relative_path, s.sha256) not in loaded
    ]
