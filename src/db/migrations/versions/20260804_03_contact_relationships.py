"""Add private workspace relationship records."""

import sqlalchemy as sa
from alembic import op

revision = "20260804_03"
down_revision = "20260803_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if "contact_relationships" in set(sa.inspect(connection).get_table_names()):
        return
    op.create_table(
        "contact_relationships",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("owner_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("subject_kind", sa.String(), nullable=False),
        sa.Column("subject_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "subject_external_contact_id",
            sa.String(),
            sa.ForeignKey("external_contacts.id"),
            nullable=True,
        ),
        sa.Column("relationship_type", sa.String(), nullable=False),
        sa.Column("custom_label", sa.String(), nullable=True),
        sa.Column("strength", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("last_interaction_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "((subject_user_id IS NOT NULL) AND (subject_external_contact_id IS NULL)) OR "
            "((subject_user_id IS NULL) AND (subject_external_contact_id IS NOT NULL))",
            name="ck_contact_relationship_exactly_one_subject",
        ),
        sa.CheckConstraint(
            "(subject_kind = 'workspace_user' AND subject_user_id IS NOT NULL "
            "AND subject_external_contact_id IS NULL) OR "
            "(subject_kind = 'external_contact' AND subject_user_id IS NULL "
            "AND subject_external_contact_id IS NOT NULL)",
            name="ck_contact_relationship_kind_matches_subject",
        ),
        sa.CheckConstraint("strength >= 1 AND strength <= 5", name="ck_contact_relationship_strength"),
        sa.CheckConstraint(
            "relationship_type IN ('colleague', 'manager', 'direct_report', 'client', 'partner', "
            "'vendor', 'friend', 'mentor', 'other')",
            name="ck_contact_relationship_type",
        ),
        sa.CheckConstraint(
            "status IN ('suggested', 'active', 'archived', 'rejected')",
            name="ck_contact_relationship_status",
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'ai_suggested', 'imported')",
            name="ck_contact_relationship_source",
        ),
        sa.CheckConstraint(
            "subject_user_id IS NULL OR owner_user_id <> subject_user_id",
            name="ck_contact_relationship_not_self",
        ),
    )
    op.create_index("ix_contact_relationships_workspace_id", "contact_relationships", ["workspace_id"])
    op.create_index("ix_contact_relationships_owner_user_id", "contact_relationships", ["owner_user_id"])
    op.create_index("ix_contact_relationships_subject_user_id", "contact_relationships", ["subject_user_id"])
    op.create_index(
        "ix_contact_relationships_subject_external_contact_id",
        "contact_relationships",
        ["subject_external_contact_id"],
    )
    op.create_index(
        "uq_contact_relationship_workspace_user",
        "contact_relationships",
        ["workspace_id", "owner_user_id", "subject_user_id"],
        unique=True,
        sqlite_where=sa.text("subject_user_id IS NOT NULL"),
        postgresql_where=sa.text("subject_user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_contact_relationship_external",
        "contact_relationships",
        ["workspace_id", "owner_user_id", "subject_external_contact_id"],
        unique=True,
        sqlite_where=sa.text("subject_external_contact_id IS NOT NULL"),
        postgresql_where=sa.text("subject_external_contact_id IS NOT NULL"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    if "contact_relationships" in set(sa.inspect(connection).get_table_names()):
        op.drop_table("contact_relationships")
