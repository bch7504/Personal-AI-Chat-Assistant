"""Typed Quality Assurance contracts and deterministic release-gate rules."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from src.agents.contracts import (
    AgentContext,
    AgentIntent,
    AgentProfile,
    BusinessRole,
    FrozenContract,
    PolicyDecision,
    ReleaseReadiness,
    RequestedScope,
    SourceReference,
)


class QualityWorkItemType(StrEnum):
    BUG = "bug"
    TEST_CASE = "test_case"
    RELEASE_CHECK = "release_check"


class QualitySeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class QualityStatus(StrEnum):
    OPEN = "open"
    TESTING = "testing"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


_QUALITY_STATUS_TRANSITIONS = {
    QualityWorkItemType.BUG: {
        QualityStatus.OPEN: frozenset({QualityStatus.TESTING, QualityStatus.BLOCKED}),
        QualityStatus.TESTING: frozenset(
            {QualityStatus.PASSED, QualityStatus.FAILED, QualityStatus.BLOCKED}
        ),
        QualityStatus.FAILED: frozenset({QualityStatus.OPEN, QualityStatus.TESTING, QualityStatus.BLOCKED}),
        QualityStatus.BLOCKED: frozenset({QualityStatus.OPEN, QualityStatus.TESTING}),
        QualityStatus.PASSED: frozenset({QualityStatus.OPEN}),
    },
    QualityWorkItemType.TEST_CASE: {
        QualityStatus.OPEN: frozenset({QualityStatus.TESTING, QualityStatus.BLOCKED}),
        QualityStatus.TESTING: frozenset(
            {QualityStatus.PASSED, QualityStatus.FAILED, QualityStatus.BLOCKED}
        ),
        QualityStatus.FAILED: frozenset({QualityStatus.TESTING}),
        QualityStatus.BLOCKED: frozenset({QualityStatus.OPEN, QualityStatus.TESTING}),
        QualityStatus.PASSED: frozenset({QualityStatus.TESTING}),
    },
    QualityWorkItemType.RELEASE_CHECK: {
        QualityStatus.OPEN: frozenset({QualityStatus.TESTING, QualityStatus.BLOCKED}),
        QualityStatus.TESTING: frozenset(
            {QualityStatus.PASSED, QualityStatus.FAILED, QualityStatus.BLOCKED}
        ),
        QualityStatus.FAILED: frozenset({QualityStatus.TESTING}),
        QualityStatus.BLOCKED: frozenset({QualityStatus.OPEN, QualityStatus.TESTING}),
        QualityStatus.PASSED: frozenset({QualityStatus.TESTING}),
    },
}


def quality_status_transition_allowed(
    work_item_type: QualityWorkItemType,
    current: QualityStatus,
    requested: QualityStatus,
) -> bool:
    return current == requested or requested in _QUALITY_STATUS_TRANSITIONS[work_item_type][current]


class QualityViewScope(StrEnum):
    WORKSPACE = "workspace"
    GROUP = "group"
    MEMBER = "member"


class QualityReadScope(FrozenContract):
    context: AgentContext
    release_id: str = Field(min_length=1, max_length=128)
    view_scope: QualityViewScope
    effective_group_ids: tuple[str, ...] = ()
    selected_conversation_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_capability(self) -> QualityReadScope:
        if self.context.runtime.agent_profile != AgentProfile.QUALITY_ASSURANCE:
            raise ValueError("Quality reads require the quality_assurance profile")
        if self.context.request.requested_scope != RequestedScope.WORKSPACE:
            raise ValueError("Quality reads require workspace scope")
        if self.context.request.intent not in {AgentIntent.QUALITY_READINESS, AgentIntent.QUALITY_BRIEF}:
            raise ValueError("Quality reads require a Quality intent")
        if self.context.authorization.decision != PolicyDecision.ALLOW:
            raise ValueError("Quality reads require an allowed authorization context")
        target = self.context.request.target_agent_workspace_id
        if target is None or target not in self.context.authorization.allowed_agent_workspace_ids:
            raise ValueError("Quality target workspace is not authorized")
        if not set(self.effective_group_ids).issubset(self.context.authorization.allowed_resource_ids):
            raise ValueError("Quality group scope exceeds the authorized resources")
        if self.view_scope == QualityViewScope.WORKSPACE:
            if self.context.actor.business_role != BusinessRole.LEAD:
                raise ValueError("Only a Quality lead can request a workspace overview")
            if self.selected_conversation_id is not None:
                raise ValueError("A workspace overview cannot select one group")
        elif self.view_scope == QualityViewScope.GROUP:
            if self.context.actor.business_role != BusinessRole.LEAD:
                raise ValueError("Only a Quality lead can select a group")
            if self.effective_group_ids != (self.selected_conversation_id,):
                raise ValueError("The selected group must be the only effective resource")
        elif self.view_scope == QualityViewScope.MEMBER:
            if self.context.actor.business_role != BusinessRole.MEMBER:
                raise ValueError("A member view requires the member role")
            if self.selected_conversation_id is not None:
                raise ValueError("Members cannot select a group")
        return self


class QualityWorkItem(FrozenContract):
    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    work_item_type: QualityWorkItemType
    severity: QualitySeverity | None = None
    quality_status: QualityStatus
    release_id: str = Field(min_length=1, max_length=128)
    required: bool = False
    owner_id: str | None = Field(default=None, max_length=128)
    sources: tuple[SourceReference, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_domain_shape(self) -> QualityWorkItem:
        if self.work_item_type == QualityWorkItemType.BUG and self.severity is None:
            raise ValueError("A bug requires severity")
        if self.work_item_type != QualityWorkItemType.BUG and self.severity is not None:
            raise ValueError("Only a bug can have severity")
        if self.required and self.work_item_type != QualityWorkItemType.RELEASE_CHECK:
            raise ValueError("Only a release check can be required")
        return self


class QualityMessageEvidence(FrozenContract):
    message_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    sender_id: str = Field(min_length=1)
    sender_name: str = Field(min_length=1)
    excerpt: str = Field(min_length=1, max_length=1_000)
    created_at: datetime
    source: SourceReference


class QualityPerson(FrozenContract):
    user_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    job_title: str = ""


class QualityTestProgress(FrozenContract):
    total: int = Field(ge=0)
    open: int = Field(ge=0)
    testing: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    blocked: int = Field(ge=0)


class QualityReadinessAssessment(FrozenContract):
    release_id: str
    release_readiness: ReleaseReadiness
    test_progress: QualityTestProgress
    critical_defects: tuple[QualityWorkItem, ...] = ()
    blocked_tests: tuple[QualityWorkItem, ...] = ()
    risks: tuple[QualityWorkItem, ...] = ()
    reasons: tuple[str, ...]
    data_gaps: tuple[str, ...] = ()

    @model_validator(mode="after")
    def ready_requires_complete_data(self) -> QualityReadinessAssessment:
        if self.release_readiness == ReleaseReadiness.READY and self.data_gaps:
            raise ValueError("READY cannot be emitted with data gaps")
        return self


def evaluate_release_readiness(
    items: tuple[QualityWorkItem, ...], *, release_id: str, extra_data_gaps: tuple[str, ...] = ()
) -> QualityReadinessAssessment:
    """Evaluate one release only; the LLM cannot alter this result."""

    if any(item.release_id != release_id for item in items):
        raise ValueError("A readiness assessment cannot mix releases")
    tests = tuple(
        item for item in items if item.work_item_type in {QualityWorkItemType.TEST_CASE, QualityWorkItemType.RELEASE_CHECK}
    )
    counts = Counter(item.quality_status for item in tests)
    progress = QualityTestProgress(
        total=len(tests),
        open=counts[QualityStatus.OPEN],
        testing=counts[QualityStatus.TESTING],
        passed=counts[QualityStatus.PASSED],
        failed=counts[QualityStatus.FAILED],
        blocked=counts[QualityStatus.BLOCKED],
    )
    active = {QualityStatus.OPEN, QualityStatus.TESTING, QualityStatus.FAILED, QualityStatus.BLOCKED}
    failed = {QualityStatus.FAILED, QualityStatus.BLOCKED}
    pending = {QualityStatus.OPEN, QualityStatus.TESTING}
    active_bugs = tuple(item for item in items if item.work_item_type == QualityWorkItemType.BUG and item.quality_status in active)
    critical = tuple(item for item in active_bugs if item.severity == QualitySeverity.CRITICAL)
    non_critical = tuple(item for item in active_bugs if item.severity != QualitySeverity.CRITICAL)
    blocked_tests = tuple(item for item in tests if item.quality_status in failed)
    required_checks = tuple(item for item in items if item.work_item_type == QualityWorkItemType.RELEASE_CHECK and item.required)
    failed_required = tuple(item for item in required_checks if item.quality_status in failed)
    pending_required = tuple(item for item in required_checks if item.quality_status in pending)
    pending_tests = tuple(item for item in tests if item.quality_status in pending)

    reasons: list[str] = []
    gaps = list(extra_data_gaps)
    if critical:
        reasons.append("critical_defect_active")
    if failed_required:
        reasons.append("required_release_check_failed")
    if not required_checks:
        reasons.append("no_required_release_checks_declared")
        gaps.append(f"No required release checks are declared for release {release_id}")
    if critical or failed_required:
        readiness = ReleaseReadiness.NOT_READY
    else:
        if pending_required:
            reasons.append("required_release_check_pending")
        if pending_tests:
            reasons.append("test_execution_incomplete")
        if non_critical:
            reasons.append("non_critical_defect_active")
        if blocked_tests:
            reasons.append("test_failure_or_blocker")
        if gaps and not reasons:
            reasons.append("incomplete_quality_data")
        readiness = ReleaseReadiness.AT_RISK if reasons or gaps else ReleaseReadiness.READY
        if readiness == ReleaseReadiness.READY:
            reasons.append("all_required_checks_passed")

    risk_items = tuple(dict.fromkeys((*non_critical, *pending_tests)))
    return QualityReadinessAssessment(
        release_id=release_id,
        release_readiness=readiness,
        test_progress=progress,
        critical_defects=critical,
        blocked_tests=blocked_tests,
        risks=risk_items,
        reasons=tuple(dict.fromkeys(reasons)),
        data_gaps=tuple(dict.fromkeys(gaps)),
    )
