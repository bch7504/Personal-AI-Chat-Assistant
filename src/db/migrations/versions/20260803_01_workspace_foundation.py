"""Add workspace ownership foundation and backfill legacy chat data."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

from src.db import models  # noqa: F401
from src.db.base import Base

revision = "20260803_01"
down_revision = None
branch_labels = None
depends_on = None


def _uuid() -> str:
    return uuid4().hex


def _table_names(connection) -> set[str]:
    return set(sa.inspect(connection).get_table_names())


def _column_names(connection, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(connection).get_columns(table_name)}


def _create_schema(connection) -> None:
    tables = _table_names(connection)
    # A fresh database has no legacy baseline revision. Build the current schema;
    # later revisions are idempotent and will simply stamp their versions.
    if "users" not in tables or "conversations" not in tables:
        Base.metadata.create_all(bind=connection)
        return
    if "platform_role" not in _column_names(connection, "users"):
        op.add_column(
            "users",
            sa.Column("platform_role", sa.String(), nullable=False, server_default="user"),
        )
    if "workspace_id" not in _column_names(connection, "conversations"):
        op.add_column("conversations", sa.Column("workspace_id", sa.String(), nullable=True))

    if "workspaces" not in tables:
        op.create_table(
            "workspaces",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("type", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("slug", sa.String(), nullable=True),
            sa.Column("personal_owner_user_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["personal_owner_user_id"], ["users.id"]),
            sa.UniqueConstraint("slug", name="uq_workspaces_slug"),
            sa.UniqueConstraint("personal_owner_user_id", name="uq_workspaces_personal_owner"),
            sa.CheckConstraint(
                "(type = 'personal' AND personal_owner_user_id IS NOT NULL) OR "
                "(type = 'organization' AND personal_owner_user_id IS NULL)",
                name="ck_workspace_owner_matches_type",
            ),
            sa.CheckConstraint("type IN ('personal', 'organization')", name="ck_workspace_type"),
            sa.CheckConstraint(
                "status IN ('active', 'suspended', 'deleting')",
                name="ck_workspace_status",
            ),
        )
        op.create_index("ix_workspaces_personal_owner_user_id", "workspaces", ["personal_owner_user_id"])

    if "workspace_memberships" not in tables:
        op.create_table(
            "workspace_memberships",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("workspace_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("role", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("invited_by_user_id", sa.String(), nullable=True),
            sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"]),
            sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_membership_user"),
            sa.CheckConstraint(
                "role IN ('owner', 'admin', 'member', 'guest')",
                name="ck_workspace_membership_role",
            ),
            sa.CheckConstraint(
                "status IN ('active', 'invited', 'suspended', 'revoked')",
                name="ck_workspace_membership_status",
            ),
        )
        op.create_index("ix_workspace_memberships_workspace_id", "workspace_memberships", ["workspace_id"])
        op.create_index("ix_workspace_memberships_user_id", "workspace_memberships", ["user_id"])

    if "migration_states" not in tables:
        op.create_table(
            "migration_states",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("migration_key", sa.String(), nullable=False, unique=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("error_code", sa.String(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )


def _resolve_owner(connection) -> str:
    bootstrap_owner_id = os.getenv("BOOTSTRAP_OWNER_USER_ID", "").strip()
    active_admin_ids = list(
        connection.execute(
            sa.text("SELECT id FROM users WHERE role = 'admin' AND is_active IS TRUE ORDER BY id")
        ).scalars()
    )
    if bootstrap_owner_id:
        if bootstrap_owner_id not in active_admin_ids:
            raise RuntimeError("invalid_bootstrap_owner")
        return bootstrap_owner_id
    if len(active_admin_ids) != 1:
        raise RuntimeError("ambiguous_bootstrap_owner")
    return active_admin_ids[0]


def _backfill(connection, owner_user_id: str | None) -> None:
    now = datetime.now(UTC)
    connection.execute(
        sa.text("UPDATE users SET platform_role = CASE WHEN role = 'admin' THEN 'platform_admin' ELSE 'user' END")
    )
    users = connection.execute(
        sa.text("SELECT id, display_name, created_at FROM users ORDER BY created_at, id")
    ).mappings()
    user_rows = list(users)
    if not user_rows:
        return
    for user in user_rows:
        exists = connection.execute(
            sa.text("SELECT id FROM workspaces WHERE type = 'personal' AND personal_owner_user_id = :user_id"),
            {"user_id": user["id"]},
        ).scalar_one_or_none()
        if exists is None:
            connection.execute(
                sa.text(
                    "INSERT INTO workspaces "
                    "(id, type, name, slug, personal_owner_user_id, status, created_at, updated_at) "
                    "VALUES (:id, 'personal', :name, NULL, :owner_id, 'active', :created_at, :updated_at)"
                ),
                {
                    "id": _uuid(),
                    "name": f"{user['display_name']}'s Workspace",
                    "owner_id": user["id"],
                    "created_at": user["created_at"] or now,
                    "updated_at": now,
                },
            )

    if owner_user_id is None:
        return

    organization_id = connection.execute(
        sa.text("SELECT id FROM workspaces WHERE slug = 'legacy-organization'")
    ).scalar_one_or_none()
    if organization_id is None:
        organization_id = _uuid()
        connection.execute(
            sa.text(
                "INSERT INTO workspaces "
                "(id, type, name, slug, personal_owner_user_id, status, created_at, updated_at) "
                "VALUES (:id, 'organization', 'Legacy Organization', 'legacy-organization', NULL, "
                "'active', :created_at, :updated_at)"
            ),
            {"id": organization_id, "created_at": now, "updated_at": now},
        )

    for user in user_rows:
        membership_exists = connection.execute(
            sa.text("SELECT id FROM workspace_memberships WHERE workspace_id = :workspace_id AND user_id = :user_id"),
            {"workspace_id": organization_id, "user_id": user["id"]},
        ).scalar_one_or_none()
        if membership_exists is None:
            connection.execute(
                sa.text(
                    "INSERT INTO workspace_memberships "
                    "(id, workspace_id, user_id, role, status, invited_by_user_id, joined_at, created_at, updated_at) "
                    "VALUES (:id, :workspace_id, :user_id, :role, 'active', :owner_id, :joined_at, :created_at, "
                    ":updated_at)"
                ),
                {
                    "id": _uuid(),
                    "workspace_id": organization_id,
                    "user_id": user["id"],
                    "role": "owner" if user["id"] == owner_user_id else "member",
                    "owner_id": owner_user_id,
                    "joined_at": now,
                    "created_at": now,
                    "updated_at": now,
                },
            )

    connection.execute(
        sa.text("UPDATE conversations SET workspace_id = :workspace_id WHERE workspace_id IS NULL"),
        {"workspace_id": organization_id},
    )
    state_exists = connection.execute(
        sa.text("SELECT id FROM migration_states WHERE migration_key = 'workspace_foundation_v1'")
    ).scalar_one_or_none()
    if state_exists is None:
        connection.execute(
            sa.text(
                "INSERT INTO migration_states "
                "(id, migration_key, status, error_code, started_at, completed_at) "
                "VALUES (:id, 'workspace_foundation_v1', 'completed', NULL, :started_at, :completed_at)"
            ),
            {"id": _uuid(), "started_at": now, "completed_at": now},
        )


def _finalize_conversations(connection) -> None:
    inspector = sa.inspect(connection)
    columns = {column["name"]: column for column in inspector.get_columns("conversations")}
    foreign_keys = inspector.get_foreign_keys("conversations")
    has_workspace_fk = any(
        foreign_key.get("referred_table") == "workspaces" and foreign_key.get("constrained_columns") == ["workspace_id"]
        for foreign_key in foreign_keys
    )
    check_names = {constraint.get("name") for constraint in inspector.get_check_constraints("conversations")}
    index_names = {index.get("name") for index in inspector.get_indexes("conversations")}
    needs_batch = (
        columns["workspace_id"].get("nullable", True)
        or not has_workspace_fk
        or "ck_conversation_type" not in check_names
        or "ix_conversations_workspace_id" not in index_names
    )
    if not needs_batch:
        return
    with op.batch_alter_table("conversations") as batch_op:
        if columns["workspace_id"].get("nullable", True):
            batch_op.alter_column("workspace_id", existing_type=sa.String(), nullable=False)
        if not has_workspace_fk:
            batch_op.create_foreign_key(
                "fk_conversations_workspace_id",
                "workspaces",
                ["workspace_id"],
                ["id"],
            )
        if "ck_conversation_type" not in check_names:
            batch_op.create_check_constraint("ck_conversation_type", "type IN ('direct', 'group')")
        if "ix_conversations_workspace_id" not in index_names:
            batch_op.create_index("ix_conversations_workspace_id", ["workspace_id"])


def upgrade() -> None:
    connection = op.get_bind()
    _create_schema(connection)
    conversation_count = connection.execute(sa.text("SELECT COUNT(*) FROM conversations")).scalar_one()
    owner_user_id = _resolve_owner(connection) if conversation_count else None
    _backfill(connection, owner_user_id)
    _finalize_conversations(connection)


def downgrade() -> None:
    connection = op.get_bind()
    if "workspace_id" in _column_names(connection, "conversations"):
        with op.batch_alter_table("conversations") as batch_op:
            batch_op.drop_column("workspace_id")
    if "platform_role" in _column_names(connection, "users"):
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_column("platform_role")
    tables = _table_names(connection)
    for table_name in ("migration_states", "workspace_memberships", "workspaces"):
        if table_name in tables:
            op.drop_table(table_name)
