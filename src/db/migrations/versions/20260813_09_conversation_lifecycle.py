"""Add per-user conversation hiding."""

import sqlalchemy as sa
from alembic import op

revision = "20260813_09"
down_revision = "20260810_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("conversation_participants")}
    if "hidden_at" not in columns:
        with op.batch_alter_table("conversation_participants") as batch_op:
            batch_op.add_column(sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("conversation_participants")}
    if "hidden_at" in columns:
        with op.batch_alter_table("conversation_participants") as batch_op:
            batch_op.drop_column("hidden_at")
