"""Link private reminders to task deadlines."""

import sqlalchemy as sa
from alembic import op

revision = "20260830_32"
down_revision = "20260830_31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "tasks" in tables:
        task_columns = {column["name"] for column in inspector.get_columns("tasks")}
        if "auto_reminder_enabled" not in task_columns:
            op.add_column(
                "tasks",
                sa.Column(
                    "auto_reminder_enabled",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                ),
            )

    if "reminders" in tables:
        reminder_columns = {column["name"] for column in inspector.get_columns("reminders")}
        if "task_id" not in reminder_columns:
            # Batch mode keeps the migration reversible on SQLite while emitting regular ALTER
            # statements on PostgreSQL.
            with op.batch_alter_table("reminders") as batch_op:
                batch_op.add_column(sa.Column("task_id", sa.String(), nullable=True))
                batch_op.create_foreign_key(
                    "fk_reminders_task_id_tasks",
                    "tasks",
                    ["task_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes("reminders")}
        if "uq_reminders_task_id" not in indexes:
            op.create_index("uq_reminders_task_id", "reminders", ["task_id"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "reminders" in tables:
        task_indexes = {
            index["name"]
            for index in inspector.get_indexes("reminders")
            if "task_id" in (index.get("column_names") or [])
        }
        for index_name in task_indexes:
            op.drop_index(index_name, table_name="reminders")
        reminder_columns = {column["name"] for column in inspector.get_columns("reminders")}
        if "task_id" in reminder_columns:
            with op.batch_alter_table(
                "reminders", reflect_kwargs={"resolve_fks": False}
            ) as batch_op:
                if bind.dialect.name != "sqlite":
                    batch_op.drop_constraint("fk_reminders_task_id_tasks", type_="foreignkey")
                batch_op.drop_column("task_id")
    if "tasks" in tables:
        task_columns = {column["name"] for column in inspector.get_columns("tasks")}
        if "auto_reminder_enabled" in task_columns:
            op.drop_column("tasks", "auto_reminder_enabled")
