"""Add runtime-editable system configuration."""

import sqlalchemy as sa
from alembic import op

revision = "20260813_10"
down_revision = "20260813_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "system_config" not in inspector.get_table_names():
        op.create_table(
            "system_config",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("daily_token_budget", sa.Integer(), nullable=True),
            sa.Column("llm_provider", sa.String(), nullable=True),
            sa.Column("model_name", sa.String(), nullable=True),
            sa.Column("llm_temperature", sa.Float(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_by", sa.String(), nullable=True),
            sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "system_config" in inspector.get_table_names():
        op.drop_table("system_config")
