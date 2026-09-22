"""Deterministic specialist router.

This router only selects a profile from a server-owned workspace record; it
does not treat the requested scope as a grant. Context building and live
resource guards remain mandatory before any model or specialist tool can run.
"""

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.contracts import (
    AgentIntent,
    AgentInvocationRequest,
    AgentProfile,
    PolicyReason,
    RequestedScope,
)
from src.agents.tools.registry import AgentProfileRegistration, get_profile_registration
from src.db.models import AgentWorkspace


class AgentRoute(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile: AgentProfile
    intent: AgentIntent
    requested_scope: RequestedScope
    target_agent_workspace_id: str | None = None
    prompt_version: str
    allowed_tools: tuple[str, ...]


class AgentRouteDeniedError(PermissionError):
    def __init__(self, reason: PolicyReason):
        super().__init__(reason.value)
        self.reason = reason


def _build_route(
    registration: AgentProfileRegistration,
    intent: AgentIntent,
    invocation: AgentInvocationRequest,
) -> AgentRoute:
    if invocation.requested_scope not in registration.allowed_scopes:
        raise AgentRouteDeniedError(PolicyReason.INVALID_SCOPE)
    if intent not in registration.allowed_intents:
        raise AgentRouteDeniedError(PolicyReason.PROFILE_MISMATCH)
    return AgentRoute(
        profile=registration.profile,
        intent=intent,
        requested_scope=invocation.requested_scope,
        target_agent_workspace_id=invocation.target_agent_workspace_id,
        prompt_version=registration.prompt_version,
        allowed_tools=registration.allowed_tools,
    )


async def route_agent_request(
    db: AsyncSession,
    *,
    organization_workspace_id: str,
    invocation: AgentInvocationRequest,
    intent: AgentIntent,
) -> AgentRoute:
    """Select a profile deterministically; authorization runs in the next stage."""

    if invocation.requested_scope == RequestedScope.PERSONAL:
        if invocation.target_agent_workspace_id is not None:
            raise AgentRouteDeniedError(PolicyReason.INVALID_SCOPE)
        return _build_route(get_profile_registration(AgentProfile.PERSONAL), intent, invocation)

    if invocation.requested_scope == RequestedScope.AGGREGATE:
        if invocation.target_agent_workspace_id is not None:
            raise AgentRouteDeniedError(PolicyReason.INVALID_SCOPE)
        return _build_route(get_profile_registration(AgentProfile.EXECUTIVE), intent, invocation)

    if invocation.requested_scope != RequestedScope.WORKSPACE or invocation.target_agent_workspace_id is None:
        raise AgentRouteDeniedError(PolicyReason.INVALID_SCOPE)
    agent_workspace = await db.get(AgentWorkspace, invocation.target_agent_workspace_id)
    if (
        agent_workspace is None
        or agent_workspace.status != "active"
        or agent_workspace.organization_workspace_id != organization_workspace_id
    ):
        raise AgentRouteDeniedError(PolicyReason.WRONG_WORKSPACE)
    try:
        profile = AgentProfile(agent_workspace.agent_profile)
    except ValueError as exc:
        raise AgentRouteDeniedError(PolicyReason.PROFILE_MISMATCH) from exc
    if profile not in {AgentProfile.PRODUCT_DELIVERY, AgentProfile.QUALITY_ASSURANCE}:
        raise AgentRouteDeniedError(PolicyReason.PROFILE_MISMATCH)
    return _build_route(get_profile_registration(profile), intent, invocation)
