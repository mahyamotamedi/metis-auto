"""meta schema: ingest runs and source files

Revision ID: 0001
Revises: None
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS meta")
    op.create_table(
        "ingest_run",
        sa.Column(
            "run_id",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column("git_sha", sa.Text(), nullable=True, comment="privacy=operational"),
        sa.Column(
            "dataset_repo", sa.Text(), nullable=False, comment="privacy=reference"
        ),
        sa.Column(
            "dataset_revision", sa.Text(), nullable=False, comment="privacy=reference"
        ),
        sa.Column(
            "tool_versions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column("status", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.CheckConstraint(
            "status IN ('running','ok','failed')", name=op.f("ck_ingest_run_status")
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_ingest_run")),
        schema="meta",
    )
    op.create_table(
        "reconciliation",
        sa.Column(
            "run_id", sa.BigInteger(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "check_name", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column("expected", sa.Text(), nullable=True, comment="privacy=operational"),
        sa.Column("actual", sa.Text(), nullable=True, comment="privacy=operational"),
        sa.Column("ok", sa.Boolean(), nullable=False, comment="privacy=operational"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["meta.ingest_run.run_id"],
            name=op.f("fk_reconciliation_run_id_ingest_run"),
        ),
        sa.PrimaryKeyConstraint("run_id", "check_name", name=op.f("pk_reconciliation")),
        schema="meta",
    )
    op.create_table(
        "source_file",
        sa.Column(
            "source_file_id",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "run_id", sa.BigInteger(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "logical_table", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "relative_path", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column("sha256", sa.Text(), nullable=False, comment="privacy=fingerprint"),
        sa.Column(
            "bytes", sa.BigInteger(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "parquet_rows",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "loaded_rows",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "schema_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column("status", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["meta.ingest_run.run_id"],
            name=op.f("fk_source_file_run_id_ingest_run"),
        ),
        sa.PrimaryKeyConstraint("source_file_id", name=op.f("pk_source_file")),
        sa.UniqueConstraint("relative_path", "sha256", name="uq_source_file_path_sha"),
        schema="meta",
    )


def downgrade() -> None:
    op.drop_table("source_file", schema="meta")
    op.drop_table("reconciliation", schema="meta")
    op.drop_table("ingest_run", schema="meta")
