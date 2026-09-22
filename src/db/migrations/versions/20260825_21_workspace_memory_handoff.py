"""Add durable workspace-agent memory and Delivery-to-QA release handoff."""

import sqlalchemy as sa
from alembic import op

revision = "20260825_21"
down_revision = "20260825_20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "tasks" in tables:
        checks = {
            item["name"]
            for item in inspector.get_check_constraints("tasks")
            if item.get("name")
        }
        with op.batch_alter_table("tasks", reflect_kwargs={"resolve_fks": False}) as batch_op:
            if "ck_task_quality_shape" in checks:
                batch_op.drop_constraint("ck_task_quality_shape", type_="check")
            batch_op.create_check_constraint(
                "ck_task_quality_shape",
                "(work_item_type IS NULL AND severity IS NULL AND quality_status IS NULL AND release_target IS NULL AND quality_required = false) OR (work_item_type IS NOT NULL AND quality_status IS NOT NULL AND release_target IS NOT NULL AND ((work_item_type = 'bug' AND severity IS NOT NULL) OR (work_item_type != 'bug' AND severity IS NULL)) AND (quality_required = false OR work_item_type = 'release_check'))",
            )

    if "workspace_agent_threads" not in tables:
        op.create_table(
            "workspace_agent_threads",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column("agent_workspace_id", sa.String(), sa.ForeignKey("agent_workspaces.id"), nullable=False),
            sa.Column("owner_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("agent_profile", sa.String(), nullable=False),
            sa.Column("authorization_scope_hash", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "agent_profile IN ('product_delivery', 'quality_assurance')",
                name="ck_workspace_agent_thread_profile",
            ),
            sa.CheckConstraint("status IN ('active', 'archived')", name="ck_workspace_agent_thread_status"),
        )
        op.create_index(
            "ix_workspace_agent_threads_scope",
            "workspace_agent_threads",
            ["organization_workspace_id", "agent_workspace_id", "owner_id", "last_active_at"],
        )
        op.create_index("ix_workspace_agent_threads_expiry", "workspace_agent_threads", ["expires_at"])
        op.create_index(
            "ix_workspace_agent_threads_authorization_scope_hash",
            "workspace_agent_threads",
            ["authorization_scope_hash"],
        )

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "workspace_agent_messages" not in tables:
        op.create_table(
            "workspace_agent_messages",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "thread_id",
                sa.String(),
                sa.ForeignKey("workspace_agent_threads.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("sequence_number", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("thread_id", "sequence_number", name="uq_workspace_agent_message_sequence"),
            sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_workspace_agent_message_role"),
        )
        op.create_index(
            "ix_workspace_agent_messages_thread_sequence",
            "workspace_agent_messages",
            ["thread_id", "sequence_number"],
        )

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "release_candidates" not in tables:
        op.create_table(
            "release_candidates",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column("delivery_agent_workspace_id", sa.String(), sa.ForeignKey("agent_workspaces.id"), nullable=False),
            sa.Column("quality_agent_workspace_id", sa.String(), sa.ForeignKey("agent_workspaces.id"), nullable=True),
            sa.Column("source_conversation_id", sa.String(), sa.ForeignKey("conversations.id"), nullable=False),
            sa.Column("delivery_milestone_id", sa.String(), sa.ForeignKey("delivery_milestones.id"), nullable=True),
            sa.Column("release_key", sa.String(), nullable=False),
            sa.Column("version", sa.String(), nullable=False, server_default=""),
            sa.Column("build_number", sa.String(), nullable=False, server_default=""),
            sa.Column("commit_sha", sa.String(), nullable=True),
            sa.Column("environment", sa.String(), nullable=False, server_default="staging"),
            sa.Column("status", sa.String(), nullable=False, server_default="draft"),
            sa.Column("quality_policy_version", sa.String(), nullable=False, server_default="quality-gate-v1"),
            sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "status IN ('draft', 'qa_requested', 'qa_in_progress', 'approved', 'rejected', "
                "'released', 'cancelled')",
                name="ck_release_candidate_status",
            ),
            sa.UniqueConstraint(
                "organization_workspace_id",
                "release_key",
                "version",
                "build_number",
                name="uq_release_candidate_identity",
            ),
        )
        op.create_index(
            "ix_release_candidates_handoff",
            "release_candidates",
            ["organization_workspace_id", "quality_agent_workspace_id", "status"],
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table_name in ("release_candidates", "workspace_agent_messages", "workspace_agent_threads"):
        if table_name in tables:
            op.drop_table(table_name)
    if "tasks" in tables:
        with op.batch_alter_table("tasks", reflect_kwargs={"resolve_fks": False}) as batch_op:
            batch_op.drop_constraint("ck_task_quality_shape", type_="check")
            batch_op.create_check_constraint(
                "ck_task_quality_shape",
                "(work_item_type IS NULL AND severity IS NULL AND quality_status IS NULL AND release_target IS NULL AND quality_required = false) OR (work_item_type IS NOT NULL AND quality_status IS NOT NULL AND release_target IS NOT NULL AND (work_item_type != 'bug' OR severity IS NOT NULL) AND (quality_required = false OR work_item_type = 'release_check'))",
            )
