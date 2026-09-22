"""Add typed, source-bound Product Delivery milestones."""

import sqlalchemy as sa
from alembic import op

revision = "20260822_17"
down_revision = "20260822_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "delivery_milestones" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "delivery_milestones",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("agent_workspace_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("owner_id", sa.String(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'blocked', 'completed', 'dismissed', 'invalidated')",
            name="ck_delivery_milestone_status",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["agent_workspace_id"], ["agent_workspaces.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_delivery_milestones_workspace_id", "delivery_milestones", ["workspace_id"])
    op.create_index("ix_delivery_milestones_agent_workspace_id", "delivery_milestones", ["agent_workspace_id"])
    op.create_index("ix_delivery_milestones_conversation_id", "delivery_milestones", ["conversation_id"])
    op.create_index("ix_delivery_milestones_owner_id", "delivery_milestones", ["owner_id"])
    op.create_index(
        "ix_delivery_milestone_scope",
        "delivery_milestones",
        ["workspace_id", "agent_workspace_id", "conversation_id", "status", "due_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_milestone_scope", table_name="delivery_milestones")
    op.drop_index("ix_delivery_milestones_owner_id", table_name="delivery_milestones")
    op.drop_index("ix_delivery_milestones_conversation_id", table_name="delivery_milestones")
    op.drop_index("ix_delivery_milestones_agent_workspace_id", table_name="delivery_milestones")
    op.drop_index("ix_delivery_milestones_workspace_id", table_name="delivery_milestones")
    op.drop_table("delivery_milestones")
