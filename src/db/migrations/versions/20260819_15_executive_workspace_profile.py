"""Allow a dedicated executive workspace profile."""

from alembic import op

revision = "20260819_15"
down_revision = "20260819_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_workspaces") as batch_op:
        batch_op.drop_constraint("ck_agent_workspace_profile", type_="check")
        batch_op.create_check_constraint(
            "ck_agent_workspace_profile",
            "agent_profile IN ('product_delivery', 'quality_assurance', 'executive')",
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_workspaces") as batch_op:
        batch_op.drop_constraint("ck_agent_workspace_profile", type_="check")
        batch_op.create_check_constraint(
            "ck_agent_workspace_profile",
            "agent_profile IN ('product_delivery', 'quality_assurance')",
        )
