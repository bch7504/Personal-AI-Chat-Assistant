"""Add manager-governed group AI and durable event extraction records."""

import sqlalchemy as sa
from alembic import op

revision = "20260810_08"
down_revision = "20260810_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    conversation_columns = {column["name"] for column in inspector.get_columns("conversations")}
    with op.batch_alter_table("conversations") as batch_op:
        if "ai_enabled" not in conversation_columns:
            batch_op.add_column(
                sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
            )
        if "ai_policy_version" not in conversation_columns:
            batch_op.add_column(
                sa.Column("ai_policy_version", sa.Integer(), nullable=False, server_default="0")
            )
        if "ai_enabled_by_user_id" not in conversation_columns:
            batch_op.add_column(sa.Column("ai_enabled_by_user_id", sa.String(), nullable=True))
            batch_op.create_foreign_key(
                "fk_conversations_ai_enabled_by_user_id_users",
                "users",
                ["ai_enabled_by_user_id"],
                ["id"],
            )
        if "ai_enabled_at" not in conversation_columns:
            batch_op.add_column(sa.Column("ai_enabled_at", sa.DateTime(timezone=True), nullable=True))

    tables = set(sa.inspect(connection).get_table_names())
    if "event_candidates" not in tables:
        op.create_table(
            "event_candidates",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=False),
            sa.Column("conversation_id", sa.String(), nullable=False),
            sa.Column("operation", sa.String(), nullable=False),
            sa.Column("target_candidate_id", sa.String(), nullable=True),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("location", sa.String(), nullable=True),
            sa.Column("attendees", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("missing_fields", sa.JSON(), nullable=False),
            sa.Column("source_message_ids", sa.JSON(), nullable=False),
            sa.Column("authorization_scope_hash", sa.String(), nullable=False),
            sa.Column("calendar_event_id", sa.String(), nullable=True),
            sa.Column("invalidated_reason", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "status IN ('suggested', 'confirmed', 'superseded', 'dismissed', 'cancelled', 'invalidated')",
                name="ck_event_candidate_status",
            ),
            sa.CheckConstraint(
                "operation IN ('create', 'update', 'cancel')",
                name="ck_event_candidate_operation",
            ),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
            sa.ForeignKeyConstraint(["target_candidate_id"], ["event_candidates.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_event_candidates_workspace_id", "event_candidates", ["workspace_id"])
        op.create_index("ix_event_candidates_conversation_id", "event_candidates", ["conversation_id"])
        op.create_index(
            "ix_event_candidates_authorization_scope_hash",
            "event_candidates",
            ["authorization_scope_hash"],
        )
        op.create_index("ix_event_candidates_calendar_event_id", "event_candidates", ["calendar_event_id"])
        op.create_index("ix_event_candidates_target_candidate_id", "event_candidates", ["target_candidate_id"])
        op.create_index(
            "ix_event_candidates_conversation_status", "event_candidates", ["conversation_id", "status"]
        )
        op.create_index(
            "ix_event_candidates_workspace_start", "event_candidates", ["workspace_id", "start_at"]
        )

    if "event_extraction_cursors" not in tables:
        op.create_table(
            "event_extraction_cursors",
            sa.Column("conversation_id", sa.String(), nullable=False),
            sa.Column("last_message_created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_message_id", sa.String(), nullable=True),
            sa.Column("processed_message_count", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
            sa.PrimaryKeyConstraint("conversation_id"),
        )


def downgrade() -> None:
    op.drop_table("event_extraction_cursors")
    op.drop_index("ix_event_candidates_workspace_start", table_name="event_candidates")
    op.drop_index("ix_event_candidates_conversation_status", table_name="event_candidates")
    op.drop_index("ix_event_candidates_calendar_event_id", table_name="event_candidates")
    op.drop_index("ix_event_candidates_target_candidate_id", table_name="event_candidates")
    op.drop_index("ix_event_candidates_authorization_scope_hash", table_name="event_candidates")
    op.drop_index("ix_event_candidates_conversation_id", table_name="event_candidates")
    op.drop_index("ix_event_candidates_workspace_id", table_name="event_candidates")
    op.drop_table("event_candidates")
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.drop_constraint("fk_conversations_ai_enabled_by_user_id_users", type_="foreignkey")
        batch_op.drop_column("ai_enabled_at")
        batch_op.drop_column("ai_enabled_by_user_id")
        batch_op.drop_column("ai_policy_version")
        batch_op.drop_column("ai_enabled")
