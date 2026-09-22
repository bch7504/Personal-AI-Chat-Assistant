"""Add evidence-backed Delivery task submission and Lead review."""

import sqlalchemy as sa
from alembic import op

revision = "20260828_29"
down_revision = "20260827_28"
branch_labels = None
depends_on = None


_STATUS_SQL = (
    "status IN ('suggested', 'pending', 'in_progress', 'blocked', 'submitted', "
    "'changes_requested', 'completed', 'dismissed', 'invalidated')"
)


def _columns(inspector) -> set[str]:
    return {column["name"] for column in inspector.get_columns("tasks")}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tasks" not in inspector.get_table_names():
        return
    columns = _columns(inspector)
    additions = (
        ("requires_review", sa.Boolean(), False, sa.text("false")),
        ("submission_note", sa.Text(), True, None),
        ("evidence_urls", sa.JSON(), False, sa.text("'[]'")),
        ("submitted_by_user_id", sa.String(), True, None),
        ("submitted_at", sa.DateTime(timezone=True), True, None),
        ("reviewed_by_user_id", sa.String(), True, None),
        ("reviewed_at", sa.DateTime(timezone=True), True, None),
        ("review_note", sa.Text(), True, None),
    )
    for name, column_type, nullable, default in additions:
        if name not in columns:
            op.add_column(
                "tasks",
                sa.Column(name, column_type, nullable=nullable, server_default=default),
            )

    constraints = {item["name"] for item in inspector.get_check_constraints("tasks")}
    with op.batch_alter_table("tasks") as batch_op:
        if "ck_task_status" in constraints:
            batch_op.drop_constraint("ck_task_status", type_="check")
        batch_op.create_check_constraint("ck_task_status", _STATUS_SQL)

    indexes = {item["name"] for item in inspector.get_indexes("tasks")}
    if "ix_tasks_submitted_by_user_id" not in indexes:
        op.create_index("ix_tasks_submitted_by_user_id", "tasks", ["submitted_by_user_id"])
    if "ix_tasks_reviewed_by_user_id" not in indexes:
        op.create_index("ix_tasks_reviewed_by_user_id", "tasks", ["reviewed_by_user_id"])
    if bind.dialect.name != "sqlite":
        foreign_keys = {item.get("name") for item in inspector.get_foreign_keys("tasks")}
        if "fk_tasks_submitted_by_user_id_users" not in foreign_keys:
            op.create_foreign_key(
                "fk_tasks_submitted_by_user_id_users", "tasks", "users", ["submitted_by_user_id"], ["id"]
            )
        if "fk_tasks_reviewed_by_user_id_users" not in foreign_keys:
            op.create_foreign_key(
                "fk_tasks_reviewed_by_user_id_users", "tasks", "users", ["reviewed_by_user_id"], ["id"]
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tasks" not in inspector.get_table_names():
        return
    constraints = {item["name"] for item in inspector.get_check_constraints("tasks")}
    with op.batch_alter_table("tasks") as batch_op:
        if "ck_task_status" in constraints:
            batch_op.drop_constraint("ck_task_status", type_="check")
        batch_op.create_check_constraint(
            "ck_task_status",
            "status IN ('suggested', 'pending', 'in_progress', 'blocked', 'completed', 'dismissed', 'invalidated')",
        )
    # SQLite cannot drop columns referenced by anonymous reflected foreign keys.
    # Keeping nullable compatibility columns is safer than rebuilding a legacy
    # task table and is consistent with the repository's older downgrade policy.
    if bind.dialect.name == "sqlite":
        return
    foreign_keys = {item.get("name") for item in sa.inspect(bind).get_foreign_keys("tasks")}
    for name in ("fk_tasks_submitted_by_user_id_users", "fk_tasks_reviewed_by_user_id_users"):
        if name in foreign_keys:
            op.drop_constraint(name, "tasks", type_="foreignkey")
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("tasks")}
    for name in ("ix_tasks_submitted_by_user_id", "ix_tasks_reviewed_by_user_id"):
        if name in indexes:
            op.drop_index(name, table_name="tasks")
    columns = _columns(sa.inspect(bind))
    for name in (
        "review_note",
        "reviewed_at",
        "reviewed_by_user_id",
        "submitted_at",
        "submitted_by_user_id",
        "evidence_urls",
        "submission_note",
        "requires_review",
    ):
        if name in columns:
            op.drop_column("tasks", name)
