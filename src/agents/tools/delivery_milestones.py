"""Fail-safe Delivery milestone adapter until a structured source is available."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from src.agents.contracts import ToolResult, ToolResultStatus
from src.agents.schemas.delivery import DeliveryItem, DeliveryReadScope
from src.services.delivery_workspace_service import DeliveryQueryScope, build_delivery_query_scope

DeliveryResourceRevalidator = Callable[[str], Awaitable[None]]


class DeliveryMilestoneRepository(Protocol):
    async def list_milestones(self, scope: DeliveryQueryScope) -> Sequence[DeliveryItem]: ...


async def get_delivery_milestones(
    *,
    scope: DeliveryReadScope,
    revalidate_resource: DeliveryResourceRevalidator,
    repository: DeliveryMilestoneRepository | None = None,
) -> ToolResult:
    """Return typed milestones or an explicit gap when no typed store is bound."""

    query_scope = build_delivery_query_scope(scope)
    for resource_id in query_scope.group_ids:
        await revalidate_resource(resource_id)
    if repository is not None:
        milestones = tuple(await repository.list_milestones(query_scope))
        sources = tuple(source for milestone in milestones for source in milestone.sources)
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            payload={"milestones": [milestone.model_dump(mode="json") for milestone in milestones]},
            sources=sources,
        )
    return ToolResult(
        status=ToolResultStatus.PARTIAL,
        payload={"milestones": []},
        data_gaps=("MILESTONE_SOURCE_NOT_AVAILABLE",),
    )
