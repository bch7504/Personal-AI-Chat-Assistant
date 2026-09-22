"""Safe preparation boundary for a Product Delivery runtime invocation.

This module deliberately prepares a specialist invocation only.  It does not
attach tools to the shared LangGraph, call an LLM, publish a brief, or enable a
feature flag.  The shared runtime must consume this prepared contract before a
Delivery Agent can run in production.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.context_builder import build_agent_context
from src.agents.contracts import (
    AgentContext,
    AgentIntent,
    AgentInvocationRequest,
    AgentProfile,
    FrozenContract,
)
from src.agents.policies.resource_guard import (
    enforce_agent_resource_access,
    enforce_agent_workspace_access,
)
from src.agents.profiles.product_delivery import (
    PRODUCT_DELIVERY_PROMPT_VERSION,
    PRODUCT_DELIVERY_SYSTEM_PROMPT,
    accepts_product_delivery_context,
)
from src.agents.router import AgentRoute, route_agent_request
from src.agents.schemas.delivery import DeliveryReadScope
from src.agents.tools.registry import assert_tool_allowed
from src.db.models import ConversationParticipant
from src.services.delivery_workspace_service import resolve_delivery_read_scope

if TYPE_CHECKING:
    from src.config import Settings


class ProductDeliveryPreparationError(PermissionError):
    """Raised before an invocation can reach any model or specialist tool."""


class PreparedProductDeliveryInvocation(FrozenContract):
    """Trusted runtime input produced solely by server-side routing and policy."""

    context: AgentContext
    prompt_version: str
    system_prompt: str
    allowed_tools: tuple[str, ...]


def _validate_delivery_route(route: AgentRoute) -> None:
    if route.profile != AgentProfile.PRODUCT_DELIVERY:
        raise ProductDeliveryPreparationError("The selected route is not Product Delivery")
    if not accepts_product_delivery_context(
        profile=route.profile,
        scope=route.requested_scope,
        intent=route.intent,
    ):
        raise ProductDeliveryPreparationError("The Product Delivery route has an invalid capability")
    if route.prompt_version != PRODUCT_DELIVERY_PROMPT_VERSION:
        raise ProductDeliveryPreparationError("The Product Delivery prompt version is not approved")
    for tool_name in route.allowed_tools:
        assert_tool_allowed(AgentProfile.PRODUCT_DELIVERY, tool_name)


async def prepare_product_delivery_invocation(
    db: AsyncSession,
    *,
    user_id: str,
    organization_workspace_id: str,
    invocation: AgentInvocationRequest,
    settings: Settings | None = None,
) -> PreparedProductDeliveryInvocation:
    """Route, authorize and constrain a Delivery turn before model/tool binding.

    The intent is deliberately server-owned and fixed to ``delivery_brief``;
    untrusted input carries only message and target workspace fields.  A future
    invocation executor must use the returned allowlist instead of global tools.
    """

    route = await route_agent_request(
        db,
        organization_workspace_id=organization_workspace_id,
        invocation=invocation,
        intent=AgentIntent.DELIVERY_BRIEF,
    )
    _validate_delivery_route(route)

    context = await build_agent_context(
        db,
        user_id=user_id,
        organization_workspace_id=organization_workspace_id,
        invocation=invocation,
        agent_profile=route.profile,
        intent=route.intent,
        prompt_version=route.prompt_version,
        settings=settings,
    )
    if not accepts_product_delivery_context(
        profile=context.runtime.agent_profile,
        scope=context.request.requested_scope,
        intent=context.request.intent,
    ):
        raise ProductDeliveryPreparationError("The resolved Delivery context is invalid")
    if context.runtime.prompt_version != PRODUCT_DELIVERY_PROMPT_VERSION:
        raise ProductDeliveryPreparationError("The resolved Delivery prompt version is not approved")

    return PreparedProductDeliveryInvocation(
        context=context,
        prompt_version=route.prompt_version,
        system_prompt=PRODUCT_DELIVERY_SYSTEM_PROMPT,
        allowed_tools=route.allowed_tools,
    )


async def resolve_prepared_delivery_read_scope(
    db: AsyncSession,
    *,
    prepared: PreparedProductDeliveryInvocation,
    requested_conversation_id: str | None,
) -> DeliveryReadScope:
    """Resolve Lead overview/group, Member My Work, or Member channel scope.

    The selector remains untrusted until the platform resource guard checks it.
    This supplies the concrete server-side composition required by A-DLV-07;
    it does not expose an HTTP capability API or bind any database repository.
    """

    if not accepts_product_delivery_context(
        profile=prepared.context.runtime.agent_profile,
        scope=prepared.context.request.requested_scope,
        intent=prepared.context.request.intent,
    ):
        raise ProductDeliveryPreparationError("The prepared Delivery context is invalid")
    if prepared.prompt_version != PRODUCT_DELIVERY_PROMPT_VERSION:
        raise ProductDeliveryPreparationError("The prepared Delivery prompt version is not approved")

    async def revalidate_workspace(agent_workspace_id: str) -> None:
        await enforce_agent_workspace_access(
            db,
            context=prepared.context,
            agent_workspace_id=agent_workspace_id,
        )

    async def revalidate_resource(resource_id: str) -> None:
        await enforce_agent_resource_access(db, context=prepared.context, resource_id=resource_id)

    allowed_group_ids = prepared.context.authorization.allowed_resource_ids
    allowed_person_ids: tuple[str, ...] = ()
    if allowed_group_ids:
        allowed_person_ids = tuple(
            (
                await db.execute(
                    select(ConversationParticipant.user_id)
                    .where(
                        ConversationParticipant.conversation_id.in_(allowed_group_ids),
                        ConversationParticipant.user_id.is_not(None),
                        ConversationParticipant.revoked_at.is_(None),
                        ConversationParticipant.hidden_at.is_(None),
                    )
                    .distinct()
                    .order_by(ConversationParticipant.user_id.asc())
                )
            )
            .scalars()
            .all()
        )

    return await resolve_delivery_read_scope(
        context=prepared.context,
        requested_conversation_id=requested_conversation_id,
        revalidate_workspace=revalidate_workspace,
        revalidate_resource=revalidate_resource,
        allowed_person_ids=allowed_person_ids,
    )
