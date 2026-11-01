# ADR-0027: A local PostgreSQL foundation for the source data and evaluation datasets

- Status: **decided** for the structure, by the owner's task of 2026-11-01. Column sets are **provisional**: they follow the current export.
- Date: 2026-11-01
- Relates to: NG-02, FR-DATA-04, FR-DATA-05, ADR-0003, ADR-0009, ADR-0017, ADR-0019, ADR-0022, ADR-0028; [deployment_and_data.md §4](../architecture/deployment_and_data.md)

## Context
NG-02 and FR-DATA-05 ruled out a persistent schema until the full dataset was inspected. The full EDA is done, and the evaluation work needs joins that files make awkward: one trustworthy request table, leakage-safe views, append-only labels. **Nothing in the repository documents what database Metis runs in production.** PostgreSQL is our engineering choice, not a claim about Metis.

The data licence (`data/full_data/raw/LICENSE.txt`) is educational and non-commercial and forbids redistribution. There is no shared server: each teammate rebuilds locally.

## Decision
1. **NG-02 and FR-DATA-05 are lifted for local storage only.** This is not a production schema, and no serving code reads it.
2. **One local PostgreSQL 17** under Docker Compose (profile `db`), bound to `127.0.0.1`, refusing to start without `METIS_DB_PASSWORD`. Compose interpolates every service, so `:?` would break the `app` service; the postgres entrypoint does the refusing instead.
3. **Four schemas:** `meta` (runs, files, reconciliation), `src` (faithful copy plus provenance), `eval` (requests, datasets, labels), `exp` (empty, for routing experiments; run files stay the record, ADR-0022).
4. **SQLAlchemy Core tables plus Alembic migrations** in `infra/db`, one revision per step, no `create_all`. `alembic check` proves no drift. Privacy classes are column comments.
5. **Libraries** (`sqlalchemy`, `alembic`, `psycopg`, `pyarrow`, extra `db`, `requirements-db.lock`) are imported only in `data_access/postgres` and the Alembic `env.py`; `wiring` may name `sqlalchemy` for engines and `text` only (`tests/architecture/test_db_imports.py`).
6. **Ingestion** streams Parquet through COPY into a temporary table, then `INSERT … ON CONFLICT DO NOTHING`, one transaction per file. It refuses another dataset revision, unknown or missing columns, or a changed file unless an explicit, logged flag is given. Text is never normalised.

## Facts found while building (verified 2026-11-01 on revision `30f578f`)
- All footer row counts match the dataset card and the EDA.
- **257 bots have an owner that is not in `users`.** So `chat_bot.user_id` has no foreign key; the count is pinned in `config/evaluation/source_v1.toml` and any change fails reconciliation. Sessions are unaffected: every session's user exists and equals its bot's owner.
- No NUL characters and no malformed JSON in any text or JSON column.
- `derived/chat_message_rag_chunks` reproduces the chunks in `chat_message.rag` exactly: 63,415 of 63,415 messages have an identical multiset of (chunk id, text).

## Chunk text is stored once
Because of that last fact, `chat_message.rag` keeps queries, ids, corpus ids and relevancy, and replaces each chunk's text by its sha256; the text lives only in `src.rag_chunk`. The reconciliation check `rag_chunks_match_message_json` re-proves on every load that the two sides agree (0 differences on the real data).

## Alternatives considered
- **Files only.** No constraints, and every consumer re-implements pairing. Rejected.
- **DuckDB or SQLite.** Simpler, but the team asked for PostgreSQL, and triggers and concurrent review tooling are weaker. Rejected.
- **A shared server or a passed-around dump.** Rejected by the team and by the licence's spirit: only code, config, IDs and labels move through git.
- **Declarative ORM classes.** No object behaviour is needed; Core tables are shorter. Rejected.
- **Storing chunk text twice.** Costs storage for no gain once equality is proven. Rejected.

## Consequences
- Measured on one Mac (2026-11-01): first load 285 to 294 s, peak client memory 690 MB, database 1.98 GB before the evaluation tables and 2.6 GB after. Re-running inserts 0 rows in 10 s.
- FR-DATA-04 holds: a later change of database touches `data_access/postgres`, `infra/db`, and configuration.
- Open: what Metis runs in production; whether derived tables may leave the licensee (`docs/full_eda/metis_questions.md`, question 5).
