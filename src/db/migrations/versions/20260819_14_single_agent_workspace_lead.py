"""Enforce one active lead per agent workspace."""

import sqlalchemy as sa
from alembic import op

revision = "20260819_14"
down_revision = "20260817_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "agent_workspace_memberships" not in inspector.get_table_names():
        return

    op.execute(
        sa.text(
            """
            UPDATE agent_workspace_memberships
            SET business_role = 'member'
            WHERE id IN (
                SELECT id FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY agent_workspace_id
                               ORDER BY created_at ASC, id ASC
                           ) AS lead_number
                    FROM agent_workspace_memberships
                    WHERE business_role = 'lead' AND status = 'active'
                ) ranked_leads
                WHERE lead_number > 1
            )
            """
        )
    )
    indexes = {index["name"] for index in inspector.get_indexes("agent_workspace_memberships")}
    if "uq_agent_workspace_active_lead" not in indexes:
        op.create_index(
            "uq_agent_workspace_active_lead",
            "agent_workspace_memberships",
            ["agent_workspace_id"],
            unique=True,
            postgresql_where=sa.text("business_role = 'lead' AND status = 'active'"),
            sqlite_where=sa.text("business_role = 'lead' AND status = 'active'"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "agent_workspace_memberships" not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes("agent_workspace_memberships")}
    if "uq_agent_workspace_active_lead" in indexes:
        op.drop_index("uq_agent_workspace_active_lead", table_name="agent_workspace_memberships")
