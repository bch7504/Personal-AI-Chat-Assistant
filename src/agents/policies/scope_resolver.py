import hashlib

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.contracts import (
    AgentProfile,
    BusinessRole,
    PolicyDecision,
    PolicyReason,
    RequestedScope,
)
from src.db.models import (
    AgentWorkspace,
    AgentWorkspaceConversation,
    AgentWorkspaceMembership,
    Conversation,
    ConversationParticipant,
    User,
    Workspace,
    WorkspaceMembership,
)


class ResolvedAgentScope(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: PolicyDecision
    reason: PolicyReason
    business_role: BusinessRole | None = None
    allowed_agent_workspace_ids: tuple[str, ...] = ()
    allowed_resource_ids: tuple[str, ...] = ()
    consent_scope_hash: str | None = None


def _denied(reason: PolicyReason) -> ResolvedAgentScope:
    return ResolvedAgentScope(decision=PolicyDecision.DENY, reason=reason)


async def _has_organization_access(db: AsyncSession, user_id: str, workspace_id: str) -> bool:
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None or workspace.type != "organization" or workspace.status != "active":
        return False
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        return False
    return (
        await db.execute(
            select(WorkspaceMembership.id).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user_id,
                WorkspaceMembership.status == "active",
                WorkspaceMembership.role.in_(("owner", "admin", "member")),
            )
        )
    ).scalar_one_or_none() is not None


async def _resolve_conversation_resources(
    db: AsyncSession,
    organization_workspace_id: str,
    agent_workspace_id: str,
    expected_classification: str,
    participant_user_id: str | None = None,
) -> tuple[tuple[str, ...], str | None]:
    """Resolve live, AI-enabled group sources for one Delivery/Quality workspace.

    A lead receives the workspace's resolved group allowlist. A member receives
    only its intersection with active conversation participation. This makes
    membership in an Agent Workspace insufficient on its own to read another
    group's data, and keeps the router's capability envelope aligned with the
    Role B Delivery policy.
    """

    statement = (
        select(Conversation.id, Conversation.ai_policy_version)
        .join(
            AgentWorkspaceConversation,
            AgentWorkspaceConversation.conversation_id == Conversation.id,
        )
        .where(
            AgentWorkspaceConversation.agent_workspace_id == agent_workspace_id,
            AgentWorkspaceConversation.classification == expected_classification,
            Conversation.workspace_id == organization_workspace_id,
            Conversation.type == "group",
            Conversation.ai_enabled.is_(True),
        )
        .order_by(Conversation.id.asc())
    )
    if participant_user_id is not None:
        statement = statement.join(
            ConversationParticipant,
            ConversationParticipant.conversation_id == Conversation.id,
        ).where(
            ConversationParticipant.user_id == participant_user_id,
            ConversationParticipant.revoked_at.is_(None),
            ConversationParticipant.hidden_at.is_(None),
        )
    rows = (
        await db.execute(statement)
    ).all()
    if not rows:
        return (), None
    resource_ids = tuple(row.id for row in rows)
    scope_material = "|".join(f"{row.id}:{row.ai_policy_version}" for row in rows)
    consent_scope_hash = hashlib.sha256(scope_material.encode("utf-8")).hexdigest()
    return resource_ids, consent_scope_hash


async def resolve_agent_scope(
    db: AsyncSession,
    *,
    user_id: str,
    organization_workspace_id: str,
    agent_profile: AgentProfile,
    requested_scope: RequestedScope,
    target_agent_workspace_id: str | None = None,
) -> ResolvedAgentScope:
    if not await _has_organization_access(db, user_id, organization_workspace_id):
        return _denied(PolicyReason.NOT_MEMBER)

    if agent_profile == AgentProfile.EXECUTIVE:
        if requested_scope != RequestedScope.AGGREGATE or target_agent_workspace_id is not None:
            return _denied(PolicyReason.INVALID_SCOPE)
        executive_membership = (
            await db.execute(
                select(AgentWorkspaceMembership.id)
                .join(
                    AgentWorkspace,
                    AgentWorkspace.id == AgentWorkspaceMembership.agent_workspace_id,
                )
                .where(
                    AgentWorkspace.organization_workspace_id == organization_workspace_id,
                    AgentWorkspace.agent_profile == AgentProfile.EXECUTIVE.value,
                    AgentWorkspace.status == "active",
                    AgentWorkspaceMembership.user_id == user_id,
                    AgentWorkspaceMembership.business_role.in_(("lead", "member", "executive_viewer")),
                    AgentWorkspaceMembership.status == "active",
                )
            )
        ).scalar_one_or_none()
        if executive_membership is None:
            return _denied(PolicyReason.NOT_MEMBER)
        allowed_ids = tuple(
            (
                await db.execute(
                    select(AgentWorkspace.id)
                    .where(
                        AgentWorkspace.organization_workspace_id == organization_workspace_id,
                        AgentWorkspace.status == "active",
                        AgentWorkspace.agent_profile.in_(
                            (
                                AgentProfile.PRODUCT_DELIVERY.value,
                                AgentProfile.QUALITY_ASSURANCE.value,
                            )
                        ),
                    )
                    .order_by(AgentWorkspace.key.asc())
                )
            )
            .scalars()
            .all()
        )
        return ResolvedAgentScope(
            decision=PolicyDecision.ALLOW,
            reason=PolicyReason.ALLOWED,
            business_role=BusinessRole.EXECUTIVE,
            allowed_agent_workspace_ids=allowed_ids,
        )

    if agent_profile not in {AgentProfile.PRODUCT_DELIVERY, AgentProfile.QUALITY_ASSURANCE}:
        return _denied(PolicyReason.PROFILE_MISMATCH)
    if requested_scope != RequestedScope.WORKSPACE or target_agent_workspace_id is None:
        return _denied(PolicyReason.INVALID_SCOPE)

    agent_workspace = await db.get(AgentWorkspace, target_agent_workspace_id)
    if (
        agent_workspace is None
        or agent_workspace.status != "active"
        or agent_workspace.organization_workspace_id != organization_workspace_id
    ):
        return _denied(PolicyReason.WRONG_WORKSPACE)
    if agent_workspace.agent_profile != agent_profile.value:
        return _denied(PolicyReason.PROFILE_MISMATCH)

    membership = (
        await db.execute(
            select(AgentWorkspaceMembership).where(
                AgentWorkspaceMembership.agent_workspace_id == target_agent_workspace_id,
                AgentWorkspaceMembership.user_id == user_id,
                AgentWorkspaceMembership.status == "active",
                AgentWorkspaceMembership.business_role.in_(("member", "lead")),
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        return _denied(PolicyReason.NOT_MEMBER)
    role = BusinessRole.LEAD if membership.business_role == "lead" else BusinessRole.MEMBER
    expected_classification = (
        "delivery" if agent_profile == AgentProfile.PRODUCT_DELIVERY else "quality"
    )
    allowed_resource_ids, consent_scope_hash = await _resolve_conversation_resources(
        db,
        organization_workspace_id,
        agent_workspace.id,
        expected_classification,
        participant_user_id=user_id if role == BusinessRole.MEMBER else None,
    )
    return ResolvedAgentScope(
        decision=PolicyDecision.ALLOW,
        reason=PolicyReason.ALLOWED,
        business_role=role,
        allowed_agent_workspace_ids=(agent_workspace.id,),
        allowed_resource_ids=allowed_resource_ids,
        consent_scope_hash=consent_scope_hash,
    )
