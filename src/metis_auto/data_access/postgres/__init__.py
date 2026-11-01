"""PostgreSQL storage for the source tables and the evaluation dataset (ADR-0027).

The only package that imports ``sqlalchemy``, ``psycopg``, ``alembic`` or ``pyarrow``
(extra ``db``; tested by ``tests/architecture/test_db_imports.py``). Imports only
``contracts``. Nothing here decides anything about sampling or labels: pure logic
lives in ``evaluation.golden`` and ``analysis``; ``wiring.golden`` joins them.
"""
