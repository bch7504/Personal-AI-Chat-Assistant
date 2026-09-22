"""Read-only, scope-bound task retrieval for Product Delivery.

This adapter is intentionally repository-injected.  A production repository is
blocked on A-DLV-01/09; the adapter can nevertheless be exercised against a
fixture repository without weakening the policy boundary.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from src.agents.contracts import ToolResult, ToolResultStatus
from src.agents.schemas.delivery import DeliveryItem, DeliveryReadScope
from src.services.delivery_workspace_service import DeliveryQueryScope, DeliveryScopeError, build_delivery_query_scope


class DeliveryTaskRepository(Protocol):
    """Repository contract to be implemented only after task scope migration."""

    async def list_tasks(self, scope: DeliveryQueryScope) -> Sequence[DeliveryItem]: ...


DeliveryResourceRevalidator = Callable[[str], Awaitable[None]]


def _validate_item_sources(item: DeliveryItem, scope: DeliveryQueryScope) -> None:
    allowed_source_ids = set(scope.group_ids) | set(scope.task_ids)
    unexpected_sources = {source.resource_id for source in item.sources} - allowed_source_ids
    if unexpected_sources:
        values = ", ".join(sorted(unexpected_sources))
        raise DeliveryScopeError(f"Task '{item.id}' returned a source outside Delivery scope: {values}")


async def get_delivery_tasks(
    *,
    scope: DeliveryReadScope,
    repository: DeliveryTaskRepository,
    revalidate_resource: DeliveryResourceRevalidator,
) -> ToolResult:
    """Return normalized tasks without permitting a broad or stale read.

    The resource callback must re-run the platform resource guard for every
    group predicate immediately before the repository call. It is injected to
    keep this B-owned module independent of database/session ownership.
    """

    query_scope = build_delivery_query_scope(scope)
    if not query_scope.requires_resource_bound_query():
        return ToolResult(status=ToolResultStatus.SUCCESS, payload={"items": []})
    for resource_id in query_scope.group_ids:
        await revalidate_resource(resource_id)

    try:
        items = tuple(await repository.list_tasks(query_scope))
    except DeliveryScopeError:
        raise
    except (OSError, TimeoutError):
        return ToolResult(
            status=ToolResultStatus.ERROR,
            error_code="DELIVERY_TASK_READ_FAILED",
            error_message="Delivery tasks are temporarily unavailable.",
        )

    for item in items:
        _validate_item_sources(item, query_scope)

    sources = tuple(source for item in items for source in item.sources)
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={"items": [item.model_dump(mode="json") for item in items]},
        sources=sources,
    )
