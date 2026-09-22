"""Server-owned preparation and scope resolution for Quality Assurance."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.context_builder import build_agent_context
from src.agents.contracts import (
    AgentContext,
    AgentIntent,
    AgentInvocationRequest,
    AgentProfile,
    BusinessRole,
    FrozenContract,
)
from src.agents.policies.resource_guard import enforce_agent_resource_access, enforce_agent_workspace_access
from src.agents.profiles.quality_assurance import (
    QUALITY_ASSURANCE_PROMPT_VERSION,
    QUALITY_ASSURANCE_SYSTEM_PROMPT,
    accepts_quality_context,
)
from src.agents.router import route_agent_request
from src.agents.schemas.quality import QualityReadScope, QualityViewScope
from src.agents.tools.registry import assert_tool_allowed


class QualityPreparationError(PermissionError):
    pass


class PreparedQualityInvocation(FrozenContract):
    context: AgentContext
    prompt_version: str
    system_prompt: str
    allowed_tools: tuple[str, ...]


async def prepare_quality_invocation(
    db: AsyncSession,
    *,
    user_id: str,
    organization_workspace_id: str,
    invocation: AgentInvocationRequest,
    settings=None,
) -> PreparedQualityInvocation:
    route = await route_agent_request(
        db,
        organization_workspace_id=organization_workspace_id,
        invocation=invocation,
        intent=AgentIntent.QUALITY_BRIEF,
    )
    if not accepts_quality_context(profile=route.profile, scope=route.requested_scope, intent=route.intent):
        raise QualityPreparationError("The selected route is not Quality Assurance")
    if route.prompt_version != QUALITY_ASSURANCE_PROMPT_VERSION:
        raise QualityPreparationError("The Quality prompt version is not approved")
    for name in route.allowed_tools:
        assert_tool_allowed(AgentProfile.QUALITY_ASSURANCE, name)
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
    return PreparedQualityInvocation(
        context=context,
        prompt_version=route.prompt_version,
        system_prompt=QUALITY_ASSURANCE_SYSTEM_PROMPT,
        allowed_tools=route.allowed_tools,
    )


async def resolve_quality_read_scope(
    db: AsyncSession,
    *,
    prepared: PreparedQualityInvocation,
    release_id: str,
    selected_conversation_id: str | None,
) -> QualityReadScope:
    context = prepared.context
    target = context.request.target_agent_workspace_id
    if target is None:
        raise QualityPreparationError("Quality target workspace is missing")
    await enforce_agent_workspace_access(db, context=context, agent_workspace_id=target)
    if context.actor.business_role == BusinessRole.LEAD:
        if selected_conversation_id is None:
            return QualityReadScope(
                context=context,
                release_id=release_id,
                view_scope=QualityViewScope.WORKSPACE,
                effective_group_ids=context.authorization.allowed_resource_ids,
            )
        await enforce_agent_resource_access(db, context=context, resource_id=selected_conversation_id)
        return QualityReadScope(
            context=context,
            release_id=release_id,
            view_scope=QualityViewScope.GROUP,
            effective_group_ids=(selected_conversation_id,),
            selected_conversation_id=selected_conversation_id,
        )
    if context.actor.business_role == BusinessRole.MEMBER:
        if selected_conversation_id is not None:
            raise QualityPreparationError("Members cannot select a Quality group")
        return QualityReadScope(
            context=context,
            release_id=release_id,
            view_scope=QualityViewScope.MEMBER,
            effective_group_ids=context.authorization.allowed_resource_ids,
        )
    raise QualityPreparationError("Unsupported Quality business role")

