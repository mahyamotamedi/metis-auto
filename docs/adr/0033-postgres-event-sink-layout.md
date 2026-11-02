# ADR-0033: Postgres event sink layout: Alembic revision, `data_access/postgres` connection, dependency-free sink class

- Status: **decided** (layout) for the sprint's services track, 2026-11-02 (Pipeline B, task T-3). `exp.lever_results` is **provisional** until the shared `LeverResult` lands. The live check against a server was **not run** (no local server on the author's machine).
- Date: 2026-11-02
- Relates to: [ADR-0009](0009-repository-structure-and-dependency-rules.md), [ADR-0012](0012-event-stream-as-measurement-record.md), [ADR-0019](0019-configuration-format-layers-and-secrets.md), [ADR-0022](0022-experiment-runner-and-run-tracking.md), [ADR-0027](0027-local-postgresql-foundation.md); sprint plan T-3 ([`2026-11-01-final-plan.md`](../2026-11-01-final-plan.md)); FR-OBS-06, FR-OBS-02, QA-PRIV, QA-REPL, NG-02.

## Context
The sprint plan's T-3 asks for `PostgresEventSink(connect)` in `adapters/sinks/postgres.py`, a `migrations/0001_events.sql` file with tables `events` and `lever_results`, a switch `events.sink = "jsonl" | "postgres"`, and a test that "psycopg is imported only in the sink". `main` already has a PostgreSQL foundation (ADR-0027) that conflicts with that layout. Migrations are Alembic revisions in `infra/db/versions/` (latest `0006`). `models.py` must match them (`alembic check`). Database libraries may be imported only inside `src/metis_auto/data_access/postgres/` (`tests/architecture/test_db_imports.py`). And `adapters` may import only `ports` and `contracts` (`tests/architecture/test_import_rules.py`).

## Decision
1. **Schema as the next Alembic revision**, `infra/db/versions/0007_events.py` (revises `0006`), in the existing `exp` schema, in the style of `0006` (every column carries `comment="privacy=<class>"`). `data_access/postgres/models.py` gets the same two tables, so the drift check still holds. There is no SQL file outside Alembic.
   - `exp.events` holds the `Event` envelope fields with the contract's privacy classes. `versions` and `payload` are JSONB. It adds one more column, `seq`, a database row ordinal (not an event ID). `(run_id, event_id)` is unique. No column holds content.
   - `exp.lever_results` (provisional) holds the content-free `LeverResult` fields known from the plan. The manifest fields are flattened, and money stays JSON decimal strings. The key is `(lever_id, baseline, config_hash)`.
2. **The sink class imports no database library.** `PostgresEventSink(connect)` takes a factory for a DB-API-style connection (`execute(sql, params)`, `commit`, `rollback`, `close`) and holds the one parameterised `INSERT` (psycopg `pyformat` placeholders, explicit casts). Tests use a fake connection.
3. **Connection code lives in `data_access/postgres/event_store.py`.** `event_connection_factory(host, port, name, user)` returns the `connect` callable. psycopg is imported lazily, at connect time. The password comes **only** from `METIS_DB_PASSWORD` in the process environment: it is not a parameter, not configuration (the settings loader already refuses secret-looking keys), and **not `.env`**. That is stricter than ADR-0027's ingestion path, which may read `.env`.
4. **Transactions.** The connection opens when the sink is built, so an unreachable server fails before the run starts. Each `emit` is one INSERT and one COMMIT: a row is durable when `emit` returns, and rows are in emit order. On a failure the transaction is rolled back, earlier events stay committed, and `EventSinkError` is raised, which fails an offline run (observability §6). The message names only the exception class (no DSN, no password, no driver text), and the driver exception is not chained. `close` is idempotent.
5. **Switch `[events] sink = "jsonl" | "postgres"`** (`settings.EventSettings`, default `jsonl`; `wiring.from_settings.event_sink`, used by `wiring.experiments`):
   - `jsonl` is the unchanged JSON Lines sink.
   - `postgres` means the same JSON Lines file **plus** `exp.events`, through `adapters/sinks/fanout.py`. The file stays the run's measurement record (ADR-0022). Postgres is a queryable copy.
   - The section is excluded from the config hash (the sink does not change a result), and experiment files may not set it (the machine decides, like `paths`).

## Alternatives considered
- **The plan's layout** (`migrations/0001_events.sql`, psycopg in the sink): a second migration system beside Alembic, and a database import outside `data_access/postgres`. It breaks `test_db_imports.py` and the adapters' import rule. Rejected.
- **The sink builds its own engine with SQLAlchemy**: needs a database import in `adapters`. Rejected for the same reason.
- **`postgres` replaces the JSON Lines file**: the run folder would lose its single record (ADR-0022), and a failed database would lose the run. Rejected. The fan-out keeps both.
- **Commit once at `close`**: faster, but a crash loses every event of the run. Rejected. Offline runs are small, and per-event commits are acceptable.
- **A new `services` extra for psycopg** (plan T-0): the existing `db` extra already pins `psycopg[binary]` (`requirements-db.lock`). The overlap is left to the T-0 owner (see below).

## Consequences
- Guarding tests: `tests/unit/adapters/test_postgres_sink.py` covers order, idempotent close, failure, the schema having no content columns, the models matching the revision, the password coming only from the environment, the default being unchanged, the switch, the hash and the fan-out. `tests/architecture/test_db_imports.py` and `tests/architecture/test_import_rules.py` are unchanged and green. The opt-in live test is `tests/integration/test_postgres_sink_live.py` (`--run-postgres`, marker `postgres`). It checks that rows read back equal the JSON Lines records. **Not run yet.**
- The plan's `test_psycopg_imported_only_in_postgres_sink` (T-0) contradicts this layout. The rule that holds is `test_db_imports.py` (database libraries only in `data_access/postgres`).
- The plan's `services` marker does not exist. The existing `postgres` marker and `--run-postgres` option are used. Adding a `services` marker is the T-0 owner's change (`pyproject.toml`).
- The demo chat (`wiring.chat`) still uses its in-memory sink. Sending its events to Postgres (plan T-3, "done when") needs a running server and a chat wiring change. Not done.
- Writing `exp.lever_results` rows (a loader for `reports/levers/*.json`) is not part of Day 1.
