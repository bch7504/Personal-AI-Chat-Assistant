"""Minimal, allowlisted assignee/audience resolver for Delivery."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from src.agents.contracts import ToolResult, ToolResultStatus
from src.agents.schemas.delivery import DeliveryPerson, DeliveryReadScope
from src.services.delivery_workspace_service import DeliveryQueryScope, DeliveryScopeError, build_delivery_query_scope


class DeliveryPeopleRepository(Protocol):
    async def resolve_people(
        self, scope: DeliveryQueryScope, *, user_ids: tuple[str, ...]
    ) -> Sequence[DeliveryPerson]: ...


DeliveryResourceRevalidator = Callable[[str], Awaitable[None]]


async def get_delivery_people(
    *,
    scope: DeliveryReadScope,
    repository: DeliveryPeopleRepository,
    revalidate_resource: DeliveryResourceRevalidator,
    user_ids: tuple[str, ...],
) -> ToolResult:
    """Resolve only server-allowlisted people and never return extra profile fields."""

    if len(set(user_ids)) != len(user_ids):
        raise ValueError("Delivery people IDs must be unique")
    if not set(user_ids).issubset(scope.allowed_person_ids):
        raise DeliveryScopeError("Requested people are outside the Delivery allowlist")
    query_scope = build_delivery_query_scope(scope)
    if not user_ids:
        return ToolResult(status=ToolResultStatus.SUCCESS, payload={"people": []})
    for resource_id in query_scope.group_ids:
        await revalidate_resource(resource_id)
    try:
        people = tuple(await repository.resolve_people(query_scope, user_ids=user_ids))
    except (OSError, TimeoutError):
        return ToolResult(
            status=ToolResultStatus.ERROR,
            error_code="DELIVERY_PEOPLE_READ_FAILED",
            error_message="Delivery people data is temporarily unavailable.",
        )
    returned_ids = {person.user_id for person in people}
    if not returned_ids.issubset(user_ids):
        raise DeliveryScopeError("People repository returned a person outside the requested allowlist")
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={"people": [person.model_dump(mode="json") for person in people]},
    )
