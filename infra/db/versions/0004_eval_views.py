"""eval views and frozen-dataset immutability

Routing-input views assemble only components, in order. They cannot see the reference
answer: it is not a component, and each view also refuses the record's answer message
and any post-generation stage. Frozen datasets reject changes through triggers.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_VIEW = """
CREATE VIEW eval.{name} AS
SELECT c.record_id, c.position, c.kind, c.role, c.availability_stage,
       c.transmitted_to_provider,
       CASE c.source_kind
         WHEN 'message' THEN m.content
         WHEN 'bot_instruction' THEN b.instructions
         WHEN 'rag_chunk' THEN rc.content
       END AS content,
       c.metadata
FROM eval.record_input_component c
JOIN eval.record_reference ref ON ref.record_id = c.record_id
LEFT JOIN src.chat_message m ON m.message_id = c.source_message_id
LEFT JOIN src.chat_bot b ON b.bot_id = c.source_bot_id
LEFT JOIN src.rag_chunk rc ON rc._source_file_id = c.source_chunk_file_id
                          AND rc._source_row = c.source_chunk_row
WHERE c.{flag}
  AND c.availability_stage <> 'post_generation'
  AND (c.source_kind <> 'message'
       OR c.source_message_id IS DISTINCT FROM ref.answer_message_id)
"""

_LOCKED = (
    "dataset_record",
    "dataset_reserve",
    "record_input_component",
    "record_reference",
    "annotation",
)


def upgrade() -> None:
    op.execute(
        _VIEW.format(
            name="routing_input_pre_retrieval_v1", flag="included_pre_retrieval"
        )
    )
    op.execute(
        _VIEW.format(
            name="routing_input_post_retrieval_v1", flag="included_post_retrieval"
        )
    )
    op.execute(
        """
        CREATE VIEW eval.record_current_label AS
        SELECT DISTINCT ON (a.record_id, a.dimension)
               a.record_id, a.dimension, a.value, a.method, a.annotator_pseudonym,
               a.rubric_version, a.confidence, a.review_status, a.created_at
        FROM eval.annotation a
        WHERE a.review_status = 'accepted'
          AND NOT EXISTS (SELECT 1 FROM eval.annotation s
                          WHERE s.supersedes_id = a.annotation_id)
        ORDER BY a.record_id, a.dimension, a.created_at DESC, a.annotation_id DESC
        """
    )
    op.execute(
        """
        CREATE FUNCTION eval.reject_frozen() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          rec text;
          ds text;
        BEGIN
          IF TG_OP = 'DELETE' THEN
            ds := to_jsonb(OLD)->>'dataset_id';
            rec := to_jsonb(OLD)->>'record_id';
          ELSE
            ds := to_jsonb(NEW)->>'dataset_id';
            rec := to_jsonb(NEW)->>'record_id';
          END IF;
          IF ds IS NULL THEN
            SELECT dataset_id INTO ds FROM eval.dataset_record WHERE record_id = rec;
          END IF;
          IF EXISTS (SELECT 1 FROM eval.dataset d
                     WHERE d.dataset_id = ds AND d.status = 'frozen') THEN
            RAISE EXCEPTION 'dataset % is frozen', ds;
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION eval.reject_unfreeze() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.status = 'frozen' THEN
            RAISE EXCEPTION 'dataset % is frozen', OLD.dataset_id;
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$
        """
    )
    for table in _LOCKED:
        op.execute(
            f"CREATE TRIGGER {table}_frozen BEFORE INSERT OR UPDATE OR DELETE "
            f"ON eval.{table} FOR EACH ROW EXECUTE FUNCTION eval.reject_frozen()"
        )
    op.execute(
        "CREATE TRIGGER dataset_frozen BEFORE UPDATE OR DELETE ON eval.dataset "
        "FOR EACH ROW EXECUTE FUNCTION eval.reject_unfreeze()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER dataset_frozen ON eval.dataset")
    for table in _LOCKED:
        op.execute(f"DROP TRIGGER {table}_frozen ON eval.{table}")
    op.execute("DROP FUNCTION eval.reject_unfreeze()")
    op.execute("DROP FUNCTION eval.reject_frozen()")
    op.execute("DROP VIEW eval.record_current_label")
    op.execute("DROP VIEW eval.routing_input_post_retrieval_v1")
    op.execute("DROP VIEW eval.routing_input_pre_retrieval_v1")
