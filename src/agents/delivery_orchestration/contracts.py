from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from src.agents.contracts import FrozenContract, SourceReference, ToolResultStatus


class DeliveryExecutionMode(StrEnum):
    DIRECT_TOOL = "direct_tool"
    WORKSPACE_ONLY = "workspace_only"
    SINGLE_SPECIALIST = "single_specialist"
    MULTI_SPECIALIST = "multi_specialist"


class DeliveryIntent(StrEnum):
    GREETING = "greeting"
    ACKNOWLEDGEMENT = "acknowledgement"
    CAPABILITY_HELP = "capability_help"
    CLARIFICATION = "clarification"
    OUT_OF_SCOPE = "out_of_scope"
    POLICY_REFUSAL = "policy_refusal"
    TASK_LOOKUP = "task_lookup"
    MY_WORK_PRIORITY = "my_work_priority"
    MY_SCHEDULE = "my_schedule"
    TASK_PROGRESS_SUMMARY = "task_progress_summary"
    CHECKPOINT_PROGRESS = "checkpoint_progress"
    WORK_HEALTH = "work_health"
    MILESTONE_HEALTH = "milestone_health"
    BLOCKER_ANALYSIS = "blocker_analysis"
    DEPENDENCY_ANALYSIS = "dependency_analysis"
    RELEASE_DELIVERY_READINESS = "release_delivery_readiness"
    DECISION_STATUS = "decision_status"
    DELIVERY_HEALTH = "delivery_health"
    CHANGE_IMPACT = "change_impact"
    CAPACITY_ANALYSIS = "capacity_analysis"
    MEETING_PLAN = "meeting_plan"


class DeliverySpecialist(StrEnum):
    TASK_INTELLIGENCE = "task_intelligence"
    RISK_DEPENDENCY = "risk_dependency"
    PLANNING_FORECAST = "planning_forecast"
    EVIDENCE_KNOWLEDGE = "evidence_knowledge"
    CAPACITY_FLOW = "capacity_flow"

    @classmethod
    def _missing_(cls, value: object) -> DeliverySpecialist | None:
        # Normalize persisted workflows from the retired split-task agent.
        # New workflows always serialize the canonical task_intelligence value.
        if value == "work_intelligence":
            return cls.TASK_INTELLIGENCE
        return None


class DeliveryWorkflowStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_EVIDENCE = "waiting_evidence"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class DeliveryRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRY_SCHEDULED = "retry_scheduled"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class RoutingLLMAttempt(FrozenContract):
    provider: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=160)
    status: Literal["succeeded", "failed"]
    duration_ms: int = Field(default=0, ge=0)
    error_code: str = Field(default="", max_length=64)


class DeliveryRoutingDecision(FrozenContract):
    schema_version: str = Field(default="1.0", pattern=r"^1\.[0-9]+$")
    execution_mode: DeliveryExecutionMode
    intent: DeliveryIntent
    specialists: tuple[DeliverySpecialist, ...] = ()
    subject_id: str | None = Field(default=None, max_length=160)
    target_group_id: str | None = Field(default=None, max_length=160)
    target_group_name: str | None = Field(default=None, max_length=160)
    target_selector: Literal["lowest_completion", "highest_risk"] | None = None
    clarification_question: str | None = Field(default=None, max_length=500)
    reason_code: str = Field(min_length=1, max_length=128)
    plan_version: str = Field(default="delivery-adaptive-routing-v2", min_length=1, max_length=64)
    routing_strategy: Literal[
        "deterministic",
        "semantic",
        "semantic_failover",
        "deterministic_fallback",
    ] = "deterministic"
    routing_llm_attempts: tuple[RoutingLLMAttempt, ...] = Field(default=(), max_length=3)

    @model_validator(mode="after")
    def validate_mode(self) -> DeliveryRoutingDecision:
        count = len(self.specialists)
        if self.execution_mode == DeliveryExecutionMode.DIRECT_TOOL and count:
            raise ValueError("Direct-tool routing cannot include specialists")
        if self.execution_mode == DeliveryExecutionMode.WORKSPACE_ONLY and count:
            raise ValueError("Workspace-only routing cannot include specialists")
        if self.execution_mode == DeliveryExecutionMode.SINGLE_SPECIALIST and count != 1:
            raise ValueError("Single-specialist routing requires exactly one specialist")
        if self.execution_mode == DeliveryExecutionMode.MULTI_SPECIALIST and count < 2:
            raise ValueError("Multi-specialist routing requires at least two specialists")
        if len(set(self.specialists)) != count:
            raise ValueError("Specialists must be unique")
        if count > 4:
            raise ValueError("Initial Delivery workflows allow at most four specialists")
        return self


class TeamTaskAssessmentArtifact(FrozenContract):
    artifact_type: Literal["team_task_assessment.v1"] = "team_task_assessment.v1"
    teams: tuple[dict[str, Any], ...] = Field(default=(), max_length=50)
    weakest_group_name: str | None = Field(default=None, max_length=160)


class DependencyRiskArtifact(FrozenContract):
    artifact_type: Literal["dependency_risk_analysis.v1"] = "dependency_risk_analysis.v1"
    groups: tuple[dict[str, Any], ...] = Field(default=(), max_length=50)


class MeetingPlanArtifact(FrozenContract):
    artifact_type: Literal["meeting_plan.v1"] = "meeting_plan.v1"
    target_group_name: str = Field(min_length=1, max_length=160)
    objective: str = Field(min_length=1, max_length=1_000)
    task_assessment: dict[str, Any] = Field(default_factory=dict)
    dependency_brief: tuple[dict[str, Any], ...] = Field(default=(), max_length=12)
    risk_brief: tuple[dict[str, Any], ...] = Field(default=(), max_length=12)
    preparation: tuple[str, ...] = Field(default=(), max_length=12)
    agenda: tuple[dict[str, Any], ...] = Field(default=(), max_length=12)
    questions: tuple[str, ...] = Field(default=(), max_length=12)
    decisions_required: tuple[dict[str, Any], ...] = Field(default=(), max_length=12)
    action_items: tuple[dict[str, Any], ...] = Field(default=(), max_length=20)
    success_criteria: tuple[str, ...] = Field(default=(), max_length=12)
    data_gaps: tuple[str, ...] = Field(default=(), max_length=20)


DeliveryArtifact = TeamTaskAssessmentArtifact | DependencyRiskArtifact | MeetingPlanArtifact


class RuntimeChildTask(FrozenContract):
    run_id: str = Field(min_length=1, max_length=128)
    specialist: DeliverySpecialist
    goal: str = Field(min_length=1, max_length=500)
    allowed_tools: tuple[str, ...] = Field(min_length=1, max_length=12)
    max_tool_calls: int = Field(default=4, ge=1, le=12)
    subject_refs: tuple[str, ...] = Field(default=(), max_length=20)
    depends_on: tuple[DeliverySpecialist, ...] = Field(default=(), max_length=4)
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_dependencies(self) -> RuntimeChildTask:
        if self.specialist in self.depends_on:
            raise ValueError("A specialist task cannot depend on itself")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("Specialist dependencies must be unique")
        return self


class DeliveryOrchestrationContext(FrozenContract):
    schema_version: str = Field(default="1.0", pattern=r"^1\.[0-9]+$")
    workflow_id: str = Field(min_length=1, max_length=128)
    execution_mode: DeliveryExecutionMode
    intent: DeliveryIntent
    plan_version: str = Field(min_length=1, max_length=64)
    child_tasks: tuple[RuntimeChildTask, ...] = Field(default=(), max_length=4)
    authorization_capability_ref: str = Field(min_length=1, max_length=256)
    authorization_scope_hash: str | None = Field(default=None, max_length=128)
    max_steps: int = Field(default=12, ge=1, le=32)
    deadline_at: datetime

    @model_validator(mode="after")
    def validate_context(self) -> DeliveryOrchestrationContext:
        if self.deadline_at.tzinfo is None:
            raise ValueError("Orchestration deadline must include a timezone")
        specialist_count = len(self.child_tasks)
        if self.execution_mode == DeliveryExecutionMode.DIRECT_TOOL:
            raise ValueError("Direct-tool requests do not cross the agent runtime boundary")
        if self.execution_mode == DeliveryExecutionMode.WORKSPACE_ONLY:
            raise ValueError("Workspace-only requests do not create specialist workflows")
        if self.execution_mode == DeliveryExecutionMode.SINGLE_SPECIALIST and specialist_count != 1:
            raise ValueError("Single-specialist context requires one child task")
        if self.execution_mode == DeliveryExecutionMode.MULTI_SPECIALIST and specialist_count < 2:
            raise ValueError("Multi-specialist context requires multiple child tasks")
        if len({task.specialist for task in self.child_tasks}) != specialist_count:
            raise ValueError("Runtime child specialists must be unique")
        return self


class DeliverySpecialistResult(FrozenContract):
    schema_version: str = Field(default="1.0", pattern=r"^1\.[0-9]+$")
    workflow_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    specialist: DeliverySpecialist
    status: ToolResultStatus
    summary: str = Field(min_length=1, max_length=4_000)
    facts: tuple[dict[str, Any], ...] = Field(default=(), max_length=200)
    inferences: tuple[dict[str, Any], ...] = Field(default=(), max_length=50)
    recommendations: tuple[dict[str, Any], ...] = Field(default=(), max_length=30)
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifact: DeliveryArtifact | None = None
    sources: tuple[SourceReference, ...] = Field(default=(), max_length=100)
    data_gaps: tuple[str, ...] = Field(default=(), max_length=100)
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_version: str = Field(min_length=1, max_length=64)
    llm_used: bool = False
    model_provider: str = Field(default="", max_length=32)
    model_name: str = Field(default="", max_length=128)
    usage: dict[str, int] = Field(default_factory=dict)
    upstream_result_hashes: tuple[str, ...] = Field(default=(), max_length=4)
    tool_calls: tuple[dict[str, Any], ...] = Field(default=(), max_length=12)
    attempt_count: int = Field(default=1, ge=1, le=3)
    generated_at: datetime

    @model_validator(mode="after")
    def validate_result(self) -> DeliverySpecialistResult:
        if self.generated_at.tzinfo is None:
            raise ValueError("Specialist result timestamp must include a timezone")
        return self


def canonical_payload_hash(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
