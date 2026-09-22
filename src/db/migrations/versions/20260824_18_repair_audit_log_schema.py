"""Repair legacy audit log tables to match the production model.

Older installations may already have ``audit_logs`` when the workspace
foundation migration runs.  That migration intentionally preserves the table,
so columns introduced by the workspace-aware audit model can be absent even
though Alembic is at head.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260824_18"
down_revision = "20260822_17"
branch_labels = None
depends_on = None


def _table_names(connection) -> set[str]:
    return set(sa.inspect(connection).get_table_names())


def _column_names(connection) -> set[str]:
    return {column["name"] for column in sa.inspect(connection).get_columns("audit_logs")}


def _indexed_columns(connection) -> set[tuple[str, ...]]:
    return {
        tuple(index.get("column_names") or ())
        for index in sa.inspect(connection).get_indexes("audit_logs")
    }


def _foreign_key_columns(connection) -> set[tuple[str, ...]]:
    return {
        tuple(foreign_key.get("constrained_columns") or ())
        for foreign_key in sa.inspect(connection).get_foreign_keys("audit_logs")
    }


def _create_audit_logs() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), nullable=True),
        sa.Column("actor_user_id", sa.String(), nullable=True),
        sa.Column("actor_type", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.String(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_audit_logs_workspace_id"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name="fk_audit_logs_actor_user_id"),
    )


def upgrade() -> None:
    connection = op.get_bind()
    if "audit_logs" not in _table_names(connection):
        _create_audit_logs()
    else:
        columns = _column_names(connection)
        with op.batch_alter_table("audit_logs", reflect_kwargs={"resolve_fks": False}) as batch_op:
            if "workspace_id" not in columns:
                batch_op.add_column(sa.Column("workspace_id", sa.String(), nullable=True))
            if "actor_user_id" not in columns:
                batch_op.add_column(sa.Column("actor_user_id", sa.String(), nullable=True))
            if "actor_type" not in columns:
                batch_op.add_column(
                    sa.Column("actor_type", sa.String(), nullable=False, server_default="system")
                )
            if "action" not in columns:
                batch_op.add_column(
                    sa.Column("action", sa.String(), nullable=False, server_default="legacy.unknown")
                )
            if "target_type" not in columns:
                batch_op.add_column(
                    sa.Column("target_type", sa.String(), nullable=False, server_default="unknown")
                )
            if "target_id" not in columns:
                batch_op.add_column(sa.Column("target_id", sa.String(), nullable=True))
            if "metadata_json" not in columns:
                batch_op.add_column(
                    sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
                )
            if "ip_address" not in columns:
                batch_op.add_column(sa.Column("ip_address", sa.String(), nullable=True))
            if "created_at" not in columns:
                batch_op.add_column(
                    sa.Column(
                        "created_at",
                        sa.DateTime(timezone=True),
                        nullable=False,
                        server_default=sa.func.now(),
                    )
                )

        foreign_keys = _foreign_key_columns(connection)
        with op.batch_alter_table("audit_logs", reflect_kwargs={"resolve_fks": False}) as batch_op:
            if ("workspace_id",) not in foreign_keys:
                batch_op.create_foreign_key(
                    "fk_audit_logs_workspace_id",
                    "workspaces",
                    ["workspace_id"],
                    ["id"],
                )
            if ("actor_user_id",) not in foreign_keys:
                batch_op.create_foreign_key(
                    "fk_audit_logs_actor_user_id",
                    "users",
                    ["actor_user_id"],
                    ["id"],
                )

    indexed_columns = _indexed_columns(connection)
    if ("workspace_id",) not in indexed_columns:
        op.create_index("ix_audit_logs_workspace_id", "audit_logs", ["workspace_id"])
    if ("actor_user_id",) not in indexed_columns:
        op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])
    if ("created_at",) not in indexed_columns:
        op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    # This revision reconciles schema drift with columns already required by
    # 20260803_02. Removing them would corrupt a correctly migrated database.
    pass
