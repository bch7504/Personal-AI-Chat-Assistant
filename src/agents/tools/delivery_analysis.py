"""Production Delivery control-plane reads and deterministic analysis."""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Protocol

from src.agents.contracts import SourceReference, ToolResult, ToolResultStatus
from src.agents.schemas.delivery import (
    TERMINAL_DELIVERY_STATUSES,
    DeliveryCapacitySummary,
    DeliveryDecision,
    DeliveryDecisionStatus,
    DeliveryDependency,
    DeliveryFlowMetrics,
    DeliveryHealth,
    DeliveryItem,
    DeliveryReadScope,
    DeliveryReleaseStatus,
    DeliveryWorkStatus,
    build_delivery_risks,
    classify_delivery_item,
    evaluate_delivery_portfolio,
)
from src.services.delivery_workspace_service import (
    DeliveryQueryScope,
    DeliveryScopeError,
    build_delivery_query_scope,
)

DeliveryResourceRevalidator = Callable[[str], Awaitable[None]]


class DeliveryControlRepository(Protocol):
    async def list_dependencies(
        self, scope: DeliveryQueryScope
    ) -> Sequence[DeliveryDependency]: ...

    async def list_decisions(
        self, scope: DeliveryQueryScope
    ) -> Sequence[DeliveryDecision]: ...


class DeliveryReleaseRepository(Protocol):
    async def list_releases(
        self, scope: DeliveryQueryScope
    ) -> Sequence[DeliveryReleaseStatus]: ...


def _unique_sources(records: Sequence[object]) -> tuple[SourceReference, ...]:
    sources: dict[tuple[str, str, str], SourceReference] = {}
    for record in records:
        for source in getattr(record, "sources", ()):
            sources.setdefault(
                (source.resource_id, source.resource_type, source.agent_workspace_id), source
            )
    return tuple(sources.values())


def _validate_sources(records: Sequence[object], query_scope: DeliveryQueryScope) -> None:
    allowed = set(query_scope.group_ids)
    for record in records:
        unexpected = {
            source.resource_id for source in getattr(record, "sources", ())
        } - allowed
        if unexpected:
            raise DeliveryScopeError("Delivery control returned a source outside Delivery scope")


async def _revalidate_scope(
    scope: DeliveryReadScope, revalidate_resource: DeliveryResourceRevalidator
) -> DeliveryQueryScope:
    query_scope = build_delivery_query_scope(scope)
    for resource_id in query_scope.group_ids:
        await revalidate_resource(resource_id)
    return query_scope


async def get_delivery_dependencies(
    *,
    scope: DeliveryReadScope,
    repository: DeliveryControlRepository,
    revalidate_resource: DeliveryResourceRevalidator,
) -> ToolResult:
    query_scope = await _revalidate_scope(scope, revalidate_resource)
    if not query_scope.group_ids:
        return ToolResult(status=ToolResultStatus.SUCCESS, payload={"dependencies": []})
    try:
        dependencies = tuple(await repository.list_dependencies(query_scope))
    except DeliveryScopeError:
        raise
    except (OSError, TimeoutError):
        return ToolResult(
            status=ToolResultStatus.ERROR,
            error_code="DELIVERY_DEPENDENCY_READ_FAILED",
            error_message="Delivery dependencies are temporarily unavailable.",
        )
    _validate_sources(dependencies, query_scope)
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={
            "dependencies": [item.model_dump(mode="json") for item in dependencies]
        },
        sources=_unique_sources(dependencies),
    )


async def get_delivery_decisions(
    *,
    scope: DeliveryReadScope,
    repository: DeliveryControlRepository,
    revalidate_resource: DeliveryResourceRevalidator,
) -> ToolResult:
    query_scope = await _revalidate_scope(scope, revalidate_resource)
    if not query_scope.group_ids:
        return ToolResult(status=ToolResultStatus.SUCCESS, payload={"decisions": []})
    try:
        decisions = tuple(await repository.list_decisions(query_scope))
    except DeliveryScopeError:
        raise
    except (OSError, TimeoutError):
        return ToolResult(
            status=ToolResultStatus.ERROR,
            error_code="DELIVERY_DECISION_READ_FAILED",
            error_message="Delivery decisions are temporarily unavailable.",
        )
    _validate_sources(decisions, query_scope)
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={
            "decisions": [item.model_dump(mode="json") for item in decisions],
            "pending_count": sum(
                item.status == DeliveryDecisionStatus.PENDING for item in decisions
            ),
        },
        sources=_unique_sources(decisions),
    )


async def get_delivery_release_status(
    *,
    scope: DeliveryReadScope,
    repository: DeliveryReleaseRepository,
    revalidate_resource: DeliveryResourceRevalidator,
) -> ToolResult:
    query_scope = await _revalidate_scope(scope, revalidate_resource)
    if not query_scope.group_ids:
        return ToolResult(status=ToolResultStatus.SUCCESS, payload={"releases": []})
    try:
        releases = tuple(await repository.list_releases(query_scope))
    except DeliveryScopeError:
        raise
    except (OSError, TimeoutError):
        return ToolResult(
            status=ToolResultStatus.ERROR,
            error_code="DELIVERY_RELEASE_READ_FAILED",
            error_message="Delivery release status is temporarily unavailable.",
        )
    _validate_sources(releases, query_scope)
    counts = Counter(item.status for item in releases)
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={
            "releases": [item.model_dump(mode="json") for item in releases],
            "by_status": dict(counts),
        },
        sources=_unique_sources(releases),
    )


async def get_delivery_risks(
    *,
    scope: DeliveryReadScope,
    items: tuple[DeliveryItem, ...],
    milestones: tuple[DeliveryItem, ...],
    dependencies: tuple[DeliveryDependency, ...],
    releases: tuple[DeliveryReleaseStatus, ...],
    now: datetime,
) -> ToolResult:
    del scope  # The records were produced by scoped tools; keep the signature executor-safe.
    risks = build_delivery_risks(
        items=items,
        milestones=milestones,
        dependencies=dependencies,
        releases=releases,
        now=now,
    )
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={"risks": [risk.model_dump(mode="json") for risk in risks]},
        sources=_unique_sources(risks),
    )


async def get_delivery_capacity_summary(
    *, scope: DeliveryReadScope, items: tuple[DeliveryItem, ...], now: datetime
) -> ToolResult:
    del scope
    active = tuple(item for item in items if item.status not in TERMINAL_DELIVERY_STATUSES)
    classifications = {item.id: classify_delivery_item(item, now=now).health for item in active}
    summary = DeliveryCapacitySummary(
        total_active=len(active),
        pending=sum(item.status.value in {"suggested", "pending"} for item in active),
        in_progress=sum(item.status.value == "in_progress" for item in active),
        blocked=sum(DeliveryHealth.BLOCKED in classifications[item.id] for item in active),
        submitted=sum(item.status == DeliveryWorkStatus.SUBMITTED for item in active),
        changes_requested=sum(item.status == DeliveryWorkStatus.CHANGES_REQUESTED for item in active),
        unassigned=sum(DeliveryHealth.UNASSIGNED in classifications[item.id] for item in active),
        due_soon=sum(DeliveryHealth.DUE_SOON in classifications[item.id] for item in active),
        overdue=sum(DeliveryHealth.OVERDUE in classifications[item.id] for item in active),
    )
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={"capacity": summary.model_dump(mode="json")},
        sources=_unique_sources(active),
    )


async def get_delivery_flow_metrics(
    *, scope: DeliveryReadScope, items: tuple[DeliveryItem, ...], now: datetime | None = None
) -> ToolResult:
    del scope
    measured_at = now or datetime.now(UTC)
    if measured_at.tzinfo is None:
        raise ValueError("now must include a timezone")
    active_wip = sum(item.status not in TERMINAL_DELIVERY_STATUSES for item in items)
    completed = tuple(item for item in items if item.status == DeliveryWorkStatus.COMPLETED)
    period_start = measured_at - timedelta(days=7)
    completed_in_period = sum(
        item.completed_at is not None and period_start <= item.completed_at <= measured_at
        for item in completed
    )

    lead_times = tuple(
        (item.completed_at - item.created_at).total_seconds() / 3600
        for item in completed
        if item.created_at is not None
        and item.completed_at is not None
        and item.completed_at >= item.created_at
    )
    cycle_times = tuple(
        (item.completed_at - item.started_at).total_seconds() / 3600
        for item in completed
        if item.started_at is not None
        and item.completed_at is not None
        and item.completed_at >= item.started_at
    )
    gaps_list: list[str] = []
    if completed and len(lead_times) != len(completed):
        gaps_list.append("LEAD_TIME_HISTORY_INCOMPLETE")
    if completed and len(cycle_times) != len(completed):
        gaps_list.append("CYCLE_TIME_HISTORY_INCOMPLETE")
    if not completed:
        gaps_list.append("NO_COMPLETED_WORK_ITEMS")
    gaps = tuple(gaps_list)
    metrics = DeliveryFlowMetrics(
        active_wip=active_wip,
        completed_in_period=completed_in_period,
        throughput_per_week=float(completed_in_period),
        cycle_time_hours_p50=round(float(median(cycle_times)), 2) if cycle_times else None,
        lead_time_hours_p50=round(float(median(lead_times)), 2) if lead_times else None,
        data_gaps=gaps,
    )
    return ToolResult(
        status=ToolResultStatus.PARTIAL if gaps else ToolResultStatus.SUCCESS,
        payload={"flow_metrics": metrics.model_dump(mode="json")},
        sources=_unique_sources(items),
        data_gaps=gaps,
    )


async def get_delivery_portfolio_health(
    *,
    scope: DeliveryReadScope,
    items: tuple[DeliveryItem, ...],
    milestones: tuple[DeliveryItem, ...],
    dependencies: tuple[DeliveryDependency, ...],
    decisions: tuple[DeliveryDecision, ...],
    releases: tuple[DeliveryReleaseStatus, ...],
    now: datetime,
) -> ToolResult:
    del scope
    assessment = evaluate_delivery_portfolio(
        items=items,
        milestones=milestones,
        dependencies=dependencies,
        decisions=decisions,
        releases=releases,
        now=now,
    )
    records = (*items, *milestones, *dependencies, *decisions, *releases)
    return ToolResult(
        status=(
            ToolResultStatus.PARTIAL
            if assessment.data_gaps
            else ToolResultStatus.SUCCESS
        ),
        payload={"portfolio_health": assessment.model_dump(mode="json")},
        sources=_unique_sources(records),
        data_gaps=assessment.data_gaps,
    )
