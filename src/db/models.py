from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


def _uuid() -> str:
    return uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    password_hash: Mapped[str]
    display_name: Mapped[str]
    role: Mapped[str] = mapped_column(default="user")  # "user" | "admin"
    platform_role: Mapped[str] = mapped_column(default="user")  # "user" | "platform_admin"
    is_active: Mapped[bool] = mapped_column(default=True)
    job_title: Mapped[str] = mapped_column(default="")
    timezone: Mapped[str] = mapped_column(default="Asia/Ho_Chi_Minh")
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class GoogleIdentity(Base):
    """Link a user to a verified Google account used for authentication."""

    __tablename__ = "google_identities"

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    google_sub: Mapped[str] = mapped_column(unique=True, index=True)  # Google's stable subject id
    email: Mapped[str] = mapped_column(default="")  # snapshot at link time, for audit only
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped["User"] = relationship()


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint("type IN ('personal', 'organization')", name="ck_workspace_type"),
        CheckConstraint("status IN ('active', 'suspended', 'deleting')", name="ck_workspace_status"),
        CheckConstraint(
            "(type = 'personal' AND personal_owner_user_id IS NOT NULL) OR "
            "(type = 'organization' AND personal_owner_user_id IS NULL)",
            name="ck_workspace_owner_matches_type",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    type: Mapped[str]
    name: Mapped[str]
    slug: Mapped[str | None] = mapped_column(default=None, unique=True)
    personal_owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), default=None, unique=True, index=True
    )
    status: Mapped[str] = mapped_column(default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class WorkspaceMembership(Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_membership_user"),
        CheckConstraint("role IN ('owner', 'admin', 'member', 'guest')", name="ck_workspace_membership_role"),
        CheckConstraint(
            "status IN ('active', 'invited', 'suspended', 'revoked')",
            name="ck_workspace_membership_status",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str]
    status: Mapped[str] = mapped_column(default="active")
    invited_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AgentWorkspace(Base):
    """A user-facing business workspace with one supporting agent profile."""

    __tablename__ = "agent_workspaces"
    __table_args__ = (
        UniqueConstraint(
            "organization_workspace_id",
            "key",
            name="uq_agent_workspace_organization_key",
        ),
        CheckConstraint(
            "agent_profile IN ('product_delivery', 'quality_assurance', 'executive')",
            name="ck_agent_workspace_profile",
        ),
        CheckConstraint(
            "status IN ('active', 'suspended', 'archived')",
            name="ck_agent_workspace_status",
        ),
        Index(
            "ix_agent_workspaces_organization_status",
            "organization_workspace_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    organization_workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    key: Mapped[str]
    name: Mapped[str]
    agent_profile: Mapped[str]
    status: Mapped[str] = mapped_column(default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AgentWorkspaceMembership(Base):
    __tablename__ = "agent_workspace_memberships"
    __table_args__ = (
        UniqueConstraint(
            "agent_workspace_id",
            "user_id",
            name="uq_agent_workspace_membership_user",
        ),
        CheckConstraint(
            "business_role IN ('member', 'lead', 'executive_viewer')",
            name="ck_agent_workspace_membership_role",
        ),
        CheckConstraint(
            "status IN ('active', 'invited', 'suspended', 'revoked')",
            name="ck_agent_workspace_membership_status",
        ),
        Index(
            "ix_agent_workspace_memberships_user_status",
            "user_id",
            "status",
        ),
        Index(
            "uq_agent_workspace_active_lead",
            "agent_workspace_id",
            unique=True,
            postgresql_where=text("business_role = 'lead' AND status = 'active'"),
            sqlite_where=text("business_role = 'lead' AND status = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    agent_workspace_id: Mapped[str] = mapped_column(ForeignKey("agent_workspaces.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    business_role: Mapped[str]
    status: Mapped[str] = mapped_column(default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class WorkspaceAgentThread(Base):
    """Durable, tenant-bound conversation memory for one workspace agent."""

    __tablename__ = "workspace_agent_threads"
    __table_args__ = (
        CheckConstraint(
            "agent_profile IN ('product_delivery', 'quality_assurance')",
            name="ck_workspace_agent_thread_profile",
        ),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_workspace_agent_thread_status",
        ),
        Index(
            "ix_workspace_agent_threads_scope",
            "organization_workspace_id",
            "agent_workspace_id",
            "owner_id",
            "last_active_at",
        ),
        Index("ix_workspace_agent_threads_expiry", "expires_at"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    organization_workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    agent_workspace_id: Mapped[str] = mapped_column(ForeignKey("agent_workspaces.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    agent_profile: Mapped[str]
    authorization_scope_hash: Mapped[str | None] = mapped_column(default=None, index=True)
    status: Mapped[str] = mapped_column(default="active")
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: _utcnow() + timedelta(days=30)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class WorkspaceAgentMessage(Base):
    """Bounded chat history; tool payloads and authorization snapshots are never persisted."""

    __tablename__ = "workspace_agent_messages"
    __table_args__ = (
        UniqueConstraint("thread_id", "sequence_number", name="uq_workspace_agent_message_sequence"),
        CheckConstraint("role IN ('user', 'assistant')", name="ck_workspace_agent_message_role"),
        Index("ix_workspace_agent_messages_thread_sequence", "thread_id", "sequence_number"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_agent_threads.id", ondelete="CASCADE"), index=True
    )
    workflow_id: Mapped[str | None] = mapped_column(
        ForeignKey("delivery_agent_workflows.id", ondelete="SET NULL"), default=None, index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer)
    role: Mapped[str]
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ReleaseCandidate(Base):
    """Structured Delivery-to-QA handoff that remains available across runtime failures."""

    __tablename__ = "release_candidates"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'qa_requested', 'qa_in_progress', 'approved', 'rejected', "
            "'released', 'cancelled')",
            name="ck_release_candidate_status",
        ),
        UniqueConstraint(
            "organization_workspace_id",
            "release_key",
            "version",
            "build_number",
            name="uq_release_candidate_identity",
        ),
        Index(
            "ix_release_candidates_handoff",
            "organization_workspace_id",
            "quality_agent_workspace_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    organization_workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    delivery_agent_workspace_id: Mapped[str] = mapped_column(ForeignKey("agent_workspaces.id"), index=True)
    quality_agent_workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_workspaces.id"), default=None, index=True
    )
    source_conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    delivery_milestone_id: Mapped[str | None] = mapped_column(
        ForeignKey("delivery_milestones.id"), default=None, index=True
    )
    release_key: Mapped[str]
    version: Mapped[str] = mapped_column(default="")
    build_number: Mapped[str] = mapped_column(default="")
    commit_sha: Mapped[str | None] = mapped_column(default=None)
    environment: Mapped[str] = mapped_column(default="staging")
    status: Mapped[str] = mapped_column(default="draft")
    quality_policy_version: Mapped[str] = mapped_column(default="quality-gate-v1")
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class QualityEvidence(Base):
    """Immutable artifact reference with an explicit human verification state."""

    __tablename__ = "quality_evidence"
    __table_args__ = (
        CheckConstraint(
            "artifact_type IN ('url', 'report', 'log', 'screenshot', 'other')",
            name="ck_quality_evidence_type",
        ),
        CheckConstraint(
            "verification_status IN ('pending', 'verified', 'rejected')",
            name="ck_quality_evidence_verification",
        ),
        Index(
            "ix_quality_evidence_scope",
            "workspace_id",
            "agent_workspace_id",
            "conversation_id",
            "release_id",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    agent_workspace_id: Mapped[str] = mapped_column(ForeignKey("agent_workspaces.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    release_id: Mapped[str] = mapped_column(index=True)
    artifact_type: Mapped[str]
    uri: Mapped[str]
    sha256: Mapped[str | None] = mapped_column(default=None)
    verification_status: Mapped[str] = mapped_column(default="pending")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    submitted_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    verified_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class QualityRequirement(Base):
    __tablename__ = "quality_requirements"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "agent_workspace_id", "release_id", "requirement_key",
            name="uq_quality_requirement_key",
        ),
        CheckConstraint("status IN ('active', 'deprecated')", name="ck_quality_requirement_status"),
        Index(
            "ix_quality_requirements_scope",
            "workspace_id", "agent_workspace_id", "conversation_id", "release_id", "status",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    agent_workspace_id: Mapped[str] = mapped_column(ForeignKey("agent_workspaces.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    release_id: Mapped[str] = mapped_column(index=True)
    requirement_key: Mapped[str]
    title: Mapped[str]
    required: Mapped[bool] = mapped_column(default=True)
    status: Mapped[str] = mapped_column(default="active")
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class QualityTestCase(Base):
    __tablename__ = "quality_test_cases"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "agent_workspace_id", "release_id", "test_case_key",
            name="uq_quality_test_case_key",
        ),
        CheckConstraint(
            "test_kind IN ('functional', 'regression', 'security', 'performance', 'compliance')",
            name="ck_quality_test_case_kind",
        ),
        CheckConstraint("status IN ('active', 'deprecated')", name="ck_quality_test_case_status"),
        Index(
            "ix_quality_test_cases_scope",
            "workspace_id", "agent_workspace_id", "conversation_id", "release_id", "status",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    agent_workspace_id: Mapped[str] = mapped_column(ForeignKey("agent_workspaces.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    release_id: Mapped[str] = mapped_column(index=True)
    requirement_id: Mapped[str | None] = mapped_column(
        ForeignKey("quality_requirements.id"), default=None, index=True
    )
    test_case_key: Mapped[str]
    title: Mapped[str]
    test_kind: Mapped[str] = mapped_column(default="functional")
    required: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(default="active")
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class QualityTestRun(Base):
    __tablename__ = "quality_test_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'passed', 'failed', 'blocked', 'cancelled')",
            name="ck_quality_test_run_status",
        ),
        Index(
            "ix_quality_test_runs_scope",
            "workspace_id", "agent_workspace_id", "conversation_id", "release_id", "status",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    agent_workspace_id: Mapped[str] = mapped_column(ForeignKey("agent_workspaces.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    release_id: Mapped[str] = mapped_column(index=True)
    test_case_id: Mapped[str] = mapped_column(ForeignKey("quality_test_cases.id"), index=True)
    release_candidate_id: Mapped[str | None] = mapped_column(
        ForeignKey("release_candidates.id"), default=None, index=True
    )
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("quality_evidence.id"), default=None)
    build_number: Mapped[str]
    environment: Mapped[str]
    status: Mapped[str] = mapped_column(default="queued")
    executed_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class QualityDefect(Base):
    __tablename__ = "quality_defects"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "agent_workspace_id", "release_id", "defect_key",
            name="uq_quality_defect_key",
        ),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_quality_defect_severity",
        ),
        CheckConstraint(
            "status IN ('open', 'triaged', 'in_progress', 'resolved', 'verified', 'waived', 'closed')",
            name="ck_quality_defect_status",
        ),
        Index(
            "ix_quality_defects_scope",
            "workspace_id", "agent_workspace_id", "conversation_id", "release_id", "status",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    agent_workspace_id: Mapped[str] = mapped_column(ForeignKey("agent_workspaces.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    release_id: Mapped[str] = mapped_column(index=True)
    defect_key: Mapped[str]
    title: Mapped[str]
    severity: Mapped[str]
    status: Mapped[str] = mapped_column(default="open")
    test_run_id: Mapped[str | None] = mapped_column(ForeignKey("quality_test_runs.id"), default=None)
    requirement_id: Mapped[str | None] = mapped_column(ForeignKey("quality_requirements.id"), default=None)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("quality_evidence.id"), default=None)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class QualityPolicy(Base):
    __tablename__ = "quality_policies"
    __table_args__ = (
        UniqueConstraint("agent_workspace_id", "version", name="uq_quality_policy_version"),
        CheckConstraint("status IN ('draft', 'active', 'retired')", name="ck_quality_policy_status"),
        Index("ix_quality_policy_active", "workspace_id", "agent_workspace_id", "status"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    agent_workspace_id: Mapped[str] = mapped_column(ForeignKey("agent_workspaces.id"), index=True)
    version: Mapped[str]
    status: Mapped[str] = mapped_column(default="draft")
    rules: Mapped[dict] = mapped_column(JSON, default=dict)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    approved_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class QualityWaiver(Base):
    __tablename__ = "quality_waivers"
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('defect', 'test_run', 'requirement')",
            name="ck_quality_waiver_target_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'revoked')",
            name="ck_quality_waiver_status",
        ),
        Index(
            "ix_quality_waivers_scope",
            "workspace_id", "agent_workspace_id", "release_id", "status",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    agent_workspace_id: Mapped[str] = mapped_column(ForeignKey("agent_workspaces.id"), index=True)
    release_id: Mapped[str] = mapped_column(index=True)
    target_type: Mapped[str]
    target_id: Mapped[str]
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(default="pending")
    expires_at: Mapped[datetime]
    requested_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    decided_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class WorkspaceActionProposalRecord(Base):
    """Durable HITL envelope; execution is impossible before explicit approval."""

    __tablename__ = "workspace_action_proposals"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_workspace_action_proposal_idempotency"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'executed', 'expired', 'failed')",
            name="ck_workspace_action_proposal_status",
        ),
        Index(
            "ix_workspace_action_proposals_scope",
            "workspace_id", "agent_workspace_id", "actor_user_id", "status",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    agent_workspace_id: Mapped[str] = mapped_column(ForeignKey("agent_workspaces.id"), index=True)
    agent_profile: Mapped[str]
    workflow_id: Mapped[str | None] = mapped_column(default=None, index=True)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str]
    idempotency_key: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")
    authorization_scope_hash: Mapped[str | None] = mapped_column(default=None)
    expires_at: Mapped[datetime]
    decided_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    result_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class WorkspaceOutboxEvent(Base):
    __tablename__ = "workspace_outbox_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_workspace_outbox_event_idempotency"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'processed', 'failed', 'dead_letter')",
            name="ck_workspace_outbox_event_status",
        ),
        Index("ix_workspace_outbox_pending", "status", "available_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    aggregate_type: Mapped[str]
    aggregate_id: Mapped[str]
    event_type: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    idempotency_key: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class DeliveryAgentWorkflow(Base):
    """Durable parent state for one Product Delivery orchestration."""

    __tablename__ = "delivery_agent_workflows"
    __table_args__ = (
        CheckConstraint(
            "status IN ('created','running','waiting_evidence','waiting_approval','completed',"
            "'partial','failed','cancelled','expired')",
            name="ck_delivery_agent_workflow_status",
        ),
        CheckConstraint(
            "execution_mode IN ('single_specialist','multi_specialist')",
            name="ck_delivery_agent_workflow_execution_mode",
        ),
        Index(
            "ix_delivery_agent_workflows_scope",
            "workspace_id",
            "agent_workspace_id",
            "actor_user_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    agent_workspace_id: Mapped[str] = mapped_column(ForeignKey("agent_workspaces.id"), index=True)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    actor_role: Mapped[str]
    workflow_type: Mapped[str]
    execution_mode: Mapped[str]
    status: Mapped[str] = mapped_column(default="created")
    subject_type: Mapped[str | None] = mapped_column(default=None)
    subject_id: Mapped[str | None] = mapped_column(default=None)
    subject_version: Mapped[str | None] = mapped_column(default=None)
    authorization_scope_hash: Mapped[str | None] = mapped_column(default=None)
    request_hash: Mapped[str]
    plan_version: Mapped[str]
    result_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    data_gaps: Mapped[list] = mapped_column(JSON, default=list)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class DeliveryAgentRun(Base):
    __tablename__ = "delivery_agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','retry_scheduled','succeeded','partial','failed',"
            "'cancelled','timed_out')",
            name="ck_delivery_agent_run_status",
        ),
        UniqueConstraint("workflow_id", "specialist", "attempt", name="uq_delivery_agent_run_attempt"),
        Index("ix_delivery_agent_runs_workflow", "workflow_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("delivery_agent_workflows.id", ondelete="CASCADE"), index=True
    )
    parent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("delivery_agent_runs.id", ondelete="SET NULL"), default=None
    )
    specialist: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    input_hash: Mapped[str]
    output_hash: Mapped[str | None] = mapped_column(default=None)
    prompt_version: Mapped[str]
    model_name: Mapped[str] = mapped_column(default="")
    error_code: Mapped[str | None] = mapped_column(default=None)
    usage_json: Mapped[dict] = mapped_column(JSON, default=dict)
    lineage_json: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class DeliverySpecialistResultRecord(Base):
    __tablename__ = "delivery_specialist_results"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_delivery_specialist_result_run"),
        Index("ix_delivery_specialist_results_workflow", "workflow_id", "specialist"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("delivery_agent_workflows.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(ForeignKey("delivery_agent_runs.id", ondelete="CASCADE"))
    specialist: Mapped[str]
    result_type: Mapped[str]
    schema_version: Mapped[str] = mapped_column(default="1.0")
    status: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    source_references: Mapped[list] = mapped_column(JSON, default=list)
    data_gaps: Mapped[list] = mapped_column(JSON, default=list)
    input_hash: Mapped[str]
    output_hash: Mapped[str]
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class DeliveryWorkflowEventRecord(Base):
    __tablename__ = "delivery_workflow_events"
    __table_args__ = (
        Index("ix_delivery_workflow_events_order", "workflow_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("delivery_agent_workflows.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class DeliveryEventInbox(Base):
    __tablename__ = "delivery_event_inbox"
    __table_args__ = (
        UniqueConstraint("consumer", "message_id", name="uq_delivery_event_inbox_message"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    consumer: Mapped[str]
    message_id: Mapped[str]
    payload_hash: Mapped[str]
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AgentWorkspaceConversation(Base):
    __tablename__ = "agent_workspace_conversations"
    __table_args__ = (
        UniqueConstraint("conversation_id", name="uq_agent_workspace_conversation"),
        CheckConstraint(
            "classification IN ('delivery', 'quality')",
            name="ck_agent_workspace_conversation_classification",
        ),
        CheckConstraint(
            "channel_kind IN ('announcement', 'team', 'project', 'release')",
            name="ck_agent_workspace_conversation_channel_kind",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    agent_workspace_id: Mapped[str] = mapped_column(ForeignKey("agent_workspaces.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    classification: Mapped[str]
    channel_kind: Mapped[str] = mapped_column(default="project")
    linked_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ExternalContact(Base):
    __tablename__ = "external_contacts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "email", name="uq_external_contact_workspace_email"),
        CheckConstraint("status IN ('invited', 'active', 'revoked')", name="ck_external_contact_status"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    email: Mapped[str]
    display_name: Mapped[str]
    organization: Mapped[str | None] = mapped_column(default=None)
    linked_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)
    status: Mapped[str] = mapped_column(default="invited")
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ContactRelationship(Base):
    """A user's private, directional relationship to a person in one workspace."""

    __tablename__ = "contact_relationships"
    __table_args__ = (
        CheckConstraint(
            "((subject_user_id IS NOT NULL) AND (subject_external_contact_id IS NULL)) OR "
            "((subject_user_id IS NULL) AND (subject_external_contact_id IS NOT NULL))",
            name="ck_contact_relationship_exactly_one_subject",
        ),
        CheckConstraint(
            "(subject_kind = 'workspace_user' AND subject_user_id IS NOT NULL "
            "AND subject_external_contact_id IS NULL) OR "
            "(subject_kind = 'external_contact' AND subject_user_id IS NULL "
            "AND subject_external_contact_id IS NOT NULL)",
            name="ck_contact_relationship_kind_matches_subject",
        ),
        CheckConstraint("strength >= 1 AND strength <= 5", name="ck_contact_relationship_strength"),
        CheckConstraint(
            "relationship_type IN ('colleague', 'manager', 'direct_report', 'client', 'partner', "
            "'vendor', 'friend', 'mentor', 'other')",
            name="ck_contact_relationship_type",
        ),
        CheckConstraint(
            "status IN ('suggested', 'active', 'archived', 'rejected')",
            name="ck_contact_relationship_status",
        ),
        CheckConstraint(
            "source IN ('manual', 'ai_suggested', 'imported')",
            name="ck_contact_relationship_source",
        ),
        CheckConstraint(
            "subject_user_id IS NULL OR owner_user_id <> subject_user_id",
            name="ck_contact_relationship_not_self",
        ),
        Index(
            "uq_contact_relationship_workspace_user",
            "workspace_id",
            "owner_user_id",
            "subject_user_id",
            unique=True,
            sqlite_where=text("subject_user_id IS NOT NULL"),
            postgresql_where=text("subject_user_id IS NOT NULL"),
        ),
        Index(
            "uq_contact_relationship_external",
            "workspace_id",
            "owner_user_id",
            "subject_external_contact_id",
            unique=True,
            sqlite_where=text("subject_external_contact_id IS NOT NULL"),
            postgresql_where=text("subject_external_contact_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    subject_kind: Mapped[str]
    subject_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)
    subject_external_contact_id: Mapped[str | None] = mapped_column(
        ForeignKey("external_contacts.id"), default=None, index=True
    )
    relationship_type: Mapped[str]
    custom_label: Mapped[str | None] = mapped_column(default=None)
    strength: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(default="active")
    source: Mapped[str] = mapped_column(default="manual")
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    last_interaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PeoplePreference(Base):
    """Sparse, private user preferences for people in an organization workspace.

    Interaction metrics are derived from workspace chat/task metadata. Only explicit personal
    choices belong here so users never need to configure every coworker manually.
    """

    __tablename__ = "people_preferences"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "subject_user_id",
            name="uq_people_preference_workspace_owner_subject",
        ),
        CheckConstraint("owner_user_id <> subject_user_id", name="ck_people_preference_not_self"),
        Index(
            "ix_people_preferences_workspace_owner_pinned",
            "workspace_id",
            "owner_user_id",
            "is_pinned",
        ),
        Index(
            "ix_people_preferences_workspace_owner_follow_up",
            "workspace_id",
            "owner_user_id",
            "follow_up_at",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    subject_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    private_note: Mapped[str | None] = mapped_column(Text, default=None)
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class MigrationState(Base):
    __tablename__ = "migration_states"

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    migration_key: Mapped[str] = mapped_column(unique=True, index=True)
    migration_version: Mapped[str] = mapped_column(default="workspace_foundation_v1")
    status: Mapped[str]
    error_code: Mapped[str | None] = mapped_column(default=None)
    error_message: Mapped[str | None] = mapped_column(default=None)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class SupportAccessGrant(Base):
    __tablename__ = "support_access_grants"

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    platform_admin_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    requested_scope: Mapped[str]
    scope_json: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(default="requested")
    approved_by_owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class SystemConfig(Base):
    """Single-row storage for runtime-editable platform settings."""

    __tablename__ = "system_config"

    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: "default")
    daily_token_budget: Mapped[int | None] = mapped_column(default=None)
    llm_provider: Mapped[str | None] = mapped_column(default=None)
    model_name: Mapped[str | None] = mapped_column(default=None)
    llm_temperature: Mapped[float | None] = mapped_column(Float, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), default=None)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), default=None, index=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)
    actor_type: Mapped[str]
    action: Mapped[str]
    target_type: Mapped[str]
    target_id: Mapped[str | None] = mapped_column(default=None)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (CheckConstraint("type IN ('direct', 'group')", name="ck_conversation_type"),)

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    type: Mapped[str]  # "direct" | "group"
    name: Mapped[str | None] = mapped_column(default=None)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    # Group conversations use one explicit, manager-controlled AI policy.  This avoids creating
    # syntactically valid but semantically broken context by deleting individual authors' turns.
    # Direct conversations keep the per-user AIPermission model below.
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_policy_version: Mapped[int] = mapped_column(Integer, default=0)
    ai_enabled_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None)
    ai_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    participants: Mapped[list["ConversationParticipant"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class ConversationParticipant(Base):
    __tablename__ = "conversation_participants"
    __table_args__ = (
        CheckConstraint(
            "((user_id IS NOT NULL) AND (external_contact_id IS NULL)) OR "
            "((user_id IS NULL) AND (external_contact_id IS NOT NULL))",
            name="ck_conversation_participant_exactly_one_principal",
        ),
        CheckConstraint(
            "(principal_kind = 'workspace_user' AND user_id IS NOT NULL AND external_contact_id IS NULL) OR "
            "(principal_kind = 'external_contact' AND user_id IS NULL AND external_contact_id IS NOT NULL)",
            name="ck_conversation_participant_kind_matches_principal",
        ),
        CheckConstraint(
            "resource_role IN ('manager', 'participant', 'viewer')",
            name="ck_conversation_participant_resource_role",
        ),
        Index(
            "uq_conversation_participant_user",
            "conversation_id",
            "user_id",
            unique=True,
            sqlite_where=text("user_id IS NOT NULL"),
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_conversation_participant_external",
            "conversation_id",
            "external_contact_id",
            unique=True,
            sqlite_where=text("external_contact_id IS NOT NULL"),
            postgresql_where=text("external_contact_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    principal_kind: Mapped[str] = mapped_column(default="workspace_user")
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)
    external_contact_id: Mapped[str | None] = mapped_column(
        ForeignKey("external_contacts.id"), default=None, index=True
    )
    resource_role: Mapped[str] = mapped_column(default="participant")
    invited_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    conversation: Mapped["Conversation"] = relationship(back_populates="participants")
    user: Mapped["User | None"] = relationship(foreign_keys=[user_id])


class AIPermission(Base):
    """Per-user AI choices inside one conversation.

    ``granted`` means this user may invoke the assistant for the conversation.  It deliberately
    does not grant the assistant permission to process messages authored by somebody else.
    ``contribution_allowed`` is the independent author-side consent used by the server-side
    authorized-message resolver.  Keeping the two choices separate avoids treating "I want to use
    AI" as "every participant has allowed my AI to process their content".
    """

    __tablename__ = "ai_permissions"

    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    granted: Mapped[bool] = mapped_column(default=False)
    contribution_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    sender_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
    sender: Mapped["User"] = relationship()


class DeliveryGroupSchedule(Base):
    """Lead-approved, one-shot Workspace Agent update scheduled for a source group."""

    __tablename__ = "delivery_group_schedules"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_delivery_group_schedule_idempotency"),
        CheckConstraint(
            "status IN ('scheduled', 'sent', 'cancelled', 'failed')",
            name="ck_delivery_group_schedule_status",
        ),
        Index(
            "ix_delivery_group_schedule_due",
            "workspace_id",
            "agent_workspace_id",
            "status",
            "scheduled_for",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    agent_workspace_id: Mapped[str] = mapped_column(ForeignKey("agent_workspaces.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    approved_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str]
    content: Mapped[str] = mapped_column(Text)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(default="scheduled")
    idempotency_key: Mapped[str]
    sent_message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id"), default=None)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("priority IN ('High', 'Medium', 'Low')", name="ck_task_priority"),
        CheckConstraint(
            "status IN ('suggested', 'pending', 'in_progress', 'blocked', 'submitted', 'changes_requested', 'completed', 'dismissed', 'invalidated')",
            name="ck_task_status",
        ),
        CheckConstraint("source IN ('manual', 'ai_extracted', 'proactive')", name="ck_task_source"),
        CheckConstraint(
            "work_item_type IS NULL OR work_item_type IN ('bug', 'test_case', 'release_check')",
            name="ck_task_quality_type",
        ),
        CheckConstraint(
            "severity IS NULL OR severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_task_quality_severity",
        ),
        CheckConstraint(
            "quality_status IS NULL OR quality_status IN ('open', 'testing', 'passed', 'failed', 'blocked')",
            name="ck_task_quality_status",
        ),
        CheckConstraint(
            "(work_item_type IS NULL AND severity IS NULL AND quality_status IS NULL AND release_target IS NULL AND quality_required = false) OR "
            "(work_item_type IS NOT NULL AND quality_status IS NOT NULL AND release_target IS NOT NULL "
            "AND ((work_item_type = 'bug' AND severity IS NOT NULL) "
            "OR (work_item_type != 'bug' AND severity IS NULL)) "
            "AND (quality_required = false OR work_item_type = 'release_check'))",
            name="ck_task_quality_shape",
        ),
        Index("ix_tasks_workspace_owner_status", "workspace_id", "owner_id", "status"),
        Index("ix_tasks_workspace_due_at", "workspace_id", "due_at"),
        Index(
            "ix_tasks_delivery_scope",
            "workspace_id",
            "agent_workspace_id",
            "conversation_id",
            "status",
            "due_at",
        ),
        Index(
            "ix_tasks_quality_scope",
            "workspace_id",
            "agent_workspace_id",
            "conversation_id",
            "release_target",
            "work_item_type",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), default=None, index=True)
    # A nullable binding preserves personal/legacy tasks.  A Delivery read may
    # use only rows explicitly bound to its Agent Workspace and source group.
    agent_workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_workspaces.id"), default=None, index=True
    )
    title: Mapped[str]
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Global user preferences decide whether task reminders are created at all. This per-task
    # switch lets a user opt one noisy task out without disabling the feature everywhere.
    auto_reminder_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[str] = mapped_column(default="Medium")  # "High" | "Medium" | "Low"
    status: Mapped[str] = mapped_column(default="suggested")
    # "suggested" | "pending" | "in_progress" | "blocked" | "completed" | "dismissed"
    blocked_reason: Mapped[str | None] = mapped_column(default=None)
    source: Mapped[str] = mapped_column(default="manual")  # "manual" | "ai_extracted" | "proactive"
    # P0 provenance for unconfirmed AI candidates.  Confirmed domain state may outlive a later
    # source-consent revocation, but a still-suggested candidate is invalidated when its source
    # author revokes contribution processing.
    source_message_ids: Mapped[list[str] | None] = mapped_column(JSON, default=None)
    source_sender_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)
    consent_scope_hash: Mapped[str | None] = mapped_column(default=None, index=True)
    invalidated_reason: Mapped[str | None] = mapped_column(default=None)
    # Quality Assurance metadata. These columns are populated only for rows explicitly bound to
    # a quality_assurance Agent Workspace and an authorized source conversation.
    work_item_type: Mapped[str | None] = mapped_column(default=None)
    severity: Mapped[str | None] = mapped_column(default=None)
    quality_status: Mapped[str | None] = mapped_column(default=None)
    release_target: Mapped[str | None] = mapped_column(default=None, index=True)
    quality_required: Mapped[bool] = mapped_column(default=False)
    # Delivery completion governance. Ordinary tasks can complete directly;
    # review-required tasks must carry explicit evidence through Lead review.
    requires_review: Mapped[bool] = mapped_column(default=False)
    submission_note: Mapped[str | None] = mapped_column(Text, default=None)
    evidence_urls: Mapped[list[str]] = mapped_column(JSON, default=list)
    submitted_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    review_note: Mapped[str | None] = mapped_column(Text, default=None)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    owner: Mapped["User"] = relationship(foreign_keys=[owner_id])
    conversation: Mapped["Conversation | None"] = relationship()
    agent_workspace: Mapped["AgentWorkspace | None"] = relationship()


class DeliveryMilestone(Base):
    """Typed, source-bound release target for Product Delivery reads."""

    __tablename__ = "delivery_milestones"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'in_progress', 'blocked', 'completed', 'dismissed', 'invalidated')",
            name="ck_delivery_milestone_status",
        ),
        CheckConstraint(
            "quality_review_status IN ('pending', 'accepted', 'rejected')",
            name="ck_delivery_milestone_quality_review",
        ),
        Index(
            "ix_delivery_milestone_scope",
            "workspace_id",
            "agent_workspace_id",
            "conversation_id",
            "status",
            "due_at",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    agent_workspace_id: Mapped[str] = mapped_column(ForeignKey("agent_workspaces.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    title: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    blocked_reason: Mapped[str | None] = mapped_column(default=None)
    # A milestone is also the durable checkpoint in a Lead-authored plan.
    # Rules own schedule/completeness; only a Lead owns quality acceptance.
    plan_key: Mapped[str] = mapped_column(default="default")
    quality_review_status: Mapped[str] = mapped_column(default="pending")
    quality_review_note: Mapped[str | None] = mapped_column(Text, default=None)
    quality_reviewed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), default=None, index=True
    )
    quality_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class DeliveryCheckpointTask(Base):
    """Required/optional task membership in one Delivery plan checkpoint."""

    __tablename__ = "delivery_checkpoint_tasks"
    __table_args__ = (
        UniqueConstraint("milestone_id", "task_id", name="uq_delivery_checkpoint_task"),
        Index("ix_delivery_checkpoint_task_scope", "workspace_id", "agent_workspace_id", "milestone_id"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    agent_workspace_id: Mapped[str] = mapped_column(ForeignKey("agent_workspaces.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    milestone_id: Mapped[str] = mapped_column(ForeignKey("delivery_milestones.id"), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class DeliveryDependencyRecord(Base):
    """Source-bound dependency owned by one Product Delivery workspace."""

    __tablename__ = "delivery_dependencies"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'blocked', 'resolved', 'invalidated')",
            name="ck_delivery_dependency_status",
        ),
        CheckConstraint(
            "predecessor_task_id IS NULL OR predecessor_task_id != successor_task_id",
            name="ck_delivery_dependency_distinct_tasks",
        ),
        Index(
            "ix_delivery_dependencies_scope",
            "workspace_id",
            "agent_workspace_id",
            "conversation_id",
            "status",
            "due_at",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    agent_workspace_id: Mapped[str] = mapped_column(ForeignKey("agent_workspaces.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    title: Mapped[str]
    status: Mapped[str] = mapped_column(default="open")
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)
    predecessor_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), default=None)
    successor_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), default=None)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class DeliveryDecisionRecord(Base):
    """Durable decision log; pending decisions are never inferred from chat sentiment."""

    __tablename__ = "delivery_decisions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'decided', 'superseded', 'invalidated')",
            name="ck_delivery_decision_status",
        ),
        CheckConstraint(
            "(status = 'decided' AND outcome IS NOT NULL) OR status != 'decided'",
            name="ck_delivery_decision_outcome",
        ),
        Index(
            "ix_delivery_decisions_scope",
            "workspace_id",
            "agent_workspace_id",
            "conversation_id",
            "status",
            "due_at",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    agent_workspace_id: Mapped[str] = mapped_column(ForeignKey("agent_workspaces.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    title: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    options: Mapped[list[str]] = mapped_column(JSON, default=list)
    outcome: Mapped[str | None] = mapped_column(Text, default=None)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class EventCandidate(Base):
    """A consent-scoped calendar fact extracted incrementally from conversation messages.

    Candidates are durable retrieval records, not Google Calendar side effects.  A conversation
    manager must explicitly confirm a complete candidate before an external event is created.
    """

    __tablename__ = "event_candidates"
    __table_args__ = (
        CheckConstraint(
            "status IN ('suggested', 'confirmed', 'superseded', 'dismissed', 'cancelled', 'invalidated')",
            name="ck_event_candidate_status",
        ),
        CheckConstraint(
            "operation IN ('create', 'update', 'cancel')",
            name="ck_event_candidate_operation",
        ),
        Index("ix_event_candidates_conversation_status", "conversation_id", "status"),
        Index("ix_event_candidates_workspace_start", "workspace_id", "start_at"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    operation: Mapped[str] = mapped_column(default="create")
    target_candidate_id: Mapped[str | None] = mapped_column(ForeignKey("event_candidates.id"), default=None, index=True)
    title: Mapped[str]
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    location: Mapped[str | None] = mapped_column(default=None)
    attendees: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(default="suggested")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    missing_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_message_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    authorization_scope_hash: Mapped[str] = mapped_column(index=True)
    calendar_event_id: Mapped[str | None] = mapped_column(default=None, index=True)
    calendar_owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)
    invalidated_reason: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class EventExtractionCursor(Base):
    """Resumable cursor for bounded historical event extraction."""

    __tablename__ = "event_extraction_cursors"

    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), primary_key=True)
    last_message_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_message_id: Mapped[str | None] = mapped_column(default=None)
    processed_message_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(default="idle")
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), default=None, index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None, index=True)
    provider: Mapped[str]
    model: Mapped[str]
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    total_tokens: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class AgentThread(Base):
    __tablename__ = "agent_threads"
    __table_args__ = (
        Index("ix_agent_threads_owner_last_active", "owner_id", "last_active_at"),
        Index("ix_agent_threads_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Memory(Base):
    __tablename__ = "memories"
    __table_args__ = (
        CheckConstraint(
            "memory_type IN ('preference', 'relationship', 'episodic', 'semantic')",
            name="ck_memory_type",
        ),
        CheckConstraint(
            "sensitivity IN ('normal', 'sensitive')",
            name="ck_memory_sensitivity",
        ),
        Index("ix_memories_workspace_owner_created", "workspace_id", "owner_id", "created_at"),
        Index("ix_memories_owner_type_expiry", "owner_id", "memory_type", "expires_at"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(default="Preference")  # "Work" | "Preference" | "People" | ...
    title: Mapped[str]
    detail: Mapped[str] = mapped_column(default="")
    memory_type: Mapped[str] = mapped_column(default="semantic")
    source_conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id"), default=None, index=True
    )
    source_message_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    consent_scope_hash: Mapped[str | None] = mapped_column(default=None, index=True)
    sensitivity: Mapped[str] = mapped_column(default="normal")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, index=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    owner: Mapped["User"] = relationship()


class CalendarSyncState(Base):
    """Per-workspace Google Calendar incremental sync cursor."""

    __tablename__ = "calendar_sync_state"

    workspace_id: Mapped[str] = mapped_column("id", ForeignKey("workspaces.id"), primary_key=True)
    sync_token: Mapped[str | None] = mapped_column(default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class AssistantThread(Base):
    """One row per Personal AI Assistant chat session (/assistant page) - lets a user browse past
    sessions ("Gần đây" sidebar). Distinct from Conversation (1-1/group human chat) and from the
    LangGraph checkpointer's own Postgres tables: those hold the full message state per thread_id
    but have no owner_id column and no title/preview concept, so they can't answer "which threads
    belong to this user" on their own - this table is the missing owner_id -> thread_id index, kept
    in sync from src/api/routes.py (chat()/resume_chat()) whenever a turn completes. Only chat()
    calls with conversation_id=None create a row here - AIPanel's embedded quick actions/Ask Orbit
    (always conversation_id-scoped) are a different, unrelated flow and must not show up in this
    list."""

    __tablename__ = "assistant_threads"

    thread_id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True, index=True)
    title: Mapped[str]  # fixed at creation from the first message - like a conversation name, never edited after
    preview: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    owner: Mapped["User"] = relationship()


class GoogleCalendarCredential(Base):
    """Encrypted per-user OAuth credential and incremental sync cursor."""

    __tablename__ = "google_calendar_credentials"

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    google_email: Mapped[str] = mapped_column(default="")
    refresh_token_enc: Mapped[str] = mapped_column(Text)
    access_token_enc: Mapped[str | None] = mapped_column(Text, default=None)
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    scopes: Mapped[str] = mapped_column(default="")
    sync_token: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    user: Mapped["User"] = relationship()


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (
        CheckConstraint("status IN ('scheduled', 'fired', 'cancelled')", name="ck_reminder_status"),
        CheckConstraint("source IN ('manual', 'agent', 'proactive')", name="ck_reminder_source"),
        Index("ix_reminders_workspace_owner_status", "workspace_id", "owner_id", "status"),
        Index("ix_reminders_workspace_fire_at", "workspace_id", "fire_at"),
        Index("uq_reminders_task_id", "task_id", unique=True),
        Index(
            "uq_reminders_owner_calendar_event",
            "owner_id",
            "calendar_event_id",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    # A task-linked reminder is private to the owner's Personal Space even when the task belongs
    # to an organization workspace. Manual/agent reminders remain independent with task_id=NULL.
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), default=None
    )
    # Google event ids are external identifiers, so this is intentionally not a foreign key.
    # Owner is part of the unique index because one shared Google event may appear on several
    # users' calendars while each Orbit reminder remains private.
    calendar_event_id: Mapped[str | None] = mapped_column(default=None)
    title: Mapped[str]
    message: Mapped[str] = mapped_column(default="")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lead_minutes: Mapped[int] = mapped_column(default=30)
    status: Mapped[str] = mapped_column(default="scheduled")  # "scheduled" | "fired" | "cancelled"
    source: Mapped[str] = mapped_column(default="manual")  # "manual" | "agent" | "proactive"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    owner: Mapped["User"] = relationship()
