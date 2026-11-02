"""exp.events and exp.lever_results: content-free event rows and lever results

exp.events mirrors the Event envelope (contracts/events.py) with its privacy
classes, plus ``seq`` (a row ordinal, not an event ID); written by
adapters/sinks/postgres.py (T-3, ADR-0033). exp.lever_results is PROVISIONAL:
the content-free LeverResult fields known from the sprint plan, until the shared
LeverResult (analysis/lever_result.py) lands; money stays JSON decimal strings.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column(
            "seq",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "schema_version", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column("event_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column(
            "event_type", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column("run_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column("run_mode", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column("request_id", sa.Text(), nullable=True, comment="privacy=reference"),
        sa.Column("session_ref", sa.Text(), nullable=True, comment="privacy=reference"),
        sa.Column("case_id", sa.Text(), nullable=True, comment="privacy=reference"),
        sa.Column("attempt_id", sa.Text(), nullable=True, comment="privacy=reference"),
        sa.Column(
            "parent_attempt_id",
            sa.Text(),
            nullable=True,
            comment="privacy=reference",
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "logged_timestamp",
            sa.DateTime(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column("span", sa.Text(), nullable=True, comment="privacy=operational"),
        sa.Column(
            "duration_ms", sa.Double(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "versions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="privacy=derived",
        ),
        sa.CheckConstraint(
            "run_mode IN ('replayed','simulated','live')",
            name=op.f("ck_events_run_mode"),
        ),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_events")),
        sa.UniqueConstraint("run_id", "event_id", name="uq_events_run"),
        schema="exp",
    )
    op.create_table(
        "lever_results",
        sa.Column("lever_id", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column("step", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column("version", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column("baseline", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column(
            "n_requests", sa.BigInteger(), nullable=False, comment="privacy=derived"
        ),
        sa.Column(
            "n_eligible", sa.BigInteger(), nullable=False, comment="privacy=derived"
        ),
        sa.Column(
            "baseline_cost",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "saving",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column("ci_low", sa.Double(), nullable=True, comment="privacy=derived"),
        sa.Column("ci_high", sa.Double(), nullable=True, comment="privacy=derived"),
        sa.Column(
            "slices",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "evidence_class", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "correctness_state",
            sa.Text(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "assumptions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "overhead_ms_p50", sa.Double(), nullable=True, comment="privacy=derived"
        ),
        sa.Column(
            "overhead_ms_p95", sa.Double(), nullable=True, comment="privacy=derived"
        ),
        sa.Column(
            "data_revision", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "code_commit", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "config_hash", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "seed", sa.BigInteger(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "price_version", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "python_version", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.CheckConstraint(
            "step IN ('cache','context','routing')",
            name=op.f("ck_lever_results_step"),
        ),
        sa.CheckConstraint(
            "correctness_state ~ '^(unmeasured|measured|sampled:[0-9]+)$'",
            name=op.f("ck_lever_results_correctness_state"),
        ),
        sa.PrimaryKeyConstraint(
            "lever_id", "baseline", "config_hash", name=op.f("pk_lever_results")
        ),
        schema="exp",
    )


def downgrade() -> None:
    op.drop_table("lever_results", schema="exp")
    op.drop_table("events", schema="exp")
