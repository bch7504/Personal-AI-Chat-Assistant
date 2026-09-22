from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from src.agents.contracts import (
    AgentProfile,
    BusinessRole,
    FrozenContract,
    PolicyDecision,
    SourceReference,
    ToolResult,
)
from src.agents.delivery_orchestration.contracts import (
    DeliveryOrchestrationContext,
    DeliverySpecialistResult,
)


class AgentRuntimeStatus(StrEnum):
    SUCCESS = "success"
    DEGRADED = "degraded"


class RuntimeTarget(FrozenContract):
    organization_workspace_id: str = Field(min_length=1)
    agent_workspace_id: str = Field(min_length=1)
    profile: AgentProfile
    runtime_version: str = Field(min_length=1, max_length=64)


class RuntimeActor(FrozenContract):
    user_id: str = Field(min_length=1)
    business_role: BusinessRole


class RuntimeAuthorization(FrozenContract):
    decision: PolicyDecision
    authorized_at: datetime
    expires_at: datetime
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope_hash: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_authorization(self) -> RuntimeAuthorization:
        if self.decision != PolicyDecision.ALLOW:
            raise ValueError("Only ALLOW decisions may cross the runtime boundary")
        if self.authorized_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("Authorization timestamps must include a timezone")
        if self.expires_at <= self.authorized_at:
            raise ValueError("Authorization expiry must be after authorization time")
        return self


class RuntimeConversationMessage(FrozenContract):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8_000)


class AgentRuntimeRequest(FrozenContract):
    schema_version: str = Field(default="1.0", pattern=r"^1\.[0-9]+$")
    run_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    requested_at: datetime
    target: RuntimeTarget
    actor: RuntimeActor
    authorization: RuntimeAuthorization
    message: str = Field(min_length=1, max_length=8_000)
    history: tuple[RuntimeConversationMessage, ...] = Field(default=(), max_length=12)
    snapshot: ToolResult
    orchestration: DeliveryOrchestrationContext | None = None
    interaction_mode: Literal["business_snapshot", "workspace_conversation"] = "business_snapshot"
    interaction_intent: str = Field(default="", max_length=64)
    routing_plan_version: str = Field(default="", max_length=64)
    progress_request_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_envelope(self) -> AgentRuntimeRequest:
        if self.requested_at.tzinfo is None:
            raise ValueError("requested_at must include a timezone")
        if self.requested_at > self.authorization.expires_at:
            raise ValueError("Runtime request uses an expired authorization")
        if snapshot_sha256(self.snapshot) != self.authorization.snapshot_sha256:
            raise ValueError("snapshot_sha256 does not match the supplied snapshot")
        if any(source.agent_workspace_id != self.target.agent_workspace_id for source in self.snapshot.sources):
            raise ValueError("Every snapshot source must belong to the target agent workspace")
        if self.interaction_mode == "workspace_conversation":
            if self.target.profile != AgentProfile.PRODUCT_DELIVERY:
                raise ValueError("Workspace conversation mode currently supports Product Delivery only")
            if self.orchestration is not None:
                raise ValueError("Workspace conversation mode cannot include specialist orchestration")
            if self.snapshot.sources:
                raise ValueError("Workspace conversation mode cannot receive business-data sources")
            if not self.interaction_intent:
                raise ValueError("Workspace conversation mode requires an interaction intent")
        if self.orchestration is not None:
            if self.target.profile != AgentProfile.PRODUCT_DELIVERY:
                raise ValueError("Delivery orchestration is valid only for the Product Delivery runtime")
            if self.orchestration.deadline_at <= self.requested_at:
                raise ValueError("Delivery orchestration deadline must be after requested_at")
            if self.orchestration.authorization_scope_hash != self.authorization.scope_hash:
                raise ValueError("Delivery orchestration scope hash does not match authorization")
        return self


class RuntimeProgressEvent(FrozenContract):
    """Signed, non-authoritative execution telemetry sent back to Core."""

    request_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    agent_workspace_id: str = Field(min_length=1)
    phase: Literal[
        "specialist_started",
        "specialist_completed",
        "specialist_failed",
        "specialist_handoff",
        "synthesis_started",
    ]
    specialist: str | None = Field(default=None, max_length=64)
    from_specialist: str | None = Field(default=None, max_length=64)
    to_specialist: str | None = Field(default=None, max_length=64)
    depends_on: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    step_index: int | None = Field(default=None, ge=1)
    total_steps: int = Field(ge=1)
    output_hash: str | None = Field(default=None, max_length=128)
    artifact_type: str | None = Field(default=None, max_length=128)
    metrics: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = Field(default=None, max_length=128)
    occurred_at: datetime


class RuntimeUsage(FrozenContract):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_total(self) -> RuntimeUsage:
        if self.total_tokens < self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens cannot be smaller than input_tokens + output_tokens")
        return self


class RuntimeMetadata(FrozenContract):
    service: str = "workspace-agent-runtime"
    profile: AgentProfile
    runtime_version: str
    duration_ms: int = Field(ge=0)
    prompt_version: str = ""
    model_provider: str = ""
    model_name: str = ""
    specialist_model_provider: str = ""
    specialist_model_name: str = ""
    llm_calls: int = Field(default=0, ge=0)
    llm_attempts: int = Field(default=0, ge=0)
    llm_successes: int = Field(default=0, ge=0)
    model_attempts: tuple[dict[str, Any], ...] = Field(default=(), max_length=6)
    verifier_applied: bool = False
    verifier_model_provider: str = ""
    verifier_model_name: str = ""
    synthesis_usage: RuntimeUsage = RuntimeUsage()
    specialist_usage: RuntimeUsage = RuntimeUsage()
    verifier_usage: RuntimeUsage = RuntimeUsage()
    synthesis_fallback: bool = False
    fallback_reason: str = ""
    prompt_input_chars: int = Field(default=0, ge=0)
    snapshot_original_chars: int = Field(default=0, ge=0)
    snapshot_included_chars: int = Field(default=0, ge=0)
    snapshot_compacted: bool = False
    execution_mode: str = "single_snapshot"
    intent: str = ""
    plan_version: str = ""
    workflow_id: str = ""
    specialists_requested: tuple[str, ...] = ()
    specialists_completed: tuple[str, ...] = ()
    specialists_failed: tuple[str, ...] = ()
    specialist_llm_attempts: int = Field(default=0, ge=0)
    specialist_fallbacks: dict[str, str] = Field(default_factory=dict)
    specialist_model_attempts: dict[str, tuple[dict[str, Any], ...]] = Field(default_factory=dict)
    evidence_branch_executed: bool = False
    specialist_results: tuple[DeliverySpecialistResult, ...] = ()


class AgentRuntimeResponse(FrozenContract):
    schema_version: str = Field(default="1.0", pattern=r"^1\.[0-9]+$")
    run_id: str
    trace_id: str
    status: AgentRuntimeStatus
    answer: str = Field(min_length=1)
    sources: tuple[SourceReference, ...] = ()
    data_gaps: tuple[str, ...] = ()
    usage: RuntimeUsage = RuntimeUsage()
    runtime: RuntimeMetadata


def snapshot_sha256(snapshot: ToolResult) -> str:
    canonical = snapshot.model_dump_json(exclude_none=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
