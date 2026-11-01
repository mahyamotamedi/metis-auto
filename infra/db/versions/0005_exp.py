"""exp schema: empty experiment tables

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS exp")
    op.create_table(
        "experiment",
        sa.Column(
            "experiment_id", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column("area", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column("plan_ref", sa.Text(), nullable=True, comment="privacy=operational"),
        sa.PrimaryKeyConstraint("experiment_id", name=op.f("pk_experiment")),
        schema="exp",
    )
    op.create_table(
        "model",
        sa.Column("model_id", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column("provider", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column(
            "facts_source", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "facts_checked_on", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "price_table_version",
            sa.Text(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.PrimaryKeyConstraint("model_id", name=op.f("pk_model")),
        schema="exp",
    )
    op.create_table(
        "run",
        sa.Column("run_id", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column(
            "experiment_id", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "dataset_id", sa.Text(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "manifest_sha256", sa.Text(), nullable=False, comment="privacy=fingerprint"
        ),
        sa.Column("git_sha", sa.Text(), nullable=True, comment="privacy=operational"),
        sa.Column("mode", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["eval.dataset.dataset_id"],
            name=op.f("fk_run_dataset_id_dataset"),
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["exp.experiment.experiment_id"],
            name=op.f("fk_run_experiment_id_experiment"),
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_run")),
        schema="exp",
    )
    op.create_table(
        "attempt",
        sa.Column(
            "attempt_id",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column("run_id", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column("record_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column(
            "attempt_index", sa.Integer(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "attempt_kind", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column("model_id", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column(
            "input_tokens",
            sa.BigInteger(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "cached_input_tokens",
            sa.BigInteger(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "output_tokens",
            sa.BigInteger(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "reasoning_tokens",
            sa.BigInteger(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column("cost", sa.Text(), nullable=True, comment="privacy=operational"),
        sa.Column(
            "cost_currency", sa.Text(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "price_table_version",
            sa.Text(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "token_count_fidelity",
            sa.Text(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "latency_ms", sa.Double(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "latency_state", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.CheckConstraint(
            "latency_state IN ('measured','unmeasured')",
            name=op.f("ck_attempt_latency_state"),
        ),
        sa.ForeignKeyConstraint(
            ["model_id"], ["exp.model.model_id"], name=op.f("fk_attempt_model_id_model")
        ),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["eval.dataset_record.record_id"],
            name=op.f("fk_attempt_record_id_dataset_record"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["exp.run.run_id"], name=op.f("fk_attempt_run_id_run")
        ),
        sa.PrimaryKeyConstraint("attempt_id", name=op.f("pk_attempt")),
        sa.UniqueConstraint(
            "run_id", "record_id", "attempt_index", name="uq_attempt_run"
        ),
        schema="exp",
    )
    op.create_table(
        "judgement",
        sa.Column(
            "judgement_id",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column("run_id", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column("record_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column(
            "agreement_with_as_logged",
            sa.Double(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "judge_score", sa.Double(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "non_inferior", sa.Boolean(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "judge_identity", sa.Text(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "judge_version", sa.Text(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "human_agreement", sa.Double(), nullable=True, comment="privacy=operational"
        ),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["eval.dataset_record.record_id"],
            name=op.f("fk_judgement_record_id_dataset_record"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["exp.run.run_id"], name=op.f("fk_judgement_run_id_run")
        ),
        sa.PrimaryKeyConstraint("judgement_id", name=op.f("pk_judgement")),
        schema="exp",
    )
    op.create_table(
        "result",
        sa.Column("run_id", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column("record_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column(
            "outcome_state", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "counterfactual_source",
            sa.Text(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["eval.dataset_record.record_id"],
            name=op.f("fk_result_record_id_dataset_record"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["exp.run.run_id"], name=op.f("fk_result_run_id_run")
        ),
        sa.PrimaryKeyConstraint("run_id", "record_id", name=op.f("pk_result")),
        schema="exp",
    )


def downgrade() -> None:
    op.drop_table("result", schema="exp")
    op.drop_table("judgement", schema="exp")
    op.drop_table("attempt", schema="exp")
    op.drop_table("run", schema="exp")
    op.drop_table("model", schema="exp")
    op.drop_table("experiment", schema="exp")
    op.execute("DROP SCHEMA IF EXISTS exp CASCADE")
