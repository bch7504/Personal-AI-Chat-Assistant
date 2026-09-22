"""Add normalized Quality, HITL proposal and workspace outbox control planes."""

import sqlalchemy as sa
from alembic import op

revision = "20260826_24"
down_revision = "20260826_23"
branch_labels = None
depends_on = None


def _scope_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("agent_workspace_id", sa.String(), sa.ForeignKey("agent_workspaces.id"), nullable=False),
        sa.Column("conversation_id", sa.String(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("release_id", sa.String(), nullable=False),
    ]


def _version_columns() -> list[sa.Column]:
    return [
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "quality_evidence" not in tables:
        op.create_table(
            "quality_evidence", *_scope_columns(),
            sa.Column("artifact_type", sa.String(), nullable=False),
            sa.Column("uri", sa.String(), nullable=False),
            sa.Column("sha256", sa.String(), nullable=True),
            sa.Column("verification_status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("submitted_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("verified_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            *_version_columns(),
            sa.CheckConstraint("artifact_type IN ('url','report','log','screenshot','other')", name="ck_quality_evidence_type"),
            sa.CheckConstraint("verification_status IN ('pending','verified','rejected')", name="ck_quality_evidence_verification"),
        )
        op.create_index("ix_quality_evidence_scope", "quality_evidence", ["workspace_id", "agent_workspace_id", "conversation_id", "release_id"])
    if "quality_requirements" not in tables:
        op.create_table(
            "quality_requirements", *_scope_columns(),
            sa.Column("requirement_key", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            *_version_columns(),
            sa.UniqueConstraint("workspace_id", "agent_workspace_id", "release_id", "requirement_key", name="uq_quality_requirement_key"),
            sa.CheckConstraint("status IN ('active','deprecated')", name="ck_quality_requirement_status"),
        )
        op.create_index("ix_quality_requirements_scope", "quality_requirements", ["workspace_id", "agent_workspace_id", "conversation_id", "release_id", "status"])
    if "quality_test_cases" not in tables:
        op.create_table(
            "quality_test_cases", *_scope_columns(),
            sa.Column("requirement_id", sa.String(), sa.ForeignKey("quality_requirements.id"), nullable=True),
            sa.Column("test_case_key", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("test_kind", sa.String(), nullable=False, server_default="functional"),
            sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            *_version_columns(),
            sa.UniqueConstraint("workspace_id", "agent_workspace_id", "release_id", "test_case_key", name="uq_quality_test_case_key"),
            sa.CheckConstraint("test_kind IN ('functional','regression','security','performance','compliance')", name="ck_quality_test_case_kind"),
            sa.CheckConstraint("status IN ('active','deprecated')", name="ck_quality_test_case_status"),
        )
        op.create_index("ix_quality_test_cases_scope", "quality_test_cases", ["workspace_id", "agent_workspace_id", "conversation_id", "release_id", "status"])
    if "quality_test_runs" not in tables:
        op.create_table(
            "quality_test_runs", *_scope_columns(),
            sa.Column("test_case_id", sa.String(), sa.ForeignKey("quality_test_cases.id"), nullable=False),
            sa.Column("release_candidate_id", sa.String(), sa.ForeignKey("release_candidates.id"), nullable=True),
            sa.Column("evidence_id", sa.String(), sa.ForeignKey("quality_evidence.id"), nullable=True),
            sa.Column("build_number", sa.String(), nullable=False),
            sa.Column("environment", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="queued"),
            sa.Column("executed_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            *_version_columns(),
            sa.CheckConstraint("status IN ('queued','running','passed','failed','blocked','cancelled')", name="ck_quality_test_run_status"),
        )
        op.create_index("ix_quality_test_runs_scope", "quality_test_runs", ["workspace_id", "agent_workspace_id", "conversation_id", "release_id", "status"])
    if "quality_defects" not in tables:
        op.create_table(
            "quality_defects", *_scope_columns(),
            sa.Column("defect_key", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("severity", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="open"),
            sa.Column("test_run_id", sa.String(), sa.ForeignKey("quality_test_runs.id"), nullable=True),
            sa.Column("requirement_id", sa.String(), sa.ForeignKey("quality_requirements.id"), nullable=True),
            sa.Column("evidence_id", sa.String(), sa.ForeignKey("quality_evidence.id"), nullable=True),
            sa.Column("owner_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            *_version_columns(),
            sa.UniqueConstraint("workspace_id", "agent_workspace_id", "release_id", "defect_key", name="uq_quality_defect_key"),
            sa.CheckConstraint("severity IN ('low','medium','high','critical')", name="ck_quality_defect_severity"),
            sa.CheckConstraint("status IN ('open','triaged','in_progress','resolved','verified','waived','closed')", name="ck_quality_defect_status"),
        )
        op.create_index("ix_quality_defects_scope", "quality_defects", ["workspace_id", "agent_workspace_id", "conversation_id", "release_id", "status"])
    if "quality_policies" not in tables:
        op.create_table(
            "quality_policies",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column("agent_workspace_id", sa.String(), sa.ForeignKey("agent_workspaces.id"), nullable=False),
            sa.Column("version", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="draft"),
            sa.Column("rules", sa.JSON(), nullable=False),
            sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("approved_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            *_version_columns(),
            sa.UniqueConstraint("agent_workspace_id", "version", name="uq_quality_policy_version"),
            sa.CheckConstraint("status IN ('draft','active','retired')", name="ck_quality_policy_status"),
        )
        op.create_index("ix_quality_policy_active", "quality_policies", ["workspace_id", "agent_workspace_id", "status"])
    if "quality_waivers" not in tables:
        op.create_table(
            "quality_waivers",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column("agent_workspace_id", sa.String(), sa.ForeignKey("agent_workspaces.id"), nullable=False),
            sa.Column("release_id", sa.String(), nullable=False),
            sa.Column("target_type", sa.String(), nullable=False),
            sa.Column("target_id", sa.String(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("requested_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("decided_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            *_version_columns(),
            sa.CheckConstraint("target_type IN ('defect','test_run','requirement')", name="ck_quality_waiver_target_type"),
            sa.CheckConstraint("status IN ('pending','approved','rejected','expired','revoked')", name="ck_quality_waiver_status"),
        )
        op.create_index("ix_quality_waivers_scope", "quality_waivers", ["workspace_id", "agent_workspace_id", "release_id", "status"])
    if "workspace_action_proposals" not in tables:
        op.create_table(
            "workspace_action_proposals",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column("agent_workspace_id", sa.String(), sa.ForeignKey("agent_workspaces.id"), nullable=False),
            sa.Column("agent_profile", sa.String(), nullable=False),
            sa.Column("actor_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("payload_hash", sa.String(), nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("authorization_scope_hash", sa.String(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("decided_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("result_json", sa.JSON(), nullable=True),
            *_version_columns(),
            sa.UniqueConstraint("idempotency_key", name="uq_workspace_action_proposal_idempotency"),
            sa.CheckConstraint("status IN ('pending','approved','rejected','executed','expired','failed')", name="ck_workspace_action_proposal_status"),
        )
        op.create_index("ix_workspace_action_proposals_scope", "workspace_action_proposals", ["workspace_id", "agent_workspace_id", "actor_user_id", "status"])
    if "workspace_outbox_events" not in tables:
        op.create_table(
            "workspace_outbox_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column("aggregate_type", sa.String(), nullable=False),
            sa.Column("aggregate_id", sa.String(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("idempotency_key", name="uq_workspace_outbox_event_idempotency"),
            sa.CheckConstraint("status IN ('pending','processing','processed','failed','dead_letter')", name="ck_workspace_outbox_event_status"),
        )
        op.create_index("ix_workspace_outbox_pending", "workspace_outbox_events", ["status", "available_at", "created_at"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for name in (
        "workspace_outbox_events", "workspace_action_proposals", "quality_waivers",
        "quality_policies", "quality_defects", "quality_test_runs", "quality_test_cases",
        "quality_requirements", "quality_evidence",
    ):
        if name in tables:
            op.drop_table(name)
