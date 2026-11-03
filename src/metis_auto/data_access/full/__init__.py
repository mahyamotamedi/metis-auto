"""The full dataset (``poriniki/metis``) read from Parquet without a database.

Planned home of the full-dataset loader (overview §3.3). R2 of the decision
router (ADR-0047) adds what the routing dev slice needs:
source pins and checks, column-projected one-file-at-a-time reads, and the local record
file. pyarrow is allowed here and in ``data_access/postgres`` only
(``tests/architecture/test_db_imports.py``; reason in
ADR-0047 point 10).
"""
