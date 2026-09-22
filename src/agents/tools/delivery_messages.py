"""Bounded, scope-bound search over Delivery group-chat evidence."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta
from typing import Protocol

from src.agents.contracts import ToolResult, ToolResultStatus
from src.agents.schemas.delivery import DeliveryMessageEvidence, DeliveryReadScope
from src.services import guardrail_service
from src.services.delivery_workspace_service import DeliveryQueryScope, DeliveryScopeError, build_delivery_query_scope


class DeliveryMessageRepository(Protocol):
    """Repository contract for a future consent-aware Delivery message search."""

    async def search_messages(
        self,
        scope: DeliveryQueryScope,
        *,
        query: str,
        from_at: datetime,
        to_at: datetime,
        limit: int,
    ) -> Sequence[DeliveryMessageEvidence]: ...


DeliveryResourceRevalidator = Callable[[str], Awaitable[None]]


def _validate_search_arguments(*, query: str, from_at: datetime, to_at: datetime, limit: int) -> None:
    if not query.strip():
        raise ValueError("Delivery message search query is required")
    if from_at.tzinfo is None or to_at.tzinfo is None:
        raise ValueError("Delivery message search timestamps must include a timezone")
    if to_at < from_at:
        raise ValueError("Delivery message search end must not be before start")
    if to_at - from_at > timedelta(days=90):
        raise ValueError("Delivery message search range cannot exceed 90 days")
    if not 1 <= limit <= 20:
        raise ValueError("Delivery message search limit must be between 1 and 20")


def _sanitize_evidence(
    evidence: DeliveryMessageEvidence,
    scope: DeliveryQueryScope,
) -> DeliveryMessageEvidence:
    if evidence.conversation_id not in scope.group_ids:
        raise DeliveryScopeError("Message evidence returned a conversation outside Delivery scope")
    return evidence.model_copy(
        update={"excerpt": guardrail_service.sanitize_untrusted_text(evidence.excerpt)}
    )


async def search_delivery_messages(
    *,
    scope: DeliveryReadScope,
    repository: DeliveryMessageRepository,
    revalidate_resource: DeliveryResourceRevalidator,
    query: str,
    from_at: datetime,
    to_at: datetime,
    limit: int = 20,
) -> ToolResult:
    """Search only effective Delivery groups and return bounded untrusted evidence."""

    _validate_search_arguments(query=query, from_at=from_at, to_at=to_at, limit=limit)
    query_scope = build_delivery_query_scope(scope)
    if not query_scope.requires_resource_bound_query():
        return ToolResult(
            status=ToolResultStatus.PARTIAL,
            payload={"evidence": []},
            data_gaps=("NO_CONSENTED_DELIVERY_SOURCE",),
        )
    for resource_id in query_scope.group_ids:
        await revalidate_resource(resource_id)

    try:
        rows = tuple(
            await repository.search_messages(
                query_scope,
                query=query,
                from_at=from_at,
                to_at=to_at,
                limit=limit,
            )
        )
    except DeliveryScopeError:
        raise
    except (OSError, TimeoutError):
        return ToolResult(
            status=ToolResultStatus.ERROR,
            error_code="DELIVERY_MESSAGE_SEARCH_FAILED",
            error_message="Delivery message search is temporarily unavailable.",
        )

    evidence = tuple(_sanitize_evidence(row, query_scope) for row in rows)
    sources = tuple(source for row in evidence for source in row.sources)
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={"evidence": [row.model_dump(mode="json") for row in evidence]},
        sources=sources,
    )
