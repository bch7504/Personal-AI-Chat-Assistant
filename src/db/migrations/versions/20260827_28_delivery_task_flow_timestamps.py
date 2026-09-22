"""Capture task start timestamps for deterministic Delivery flow metrics."""

import sqlalchemy as sa
from alembic import op

revision = "20260827_28"
down_revision = "20260827_27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tasks" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("tasks")}
    if "started_at" not in columns:
        op.add_column("tasks", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tasks" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("tasks")}
    if "started_at" in columns:
        op.drop_column("tasks", "started_at")
