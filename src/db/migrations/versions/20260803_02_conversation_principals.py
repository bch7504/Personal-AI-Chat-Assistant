"""Add scoped conversation principals and support audit tables."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "20260803_02"
down_revision = "20260803_01"
branch_labels = None
depends_on = None


def _uuid() -> str:
    return uuid4().hex


def _table_names(connection) -> set[str]:
    return set(sa.inspect(connection).get_table_names())


def _column_names(connection, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(connection).get_columns(table_name)}


def _create_support_tables(connection) -> None:
    tables = _table_names(connection)
    now = sa.DateTime(timezone=True)
    if "support_access_grants" not in tables:
        op.create_table(
            "support_access_grants",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("platform_admin_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column("requested_scope", sa.String(), nullable=False),
            sa.Column("scope_json", sa.JSON(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="requested"),
            sa.Column("approved_by_owner_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", now, nullable=False),
            sa.Column("approved_at", now, nullable=True),
            sa.Column("expires_at", now, nullable=False),
            sa.Column("revoked_at", now, nullable=True),
        )
        op.create_index("ix_support_access_grants_platform_admin_id", "support_access_grants", ["platform_admin_id"])
        op.create_index("ix_support_access_grants_workspace_id", "support_access_grants", ["workspace_id"])
    if "audit_logs" not in tables:
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=True),
            sa.Column("actor_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("actor_type", sa.String(), nullable=False),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("target_type", sa.String(), nullable=False),
            sa.Column("target_id", sa.String(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("ip_address", sa.String(), nullable=True),
            sa.Column("created_at", now, nullable=False),
        )
        op.create_index("ix_audit_logs_workspace_id", "audit_logs", ["workspace_id"])
        op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])
        op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    if "migration_states" in tables:
        columns = _column_names(connection, "migration_states")
        if "migration_version" not in columns:
            op.add_column(
                "migration_states",
                sa.Column("migration_version", sa.String(), nullable=False, server_default="workspace_foundation_v1"),
            )
        if "error_message" not in columns:
            op.add_column("migration_states", sa.Column("error_message", sa.String(), nullable=True))


def _replace_participant_table(connection) -> None:
    if "conversation_participants" not in _table_names(connection):
        return
    if "id" in _column_names(connection, "conversation_participants"):
        return

    op.create_table(
        "conversation_participants_v2",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("conversation_id", sa.String(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("principal_kind", sa.String(), nullable=False, server_default="workspace_user"),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("external_contact_id", sa.String(), sa.ForeignKey("external_contacts.id"), nullable=True),
        sa.Column("resource_role", sa.String(), nullable=False, server_default="participant"),
        sa.Column("invited_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "((user_id IS NOT NULL) AND (external_contact_id IS NULL)) OR "
            "((user_id IS NULL) AND (external_contact_id IS NOT NULL))",
            name="ck_conversation_participant_exactly_one_principal",
        ),
        sa.CheckConstraint(
            "(principal_kind = 'workspace_user' AND user_id IS NOT NULL AND external_contact_id IS NULL) OR "
            "(principal_kind = 'external_contact' AND user_id IS NULL AND external_contact_id IS NOT NULL)",
            name="ck_conversation_participant_kind_matches_principal",
        ),
        sa.CheckConstraint(
            "resource_role IN ('manager', 'participant', 'viewer')",
            name="ck_conversation_participant_resource_role",
        ),
    )
    connection.execute(
        sa.text(
            "INSERT INTO conversation_participants_v2 "
            "(id, conversation_id, principal_kind, user_id, resource_role, joined_at, last_read_at) "
            "SELECT :prefix || conversation_id || ':' || user_id, conversation_id, 'workspace_user', "
            "user_id, 'participant', joined_at, last_read_at FROM conversation_participants"
        ),
        {"prefix": _uuid() + ":"},
    )
    op.drop_table("conversation_participants")
    op.rename_table("conversation_participants_v2", "conversation_participants")
    op.create_index("ix_conversation_participants_conversation_id", "conversation_participants", ["conversation_id"])
    op.create_index("ix_conversation_participants_user_id", "conversation_participants", ["user_id"])
    op.create_index(
        "ix_conversation_participants_external_contact_id", "conversation_participants", ["external_contact_id"]
    )
    op.create_index(
        "uq_conversation_participant_user",
        "conversation_participants",
        ["conversation_id", "user_id"],
        unique=True,
        sqlite_where=sa.text("user_id IS NOT NULL"),
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_conversation_participant_external",
        "conversation_participants",
        ["conversation_id", "external_contact_id"],
        unique=True,
        sqlite_where=sa.text("external_contact_id IS NOT NULL"),
        postgresql_where=sa.text("external_contact_id IS NOT NULL"),
    )


def upgrade() -> None:
    connection = op.get_bind()
    if "external_contacts" not in _table_names(connection):
        op.create_table(
            "external_contacts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column("email", sa.String(), nullable=False),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("organization", sa.String(), nullable=True),
            sa.Column("linked_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="invited"),
            sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("workspace_id", "email", name="uq_external_contact_workspace_email"),
            sa.CheckConstraint(
                "status IN ('invited', 'active', 'revoked')",
                name="ck_external_contact_status",
            ),
        )
        op.create_index("ix_external_contacts_workspace_id", "external_contacts", ["workspace_id"])
        op.create_index("ix_external_contacts_linked_user_id", "external_contacts", ["linked_user_id"])
    _replace_participant_table(connection)
    _create_support_tables(connection)


def downgrade() -> None:
    connection = op.get_bind()
    if "conversation_participants" in _table_names(connection) and "id" in _column_names(
        connection, "conversation_participants"
    ):
        op.create_table(
            "conversation_participants_legacy",
            sa.Column("conversation_id", sa.String(), sa.ForeignKey("conversations.id"), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=False),
        )
        connection.execute(
            sa.text(
                "INSERT INTO conversation_participants_legacy "
                "SELECT conversation_id, user_id, joined_at, last_read_at "
                "FROM conversation_participants WHERE principal_kind = 'workspace_user' AND user_id IS NOT NULL"
            )
        )
        op.drop_table("conversation_participants")
        op.rename_table("conversation_participants_legacy", "conversation_participants")
    for table in ("audit_logs", "support_access_grants", "external_contacts"):
        if table in _table_names(connection):
            op.drop_table(table)
