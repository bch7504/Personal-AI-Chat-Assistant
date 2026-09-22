"""Add durable Product Delivery multi-agent workflow state."""

import sqlalchemy as sa
from alembic import op

revision = "20260826_25"
down_revision = "20260826_24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "delivery_agent_workflows" not in tables:
        op.create_table(
            "delivery_agent_workflows",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column("agent_workspace_id", sa.String(), sa.ForeignKey("agent_workspaces.id"), nullable=False),
            sa.Column("actor_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("actor_role", sa.String(), nullable=False),
            sa.Column("workflow_type", sa.String(), nullable=False),
            sa.Column("execution_mode", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="created"),
            sa.Column("subject_type", sa.String(), nullable=True),
            sa.Column("subject_id", sa.String(), nullable=True),
            sa.Column("subject_version", sa.String(), nullable=True),
            sa.Column("authorization_scope_hash", sa.String(), nullable=True),
            sa.Column("request_hash", sa.String(), nullable=False),
            sa.Column("plan_version", sa.String(), nullable=False),
            sa.Column("result_json", sa.JSON(), nullable=True),
            sa.Column("data_gaps", sa.JSON(), nullable=False),
            sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "status IN ('created','running','waiting_evidence','waiting_approval','completed',"
                "'partial','failed','cancelled','expired')",
                name="ck_delivery_agent_workflow_status",
            ),
            sa.CheckConstraint(
                "execution_mode IN ('single_specialist','multi_specialist')",
                name="ck_delivery_agent_workflow_execution_mode",
            ),
        )
        op.create_index(
            "ix_delivery_agent_workflows_scope",
            "delivery_agent_workflows",
            ["workspace_id", "agent_workspace_id", "actor_user_id", "created_at"],
        )

    if "delivery_agent_runs" not in tables:
        op.create_table(
            "delivery_agent_runs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "workflow_id", sa.String(), sa.ForeignKey("delivery_agent_workflows.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column(
                "parent_run_id", sa.String(), sa.ForeignKey("delivery_agent_runs.id", ondelete="SET NULL"), nullable=True
            ),
            sa.Column("specialist", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("input_hash", sa.String(), nullable=False),
            sa.Column("output_hash", sa.String(), nullable=True),
            sa.Column("prompt_version", sa.String(), nullable=False),
            sa.Column("model_name", sa.String(), nullable=False, server_default=""),
            sa.Column("error_code", sa.String(), nullable=True),
            sa.Column("usage_json", sa.JSON(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "status IN ('pending','running','retry_scheduled','succeeded','partial','failed',"
                "'cancelled','timed_out')",
                name="ck_delivery_agent_run_status",
            ),
            sa.UniqueConstraint("workflow_id", "specialist", "attempt", name="uq_delivery_agent_run_attempt"),
        )
        op.create_index(
            "ix_delivery_agent_runs_workflow",
            "delivery_agent_runs",
            ["workflow_id", "status", "created_at"],
        )

    if "delivery_specialist_results" not in tables:
        op.create_table(
            "delivery_specialist_results",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "workflow_id", sa.String(), sa.ForeignKey("delivery_agent_workflows.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("run_id", sa.String(), sa.ForeignKey("delivery_agent_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("specialist", sa.String(), nullable=False),
            sa.Column("result_type", sa.String(), nullable=False),
            sa.Column("schema_version", sa.String(), nullable=False, server_default="1.0"),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("source_references", sa.JSON(), nullable=False),
            sa.Column("data_gaps", sa.JSON(), nullable=False),
            sa.Column("input_hash", sa.String(), nullable=False),
            sa.Column("output_hash", sa.String(), nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("run_id", name="uq_delivery_specialist_result_run"),
        )
        op.create_index(
            "ix_delivery_specialist_results_workflow",
            "delivery_specialist_results",
            ["workflow_id", "specialist"],
        )

    if "delivery_workflow_events" not in tables:
        op.create_table(
            "delivery_workflow_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "workflow_id", sa.String(), sa.ForeignKey("delivery_agent_workflows.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_delivery_workflow_events_order",
            "delivery_workflow_events",
            ["workflow_id", "created_at", "id"],
        )

    if "delivery_event_inbox" not in tables:
        op.create_table(
            "delivery_event_inbox",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("consumer", sa.String(), nullable=False),
            sa.Column("message_id", sa.String(), nullable=False),
            sa.Column("payload_hash", sa.String(), nullable=False),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("consumer", "message_id", name="uq_delivery_event_inbox_message"),
        )

    if "workspace_action_proposals" in tables:
        columns = {column["name"] for column in sa.inspect(bind).get_columns("workspace_action_proposals")}
        if "workflow_id" not in columns:
            op.add_column("workspace_action_proposals", sa.Column("workflow_id", sa.String(), nullable=True))
            op.create_index(
                "ix_workspace_action_proposals_workflow_id",
                "workspace_action_proposals",
                ["workflow_id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "workspace_action_proposals" in tables:
        columns = {column["name"] for column in sa.inspect(bind).get_columns("workspace_action_proposals")}
        if "workflow_id" in columns:
            indexes = {item["name"] for item in sa.inspect(bind).get_indexes("workspace_action_proposals")}
            if "ix_workspace_action_proposals_workflow_id" in indexes:
                op.drop_index("ix_workspace_action_proposals_workflow_id", table_name="workspace_action_proposals")
            op.drop_column("workspace_action_proposals", "workflow_id")
    for table in (
        "delivery_event_inbox",
        "delivery_workflow_events",
        "delivery_specialist_results",
        "delivery_agent_runs",
        "delivery_agent_workflows",
    ):
        if table in tables:
            op.drop_table(table)
