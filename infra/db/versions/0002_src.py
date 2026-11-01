"""src schema: faithful source tables

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS src")
    op.create_table(
        "chat_bot",
        sa.Column("bot_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column(
            "created_at", sa.DateTime(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "deleted_at", sa.DateTime(), nullable=True, comment="privacy=operational"
        ),
        sa.Column("user_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column("instructions", sa.Text(), nullable=True, comment="privacy=content"),
        sa.Column(
            "instructions_sha256",
            sa.Text(),
            nullable=True,
            comment="privacy=fingerprint",
        ),
        sa.Column(
            "provider_args",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="privacy=content",
        ),
        sa.Column(
            "provider_args_state",
            sa.Text(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "corpus_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="privacy=content",
        ),
        sa.Column(
            "corpus_ids_state", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "summarizer_provider_name",
            sa.Text(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "summarizer_provider_model",
            sa.Text(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "summarizer_provider_args",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="privacy=content",
        ),
        sa.Column(
            "summarizer_provider_args_state",
            sa.Text(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "functions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="privacy=content",
        ),
        sa.Column(
            "functions_state", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column("description", sa.Text(), nullable=True, comment="privacy=content"),
        sa.Column(
            "enabled", sa.Boolean(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "provider_name", sa.Text(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "provider_model", sa.Text(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "auto_generate_headline",
            sa.Boolean(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column("public", sa.Boolean(), nullable=True, comment="privacy=operational"),
        sa.Column(
            "memory_enabled", sa.Boolean(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "google_search_enabled",
            sa.Boolean(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column("async_webhook", sa.Text(), nullable=True, comment="privacy=content"),
        sa.Column("bot_type", sa.Text(), nullable=True, comment="privacy=operational"),
        sa.Column(
            "rag_top_k", sa.BigInteger(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "rag_reranking", sa.Text(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "independent_function_call",
            sa.Boolean(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "summarizer_mode", sa.Text(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "rag_source_urls_enabled",
            sa.Boolean(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "_source_file_id",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "_source_row",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.CheckConstraint(
            "corpus_ids_state IN ('null','empty','malformed','ok')",
            name=op.f("ck_chat_bot_corpus_ids_state"),
        ),
        sa.CheckConstraint(
            "functions_state IN ('null','empty','malformed','ok')",
            name=op.f("ck_chat_bot_functions_state"),
        ),
        sa.CheckConstraint(
            "provider_args_state IN ('null','empty','malformed','ok')",
            name=op.f("ck_chat_bot_provider_args_state"),
        ),
        sa.CheckConstraint(
            "summarizer_provider_args_state IN ('null','empty','malformed','ok')",
            name=op.f("ck_chat_bot_summarizer_provider_args_state"),
        ),
        sa.ForeignKeyConstraint(
            ["_source_file_id"],
            ["meta.source_file.source_file_id"],
            name=op.f("fk_chat_bot__source_file_id_source_file"),
        ),
        sa.PrimaryKeyConstraint("bot_id", name=op.f("pk_chat_bot")),
        schema="src",
    )
    op.create_table(
        "users",
        sa.Column("user_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column(
            "activated", sa.Boolean(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "owner_user_id", sa.Text(), nullable=True, comment="privacy=reference"
        ),
        sa.Column("username_anon", sa.Text(), nullable=True, comment="privacy=content"),
        sa.Column(
            "_source_file_id",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "_source_row",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.ForeignKeyConstraint(
            ["_source_file_id"],
            ["meta.source_file.source_file_id"],
            name=op.f("fk_users__source_file_id_source_file"),
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_users")),
        schema="src",
    )
    op.create_table(
        "chat_session",
        sa.Column("session_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column("user_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column(
            "created_at", sa.DateTime(), nullable=True, comment="privacy=operational"
        ),
        sa.Column("bot_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column(
            "last_update_date",
            sa.DateTime(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "dialogue_length",
            sa.BigInteger(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column("headline", sa.Text(), nullable=True, comment="privacy=content"),
        sa.Column(
            "_source_file_id",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "_source_row",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.ForeignKeyConstraint(
            ["_source_file_id"],
            ["meta.source_file.source_file_id"],
            name=op.f("fk_chat_session__source_file_id_source_file"),
        ),
        sa.ForeignKeyConstraint(
            ["bot_id"],
            ["src.chat_bot.bot_id"],
            name=op.f("fk_chat_session_bot_id_chat_bot"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["src.users.user_id"],
            name=op.f("fk_chat_session_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_chat_session")),
        schema="src",
    )
    op.create_index(
        "ix_chat_session_bot_id", "chat_session", ["bot_id"], unique=False, schema="src"
    )
    op.create_index(
        "ix_chat_session_created_at",
        "chat_session",
        ["created_at"],
        unique=False,
        schema="src",
    )
    op.create_index(
        "ix_chat_session_user_id",
        "chat_session",
        ["user_id"],
        unique=False,
        schema="src",
    )
    op.create_table(
        "chat_message",
        sa.Column("message_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column("session_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column("type", sa.Text(), nullable=False, comment="privacy=operational"),
        sa.Column(
            "timestamp", sa.DateTime(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "source_ordinal",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column("content", sa.Text(), nullable=True, comment="privacy=content"),
        sa.Column(
            "finish_reason", sa.Text(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "attachments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="privacy=content",
        ),
        sa.Column(
            "attachments_state",
            sa.Text(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "citations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="privacy=content",
        ),
        sa.Column(
            "citations_state", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "tool_calls",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="privacy=content",
        ),
        sa.Column(
            "tool_calls_state", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "rag",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="privacy=content",
        ),
        sa.Column(
            "rag_state", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "billing",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="privacy=content",
        ),
        sa.Column(
            "billing_state", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "input",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="privacy=content",
        ),
        sa.Column(
            "input_state", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "actions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="privacy=content",
        ),
        sa.Column(
            "actions_state", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "google_search_query", sa.Text(), nullable=True, comment="privacy=content"
        ),
        sa.Column(
            "_source_file_id",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "_source_row",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.CheckConstraint(
            "actions_state IN ('null','empty','malformed','ok')",
            name=op.f("ck_chat_message_actions_state"),
        ),
        sa.CheckConstraint(
            "attachments_state IN ('null','empty','malformed','ok')",
            name=op.f("ck_chat_message_attachments_state"),
        ),
        sa.CheckConstraint(
            "billing_state IN ('null','empty','malformed','ok')",
            name=op.f("ck_chat_message_billing_state"),
        ),
        sa.CheckConstraint(
            "citations_state IN ('null','empty','malformed','ok')",
            name=op.f("ck_chat_message_citations_state"),
        ),
        sa.CheckConstraint(
            "input_state IN ('null','empty','malformed','ok')",
            name=op.f("ck_chat_message_input_state"),
        ),
        sa.CheckConstraint(
            "rag_state IN ('null','empty','malformed','ok')",
            name=op.f("ck_chat_message_rag_state"),
        ),
        sa.CheckConstraint(
            "tool_calls_state IN ('null','empty','malformed','ok')",
            name=op.f("ck_chat_message_tool_calls_state"),
        ),
        sa.CheckConstraint(
            "type IN ('USER','AI','SYSTEM','TOOL')", name=op.f("ck_chat_message_type")
        ),
        sa.ForeignKeyConstraint(
            ["_source_file_id"],
            ["meta.source_file.source_file_id"],
            name=op.f("fk_chat_message__source_file_id_source_file"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["src.chat_session.session_id"],
            name=op.f("fk_chat_message_session_id_chat_session"),
        ),
        sa.PrimaryKeyConstraint("message_id", name=op.f("pk_chat_message")),
        schema="src",
    )
    op.create_index(
        "ix_chat_message_session_order",
        "chat_message",
        ["session_id", "timestamp", "source_ordinal"],
        unique=False,
        schema="src",
    )
    op.create_index(
        "ix_chat_message_type", "chat_message", ["type"], unique=False, schema="src"
    )
    op.create_table(
        "action",
        sa.Column("message_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column("type", sa.Text(), nullable=True, comment="privacy=operational"),
        sa.Column("reason", sa.Text(), nullable=True, comment="privacy=operational"),
        sa.Column(
            "_source_file_id",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "_source_row",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.ForeignKeyConstraint(
            ["_source_file_id"],
            ["meta.source_file.source_file_id"],
            name=op.f("fk_action__source_file_id_source_file"),
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["src.chat_message.message_id"],
            name=op.f("fk_action_message_id_chat_message"),
        ),
        sa.PrimaryKeyConstraint(
            "_source_file_id", "_source_row", name=op.f("pk_action")
        ),
        schema="src",
    )
    op.create_index(
        "ix_action_message_id", "action", ["message_id"], unique=False, schema="src"
    )
    op.create_table(
        "billing_item",
        sa.Column("message_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column(
            "call_count", sa.BigInteger(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "fixed_cost", sa.Double(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "total_cost", sa.Double(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "usage_cost", sa.Double(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "is_not_empty", sa.Boolean(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "fixed_income", sa.Double(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "input_tokens",
            sa.BigInteger(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "total_income", sa.Double(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "usage_income", sa.Double(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "output_tokens",
            sa.BigInteger(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "web_search_calls",
            sa.Double(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "billable_seconds",
            sa.Double(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "provider_key_name", sa.Text(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "audio_input_tokens",
            sa.Double(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "audio_output_tokens",
            sa.Double(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "cached_input_tokens",
            sa.Double(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "grounding_search_queries",
            sa.Double(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "cost_input_tokens",
            sa.Double(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "cost_output_tokens",
            sa.Double(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "income_input_tokens",
            sa.Double(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "income_output_tokens",
            sa.Double(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "cost_per_call", sa.Double(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "income_per_call", sa.Double(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "cost_cached_input_tokens",
            sa.Double(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "income_cached_input_tokens",
            sa.Double(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "provider_account", sa.Text(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "cache_write_tokens",
            sa.Double(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "cost_cache_write_tokens",
            sa.Double(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "income_cache_write_tokens",
            sa.Double(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "_source_file_id",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "_source_row",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.ForeignKeyConstraint(
            ["_source_file_id"],
            ["meta.source_file.source_file_id"],
            name=op.f("fk_billing_item__source_file_id_source_file"),
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["src.chat_message.message_id"],
            name=op.f("fk_billing_item_message_id_chat_message"),
        ),
        sa.PrimaryKeyConstraint(
            "_source_file_id", "_source_row", name=op.f("pk_billing_item")
        ),
        schema="src",
    )
    op.create_index(
        "ix_billing_item_message_id",
        "billing_item",
        ["message_id"],
        unique=False,
        schema="src",
    )
    op.create_table(
        "input_item",
        sa.Column("message_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column(
            "items",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="privacy=content",
        ),
        sa.Column(
            "items_state", sa.Text(), nullable=False, comment="privacy=operational"
        ),
        sa.Column(
            "_source_file_id",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "_source_row",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.CheckConstraint(
            "items_state IN ('null','empty','malformed','ok')",
            name=op.f("ck_input_item_items_state"),
        ),
        sa.ForeignKeyConstraint(
            ["_source_file_id"],
            ["meta.source_file.source_file_id"],
            name=op.f("fk_input_item__source_file_id_source_file"),
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["src.chat_message.message_id"],
            name=op.f("fk_input_item_message_id_chat_message"),
        ),
        sa.PrimaryKeyConstraint(
            "_source_file_id", "_source_row", name=op.f("pk_input_item")
        ),
        schema="src",
    )
    op.create_index(
        "ix_input_item_message_id",
        "input_item",
        ["message_id"],
        unique=False,
        schema="src",
    )
    op.create_table(
        "rag_chunk",
        sa.Column("message_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column("chunk_id", sa.Text(), nullable=True, comment="privacy=reference"),
        sa.Column("content", sa.Text(), nullable=True, comment="privacy=content"),
        sa.Column(
            "content_sha256", sa.Text(), nullable=True, comment="privacy=fingerprint"
        ),
        sa.Column("corpus_id", sa.Text(), nullable=True, comment="privacy=reference"),
        sa.Column(
            "reference", sa.Double(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "relevancy", sa.Double(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "reference_page", sa.Double(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "reference_type", sa.Text(), nullable=True, comment="privacy=operational"
        ),
        sa.Column(
            "reference_download_url",
            sa.Text(),
            nullable=True,
            comment="privacy=content",
        ),
        sa.Column("reference_url", sa.Text(), nullable=True, comment="privacy=content"),
        sa.Column(
            "source_index",
            sa.BigInteger(),
            nullable=True,
            comment="privacy=operational",
        ),
        sa.Column(
            "_source_file_id",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "_source_row",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.ForeignKeyConstraint(
            ["_source_file_id"],
            ["meta.source_file.source_file_id"],
            name=op.f("fk_rag_chunk__source_file_id_source_file"),
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["src.chat_message.message_id"],
            name=op.f("fk_rag_chunk_message_id_chat_message"),
        ),
        sa.PrimaryKeyConstraint(
            "_source_file_id", "_source_row", name=op.f("pk_rag_chunk")
        ),
        schema="src",
    )
    op.create_index(
        "ix_rag_chunk_message_id",
        "rag_chunk",
        ["message_id"],
        unique=False,
        schema="src",
    )
    op.create_table(
        "rag_query",
        sa.Column("message_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column("query", sa.Text(), nullable=True, comment="privacy=content"),
        sa.Column(
            "_source_file_id",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "_source_row",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.ForeignKeyConstraint(
            ["_source_file_id"],
            ["meta.source_file.source_file_id"],
            name=op.f("fk_rag_query__source_file_id_source_file"),
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["src.chat_message.message_id"],
            name=op.f("fk_rag_query_message_id_chat_message"),
        ),
        sa.PrimaryKeyConstraint(
            "_source_file_id", "_source_row", name=op.f("pk_rag_query")
        ),
        schema="src",
    )
    op.create_index(
        "ix_rag_query_message_id",
        "rag_query",
        ["message_id"],
        unique=False,
        schema="src",
    )
    op.create_table(
        "tool_call",
        sa.Column("message_id", sa.Text(), nullable=False, comment="privacy=reference"),
        sa.Column("call_id", sa.Text(), nullable=True, comment="privacy=reference"),
        sa.Column("call_name", sa.Text(), nullable=True, comment="privacy=operational"),
        sa.Column(
            "row_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="privacy=content",
        ),
        sa.Column(
            "_source_file_id",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.Column(
            "_source_row",
            sa.BigInteger(),
            nullable=False,
            comment="privacy=operational",
        ),
        sa.ForeignKeyConstraint(
            ["_source_file_id"],
            ["meta.source_file.source_file_id"],
            name=op.f("fk_tool_call__source_file_id_source_file"),
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["src.chat_message.message_id"],
            name=op.f("fk_tool_call_message_id_chat_message"),
        ),
        sa.PrimaryKeyConstraint(
            "_source_file_id", "_source_row", name=op.f("pk_tool_call")
        ),
        schema="src",
    )
    op.create_index(
        "ix_tool_call_message_id",
        "tool_call",
        ["message_id"],
        unique=False,
        schema="src",
    )


def downgrade() -> None:
    op.drop_index("ix_tool_call_message_id", table_name="tool_call", schema="src")
    op.drop_table("tool_call", schema="src")
    op.drop_index("ix_rag_query_message_id", table_name="rag_query", schema="src")
    op.drop_table("rag_query", schema="src")
    op.drop_index("ix_rag_chunk_message_id", table_name="rag_chunk", schema="src")
    op.drop_table("rag_chunk", schema="src")
    op.drop_index("ix_input_item_message_id", table_name="input_item", schema="src")
    op.drop_table("input_item", schema="src")
    op.drop_index("ix_billing_item_message_id", table_name="billing_item", schema="src")
    op.drop_table("billing_item", schema="src")
    op.drop_index("ix_action_message_id", table_name="action", schema="src")
    op.drop_table("action", schema="src")
    op.drop_index("ix_chat_message_type", table_name="chat_message", schema="src")
    op.drop_index(
        "ix_chat_message_session_order", table_name="chat_message", schema="src"
    )
    op.drop_table("chat_message", schema="src")
    op.drop_index("ix_chat_session_user_id", table_name="chat_session", schema="src")
    op.drop_index("ix_chat_session_created_at", table_name="chat_session", schema="src")
    op.drop_index("ix_chat_session_bot_id", table_name="chat_session", schema="src")
    op.drop_table("chat_session", schema="src")
    op.drop_table("users", schema="src")
    op.drop_table("chat_bot", schema="src")
    op.execute("DROP SCHEMA IF EXISTS src CASCADE")
