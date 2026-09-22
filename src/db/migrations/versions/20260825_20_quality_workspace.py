"""Add release-scoped Quality Assurance metadata to source-bound tasks."""

import sqlalchemy as sa
from alembic import op

revision = "20260825_20"
down_revision = "20260824_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "tasks" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("tasks")}
    additions = (
        ("work_item_type", sa.Column("work_item_type", sa.String(), nullable=True)),
        ("severity", sa.Column("severity", sa.String(), nullable=True)),
        ("quality_status", sa.Column("quality_status", sa.String(), nullable=True)),
        ("release_target", sa.Column("release_target", sa.String(), nullable=True)),
        (
            "quality_required",
            sa.Column("quality_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        ),
    )
    with op.batch_alter_table("tasks", reflect_kwargs={"resolve_fks": False}) as batch_op:
        for name, column in additions:
            if name not in columns:
                batch_op.add_column(column)

    inspector = sa.inspect(op.get_bind())
    checks = {item["name"] for item in inspector.get_check_constraints("tasks") if item.get("name")}
    with op.batch_alter_table("tasks", reflect_kwargs={"resolve_fks": False}) as batch_op:
        if "ck_task_quality_type" not in checks:
            batch_op.create_check_constraint(
                "ck_task_quality_type",
                "work_item_type IS NULL OR work_item_type IN ('bug', 'test_case', 'release_check')",
            )
        if "ck_task_quality_severity" not in checks:
            batch_op.create_check_constraint(
                "ck_task_quality_severity",
                "severity IS NULL OR severity IN ('low', 'medium', 'high', 'critical')",
            )
        if "ck_task_quality_status" not in checks:
            batch_op.create_check_constraint(
                "ck_task_quality_status",
                "quality_status IS NULL OR quality_status IN ('open', 'testing', 'passed', 'failed', 'blocked')",
            )
        if "ck_task_quality_shape" not in checks:
            batch_op.create_check_constraint(
                "ck_task_quality_shape",
                "(work_item_type IS NULL AND severity IS NULL AND quality_status IS NULL AND release_target IS NULL AND quality_required = false) OR "
                "(work_item_type IS NOT NULL AND quality_status IS NOT NULL AND release_target IS NOT NULL "
                "AND (work_item_type != 'bug' OR severity IS NOT NULL) "
                "AND (quality_required = false OR work_item_type = 'release_check'))",
            )

    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("tasks")}
    if "ix_tasks_quality_scope" not in indexes:
        op.create_index(
            "ix_tasks_quality_scope",
            "tasks",
            ["workspace_id", "agent_workspace_id", "conversation_id", "release_target", "work_item_type"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "tasks" not in inspector.get_table_names():
        return
    indexes = {item["name"] for item in inspector.get_indexes("tasks")}
    for index_name in ("ix_tasks_quality_scope", "ix_tasks_release_target"):
        if index_name in indexes:
            op.drop_index(index_name, table_name="tasks")
    checks = {item["name"] for item in inspector.get_check_constraints("tasks") if item.get("name")}
    columns = {column["name"] for column in inspector.get_columns("tasks")}
    with op.batch_alter_table("tasks", reflect_kwargs={"resolve_fks": False}) as batch_op:
        for name in (
            "ck_task_quality_shape",
            "ck_task_quality_status",
            "ck_task_quality_severity",
            "ck_task_quality_type",
        ):
            if name in checks:
                batch_op.drop_constraint(name, type_="check")
        for name in ("quality_required", "release_target", "quality_status", "severity", "work_item_type"):
            if name in columns:
                batch_op.drop_column(name)
