"""Classify governed workspace conversations as structured channels."""

import sqlalchemy as sa
from alembic import op

revision = "20260830_31"
down_revision = "20260829_30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "agent_workspace_conversations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("agent_workspace_conversations")}
    if "channel_kind" in columns:
        return

    op.add_column(
        "agent_workspace_conversations",
        sa.Column("channel_kind", sa.String(), nullable=False, server_default="project"),
    )
    op.execute(
        sa.text(
            """
            UPDATE agent_workspace_conversations
            SET channel_kind = CASE
                WHEN lower(COALESCE((
                    SELECT conversations.name
                    FROM conversations
                    WHERE conversations.id = agent_workspace_conversations.conversation_id
                ), '')) LIKE '%release%' THEN 'release'
                WHEN lower(COALESCE((
                    SELECT conversations.name
                    FROM conversations
                    WHERE conversations.id = agent_workspace_conversations.conversation_id
                ), '')) LIKE '%team%' THEN 'team'
                WHEN lower(COALESCE((
                    SELECT conversations.name
                    FROM conversations
                    WHERE conversations.id = agent_workspace_conversations.conversation_id
                ), '')) LIKE '%announcement%'
                  OR lower(COALESCE((
                    SELECT conversations.name
                    FROM conversations
                    WHERE conversations.id = agent_workspace_conversations.conversation_id
                ), '')) LIKE '%general%' THEN 'announcement'
                ELSE 'project'
            END
            """
        )
    )
    with op.batch_alter_table("agent_workspace_conversations") as batch_op:
        batch_op.create_check_constraint(
            "ck_agent_workspace_conversation_channel_kind",
            "channel_kind IN ('announcement', 'team', 'project', 'release')",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "agent_workspace_conversations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("agent_workspace_conversations")}
    if "channel_kind" not in columns:
        return
    with op.batch_alter_table("agent_workspace_conversations") as batch_op:
        batch_op.drop_constraint("ck_agent_workspace_conversation_channel_kind", type_="check")
        batch_op.drop_column("channel_kind")
