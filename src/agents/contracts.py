from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentProfile(StrEnum):
    PERSONAL = "personal"
    PRODUCT_DELIVERY = "product_delivery"
    QUALITY_ASSURANCE = "quality_assurance"
    EXECUTIVE = "executive"


class BusinessRole(StrEnum):
    MEMBER = "member"
    LEAD = "lead"
    EXECUTIVE = "executive"


class RequestedScope(StrEnum):
    PERSONAL = "personal"
    WORKSPACE = "workspace"
    AGGREGATE = "aggregate"


class AgentIntent(StrEnum):
    PERSONAL_ASSISTANCE = "personal_assistance"
    SUMMARIZE = "summarize"
    SEARCH = "search"
    EXTRACT_TASK = "extract_task"
    MANAGE_TASK = "manage_task"
    CALENDAR = "calendar"
    REMINDER = "reminder"
    DELIVERY_BRIEF = "delivery_brief"
    QUALITY_READINESS = "quality_readiness"
    QUALITY_BRIEF = "quality_brief"
    EXECUTIVE_BRIEF = "executive_brief"


class PolicyDecision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    MASK = "MASK"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class PolicyReason(StrEnum):
    ALLOWED = "ALLOWED"
    FEATURE_DISABLED = "FEATURE_DISABLED"
    NOT_MEMBER = "DENY_NOT_MEMBER"
    WRONG_WORKSPACE = "DENY_WRONG_WORKSPACE"
    PROFILE_MISMATCH = "DENY_PROFILE_MISMATCH"
    INVALID_SCOPE = "DENY_INVALID_SCOPE"
    RESOURCE_NOT_ALLOWED = "DENY_RESOURCE_NOT_ALLOWED"
    CONSENT_CHANGED = "DENY_CONSENT_CHANGED"
    SENSITIVE_DATA = "MASK_SENSITIVE"
    APPROVAL_REQUIRED = "REQUIRE_APPROVAL"


class ToolResultStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    ERROR = "error"


class BriefType(StrEnum):
    DELIVERY = "delivery"
    QUALITY = "quality"


class ReleaseReadiness(StrEnum):
    READY = "READY"
    AT_RISK = "AT_RISK"
    NOT_READY = "NOT_READY"


class FrozenContract(BaseModel):
    """Immutable, strict base for context supplied to the agent runtime by the server."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ActorContext(FrozenContract):
    user_id: str = Field(min_length=1)
    organization_workspace_id: str = Field(min_length=1)
    business_role: BusinessRole
    agent_workspace_ids: tuple[str, ...] = ()


class AgentRequestContext(FrozenContract):
    text: str = Field(min_length=1)
    intent: AgentIntent
    requested_scope: RequestedScope
    target_agent_workspace_id: str | None = None


class AuthorizationContext(FrozenContract):
    decision: PolicyDecision
    reason: PolicyReason
    allowed_agent_workspace_ids: tuple[str, ...] = ()
    allowed_resource_ids: tuple[str, ...] = ()
    consent_scope_hash: str | None = None
    masked_fields: tuple[str, ...] = ()

    @model_validator(mode="after")
    def denied_context_has_no_capabilities(self) -> AuthorizationContext:
        if self.decision == PolicyDecision.DENY and (
            self.allowed_agent_workspace_ids or self.allowed_resource_ids
        ):
            raise ValueError("A denied authorization context cannot include allowed capabilities")
        return self


class AgentRuntimeContext(FrozenContract):
    agent_profile: AgentProfile
    prompt_version: str = Field(min_length=1)
    tool_budget: int = Field(default=6, ge=0, le=20)
    token_budget: int = Field(default=8000, ge=256, le=100_000)


class AgentContext(FrozenContract):
    """Trusted envelope built after identity, workspace and policy resolution."""

    trace_id: str = Field(min_length=1)
    actor: ActorContext
    request: AgentRequestContext
    authorization: AuthorizationContext
    runtime: AgentRuntimeContext

    @model_validator(mode="after")
    def target_workspace_is_authorized(self) -> AgentContext:
        target = self.request.target_agent_workspace_id
        if (
            target
            and self.authorization.decision != PolicyDecision.DENY
            and target not in self.authorization.allowed_agent_workspace_ids
        ):
            raise ValueError("Target agent workspace is outside the resolved authorization scope")
        return self


class AgentInvocationRequest(BaseModel):
    """Untrusted client input. Authorization/profile fields are intentionally absent."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    conversation_id: str | None = None
    requested_scope: RequestedScope = RequestedScope.PERSONAL
    target_agent_workspace_id: str | None = None


class SourceReference(FrozenContract):
    """Minimal provenance record safe to pass between agents."""

    schema_version: str = Field(default="1.0", pattern=r"^1\.[0-9]+$")
    resource_id: str = Field(min_length=1)
    resource_type: str = Field(min_length=1, max_length=64)
    agent_workspace_id: str = Field(min_length=1)
    classification: str = Field(min_length=1, max_length=32)
    captured_at: datetime

    @model_validator(mode="after")
    def captured_at_is_timezone_aware(self) -> SourceReference:
        if self.captured_at.tzinfo is None:
            raise ValueError("captured_at must include a timezone")
        return self


class ToolResult(FrozenContract):
    schema_version: str = Field(default="1.0", pattern=r"^1\.[0-9]+$")
    status: ToolResultStatus
    payload: dict[str, Any] = Field(default_factory=dict)
    sources: tuple[SourceReference, ...] = ()
    data_gaps: tuple[str, ...] = ()
    error_code: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def status_matches_error_fields(self) -> ToolResult:
        if self.status == ToolResultStatus.SUCCESS and (self.error_code or self.error_message):
            raise ValueError("A successful tool result cannot contain error fields")
        if self.status == ToolResultStatus.ERROR and not self.error_code:
            raise ValueError("An error tool result requires error_code")
        if self.status == ToolResultStatus.PARTIAL and not self.data_gaps:
            raise ValueError("A partial tool result requires at least one data gap")
        return self


def action_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ActionProposal(FrozenContract):
    schema_version: str = Field(default="1.0", pattern=r"^1\.[0-9]+$")
    proposal_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    actor_user_id: str = Field(min_length=1)
    action: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any]
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=255)
    created_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def proposal_is_bound_and_expiring(self) -> ActionProposal:
        if self.created_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("Proposal timestamps must include a timezone")
        if self.expires_at <= self.created_at:
            raise ValueError("Proposal expiry must be after creation")
        if self.payload_hash != action_payload_hash(self.payload):
            raise ValueError("payload_hash does not match proposal payload")
        return self

    def is_expired(self, *, at: datetime | None = None) -> bool:
        checked_at = at or datetime.now(UTC)
        if checked_at.tzinfo is None:
            raise ValueError("Expiry checks require a timezone-aware datetime")
        return checked_at >= self.expires_at


class WorkspaceBrief(FrozenContract):
    """Versioned, source-backed handoff produced by one specialist workspace."""

    schema_version: str = Field(default="1.0", pattern=r"^1\.[0-9]+$")
    brief_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    organization_workspace_id: str = Field(min_length=1)
    agent_workspace_id: str = Field(min_length=1)
    brief_type: BriefType
    producer_profile: AgentProfile
    period_start: datetime
    period_end: datetime
    generated_at: datetime
    expires_at: datetime
    headline: str = Field(min_length=1)
    facts: tuple[dict[str, Any], ...] = ()
    risks: tuple[dict[str, Any], ...] = ()
    dependencies: tuple[dict[str, Any], ...] = ()
    decisions_needed: tuple[dict[str, Any], ...] = ()
    data_gaps: tuple[str, ...] = ()
    sources: tuple[SourceReference, ...] = ()
    release_readiness: ReleaseReadiness | None = None

    @model_validator(mode="after")
    def validate_brief_envelope(self) -> WorkspaceBrief:
        timestamps = (self.period_start, self.period_end, self.generated_at, self.expires_at)
        if any(value.tzinfo is None for value in timestamps):
            raise ValueError("WorkspaceBrief timestamps must include a timezone")
        if self.period_end < self.period_start:
            raise ValueError("period_end must not be before period_start")
        if self.expires_at <= self.generated_at:
            raise ValueError("expires_at must be after generated_at")
        expected_profile = {
            BriefType.DELIVERY: AgentProfile.PRODUCT_DELIVERY,
            BriefType.QUALITY: AgentProfile.QUALITY_ASSURANCE,
        }[self.brief_type]
        if self.producer_profile != expected_profile:
            raise ValueError("brief_type and producer_profile do not match")
        if self.brief_type == BriefType.DELIVERY and self.release_readiness is not None:
            raise ValueError("release_readiness belongs only to a quality brief")
        if self.brief_type == BriefType.QUALITY and self.release_readiness is None:
            raise ValueError("A quality brief requires release_readiness")
        if self.release_readiness == ReleaseReadiness.READY and self.data_gaps:
            raise ValueError("A READY quality brief cannot contain data gaps")
        structured_content = (*self.facts, *self.risks, *self.dependencies, *self.decisions_needed)
        if structured_content and not self.sources:
            raise ValueError("A factual WorkspaceBrief requires at least one source")
        if any(source.agent_workspace_id != self.agent_workspace_id for source in self.sources):
            raise ValueError("Every source must belong to the producing agent workspace")
        return self

    def is_stale(self, *, at: datetime | None = None) -> bool:
        checked_at = at or datetime.now(UTC)
        if checked_at.tzinfo is None:
            raise ValueError("Freshness checks require a timezone-aware datetime")
        return checked_at >= self.expires_at


class ExecutiveBrief(FrozenContract):
    schema_version: str = Field(default="1.0", pattern=r"^1\.[0-9]+$")
    brief_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    organization_workspace_id: str = Field(min_length=1)
    generated_at: datetime
    workspace_brief_ids: tuple[str, ...]
    headline: str = Field(min_length=1)
    facts: tuple[dict[str, Any], ...] = ()
    risks: tuple[dict[str, Any], ...] = ()
    cross_workspace_dependencies: tuple[dict[str, Any], ...] = ()
    decisions_needed: tuple[dict[str, Any], ...] = ()
    recommendations: tuple[dict[str, Any], ...] = ()
    data_gaps: tuple[str, ...] = ()

    @model_validator(mode="after")
    def executive_brief_uses_structured_handoffs(self) -> ExecutiveBrief:
        if self.generated_at.tzinfo is None:
            raise ValueError("generated_at must include a timezone")
        if not self.workspace_brief_ids and not self.data_gaps:
            raise ValueError("An ExecutiveBrief without source briefs must report a data gap")
        if len(set(self.workspace_brief_ids)) != len(self.workspace_brief_ids):
            raise ValueError("workspace_brief_ids must be unique")
        return self
