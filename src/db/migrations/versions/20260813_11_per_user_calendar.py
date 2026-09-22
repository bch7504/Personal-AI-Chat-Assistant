"""Add encrypted per-user Google Calendar credentials."""

import sqlalchemy as sa
from alembic import op

revision = "20260813_11"
down_revision = "20260813_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "google_calendar_credentials" not in inspector.get_table_names():
        op.create_table(
            "google_calendar_credentials",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("google_email", sa.String(), nullable=False),
            sa.Column("refresh_token_enc", sa.Text(), nullable=False),
            sa.Column("access_token_enc", sa.Text(), nullable=True),
            sa.Column("token_expiry", sa.DateTime(timezone=True), nullable=True),
            sa.Column("scopes", sa.String(), nullable=False),
            sa.Column("sync_token", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id"),
        )
        op.create_index(
            "ix_google_calendar_credentials_user_id",
            "google_calendar_credentials",
            ["user_id"],
            unique=True,
        )

    candidate_columns = {column["name"] for column in inspector.get_columns("event_candidates")}
    if "calendar_owner_user_id" not in candidate_columns:
        with op.batch_alter_table("event_candidates") as batch_op:
            batch_op.add_column(sa.Column("calendar_owner_user_id", sa.String(), nullable=True))
            batch_op.create_foreign_key(
                "fk_event_candidates_calendar_owner_user_id_users",
                "users",
                ["calendar_owner_user_id"],
                ["id"],
            )
            batch_op.create_index(
                "ix_event_candidates_calendar_owner_user_id",
                ["calendar_owner_user_id"],
                unique=False,
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    candidate_columns = {column["name"] for column in inspector.get_columns("event_candidates")}
    if "calendar_owner_user_id" in candidate_columns:
        with op.batch_alter_table("event_candidates") as batch_op:
            batch_op.drop_index("ix_event_candidates_calendar_owner_user_id")
            batch_op.drop_constraint("fk_event_candidates_calendar_owner_user_id_users", type_="foreignkey")
            batch_op.drop_column("calendar_owner_user_id")
    if "google_calendar_credentials" in inspector.get_table_names():
        op.drop_index(
            "ix_google_calendar_credentials_user_id",
            table_name="google_calendar_credentials",
        )
        op.drop_table("google_calendar_credentials")
