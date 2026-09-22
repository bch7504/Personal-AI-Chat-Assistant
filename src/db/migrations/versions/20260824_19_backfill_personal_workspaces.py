"""Backfill the Personal Space invariant for every existing user.

Accounts created through imports, fixtures or older administrative flows may
not have passed through the registration service. Personal APIs resolve this
internal namespace from the authenticated user and must never require the UI
to provide an organization ``workspace_id``.
"""

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "20260824_19"
down_revision = "20260824_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    now = datetime.now(UTC)
    missing_users = connection.execute(
        sa.text(
            "SELECT u.id, u.display_name, u.created_at "
            "FROM users AS u "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM workspaces AS w "
            "  WHERE w.type = 'personal' AND w.personal_owner_user_id = u.id"
            ") "
            "ORDER BY u.created_at, u.id"
        )
    ).mappings()

    for user in missing_users:
        connection.execute(
            sa.text(
                "INSERT INTO workspaces "
                "(id, type, name, slug, personal_owner_user_id, status, created_at, updated_at) "
                "VALUES (:id, 'personal', :name, NULL, :owner_id, 'active', :created_at, :updated_at)"
            ),
            {
                "id": uuid4().hex,
                "name": f"{user['display_name']}'s Personal Space",
                "owner_id": user["id"],
                "created_at": user["created_at"] or now,
                "updated_at": now,
            },
        )


def downgrade() -> None:
    # Deleting repaired Personal Spaces would orphan their personal resources.
    pass
