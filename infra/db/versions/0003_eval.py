"""eval schema: requests, datasets, annotations

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS eval")
    op.create_table(
        "dataset",
        sa.Column(
            "dataset_id", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column("name", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column("version", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column("status", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column(
            "config_sha256", sa.Text(), nullable=False, comment="privacy=fingerprint"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.CheckConstraint(
            "status IN ('draft','annotated_provisional','validated','frozen')",
            name=op.f("ck_dataset_status"),
        ),
        sa.PrimaryKeyConstraint("dataset_id", name=op.f("pk_dataset")),
        schema="eval",
    )
    op.create_table(
        "rubric",
        sa.Column(
            "rubric_version", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column("document", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column(
            "config_sha256", sa.Text(), nullable=False, comment="privacy=fingerprint"
        ),
        sa.PrimaryKeyConstraint("rubric_version", name=op.f("pk_rubric")),
        schema="eval",
    )
    op.create_table(
        "rubric_value",
        sa.Column(
            "rubric_version", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "dimension", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column("value", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column(
            "definition_ref", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.ForeignKeyConstraint(
            ["rubric_version"],
            ["eval.rubric.rubric_version"],
            name=op.f("fk_rubric_value_rubric_version_rubric"),
        ),
        sa.PrimaryKeyConstraint(
            "rubric_version", "dimension", "value", name=op.f("pk_rubric_value")
        ),
        schema="eval",
    )
    op.create_table(
        "sampling_run",
        sa.Column(
            "sampling_run_id",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "dataset_id", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "seed", sa.BigInteger(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "code_git_sha", sa.Text(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "population_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column("status", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["eval.dataset.dataset_id"],
            name=op.f("fk_sampling_run_dataset_id_dataset"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("sampling_run_id", name=op.f("pk_sampling_run")),
        schema="eval",
    )
    op.create_table(
        "stratum_population",
        sa.Column(
            "sampling_run_id",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column("margin", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column("key", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column(
            "population_n",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column("quota", sa.Integer(), nullable=False, comment="privacy=operational"),
        sa.Column(
            "achieved", sa.Integer(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "shortfall", sa.Integer(), nullable=False, comment="privacy=operational"
        ),
        sa.Column("basis", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column(
            "redistribution_note",
            sa.Text(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.ForeignKeyConstraint(
            ["sampling_run_id"],
            ["eval.sampling_run.sampling_run_id"],
            name=op.f("fk_stratum_population_sampling_run_id_sampling_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "sampling_run_id", "margin", "key", name=op.f("pk_stratum_population")
        ),
        schema="eval",
    )
    op.create_table(
        "request",
        sa.Column("request_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column("session_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column("bot_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column("owner_cohort", sa.Text(), nullable=False, comment="privacy=derived"),
        sa.Column(
            "turn_index", sa.Integer(), nullable=False, comment="privacy=derived"
        ),
        sa.Column(
            "answer_message_id", sa.Text(), nullable=True, comment="privacy=reference"
        ),
        sa.Column("pair_flag", sa.Text(), nullable=False, comment="privacy=derived"),
        sa.Column("eligible", sa.Boolean(), nullable=False, comment="privacy=derived"),
        sa.Column(
            "exclusion_reason", sa.Text(), nullable=True, comment="privacy=derived"
        ),
        sa.Column(
            "language_label", sa.Text(), nullable=False, comment="privacy=derived"
        ),
        sa.Column(
            "language_group", sa.Text(), nullable=False, comment="privacy=derived"
        ),
        sa.Column(
            "language_method", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "target_chars", sa.Integer(), nullable=False, comment="privacy=derived"
        ),
        sa.Column(
            "target_words", sa.Integer(), nullable=False, comment="privacy=derived"
        ),
        sa.Column(
            "n_prior_messages", sa.Integer(), nullable=False, comment="privacy=derived"
        ),
        sa.Column(
            "history_chars", sa.BigInteger(), nullable=False, comment="privacy=derived"
        ),
        sa.Column(
            "instruction_chars",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=derived",
        ),
        sa.Column(
            "rag_chunk_chars",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=derived",
        ),
        sa.Column("bot_class", sa.Text(), nullable=False, comment="privacy=derived"),
        sa.Column(
            "instruction_evidence", sa.Text(), nullable=False, comment="privacy=derived"
        ),
        sa.Column("rag_config", sa.Text(), nullable=False, comment="privacy=derived"),
        sa.Column(
            "config_unknown", sa.Boolean(), nullable=False, comment="privacy=derived"
        ),
        sa.Column(
            "attachment_count", sa.Integer(), nullable=False, comment="privacy=derived"
        ),
        sa.Column(
            "attachment_types",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="privacy=derived",
        ),
        sa.Column(
            "after_widget", sa.Boolean(), nullable=False, comment="privacy=derived"
        ),
        sa.Column(
            "answer_finish_reason",
            sa.Text(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "rag_observed_on_answer",
            sa.Boolean(),
            nullable=False,
            comment="privacy=derived",
        ),
        sa.Column("rule_intent", sa.Text(), nullable=False, comment="privacy=derived"),
        sa.Column(
            "rule_tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="privacy=derived",
        ),
        sa.Column(
            "complexity_proxy", sa.Text(), nullable=False, comment="privacy=derived"
        ),
        sa.Column(
            "exact_family_id", sa.Text(), nullable=True, comment="privacy=fingerprint"
        ),
        sa.Column(
            "near_family_id", sa.Text(), nullable=True, comment="privacy=fingerprint"
        ),
        sa.Column(
            "family_size", sa.Integer(), nullable=True, comment="privacy=derived"
        ),
        sa.Column(
            "timestamp_is_null", sa.Boolean(), nullable=False, comment="privacy=derived"
        ),
        sa.Column(
            "feature_version", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.ForeignKeyConstraint(
            ["answer_message_id"],
            ["src.chat_message.message_id"],
            name=op.f("fk_request_answer_message_id_chat_message"),
        ),
        sa.ForeignKeyConstraint(
            ["bot_id"], ["src.chat_bot.bot_id"], name=op.f("fk_request_bot_id_chat_bot")
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["src.chat_message.message_id"],
            name=op.f("fk_request_request_id_chat_message"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["src.chat_session.session_id"],
            name=op.f("fk_request_session_id_chat_session"),
        ),
        sa.PrimaryKeyConstraint("request_id", name=op.f("pk_request")),
        schema="eval",
    )
    op.create_index(
        "ix_request_eligible_cell",
        "request",
        ["eligible", "rule_intent", "owner_cohort"],
        unique=False,
        schema="eval",
    )
    op.create_index(
        "ix_request_session_id", "request", ["session_id"], unique=False, schema="eval"
    )
    op.create_table(
        "dataset_record",
        sa.Column("record_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column(
            "dataset_id", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column("request_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column("session_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column(
            "stratum",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "population_weight",
            sa.Double(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "weight_basis", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "selection_rank",
            sa.Integer(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "selection_rationale",
            sa.Text(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["eval.dataset.dataset_id"],
            name=op.f("fk_dataset_record_dataset_id_dataset"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["eval.request.request_id"],
            name=op.f("fk_dataset_record_request_id_request"),
        ),
        sa.PrimaryKeyConstraint("record_id", name=op.f("pk_dataset_record")),
        sa.UniqueConstraint(
            "dataset_id", "request_id", name="uq_dataset_record_request"
        ),
        sa.UniqueConstraint(
            "dataset_id", "session_id", name="uq_dataset_record_session"
        ),
        schema="eval",
    )
    op.create_table(
        "dataset_reserve",
        sa.Column(
            "dataset_id", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column("request_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column("session_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column("cell", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column(
            "reserve_rank", sa.Integer(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "stratum",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["eval.dataset.dataset_id"],
            name=op.f("fk_dataset_reserve_dataset_id_dataset"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["eval.request.request_id"],
            name=op.f("fk_dataset_reserve_request_id_request"),
        ),
        sa.PrimaryKeyConstraint(
            "dataset_id", "request_id", name=op.f("pk_dataset_reserve")
        ),
        schema="eval",
    )
    op.create_table(
        "annotation",
        sa.Column(
            "annotation_id",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column("record_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column(
            "dimension", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column("value", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column("method", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column(
            "annotator_pseudonym",
            sa.Text(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "rubric_version", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "confidence", sa.Double(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "review_status", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "rationale_code", sa.Text(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "supersedes_id",
            sa.BigInteger(),
            nullable=True,
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
            "method IN ('rule','human','llm_assisted')",
            name=op.f("ck_annotation_method"),
        ),
        sa.CheckConstraint(
            "review_status IN ('proposed','accepted','rejected')",
            name=op.f("ck_annotation_review_status"),
        ),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["eval.dataset_record.record_id"],
            name=op.f("fk_annotation_record_id_dataset_record"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rubric_version"],
            ["eval.rubric.rubric_version"],
            name=op.f("fk_annotation_rubric_version_rubric"),
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["eval.annotation.annotation_id"],
            name=op.f("fk_annotation_supersedes_id_annotation"),
        ),
        sa.PrimaryKeyConstraint("annotation_id", name=op.f("pk_annotation")),
        schema="eval",
    )
    op.create_index(
        "ix_annotation_record_dimension",
        "annotation",
        ["record_id", "dimension"],
        unique=False,
        schema="eval",
    )
    op.create_table(
        "record_input_component",
        sa.Column("record_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column(
            "position", sa.Integer(), nullable=False, comment="privacy=operational"
        ),
        sa.Column("kind", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column("role", sa.Text(), nullable=True, comment="privacy=operational"),
        sa.Column(
            "source_kind", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "source_message_id", sa.Text(), nullable=True, comment="privacy=reference"
        ),
        sa.Column(
            "source_bot_id", sa.Text(), nullable=True, comment="privacy=reference"
        ),
        sa.Column(
            "source_chunk_file_id",
            sa.BigInteger(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "source_chunk_row",
            sa.BigInteger(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "availability_stage",
            sa.Text(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "included_pre_retrieval",
            sa.Boolean(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "included_post_retrieval",
            sa.Boolean(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "transmitted_to_provider",
            sa.Text(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "content_sha256", sa.Text(), nullable=True, comment="privacy=fingerprint"
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.CheckConstraint(
            "availability_stage IN ('request_arrival','configuration_snapshot','retrieval_order_unknown')",  # noqa: E501
            name=op.f("ck_record_input_component_stage"),
        ),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["eval.dataset_record.record_id"],
            name=op.f("fk_record_input_component_record_id_dataset_record"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_bot_id"],
            ["src.chat_bot.bot_id"],
            name=op.f("fk_record_input_component_source_bot_id_chat_bot"),
        ),
        sa.ForeignKeyConstraint(
            ["source_chunk_file_id", "source_chunk_row"],
            ["src.rag_chunk._source_file_id", "src.rag_chunk._source_row"],
            name="fk_component_rag_chunk",
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"],
            ["src.chat_message.message_id"],
            name=op.f("fk_record_input_component_source_message_id_chat_message"),
        ),
        sa.PrimaryKeyConstraint(
            "record_id", "position", name=op.f("pk_record_input_component")
        ),
        schema="eval",
    )
    op.create_table(
        "record_reference",
        sa.Column("record_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column(
            "answer_message_id", sa.Text(), nullable=False, comment="privacy=reference"
        ),
        sa.Column(
            "reference_provider_label",
            sa.Text(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "reference_model_label",
            sa.Text(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "reference_model_source",
            sa.Text(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "finish_reason", sa.Text(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "billing_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "availability_stage",
            sa.Text(),
            server_default="post_generation",
            nullable=False,
            comment="privacy=operational",
        ),
        sa.ForeignKeyConstraint(
            ["answer_message_id"],
            ["src.chat_message.message_id"],
            name=op.f("fk_record_reference_answer_message_id_chat_message"),
        ),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["eval.dataset_record.record_id"],
            name=op.f("fk_record_reference_record_id_dataset_record"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("record_id", name=op.f("pk_record_reference")),
        schema="eval",
    )


def downgrade() -> None:
    op.drop_table("record_reference", schema="eval")
    op.drop_table("record_input_component", schema="eval")
    op.drop_index(
        "ix_annotation_record_dimension", table_name="annotation", schema="eval"
    )
    op.drop_table("annotation", schema="eval")
    op.drop_table("dataset_reserve", schema="eval")
    op.drop_table("dataset_record", schema="eval")
    op.drop_index("ix_request_session_id", table_name="request", schema="eval")
    op.drop_index("ix_request_eligible_cell", table_name="request", schema="eval")
    op.drop_table("request", schema="eval")
    op.drop_table("stratum_population", schema="eval")
    op.drop_table("sampling_run", schema="eval")
    op.drop_table("rubric_value", schema="eval")
    op.drop_table("rubric", schema="eval")
    op.drop_table("dataset", schema="eval")
    op.execute("DROP SCHEMA IF EXISTS eval CASCADE")
