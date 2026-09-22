"""Add sparse private preferences for the people-intelligence layer."""

import sqlalchemy as sa
from alembic import op

revision = "20260806_05"
down_revision = "20260805_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if "people_preferences" not in sa.inspect(connection).get_table_names():
        op.create_table(
            "people_preferences",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("workspace_id", sa.String(), nullable=False),
            sa.Column("owner_user_id", sa.String(), nullable=False),
            sa.Column("subject_user_id", sa.String(), nullable=False),
            sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("private_note", sa.Text(), nullable=True),
            sa.Column("follow_up_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["subject_user_id"], ["users.id"]),
            sa.UniqueConstraint(
                "workspace_id",
                "owner_user_id",
                "subject_user_id",
                name="uq_people_preference_workspace_owner_subject",
            ),
            sa.CheckConstraint(
                "owner_user_id <> subject_user_id",
                name="ck_people_preference_not_self",
            ),
        )

    existing_indexes = {
        item["name"] for item in sa.inspect(connection).get_indexes("people_preferences")
    }
    indexes = {
        "ix_people_preferences_workspace_id": ["workspace_id"],
        "ix_people_preferences_owner_user_id": ["owner_user_id"],
        "ix_people_preferences_subject_user_id": ["subject_user_id"],
        "ix_people_preferences_workspace_owner_pinned": [
            "workspace_id",
            "owner_user_id",
            "is_pinned",
        ],
        "ix_people_preferences_workspace_owner_follow_up": [
            "workspace_id",
            "owner_user_id",
            "follow_up_at",
        ],
    }
    for name, columns in indexes.items():
        if name not in existing_indexes:
            op.create_index(name, "people_preferences", columns)


def downgrade() -> None:
    op.drop_table("people_preferences")
