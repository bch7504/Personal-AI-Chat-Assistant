"""Add the user-owned Personal Assistant thread index."""

import sqlalchemy as sa
from alembic import op

revision = "20260815_12"
down_revision = "20260813_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "assistant_threads" in inspector.get_table_names():
        return
    op.create_table(
        "assistant_threads",
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("preview", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("thread_id", "owner_id"),
    )
    op.create_index("ix_assistant_threads_owner_id", "assistant_threads", ["owner_id"], unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "assistant_threads" not in inspector.get_table_names():
        return
    op.drop_index("ix_assistant_threads_owner_id", table_name="assistant_threads")
    op.drop_table("assistant_threads")
