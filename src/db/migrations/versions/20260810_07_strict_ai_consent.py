"""Split AI-use/content consent and add P0 candidate provenance."""

import sqlalchemy as sa
from alembic import op

revision = "20260810_07"
down_revision = "20260806_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    ai_columns = {column["name"] for column in inspector.get_columns("ai_permissions")}
    if "contribution_allowed" not in ai_columns:
        with op.batch_alter_table("ai_permissions") as batch_op:
            batch_op.add_column(
                sa.Column("contribution_allowed", sa.Boolean(), nullable=False, server_default=sa.false())
            )
        # Preserve the old single-toggle meaning for existing grants.  New writes keep the two
        # choices independent.
        op.execute(sa.text("UPDATE ai_permissions SET contribution_allowed = granted"))

    task_columns = {column["name"] for column in sa.inspect(connection).get_columns("tasks")}
    task_constraints = {
        item["name"] for item in sa.inspect(connection).get_check_constraints("tasks") if item.get("name")
    }
    # Fresh databases are built from current metadata at revision 01 and may
    # already carry future FKs. Do not resolve those not-yet-historical tables
    # while SQLite reflects ``tasks`` for this revision.
    with op.batch_alter_table("tasks", reflect_kwargs={"resolve_fks": False}) as batch_op:
        if "source_message_ids" not in task_columns:
            batch_op.add_column(sa.Column("source_message_ids", sa.JSON(), nullable=True))
        if "source_sender_id" not in task_columns:
            batch_op.add_column(sa.Column("source_sender_id", sa.String(), nullable=True))
            batch_op.create_foreign_key(
                "fk_tasks_source_sender_id_users", "users", ["source_sender_id"], ["id"]
            )
            batch_op.create_index("ix_tasks_source_sender_id", ["source_sender_id"], unique=False)
        if "consent_scope_hash" not in task_columns:
            batch_op.add_column(sa.Column("consent_scope_hash", sa.String(), nullable=True))
            batch_op.create_index("ix_tasks_consent_scope_hash", ["consent_scope_hash"], unique=False)
        if "invalidated_reason" not in task_columns:
            batch_op.add_column(sa.Column("invalidated_reason", sa.String(), nullable=True))
        if "ck_task_status" in task_constraints:
            batch_op.drop_constraint("ck_task_status", type_="check")
        batch_op.create_check_constraint(
            "ck_task_status",
            "status IN ('suggested', 'pending', 'in_progress', 'completed', 'dismissed', 'invalidated')",
        )


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_constraint("ck_task_status", type_="check")
        batch_op.create_check_constraint(
            "ck_task_status",
            "status IN ('suggested', 'pending', 'in_progress', 'completed', 'dismissed')",
        )
        batch_op.drop_index("ix_tasks_consent_scope_hash")
        batch_op.drop_index("ix_tasks_source_sender_id")
        batch_op.drop_constraint("fk_tasks_source_sender_id_users", type_="foreignkey")
        batch_op.drop_column("invalidated_reason")
        batch_op.drop_column("consent_scope_hash")
        batch_op.drop_column("source_sender_id")
        batch_op.drop_column("source_message_ids")
    with op.batch_alter_table("ai_permissions") as batch_op:
        batch_op.drop_column("contribution_allowed")
