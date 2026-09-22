"""Bind Delivery tasks to a specialist workspace and support explicit blockers."""

import sqlalchemy as sa
from alembic import op

revision = "20260822_16"
down_revision = "20260819_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "tasks" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("tasks")}
    with op.batch_alter_table("tasks", reflect_kwargs={"resolve_fks": False}) as batch_op:
        if "agent_workspace_id" not in columns:
            batch_op.add_column(sa.Column("agent_workspace_id", sa.String(), nullable=True))
            batch_op.create_foreign_key(
                "fk_tasks_agent_workspace_id", "agent_workspaces", ["agent_workspace_id"], ["id"]
            )
        if "blocked_reason" not in columns:
            batch_op.add_column(sa.Column("blocked_reason", sa.String(), nullable=True))
        batch_op.drop_constraint("ck_task_status", type_="check")
        batch_op.create_check_constraint(
            "ck_task_status",
            "status IN ('suggested', 'pending', 'in_progress', 'blocked', 'completed', 'dismissed', 'invalidated')",
        )

    indexes = {index["name"] for index in inspector.get_indexes("tasks")}
    if "ix_tasks_delivery_scope" not in indexes:
        op.create_index(
            "ix_tasks_delivery_scope",
            "tasks",
            ["workspace_id", "agent_workspace_id", "conversation_id", "status", "due_at"],
        )

    # Backfill only rows with an unambiguous linked source.  A task without a
    # source conversation remains unbound and can never become a Delivery fact.
    op.execute(
        sa.text(
            """
            UPDATE tasks
            SET agent_workspace_id = (
                SELECT mappings.agent_workspace_id
                FROM agent_workspace_conversations AS mappings
                JOIN agent_workspaces AS agents ON agents.id = mappings.agent_workspace_id
                WHERE mappings.conversation_id = tasks.conversation_id
                  AND agents.organization_workspace_id = tasks.workspace_id
                  AND agents.status = 'active'
                ORDER BY mappings.created_at ASC, mappings.id ASC
                LIMIT 1
            )
            WHERE conversation_id IS NOT NULL
              AND agent_workspace_id IS NULL
              AND EXISTS (
                SELECT 1
                FROM agent_workspace_conversations AS mappings
                JOIN agent_workspaces AS agents ON agents.id = mappings.agent_workspace_id
                WHERE mappings.conversation_id = tasks.conversation_id
                  AND agents.organization_workspace_id = tasks.workspace_id
                  AND agents.status = 'active'
              )
            """
        )
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "tasks" not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes("tasks")}
    if "ix_tasks_delivery_scope" in indexes:
        op.drop_index("ix_tasks_delivery_scope", table_name="tasks")
    columns = {column["name"] for column in inspector.get_columns("tasks")}
    check_constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("tasks")
        if constraint.get("name")
    }
    foreign_keys = {
        foreign_key["name"]
        for foreign_key in inspector.get_foreign_keys("tasks")
        if foreign_key.get("name")
    }
    with op.batch_alter_table("tasks", reflect_kwargs={"resolve_fks": False}) as batch_op:
        if "ck_task_status" in check_constraints:
            batch_op.drop_constraint("ck_task_status", type_="check")
        batch_op.create_check_constraint(
            "ck_task_status",
            "status IN ('suggested', 'pending', 'in_progress', 'completed', 'dismissed', 'invalidated')",
        )
        if "blocked_reason" in columns:
            batch_op.drop_column("blocked_reason")
        if "agent_workspace_id" in columns and "fk_tasks_agent_workspace_id" in foreign_keys:
            batch_op.drop_constraint("fk_tasks_agent_workspace_id", type_="foreignkey")
            batch_op.drop_column("agent_workspace_id")
