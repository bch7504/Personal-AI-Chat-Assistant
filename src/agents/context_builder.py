from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.contracts import (
    ActorContext,
    AgentContext,
    AgentIntent,
    AgentInvocationRequest,
    AgentProfile,
    AgentRequestContext,
    AgentRuntimeContext,
    AuthorizationContext,
    PolicyDecision,
    PolicyReason,
)
from src.agents.policies.scope_resolver import ResolvedAgentScope, resolve_agent_scope
from src.config import Settings, get_settings


class AgentScopeDeniedError(PermissionError):
    def __init__(self, resolution: ResolvedAgentScope):
        super().__init__(resolution.reason.value)
        self.resolution = resolution


def is_agent_profile_enabled(settings: Settings, profile: AgentProfile) -> bool:
    if profile == AgentProfile.PERSONAL:
        return True
    if not settings.multi_agent_enabled:
        return False
    return {
        AgentProfile.PRODUCT_DELIVERY: settings.product_delivery_agent_enabled,
        AgentProfile.QUALITY_ASSURANCE: settings.quality_assurance_agent_enabled,
        AgentProfile.EXECUTIVE: settings.executive_agent_enabled,
    }[profile]


async def build_agent_context(
    db: AsyncSession,
    *,
    user_id: str,
    organization_workspace_id: str,
    invocation: AgentInvocationRequest,
    agent_profile: AgentProfile,
    intent: AgentIntent,
    prompt_version: str,
    settings: Settings | None = None,
) -> AgentContext:
    runtime_settings = settings or get_settings()
    if not is_agent_profile_enabled(runtime_settings, agent_profile):
        raise AgentScopeDeniedError(
            ResolvedAgentScope(
                decision=PolicyDecision.DENY,
                reason=PolicyReason.FEATURE_DISABLED,
            )
        )
    resolution = await resolve_agent_scope(
        db,
        user_id=user_id,
        organization_workspace_id=organization_workspace_id,
        agent_profile=agent_profile,
        requested_scope=invocation.requested_scope,
        target_agent_workspace_id=invocation.target_agent_workspace_id,
    )
    if resolution.decision == PolicyDecision.DENY or resolution.business_role is None:
        raise AgentScopeDeniedError(resolution)

    return AgentContext(
        trace_id=uuid4().hex,
        actor=ActorContext(
            user_id=user_id,
            organization_workspace_id=organization_workspace_id,
            business_role=resolution.business_role,
            agent_workspace_ids=resolution.allowed_agent_workspace_ids,
        ),
        request=AgentRequestContext(
            text=invocation.message,
            intent=intent,
            requested_scope=invocation.requested_scope,
            target_agent_workspace_id=invocation.target_agent_workspace_id,
        ),
        authorization=AuthorizationContext(
            decision=resolution.decision,
            reason=resolution.reason,
            allowed_agent_workspace_ids=resolution.allowed_agent_workspace_ids,
            allowed_resource_ids=resolution.allowed_resource_ids,
            consent_scope_hash=resolution.consent_scope_hash,
        ),
        runtime=AgentRuntimeContext(
            agent_profile=agent_profile,
            prompt_version=prompt_version,
        ),
    )
