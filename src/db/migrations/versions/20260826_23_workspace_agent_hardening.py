"""Add optimistic concurrency to QA work items."""

import sqlalchemy as sa
from alembic import op

revision = "20260826_23"
down_revision = "20260825_22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "tasks" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("tasks")}
    if "row_version" not in columns:
        with op.batch_alter_table("tasks", reflect_kwargs={"resolve_fks": False}) as batch_op:
            batch_op.add_column(
                sa.Column("row_version", sa.Integer(), nullable=False, server_default="1")
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "tasks" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("tasks")}
    if "row_version" in columns:
        with op.batch_alter_table("tasks", reflect_kwargs={"resolve_fks": False}) as batch_op:
            batch_op.drop_column("row_version")
