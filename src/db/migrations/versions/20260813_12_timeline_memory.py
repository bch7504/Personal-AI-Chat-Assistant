"""Add governed long-term memory metadata for timeline-aware agents."""

import sqlalchemy as sa
from alembic import op

revision = "20260813_12"
down_revision = "20260815_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "agent_threads" not in inspector.get_table_names():
        op.create_table(
            "agent_threads",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("owner_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=False),
            sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_agent_threads_owner_id", "agent_threads", ["owner_id"])
        op.create_index("ix_agent_threads_workspace_id", "agent_threads", ["workspace_id"])
        op.create_index(
            "ix_agent_threads_owner_last_active",
            "agent_threads",
            ["owner_id", "last_active_at"],
        )
        op.create_index("ix_agent_threads_expires_at", "agent_threads", ["expires_at"])
    columns = {column["name"] for column in inspector.get_columns("memories")}
    with op.batch_alter_table("memories") as batch_op:
        if "memory_type" not in columns:
            batch_op.add_column(
                sa.Column("memory_type", sa.String(), nullable=False, server_default="semantic")
            )
        if "source_conversation_id" not in columns:
            batch_op.add_column(sa.Column("source_conversation_id", sa.String(), nullable=True))
            batch_op.create_foreign_key(
                "fk_memories_source_conversation_id_conversations",
                "conversations",
                ["source_conversation_id"],
                ["id"],
            )
            batch_op.create_index(
                "ix_memories_source_conversation_id", ["source_conversation_id"], unique=False
            )
        if "source_message_ids" not in columns:
            batch_op.add_column(
                sa.Column("source_message_ids", sa.JSON(), nullable=False, server_default="[]")
            )
        if "consent_scope_hash" not in columns:
            batch_op.add_column(sa.Column("consent_scope_hash", sa.String(), nullable=True))
            batch_op.create_index("ix_memories_consent_scope_hash", ["consent_scope_hash"], unique=False)
        if "sensitivity" not in columns:
            batch_op.add_column(
                sa.Column("sensitivity", sa.String(), nullable=False, server_default="normal")
            )
        if "confidence" not in columns:
            batch_op.add_column(sa.Column("confidence", sa.Float(), nullable=False, server_default="1"))
        if "expires_at" not in columns:
            batch_op.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
            batch_op.create_index("ix_memories_expires_at", ["expires_at"], unique=False)
        if "last_accessed_at" not in columns:
            batch_op.add_column(sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True))

    # Legacy deployments used values such as ``fact`` before governed memory
    # types existed. Normalize them before adding the database constraint so a
    # valid pre-existing row cannot make the whole migration rollback.
    connection.execute(
        sa.text(
            "UPDATE memories SET memory_type = 'semantic' "
            "WHERE memory_type IS NULL OR memory_type NOT IN "
            "('preference', 'relationship', 'episodic', 'semantic')"
        )
    )

    inspector = sa.inspect(connection)
    index_names = {index["name"] for index in inspector.get_indexes("memories")}
    constraint_names = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("memories")
        if constraint.get("name")
    }
    with op.batch_alter_table("memories") as batch_op:
        if "ix_memories_owner_type_expiry" not in index_names:
            batch_op.create_index(
                "ix_memories_owner_type_expiry",
                ["owner_id", "memory_type", "expires_at"],
                unique=False,
            )
        if "ck_memory_type" not in constraint_names:
            batch_op.create_check_constraint(
                "ck_memory_type",
                "memory_type IN ('preference', 'relationship', 'episodic', 'semantic')",
            )
        if "ck_memory_sensitivity" not in constraint_names:
            batch_op.create_check_constraint(
                "ck_memory_sensitivity", "sensitivity IN ('normal', 'sensitive')"
            )


def downgrade() -> None:
    with op.batch_alter_table("memories") as batch_op:
        batch_op.drop_constraint("ck_memory_sensitivity", type_="check")
        batch_op.drop_constraint("ck_memory_type", type_="check")
        batch_op.drop_index("ix_memories_owner_type_expiry")
        batch_op.drop_index("ix_memories_expires_at")
        batch_op.drop_index("ix_memories_consent_scope_hash")
        batch_op.drop_index("ix_memories_source_conversation_id")
        batch_op.drop_constraint(
            "fk_memories_source_conversation_id_conversations", type_="foreignkey"
        )
        batch_op.drop_column("last_accessed_at")
        batch_op.drop_column("expires_at")
        batch_op.drop_column("confidence")
        batch_op.drop_column("sensitivity")
        batch_op.drop_column("consent_scope_hash")
        batch_op.drop_column("source_message_ids")
        batch_op.drop_column("source_conversation_id")
        batch_op.drop_column("memory_type")
    op.drop_index("ix_agent_threads_expires_at", table_name="agent_threads")
    op.drop_index("ix_agent_threads_owner_last_active", table_name="agent_threads")
    op.drop_index("ix_agent_threads_workspace_id", table_name="agent_threads")
    op.drop_index("ix_agent_threads_owner_id", table_name="agent_threads")
    op.drop_table("agent_threads")
