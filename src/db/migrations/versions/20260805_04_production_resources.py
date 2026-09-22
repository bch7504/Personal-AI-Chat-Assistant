"""Harden personal resources for workspace-aware production use."""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from src.db import models  # noqa: F401
from src.db.base import Base

revision = "20260805_04"
down_revision = "20260804_03"
branch_labels = None
depends_on = None


def _tables(connection) -> set[str]:
    return set(sa.inspect(connection).get_table_names())


def _columns(connection, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(connection).get_columns(table)}


def _indexes(connection, table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(connection).get_indexes(table)}


def _foreign_key_targets(connection, table: str) -> set[tuple[str, str]]:
    targets: set[tuple[str, str]] = set()
    for foreign_key in sa.inspect(connection).get_foreign_keys(table):
        referred_table = foreign_key.get("referred_table")
        for local_column in foreign_key.get("constrained_columns") or []:
            if referred_table:
                targets.add((local_column, referred_table))
    return targets


def _create_missing_tables(connection) -> None:
    for table_name in ("tasks", "usage_logs", "memories", "calendar_sync_state", "reminders"):
        Base.metadata.tables[table_name].create(bind=connection, checkfirst=True)


def _add_user_profile_columns(connection) -> None:
    columns = _columns(connection, "users")
    if "job_title" not in columns:
        op.add_column("users", sa.Column("job_title", sa.String(), nullable=False, server_default=""))
    if "timezone" not in columns:
        op.add_column(
            "users",
            sa.Column("timezone", sa.String(), nullable=False, server_default="Asia/Ho_Chi_Minh"),
        )
    if "preferences" not in columns:
        op.add_column(
            "users",
            sa.Column("preferences", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )


def _add_resource_columns(connection, table: str) -> None:
    columns = _columns(connection, table)
    if "workspace_id" not in columns:
        op.add_column(table, sa.Column("workspace_id", sa.String(), nullable=True))
    if "updated_at" not in columns:
        op.add_column(table, sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))


def _backfill_workspace_resources(connection) -> None:
    now = datetime.now(UTC)
    for table in ("tasks", "memories", "reminders"):
        connection.execute(sa.text(f"UPDATE {table} SET updated_at = COALESCE(updated_at, created_at, :now)"), {"now": now})

    connection.execute(
        sa.text(
            "UPDATE tasks SET workspace_id = ("
            "SELECT conversations.workspace_id FROM conversations "
            "WHERE conversations.id = tasks.conversation_id"
            ") WHERE workspace_id IS NULL AND conversation_id IS NOT NULL"
        )
    )
    for table in ("tasks", "memories", "reminders"):
        connection.execute(
            sa.text(
                f"UPDATE {table} SET workspace_id = ("
                "SELECT workspaces.id FROM workspaces "
                f"WHERE workspaces.type = 'personal' AND workspaces.personal_owner_user_id = {table}.owner_id "
                "LIMIT 1"
                ") WHERE workspace_id IS NULL AND owner_id IS NOT NULL"
            )
        )
    # Old agent-created reminders had no owner, could never be delivered, and cannot be
    # attributed safely to a tenant. Dropping those unusable rows is safer than guessing.
    connection.execute(sa.text("DELETE FROM reminders WHERE owner_id IS NULL OR workspace_id IS NULL"))


def _add_resource_indexes(connection) -> None:
    definitions = {
        "tasks": (
            ("ix_tasks_workspace_id", ["workspace_id"]),
            ("ix_tasks_conversation_id", ["conversation_id"]),
            ("ix_tasks_workspace_owner_status", ["workspace_id", "owner_id", "status"]),
            ("ix_tasks_workspace_due_at", ["workspace_id", "due_at"]),
        ),
        "memories": (
            ("ix_memories_workspace_id", ["workspace_id"]),
            ("ix_memories_workspace_owner_created", ["workspace_id", "owner_id", "created_at"]),
        ),
        "reminders": (
            ("ix_reminders_workspace_id", ["workspace_id"]),
            ("ix_reminders_workspace_owner_status", ["workspace_id", "owner_id", "status"]),
            ("ix_reminders_workspace_fire_at", ["workspace_id", "fire_at"]),
        ),
        "usage_logs": (
            ("ix_usage_logs_workspace_id", ["workspace_id"]),
            ("ix_usage_logs_user_id", ["user_id"]),
        ),
    }
    for table, indexes in definitions.items():
        existing = _indexes(connection, table)
        for name, columns in indexes:
            if name not in existing:
                op.create_index(name, table, columns)


def _harden_constraints(connection) -> None:
    for table in ("tasks", "memories", "reminders"):
        targets = _foreign_key_targets(connection, table)
        # A fresh database is created from current metadata by revision 01.
        # It can therefore contain a later FK whose target table has not yet
        # been introduced by this historical revision. Reflection must not
        # resolve that future FK while rebuilding this older table on SQLite.
        with op.batch_alter_table(table, reflect_kwargs={"resolve_fks": False}) as batch_op:
            if ("workspace_id", "workspaces") not in targets:
                batch_op.create_foreign_key(
                    f"fk_{table}_workspace_id_workspaces",
                    "workspaces",
                    ["workspace_id"],
                    ["id"],
                )
            batch_op.alter_column(
                "updated_at",
                existing_type=sa.DateTime(timezone=True),
                nullable=False,
            )
            batch_op.alter_column("workspace_id", existing_type=sa.String(), nullable=False)
            if table == "reminders":
                batch_op.alter_column("owner_id", existing_type=sa.String(), nullable=False)

    usage_targets = _foreign_key_targets(connection, "usage_logs")
    with op.batch_alter_table("usage_logs") as batch_op:
        if ("workspace_id", "workspaces") not in usage_targets:
            batch_op.create_foreign_key(
                "fk_usage_logs_workspace_id_workspaces", "workspaces", ["workspace_id"], ["id"]
            )
        if ("user_id", "users") not in usage_targets:
            batch_op.create_foreign_key("fk_usage_logs_user_id_users", "users", ["user_id"], ["id"])


def upgrade() -> None:
    connection = op.get_bind()
    _add_user_profile_columns(connection)
    _create_missing_tables(connection)

    for table in ("tasks", "memories", "reminders"):
        _add_resource_columns(connection, table)

    usage_columns = _columns(connection, "usage_logs")
    if "workspace_id" not in usage_columns:
        op.add_column("usage_logs", sa.Column("workspace_id", sa.String(), nullable=True))
    if "user_id" not in usage_columns:
        op.add_column("usage_logs", sa.Column("user_id", sa.String(), nullable=True))

    _backfill_workspace_resources(connection)
    _harden_constraints(connection)
    _add_resource_indexes(connection)

    # The legacy global cursor cannot safely be assigned to an arbitrary tenant.
    if "calendar_sync_state" in _tables(connection):
        connection.execute(sa.text("DELETE FROM calendar_sync_state WHERE id = 'default'"))


def downgrade() -> None:
    # This migration intentionally keeps data-bearing resource tables. Removing workspace
    # ownership columns would destroy tenant attribution and is not a safe automatic downgrade.
    pass
