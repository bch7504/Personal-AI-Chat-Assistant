"""Add Product Delivery agent-first run lineage."""

import sqlalchemy as sa
from alembic import op

revision = "20260827_26"
down_revision = "20260826_25"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "delivery_agent_runs" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("delivery_agent_runs")}
    if "lineage_json" not in columns:
        op.add_column(
            "delivery_agent_runs",
            sa.Column("lineage_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "delivery_agent_runs" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("delivery_agent_runs")}
    if "lineage_json" in columns:
        op.drop_column("delivery_agent_runs", "lineage_json")
