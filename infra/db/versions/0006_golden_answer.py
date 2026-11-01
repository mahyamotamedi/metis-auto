"""eval.golden_answer: reference answers of a strong model for a dataset's records

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "golden_answer",
        sa.Column("run_id", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column("record_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column("model_id", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column("effort", sa.Text(), nullable=True, comment="privacy=operational"),
        sa.Column(
            "max_output_tokens",
            sa.Integer(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "settings_hash", sa.Text(), nullable=False, comment="privacy=fingerprint"
        ),
        sa.Column(
            "prompt_fingerprint",
            sa.Text(),
            nullable=False,
            comment="privacy=fingerprint",
        ),
        sa.Column("status", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column("answer", sa.Text(), nullable=True, comment="privacy=content"),
        sa.Column(
            "answer_chars", sa.Integer(), nullable=True, comment="privacy=derived"
        ),
        sa.Column(
            "answer_language_group",
            sa.Text(),
            nullable=True,
            comment="privacy=derived",
        ),
        sa.Column(
            "finish_reason", sa.Text(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "error_class", sa.Text(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            server_default="1",
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "provider_model_version",
            sa.Text(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "input_tokens", sa.Integer(), nullable=True, comment="privacy=derived"
        ),
        sa.Column(
            "cached_input_tokens",
            sa.Integer(),
            nullable=True,
            comment="privacy=derived",
        ),
        sa.Column(
            "output_tokens", sa.Integer(), nullable=True, comment="privacy=derived"
        ),
        sa.Column(
            "reasoning_tokens", sa.Integer(), nullable=True, comment="privacy=derived"
        ),
        sa.Column(
            "cost_usd", sa.Numeric(14, 8), nullable=True, comment="privacy=derived"
        ),
        sa.Column(
            "cost_state", sa.Text(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "latency_ms", sa.Double(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "caveats",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.CheckConstraint(
            "status IN ('answered','failed','skipped')",
            name=op.f("ck_golden_answer_status"),
        ),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["eval.dataset_record.record_id"],
            name=op.f("fk_golden_answer_record_id_dataset_record"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", "record_id", name=op.f("pk_golden_answer")),
        schema="eval",
    )


def downgrade() -> None:
    op.drop_table("golden_answer", schema="eval")
