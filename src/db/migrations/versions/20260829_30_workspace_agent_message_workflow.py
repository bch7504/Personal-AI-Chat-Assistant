"""Link persisted workspace-agent answers to their durable workflow."""

import sqlalchemy as sa
from alembic import op

revision = "20260829_30"
down_revision = "20260828_29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "workspace_agent_messages" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("workspace_agent_messages")}
    if "workflow_id" not in columns:
        # Batch mode is required for SQLite test/development databases because
        # SQLite cannot ALTER an existing table to add a foreign key directly.
        # PostgreSQL also supports the generated batch operations.
        with op.batch_alter_table(
            "workspace_agent_messages",
            reflect_kwargs={"resolve_fks": False},
        ) as batch_op:
            batch_op.add_column(sa.Column("workflow_id", sa.String(), nullable=True))
            batch_op.create_foreign_key(
                "fk_workspace_agent_messages_workflow_id",
                "delivery_agent_workflows",
                ["workflow_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_index(
                "ix_workspace_agent_messages_workflow_id",
                ["workflow_id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "workspace_agent_messages" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("workspace_agent_messages")}
    if "workflow_id" in columns:
        with op.batch_alter_table(
            "workspace_agent_messages",
            reflect_kwargs={"resolve_fks": False},
        ) as batch_op:
            batch_op.drop_index("ix_workspace_agent_messages_workflow_id")
            # SQLite does not preserve a user-supplied FK constraint name in
            # reflection. Dropping the column during batch table recreation
            # removes that FK automatically.
            if bind.dialect.name != "sqlite":
                batch_op.drop_constraint(
                    "fk_workspace_agent_messages_workflow_id",
                    type_="foreignkey",
                )
            batch_op.drop_column("workflow_id")
