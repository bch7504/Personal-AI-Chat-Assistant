"""Add Google sign-in identities and per-user conversation AI consent."""

import sqlalchemy as sa
from alembic import op

revision = "20260806_06"
down_revision = "20260806_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    tables = set(sa.inspect(connection).get_table_names())

    if "google_identities" not in tables:
        op.create_table(
            "google_identities",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("google_sub", sa.String(), nullable=False),
            sa.Column("email", sa.String(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id"),
        )
        op.create_index("ix_google_identities_user_id", "google_identities", ["user_id"], unique=True)
        op.create_index("ix_google_identities_google_sub", "google_identities", ["google_sub"], unique=True)

    if "ai_permissions" not in tables:
        op.create_table(
            "ai_permissions",
            sa.Column("conversation_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("granted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("conversation_id", "user_id"),
        )

    if "reminders" in tables:
        constraints = {
            item["name"] for item in sa.inspect(connection).get_check_constraints("reminders")
        }
        if "ck_reminder_source" in constraints:
            with op.batch_alter_table(
                "reminders", reflect_kwargs={"resolve_fks": False}
            ) as batch_op:
                batch_op.drop_constraint("ck_reminder_source", type_="check")
                batch_op.create_check_constraint(
                    "ck_reminder_source",
                    "source IN ('manual', 'agent', 'proactive')",
                )


def downgrade() -> None:
    with op.batch_alter_table(
        "reminders", reflect_kwargs={"resolve_fks": False}
    ) as batch_op:
        batch_op.drop_constraint("ck_reminder_source", type_="check")
        batch_op.create_check_constraint(
            "ck_reminder_source",
            "source IN ('manual', 'agent')",
        )
    op.drop_table("ai_permissions")
    op.drop_table("google_identities")
