"""Add business-scoped agent workspaces and memberships."""

import sqlalchemy as sa
from alembic import op

revision = "20260817_13"
down_revision = "20260813_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "agent_workspaces" not in inspector.get_table_names():
        op.create_table(
            "agent_workspaces",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("organization_workspace_id", sa.String(), nullable=False),
            sa.Column("key", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("agent_profile", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "agent_profile IN ('product_delivery', 'quality_assurance')",
                name="ck_agent_workspace_profile",
            ),
            sa.CheckConstraint(
                "status IN ('active', 'suspended', 'archived')",
                name="ck_agent_workspace_status",
            ),
            sa.ForeignKeyConstraint(["organization_workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "organization_workspace_id",
                "key",
                name="uq_agent_workspace_organization_key",
            ),
        )
        op.create_index(
            "ix_agent_workspaces_organization_workspace_id",
            "agent_workspaces",
            ["organization_workspace_id"],
        )
        op.create_index(
            "ix_agent_workspaces_organization_status",
            "agent_workspaces",
            ["organization_workspace_id", "status"],
        )

    inspector = sa.inspect(op.get_bind())
    if "agent_workspace_memberships" not in inspector.get_table_names():
        op.create_table(
            "agent_workspace_memberships",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("agent_workspace_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("business_role", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "business_role IN ('member', 'lead', 'executive_viewer')",
                name="ck_agent_workspace_membership_role",
            ),
            sa.CheckConstraint(
                "status IN ('active', 'invited', 'suspended', 'revoked')",
                name="ck_agent_workspace_membership_status",
            ),
            sa.ForeignKeyConstraint(["agent_workspace_id"], ["agent_workspaces.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "agent_workspace_id",
                "user_id",
                name="uq_agent_workspace_membership_user",
            ),
        )
        op.create_index(
            "ix_agent_workspace_memberships_agent_workspace_id",
            "agent_workspace_memberships",
            ["agent_workspace_id"],
        )
        op.create_index(
            "ix_agent_workspace_memberships_user_id",
            "agent_workspace_memberships",
            ["user_id"],
        )
        op.create_index(
            "ix_agent_workspace_memberships_user_status",
            "agent_workspace_memberships",
            ["user_id", "status"],
        )

    inspector = sa.inspect(op.get_bind())
    if "agent_workspace_conversations" not in inspector.get_table_names():
        op.create_table(
            "agent_workspace_conversations",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("agent_workspace_id", sa.String(), nullable=False),
            sa.Column("conversation_id", sa.String(), nullable=False),
            sa.Column("classification", sa.String(), nullable=False),
            sa.Column("linked_by_user_id", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "classification IN ('delivery', 'quality')",
                name="ck_agent_workspace_conversation_classification",
            ),
            sa.ForeignKeyConstraint(["agent_workspace_id"], ["agent_workspaces.id"]),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
            sa.ForeignKeyConstraint(["linked_by_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("conversation_id", name="uq_agent_workspace_conversation"),
        )
        op.create_index(
            "ix_agent_workspace_conversations_agent_workspace_id",
            "agent_workspace_conversations",
            ["agent_workspace_id"],
        )
        op.create_index(
            "ix_agent_workspace_conversations_conversation_id",
            "agent_workspace_conversations",
            ["conversation_id"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "agent_workspace_conversations" in inspector.get_table_names():
        op.drop_index(
            "ix_agent_workspace_conversations_conversation_id",
            table_name="agent_workspace_conversations",
        )
        op.drop_index(
            "ix_agent_workspace_conversations_agent_workspace_id",
            table_name="agent_workspace_conversations",
        )
        op.drop_table("agent_workspace_conversations")
    inspector = sa.inspect(op.get_bind())
    if "agent_workspace_memberships" in inspector.get_table_names():
        op.drop_index(
            "ix_agent_workspace_memberships_user_status",
            table_name="agent_workspace_memberships",
        )
        op.drop_index(
            "ix_agent_workspace_memberships_user_id",
            table_name="agent_workspace_memberships",
        )
        op.drop_index(
            "ix_agent_workspace_memberships_agent_workspace_id",
            table_name="agent_workspace_memberships",
        )
        op.drop_table("agent_workspace_memberships")
    inspector = sa.inspect(op.get_bind())
    if "agent_workspaces" in inspector.get_table_names():
        op.drop_index(
            "ix_agent_workspaces_organization_status",
            table_name="agent_workspaces",
        )
        op.drop_index(
            "ix_agent_workspaces_organization_workspace_id",
            table_name="agent_workspaces",
        )
        op.drop_table("agent_workspaces")
