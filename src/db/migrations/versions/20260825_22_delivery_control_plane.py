"""Add source-bound Delivery dependency and decision registers."""

import sqlalchemy as sa
from alembic import op

revision = "20260825_22"
down_revision = "20260825_21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "delivery_dependencies" not in tables:
        op.create_table(
            "delivery_dependencies",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column("agent_workspace_id", sa.String(), sa.ForeignKey("agent_workspaces.id"), nullable=False),
            sa.Column("conversation_id", sa.String(), sa.ForeignKey("conversations.id"), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="open"),
            sa.Column("owner_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("predecessor_task_id", sa.String(), sa.ForeignKey("tasks.id"), nullable=True),
            sa.Column("successor_task_id", sa.String(), sa.ForeignKey("tasks.id"), nullable=True),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "status IN ('open', 'blocked', 'resolved', 'invalidated')",
                name="ck_delivery_dependency_status",
            ),
            sa.CheckConstraint(
                "predecessor_task_id IS NULL OR predecessor_task_id != successor_task_id",
                name="ck_delivery_dependency_distinct_tasks",
            ),
        )
        op.create_index(
            "ix_delivery_dependencies_scope",
            "delivery_dependencies",
            ["workspace_id", "agent_workspace_id", "conversation_id", "status", "due_at"],
        )

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "delivery_decisions" not in tables:
        op.create_table(
            "delivery_decisions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column("agent_workspace_id", sa.String(), sa.ForeignKey("agent_workspaces.id"), nullable=False),
            sa.Column("conversation_id", sa.String(), sa.ForeignKey("conversations.id"), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("owner_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("options", sa.JSON(), nullable=False),
            sa.Column("outcome", sa.Text(), nullable=True),
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "status IN ('pending', 'decided', 'superseded', 'invalidated')",
                name="ck_delivery_decision_status",
            ),
            sa.CheckConstraint(
                "(status = 'decided' AND outcome IS NOT NULL) OR status != 'decided'",
                name="ck_delivery_decision_outcome",
            ),
        )
        op.create_index(
            "ix_delivery_decisions_scope",
            "delivery_decisions",
            ["workspace_id", "agent_workspace_id", "conversation_id", "status", "due_at"],
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table_name in ("delivery_decisions", "delivery_dependencies"):
        if table_name in tables:
            op.drop_table(table_name)

