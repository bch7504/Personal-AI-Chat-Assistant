"""Deterministic Delivery brief producer from already-scoped tool data."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from src.agents.contracts import (
    AgentProfile,
    BriefType,
    SourceReference,
    ToolResult,
    ToolResultStatus,
    WorkspaceBrief,
)
from src.agents.schemas.delivery import (
    DeliveryBriefPayload,
    DeliveryCapacitySummary,
    DeliveryDecision,
    DeliveryDependency,
    DeliveryFlowMetrics,
    DeliveryHealth,
    DeliveryItem,
    DeliveryPortfolioAssessment,
    DeliveryPortfolioHealth,
    DeliveryReadScope,
    DeliveryRecommendation,
    DeliveryReleaseStatus,
    DeliveryRisk,
    DeliveryViewScope,
    classify_delivery_item,
)


def _unique_sources(records: Iterable[DeliveryItem | DeliveryDependency]) -> tuple[SourceReference, ...]:
    sources: dict[str, SourceReference] = {}
    for record in records:
        for source in record.sources:
            sources.setdefault(source.resource_id, source)
    return tuple(sources.values())


def _headline(
    *,
    blocked: tuple[DeliveryItem, ...],
    overdue: tuple[DeliveryItem, ...],
    data_gaps: tuple[str, ...],
    portfolio_health: DeliveryPortfolioAssessment | None = None,
) -> str:
    if portfolio_health is not None:
        labels = {
            DeliveryPortfolioHealth.BLOCKED: "Delivery portfolio is blocked and requires intervention.",
            DeliveryPortfolioHealth.AT_RISK: "Delivery portfolio is at risk and requires attention.",
            DeliveryPortfolioHealth.INSUFFICIENT_DATA: "Delivery data is insufficient for a reliable portfolio assessment.",
            DeliveryPortfolioHealth.ON_TRACK: "Delivery portfolio is on track in the selected scope.",
        }
        return labels[portfolio_health.health]
    if blocked:
        return f"Delivery has {len(blocked)} blocked item(s) requiring attention."
    if overdue:
        return f"Delivery has {len(overdue)} overdue item(s) requiring attention."
    if data_gaps:
        return "Delivery data is partial; see data gaps before making a decision."
    return "Delivery is on track in the selected scope."


def build_delivery_payload(
    *,
    scope: DeliveryReadScope,
    items: tuple[DeliveryItem, ...],
    period_start: datetime,
    period_end: datetime,
    generated_at: datetime,
    expires_at: datetime,
    milestones: tuple[DeliveryItem, ...] = (),
    dependencies: tuple[DeliveryDependency, ...] = (),
    decisions_needed: tuple[DeliveryDecision, ...] = (),
    risks: tuple[DeliveryRisk, ...] = (),
    releases: tuple[DeliveryReleaseStatus, ...] = (),
    portfolio_health: DeliveryPortfolioAssessment | None = None,
    capacity: DeliveryCapacitySummary | None = None,
    flow_metrics: DeliveryFlowMetrics | None = None,
    recommendations: tuple[DeliveryRecommendation, ...] = (),
    data_gaps: tuple[str, ...] = (),
) -> DeliveryBriefPayload:
    """Classify source-backed items and build a strict domain payload.

    The caller must have completed all reads through scoped tools first. This
    function deliberately has no database, model, side-effect or publication
    dependency.
    """

    classifications = {item.id: classify_delivery_item(item, now=generated_at).health for item in items}
    blocked = tuple(item for item in items if DeliveryHealth.BLOCKED in classifications[item.id])
    overdue = tuple(item for item in items if DeliveryHealth.OVERDUE in classifications[item.id])
    due_soon = tuple(item for item in items if DeliveryHealth.DUE_SOON in classifications[item.id])
    unassigned = tuple(item for item in items if DeliveryHealth.UNASSIGNED in classifications[item.id])

    all_records = (
        *items,
        *milestones,
        *dependencies,
        *decisions_needed,
        *risks,
        *releases,
    )
    resolved_data_gaps = data_gaps or (("NO_DELIVERY_FACTS",) if not all_records else ())
    headline_sources = tuple(source.resource_id for source in _unique_sources(all_records))
    if not all_records:
        headline_sources = ()

    target_workspace_id = scope.context.request.target_agent_workspace_id
    if target_workspace_id is None:  # Defensive; DeliveryReadScope validates this.
        raise ValueError("Delivery target workspace is missing")

    return DeliveryBriefPayload(
        agent_workspace_id=target_workspace_id,
        view_scope=scope.view_scope,
        conversation_id=scope.selected_conversation_id,
        period_start=period_start,
        period_end=period_end,
        generated_at=generated_at,
        expires_at=expires_at,
        headline=_headline(
            blocked=blocked,
            overdue=overdue,
            data_gaps=resolved_data_gaps,
            portfolio_health=portfolio_health,
        ),
        headline_source_ids=headline_sources,
        portfolio_health=portfolio_health,
        milestones=milestones,
        overdue_items=overdue,
        due_soon_items=due_soon,
        blocked_items=blocked,
        unassigned_items=unassigned,
        dependencies=dependencies,
        decisions_needed=decisions_needed,
        risks=risks,
        releases=releases,
        capacity=capacity,
        flow_metrics=flow_metrics,
        recommendations=recommendations,
        data_gaps=resolved_data_gaps,
    )


def to_workspace_brief(
    *,
    payload: DeliveryBriefPayload,
    scope: DeliveryReadScope,
    brief_id: str,
    trace_id: str,
) -> WorkspaceBrief:
    """Create the common handoff only for a lead's workspace-level overview."""

    if scope.view_scope != DeliveryViewScope.WORKSPACE or payload.view_scope != DeliveryViewScope.WORKSPACE:
        raise ValueError("Only a workspace overview can be published as a WorkspaceBrief")
    if payload.agent_workspace_id != scope.context.request.target_agent_workspace_id:
        raise ValueError("Delivery payload workspace does not match the trusted scope")

    records = (
        *payload.milestones,
        *payload.overdue_items,
        *payload.due_soon_items,
        *payload.blocked_items,
        *payload.unassigned_items,
        *payload.dependencies,
        *payload.decisions_needed,
        *payload.risks,
        *payload.releases,
    )
    sources = _unique_sources(records)
    facts = tuple(
        item.model_dump(mode="json")
        for item in (*payload.milestones, *payload.due_soon_items, *payload.unassigned_items)
    )
    risks = tuple(
        item.model_dump(mode="json") for item in (*payload.blocked_items, *payload.overdue_items)
    )
    return WorkspaceBrief(
        brief_id=brief_id,
        trace_id=trace_id,
        organization_workspace_id=scope.context.actor.organization_workspace_id,
        agent_workspace_id=payload.agent_workspace_id,
        brief_type=BriefType.DELIVERY,
        producer_profile=AgentProfile.PRODUCT_DELIVERY,
        period_start=payload.period_start,
        period_end=payload.period_end,
        generated_at=payload.generated_at,
        expires_at=payload.expires_at,
        headline=payload.headline,
        facts=facts,
        risks=tuple((*risks, *(item.model_dump(mode="json") for item in payload.risks))),
        dependencies=tuple(item.model_dump(mode="json") for item in payload.dependencies),
        decisions_needed=tuple(item.model_dump(mode="json") for item in payload.decisions_needed),
        data_gaps=payload.data_gaps,
        sources=sources,
    )


def as_delivery_brief_result(
    *, payload: DeliveryBriefPayload, checked_at: datetime
) -> ToolResult:
    """Expose a brief without allowing an expired result to look current.

    Runtime/API wiring must call this boundary after it has revalidated the
    caller's capability.  It does not refresh, publish, or widen access; it
    only preserves freshness and known data gaps in a transport-safe result.
    """

    if checked_at.tzinfo is None:
        raise ValueError("Freshness checks require a timezone-aware datetime")

    records = (
        *payload.milestones,
        *payload.overdue_items,
        *payload.due_soon_items,
        *payload.blocked_items,
        *payload.unassigned_items,
        *payload.dependencies,
        *payload.decisions_needed,
        *payload.risks,
        *payload.releases,
    )
    data_gaps = payload.data_gaps
    freshness = "fresh"
    is_current = True
    if payload.is_stale(at=checked_at):
        freshness = "stale"
        is_current = False
        data_gaps = tuple(dict.fromkeys((*data_gaps, "DELIVERY_BRIEF_STALE")))

    return ToolResult(
        status=ToolResultStatus.PARTIAL if data_gaps else ToolResultStatus.SUCCESS,
        payload={
            "brief": payload.model_dump(mode="json"),
            "freshness": freshness,
            "is_current": is_current,
        },
        sources=_unique_sources(records),
        data_gaps=data_gaps,
    )
