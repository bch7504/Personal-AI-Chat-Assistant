"""Add Delivery checkpoint evaluation and approved group scheduling."""

import sqlalchemy as sa
from alembic import op

revision = "20260827_27"
down_revision = "20260827_26"
branch_labels = None
depends_on = None


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "tasks" in tables and "completed_at" not in _columns(inspector, "tasks"):
        op.add_column("tasks", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        op.execute("UPDATE tasks SET completed_at = updated_at WHERE status = 'completed'")

    if "delivery_milestones" in tables:
        columns = _columns(inspector, "delivery_milestones")
        additions = (
            ("plan_key", sa.String(), False, "'default'"),
            ("quality_review_status", sa.String(), False, "'pending'"),
            ("quality_review_note", sa.Text(), True, None),
            ("quality_reviewed_by_user_id", sa.String(), True, None),
            ("quality_reviewed_at", sa.DateTime(timezone=True), True, None),
            ("row_version", sa.Integer(), False, "1"),
        )
        for name, column_type, nullable, default in additions:
            if name not in columns:
                op.add_column(
                    "delivery_milestones",
                    sa.Column(name, column_type, nullable=nullable, server_default=sa.text(default) if default else None),
                )
        # Existing deployments do not have this FK/index; a fresh schema gets it
        # directly from the ORM metadata.
        indexes = {index["name"] for index in inspector.get_indexes("delivery_milestones")}
        if "ix_delivery_milestones_quality_reviewer" not in indexes:
            op.create_index(
                "ix_delivery_milestones_quality_reviewer",
                "delivery_milestones",
                ["quality_reviewed_by_user_id"],
            )
        if bind.dialect.name != "sqlite":
            foreign_key_columns = {
                tuple(foreign_key.get("constrained_columns") or ())
                for foreign_key in inspector.get_foreign_keys("delivery_milestones")
            }
            if ("quality_reviewed_by_user_id",) not in foreign_key_columns:
                op.create_foreign_key(
                    "fk_delivery_milestone_quality_reviewer",
                    "delivery_milestones",
                    "users",
                    ["quality_reviewed_by_user_id"],
                    ["id"],
                )
            check_constraint_names = {
                constraint["name"]
                for constraint in inspector.get_check_constraints("delivery_milestones")
                if constraint.get("name")
            }
            if "ck_delivery_milestone_quality_review" not in check_constraint_names:
                op.create_check_constraint(
                    "ck_delivery_milestone_quality_review",
                    "delivery_milestones",
                    "quality_review_status IN ('pending', 'accepted', 'rejected')",
                )

    if "delivery_checkpoint_tasks" not in tables:
        op.create_table(
            "delivery_checkpoint_tasks",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=False),
            sa.Column("agent_workspace_id", sa.String(), nullable=False),
            sa.Column("conversation_id", sa.String(), nullable=False),
            sa.Column("milestone_id", sa.String(), nullable=False),
            sa.Column("task_id", sa.String(), nullable=False),
            sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by_user_id", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.ForeignKeyConstraint(["agent_workspace_id"], ["agent_workspaces.id"]),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
            sa.ForeignKeyConstraint(["milestone_id"], ["delivery_milestones.id"]),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("milestone_id", "task_id", name="uq_delivery_checkpoint_task"),
        )
        op.create_index(
            "ix_delivery_checkpoint_task_scope",
            "delivery_checkpoint_tasks",
            ["workspace_id", "agent_workspace_id", "milestone_id"],
        )

    if "delivery_group_schedules" not in tables:
        op.create_table(
            "delivery_group_schedules",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=False),
            sa.Column("agent_workspace_id", sa.String(), nullable=False),
            sa.Column("conversation_id", sa.String(), nullable=False),
            sa.Column("created_by_user_id", sa.String(), nullable=False),
            sa.Column("approved_by_user_id", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="scheduled"),
            sa.Column("idempotency_key", sa.String(), nullable=False),
            sa.Column("sent_message_id", sa.String(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.ForeignKeyConstraint(["agent_workspace_id"], ["agent_workspaces.id"]),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["sent_message_id"], ["messages.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("idempotency_key", name="uq_delivery_group_schedule_idempotency"),
            sa.CheckConstraint(
                "status IN ('scheduled', 'sent', 'cancelled', 'failed')",
                name="ck_delivery_group_schedule_status",
            ),
        )
        op.create_index(
            "ix_delivery_group_schedule_due",
            "delivery_group_schedules",
            ["workspace_id", "agent_workspace_id", "status", "scheduled_for"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "delivery_group_schedules" in tables:
        op.drop_table("delivery_group_schedules")
    if "delivery_checkpoint_tasks" in tables:
        op.drop_table("delivery_checkpoint_tasks")
    if "delivery_milestones" in tables:
        added_columns = {
            "row_version",
            "quality_reviewed_at",
            "quality_reviewed_by_user_id",
            "quality_review_note",
            "quality_review_status",
            "plan_key",
        }
        for index in sa.inspect(bind).get_indexes("delivery_milestones"):
            if set(index.get("column_names") or ()) & added_columns:
                op.drop_index(index["name"], table_name="delivery_milestones")
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table(
                "delivery_milestones",
                reflect_kwargs={"resolve_fks": False},
            ) as batch_op:
                batch_op.drop_constraint(
                    "ck_delivery_milestone_quality_review",
                    type_="check",
                )
                for column in (
                    "row_version",
                    "quality_reviewed_at",
                    "quality_reviewed_by_user_id",
                    "quality_review_note",
                    "quality_review_status",
                    "plan_key",
                ):
                    if column in _columns(sa.inspect(bind), "delivery_milestones"):
                        batch_op.drop_column(column)
        else:
            op.drop_constraint(
                "ck_delivery_milestone_quality_review",
                "delivery_milestones",
                type_="check",
            )
            op.drop_constraint(
                "fk_delivery_milestone_quality_reviewer",
                "delivery_milestones",
                type_="foreignkey",
            )
            for column in (
                "row_version",
                "quality_reviewed_at",
                "quality_reviewed_by_user_id",
                "quality_review_note",
                "quality_review_status",
                "plan_key",
            ):
                if column in _columns(sa.inspect(bind), "delivery_milestones"):
                    op.drop_column("delivery_milestones", column)
    if "tasks" in tables and "completed_at" in _columns(sa.inspect(bind), "tasks"):
        op.drop_column("tasks", "completed_at")
