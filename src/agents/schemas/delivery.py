"""Contracts and deterministic business rules owned by Product Delivery.

These models deliberately sit below the shared ``WorkspaceBrief`` contract.  They
make Delivery facts evidence-backed before a producer maps them to the common
handoff format; they do not grant data access or publish anything by themselves.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import Field, model_validator

from src.agents.contracts import (
    AgentContext,
    AgentIntent,
    AgentProfile,
    BusinessRole,
    FrozenContract,
    PolicyDecision,
    RequestedScope,
    SourceReference,
)


class DeliveryWorkStatus(StrEnum):
    SUGGESTED = "suggested"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    SUBMITTED = "submitted"
    CHANGES_REQUESTED = "changes_requested"
    COMPLETED = "completed"
    DISMISSED = "dismissed"
    INVALIDATED = "invalidated"
    UNKNOWN = "unknown"


class DeliveryHealth(StrEnum):
    ON_TRACK = "on_track"
    OVERDUE = "overdue"
    DUE_SOON = "due_soon"
    BLOCKED = "blocked"
    UNASSIGNED = "unassigned"
    DATA_GAP = "data_gap"


class DeliveryPortfolioHealth(StrEnum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    BLOCKED = "BLOCKED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class DeliveryDependencyStatus(StrEnum):
    OPEN = "open"
    BLOCKED = "blocked"
    RESOLVED = "resolved"
    INVALIDATED = "invalidated"


class DeliveryDecisionStatus(StrEnum):
    PENDING = "pending"
    DECIDED = "decided"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"


class DeliveryRiskSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DeliveryViewScope(StrEnum):
    WORKSPACE = "workspace"
    GROUP = "group"
    MEMBER = "member"


class DeliveryReadScope(FrozenContract):
    """Server-resolved capability envelope for every Delivery read.

    This is deliberately not an API request schema. The platform resolver creates
    it only after authentication, membership and consent checks; tools consume it
    as an immutable allowlist and cannot broaden it.
    """

    context: AgentContext
    view_scope: DeliveryViewScope
    effective_group_ids: tuple[str, ...] = ()
    allowed_task_ids: tuple[str, ...] = ()
    allowed_decision_ids: tuple[str, ...] = ()
    allowed_person_ids: tuple[str, ...] = ()
    selected_conversation_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def is_a_valid_delivery_capability(self) -> DeliveryReadScope:
        if self.context.runtime.agent_profile != AgentProfile.PRODUCT_DELIVERY:
            raise ValueError("Delivery reads require the product_delivery profile")
        if self.context.request.requested_scope != RequestedScope.WORKSPACE:
            raise ValueError("Delivery reads require workspace scope")
        if self.context.request.intent != AgentIntent.DELIVERY_BRIEF:
            raise ValueError("Delivery reads require the delivery_brief intent")
        if self.context.authorization.decision != PolicyDecision.ALLOW:
            raise ValueError("Delivery reads require an allowed authorization context")

        target_workspace_id = self.context.request.target_agent_workspace_id
        if (
            target_workspace_id is None
            or target_workspace_id not in self.context.authorization.allowed_agent_workspace_ids
        ):
            raise ValueError("Delivery target workspace is not authorized")
        allowed_resources = set(self.context.authorization.allowed_resource_ids)
        if not set(self.effective_group_ids).issubset(allowed_resources):
            raise ValueError("Effective group scope must be a subset of authorized resources")

        if self.view_scope == DeliveryViewScope.WORKSPACE:
            if self.context.actor.business_role != BusinessRole.LEAD:
                raise ValueError("Only a Delivery lead can request a workspace overview")
            if self.selected_conversation_id is not None:
                raise ValueError("A workspace overview cannot target one conversation")
            if self.effective_group_ids != self.context.authorization.allowed_resource_ids:
                raise ValueError("A workspace overview must use the full resolved group allowlist")
        elif self.view_scope == DeliveryViewScope.GROUP:
            # Both Lead and Member may read a single explicitly authorized
            # channel. Write capabilities are enforced independently.
            if len(self.effective_group_ids) != 1 or self.selected_conversation_id is None:
                raise ValueError("A group snapshot requires exactly one selected authorized group")
            if self.effective_group_ids != (self.selected_conversation_id,):
                raise ValueError("Selected conversation must match the effective group scope")
        elif self.view_scope == DeliveryViewScope.MEMBER:
            if self.context.actor.business_role != BusinessRole.MEMBER:
                raise ValueError("A member view requires the member business role")
            if self.selected_conversation_id is not None:
                raise ValueError("A member view cannot target one conversation")

        return self


TERMINAL_DELIVERY_STATUSES = frozenset(
    {DeliveryWorkStatus.COMPLETED, DeliveryWorkStatus.DISMISSED, DeliveryWorkStatus.INVALIDATED}
)


class DeliveryItem(FrozenContract):
    """A source-backed task or work item.  It is never a free-text extraction."""

    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    status: DeliveryWorkStatus
    assignee_id: str | None = Field(default=None, max_length=128)
    due_at: datetime | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    sources: tuple[SourceReference, ...] = Field(min_length=1, max_length=20)
    confidence: float | None = Field(default=None, ge=0, le=1)
    blocked_reason: str | None = Field(default=None, max_length=500)
    row_version: int | None = Field(default=None, ge=1)
    requires_review: bool = False
    submission_note: str | None = Field(default=None, max_length=4000)
    evidence_urls: tuple[str, ...] = Field(default=(), max_length=20)
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def timestamps_are_timezone_aware(self) -> DeliveryItem:
        for field_name in ("due_at", "created_at", "started_at", "completed_at", "submitted_at", "reviewed_at"):
            value = getattr(self, field_name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{field_name} must include a timezone")
        if self.started_at is not None and self.created_at is not None and self.started_at < self.created_at:
            raise ValueError("started_at cannot precede created_at")
        if self.completed_at is not None and self.started_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if self.status == DeliveryWorkStatus.BLOCKED and not self.blocked_reason:
            raise ValueError("A blocked item requires a source-backed blocked_reason")
        if self.status == DeliveryWorkStatus.SUBMITTED and not (self.submission_note or self.evidence_urls):
            raise ValueError("A submitted item requires a note or evidence URL")
        return self


class DeliveryDependency(FrozenContract):
    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    status: DeliveryDependencyStatus = DeliveryDependencyStatus.OPEN
    assignee_id: str | None = Field(default=None, max_length=128)
    predecessor_task_id: str | None = Field(default=None, max_length=128)
    successor_task_id: str | None = Field(default=None, max_length=128)
    due_at: datetime | None = None
    sources: tuple[SourceReference, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def due_at_is_timezone_aware(self) -> DeliveryDependency:
        if self.due_at is not None and self.due_at.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        if self.predecessor_task_id is not None and self.predecessor_task_id == self.successor_task_id:
            raise ValueError("A dependency cannot link a task to itself")
        return self


class DeliveryDecision(FrozenContract):
    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    status: DeliveryDecisionStatus = DeliveryDecisionStatus.PENDING
    owner_id: str | None = Field(default=None, max_length=128)
    due_at: datetime | None = None
    options: tuple[str, ...] = Field(default=(), max_length=20)
    outcome: str | None = Field(default=None, max_length=2000)
    sources: tuple[SourceReference, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def is_a_valid_decision(self) -> DeliveryDecision:
        if self.due_at is not None and self.due_at.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        if self.status == DeliveryDecisionStatus.DECIDED and not self.outcome:
            raise ValueError("A decided item requires an outcome")
        return self


class DeliveryReleaseStatus(FrozenContract):
    id: str = Field(min_length=1, max_length=128)
    release_key: str = Field(min_length=1, max_length=160)
    status: str = Field(pattern=r"^(draft|qa_requested|qa_in_progress|approved|rejected|released|cancelled)$")
    version: str = Field(default="", max_length=128)
    build_number: str = Field(default="", max_length=128)
    environment: str = Field(default="staging", max_length=128)
    quality_policy_version: str = Field(min_length=1, max_length=128)
    sources: tuple[SourceReference, ...] = Field(min_length=1, max_length=5)


class DeliveryRisk(FrozenContract):
    id: str = Field(min_length=1, max_length=180)
    title: str = Field(min_length=1, max_length=500)
    severity: DeliveryRiskSeverity
    reason_code: str = Field(min_length=1, max_length=128)
    sources: tuple[SourceReference, ...] = Field(min_length=1, max_length=20)


class DeliveryCapacitySummary(FrozenContract):
    total_active: int = Field(ge=0)
    pending: int = Field(ge=0)
    in_progress: int = Field(ge=0)
    blocked: int = Field(ge=0)
    submitted: int = Field(default=0, ge=0)
    changes_requested: int = Field(default=0, ge=0)
    unassigned: int = Field(ge=0)
    due_soon: int = Field(ge=0)
    overdue: int = Field(ge=0)


class DeliveryFlowMetrics(FrozenContract):
    active_wip: int = Field(ge=0)
    completed_in_period: int | None = Field(default=None, ge=0)
    throughput_per_week: float | None = Field(default=None, ge=0)
    cycle_time_hours_p50: float | None = Field(default=None, ge=0)
    lead_time_hours_p50: float | None = Field(default=None, ge=0)
    data_gaps: tuple[str, ...] = ()


class DeliveryPortfolioAssessment(FrozenContract):
    health: DeliveryPortfolioHealth
    reasons: tuple[str, ...]
    risk_count: int = Field(ge=0)
    pending_decision_count: int = Field(ge=0)
    open_dependency_count: int = Field(ge=0)
    data_gaps: tuple[str, ...] = ()


class DeliveryRecommendation(FrozenContract):
    text: str = Field(min_length=1, max_length=1000)
    based_on_source_ids: tuple[str, ...] = Field(min_length=1, max_length=20)


class DeliveryMessageEvidence(FrozenContract):
    """A bounded, source-backed group-chat excerpt; never a tool instruction."""

    message_id: str = Field(min_length=1, max_length=128)
    conversation_id: str = Field(min_length=1, max_length=128)
    excerpt: str = Field(min_length=1, max_length=1200)
    sources: tuple[SourceReference, ...] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def source_belongs_to_the_evidence_conversation(self) -> DeliveryMessageEvidence:
        if any(source.resource_id != self.conversation_id for source in self.sources):
            raise ValueError("Message evidence sources must refer to its conversation")
        return self


class DeliveryPerson(FrozenContract):
    """Minimal person projection safe for a Delivery brief or work view."""

    user_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=160)


class DeliveryClassification(FrozenContract):
    item_id: str
    health: tuple[DeliveryHealth, ...]


def classify_delivery_item(
    item: DeliveryItem,
    *,
    now: datetime,
    due_soon_window: timedelta = timedelta(days=7),
) -> DeliveryClassification:
    """Classify a Delivery item without querying data or inferring new facts.

    Blocked state is explicit.  Missing assignee/date is reported as a data gap or
    unassigned state rather than guessed from message volume or model sentiment.
    """

    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    if due_soon_window <= timedelta(0):
        raise ValueError("due_soon_window must be positive")

    health: list[DeliveryHealth] = []
    if item.status == DeliveryWorkStatus.UNKNOWN:
        health.append(DeliveryHealth.DATA_GAP)
    if item.status == DeliveryWorkStatus.BLOCKED:
        health.append(DeliveryHealth.BLOCKED)
    if not item.assignee_id:
        health.append(DeliveryHealth.UNASSIGNED)

    if item.status not in TERMINAL_DELIVERY_STATUSES:
        if item.due_at is None:
            health.append(DeliveryHealth.DATA_GAP)
        elif item.due_at < now:
            health.append(DeliveryHealth.OVERDUE)
        elif item.due_at <= now + due_soon_window:
            health.append(DeliveryHealth.DUE_SOON)

    return DeliveryClassification(
        item_id=item.id,
        health=tuple(health) if health else (DeliveryHealth.ON_TRACK,),
    )


def build_delivery_risks(
    *,
    items: tuple[DeliveryItem, ...],
    milestones: tuple[DeliveryItem, ...],
    dependencies: tuple[DeliveryDependency, ...],
    releases: tuple[DeliveryReleaseStatus, ...],
    now: datetime,
) -> tuple[DeliveryRisk, ...]:
    """Build a reproducible risk register from explicit domain state."""

    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    risks: list[DeliveryRisk] = []
    for item in (*items, *milestones):
        health = classify_delivery_item(item, now=now).health
        if item.status == DeliveryWorkStatus.CHANGES_REQUESTED:
            risks.append(
                DeliveryRisk(
                    id=f"changes-requested:{item.id}",
                    title=f"Changes requested: {item.title}",
                    severity=DeliveryRiskSeverity.HIGH,
                    reason_code="TASK_CHANGES_REQUESTED",
                    sources=item.sources,
                )
            )
        elif DeliveryHealth.BLOCKED in health:
            risks.append(
                DeliveryRisk(
                    id=f"blocked:{item.id}",
                    title=f"Blocked: {item.title}",
                    severity=DeliveryRiskSeverity.CRITICAL,
                    reason_code="WORK_ITEM_BLOCKED",
                    sources=item.sources,
                )
            )
        elif DeliveryHealth.OVERDUE in health:
            risks.append(
                DeliveryRisk(
                    id=f"overdue:{item.id}",
                    title=f"Overdue: {item.title}",
                    severity=DeliveryRiskSeverity.HIGH,
                    reason_code="WORK_ITEM_OVERDUE",
                    sources=item.sources,
                )
            )
    for dependency in dependencies:
        is_overdue = (
            dependency.due_at is not None
            and dependency.due_at < now
            and dependency.status
            not in {
                DeliveryDependencyStatus.RESOLVED,
                DeliveryDependencyStatus.INVALIDATED,
            }
        )
        if dependency.status == DeliveryDependencyStatus.BLOCKED or is_overdue:
            risks.append(
                DeliveryRisk(
                    id=f"dependency:{dependency.id}",
                    title=f"Dependency at risk: {dependency.title}",
                    severity=(
                        DeliveryRiskSeverity.CRITICAL
                        if dependency.status == DeliveryDependencyStatus.BLOCKED
                        else DeliveryRiskSeverity.HIGH
                    ),
                    reason_code=(
                        "DEPENDENCY_BLOCKED"
                        if dependency.status == DeliveryDependencyStatus.BLOCKED
                        else "DEPENDENCY_OVERDUE"
                    ),
                    sources=dependency.sources,
                )
            )
    for release in releases:
        if release.status == "rejected":
            risks.append(
                DeliveryRisk(
                    id=f"release:{release.id}",
                    title=f"QA rejected release {release.release_key}",
                    severity=DeliveryRiskSeverity.CRITICAL,
                    reason_code="QA_RELEASE_REJECTED",
                    sources=release.sources,
                )
            )
    return tuple(risks)


def evaluate_delivery_portfolio(
    *,
    items: tuple[DeliveryItem, ...],
    milestones: tuple[DeliveryItem, ...] = (),
    dependencies: tuple[DeliveryDependency, ...] = (),
    decisions: tuple[DeliveryDecision, ...] = (),
    releases: tuple[DeliveryReleaseStatus, ...] = (),
    now: datetime,
) -> DeliveryPortfolioAssessment:
    """Compute the portfolio label which the narrative layer must preserve."""

    facts = (*items, *milestones, *dependencies, *decisions, *releases)
    if not facts:
        return DeliveryPortfolioAssessment(
            health=DeliveryPortfolioHealth.INSUFFICIENT_DATA,
            reasons=("NO_DELIVERY_FACTS",),
            risk_count=0,
            pending_decision_count=0,
            open_dependency_count=0,
            data_gaps=("NO_DELIVERY_FACTS",),
        )
    risks = build_delivery_risks(
        items=items,
        milestones=milestones,
        dependencies=dependencies,
        releases=releases,
        now=now,
    )
    pending_decisions = tuple(decision for decision in decisions if decision.status == DeliveryDecisionStatus.PENDING)
    open_dependencies = tuple(
        dependency
        for dependency in dependencies
        if dependency.status not in {DeliveryDependencyStatus.RESOLVED, DeliveryDependencyStatus.INVALIDATED}
    )
    reasons = [risk.reason_code for risk in risks]
    overdue_decisions = tuple(
        decision for decision in pending_decisions if decision.due_at is not None and decision.due_at < now
    )
    if overdue_decisions:
        reasons.append("DECISION_OVERDUE")
    unresolved_qa = tuple(release for release in releases if release.status in {"qa_requested", "qa_in_progress"})
    if unresolved_qa:
        reasons.append("QA_GATE_PENDING")

    critical = any(risk.severity == DeliveryRiskSeverity.CRITICAL for risk in risks)
    if critical:
        health = DeliveryPortfolioHealth.BLOCKED
    elif risks or overdue_decisions or unresolved_qa:
        health = DeliveryPortfolioHealth.AT_RISK
    else:
        health = DeliveryPortfolioHealth.ON_TRACK
    return DeliveryPortfolioAssessment(
        health=health,
        reasons=tuple(dict.fromkeys(reasons)) or ("NO_ACTIVE_DELIVERY_RISK",),
        risk_count=len(risks),
        pending_decision_count=len(pending_decisions),
        open_dependency_count=len(open_dependencies),
    )


class DeliveryBriefPayload(FrozenContract):
    """Validated Delivery-domain payload before conversion to ``WorkspaceBrief``."""

    schema_version: str = Field(default="1.0", pattern=r"^1\.[0-9]+$")
    agent_workspace_id: str = Field(min_length=1)
    view_scope: DeliveryViewScope = DeliveryViewScope.WORKSPACE
    conversation_id: str | None = Field(default=None, min_length=1)
    period_start: datetime
    period_end: datetime
    generated_at: datetime
    expires_at: datetime
    headline: str = Field(min_length=1, max_length=1000)
    headline_source_ids: tuple[str, ...] = Field(default=(), max_length=20)
    portfolio_health: DeliveryPortfolioAssessment | None = None
    milestones: tuple[DeliveryItem, ...] = ()
    overdue_items: tuple[DeliveryItem, ...] = ()
    due_soon_items: tuple[DeliveryItem, ...] = ()
    blocked_items: tuple[DeliveryItem, ...] = ()
    unassigned_items: tuple[DeliveryItem, ...] = ()
    dependencies: tuple[DeliveryDependency, ...] = ()
    decisions_needed: tuple[DeliveryDecision, ...] = ()
    risks: tuple[DeliveryRisk, ...] = ()
    releases: tuple[DeliveryReleaseStatus, ...] = ()
    capacity: DeliveryCapacitySummary | None = None
    flow_metrics: DeliveryFlowMetrics | None = None
    recommendations: tuple[DeliveryRecommendation, ...] = ()
    data_gaps: tuple[str, ...] = ()

    @model_validator(mode="after")
    def is_complete_and_source_scoped(self) -> DeliveryBriefPayload:
        timestamps = (self.period_start, self.period_end, self.generated_at, self.expires_at)
        if any(value.tzinfo is None for value in timestamps):
            raise ValueError("Delivery brief timestamps must include a timezone")
        if self.period_end < self.period_start:
            raise ValueError("period_end must not be before period_start")
        if self.expires_at <= self.generated_at:
            raise ValueError("expires_at must be after generated_at")
        if self.view_scope == DeliveryViewScope.GROUP and self.conversation_id is None:
            raise ValueError("A group snapshot requires conversation_id")
        if self.view_scope != DeliveryViewScope.GROUP and self.conversation_id is not None:
            raise ValueError("conversation_id is valid only for a group snapshot")

        facts = (
            *self.milestones,
            *self.overdue_items,
            *self.due_soon_items,
            *self.blocked_items,
            *self.unassigned_items,
            *self.dependencies,
            *self.decisions_needed,
            *self.risks,
            *self.releases,
        )
        source_ids = {source.resource_id for fact in facts for source in fact.sources}
        if facts and not self.headline_source_ids:
            raise ValueError("A factual headline requires source references")
        if not facts and not self.data_gaps:
            raise ValueError("An empty Delivery brief requires at least one data gap")
        if not set(self.headline_source_ids).issubset(source_ids):
            raise ValueError("headline_source_ids must refer to returned facts")
        if any(source.agent_workspace_id != self.agent_workspace_id for fact in facts for source in fact.sources):
            raise ValueError("Every fact source must belong to the Delivery agent workspace")
        if any(
            not set(recommendation.based_on_source_ids).issubset(source_ids) for recommendation in self.recommendations
        ):
            raise ValueError("Recommendations must be grounded in returned fact sources")
        expected_health = (
            (self.overdue_items, DeliveryHealth.OVERDUE),
            (self.due_soon_items, DeliveryHealth.DUE_SOON),
            (self.blocked_items, DeliveryHealth.BLOCKED),
            (self.unassigned_items, DeliveryHealth.UNASSIGNED),
        )
        for items, expected in expected_health:
            for item in items:
                if expected not in classify_delivery_item(item, now=self.generated_at).health:
                    raise ValueError(f"Item '{item.id}' does not belong in '{expected.value}'")
        return self

    def is_stale(self, *, at: datetime | None = None) -> bool:
        """Return whether a consumer must stop presenting this brief as current."""

        checked_at = at or datetime.now(UTC)
        if checked_at.tzinfo is None:
            raise ValueError("Freshness checks require a timezone-aware datetime")
        return checked_at >= self.expires_at


def utc_now() -> datetime:
    """Injectable default for callers that need a timezone-aware current time."""

    return datetime.now(UTC)
