"""Link private reminders to Google Calendar events."""

import sqlalchemy as sa
from alembic import op

revision = "20260831_33"
down_revision = "20260830_32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "reminders" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("reminders")}
    with op.batch_alter_table("reminders") as batch_op:
        if "calendar_event_id" not in columns:
            batch_op.add_column(sa.Column("calendar_event_id", sa.String(), nullable=True))
        if "lead_minutes" not in columns:
            batch_op.add_column(
                sa.Column("lead_minutes", sa.Integer(), nullable=False, server_default="30")
            )

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("reminders")}
    if "uq_reminders_owner_calendar_event" not in indexes:
        op.create_index(
            "uq_reminders_owner_calendar_event",
            "reminders",
            ["owner_id", "calendar_event_id"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "reminders" not in inspector.get_table_names():
        return

    indexes = {index["name"] for index in inspector.get_indexes("reminders")}
    if "uq_reminders_owner_calendar_event" in indexes:
        op.drop_index("uq_reminders_owner_calendar_event", table_name="reminders")

    columns = {column["name"] for column in inspector.get_columns("reminders")}
    with op.batch_alter_table("reminders") as batch_op:
        if "lead_minutes" in columns:
            batch_op.drop_column("lead_minutes")
        if "calendar_event_id" in columns:
            batch_op.drop_column("calendar_event_id")
