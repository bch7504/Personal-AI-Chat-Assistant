from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.contracts import AgentProfile
from src.db.models import (
    AgentWorkspace,
    AgentWorkspaceConversation,
    AgentWorkspaceMembership,
    Conversation,
    User,
    Workspace,
    WorkspaceMembership,
)

WORKSPACE_AGENT_PROFILES = {
    AgentProfile.PRODUCT_DELIVERY,
    AgentProfile.QUALITY_ASSURANCE,
    AgentProfile.EXECUTIVE,
}
AGENT_WORKSPACE_ROLES = {"member", "lead", "executive_viewer"}
PROFILE_CLASSIFICATION = {
    AgentProfile.PRODUCT_DELIVERY: "delivery",
    AgentProfile.QUALITY_ASSURANCE: "quality",
}


async def require_agent_workspace(
    db: AsyncSession,
    organization_workspace_id: str,
    agent_workspace_id: str,
) -> AgentWorkspace:
    workspace = await db.get(AgentWorkspace, agent_workspace_id)
    if (
        workspace is None
        or workspace.organization_workspace_id != organization_workspace_id
        or workspace.status == "archived"
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent workspace not found")
    return workspace


async def list_agent_workspaces(
    db: AsyncSession,
    organization_workspace_id: str,
) -> list[AgentWorkspace]:
    return list(
        (
            await db.execute(
                select(AgentWorkspace)
                .where(
                    AgentWorkspace.organization_workspace_id == organization_workspace_id,
                    AgentWorkspace.status != "archived",
                )
                .order_by(AgentWorkspace.key.asc())
            )
        )
        .scalars()
        .all()
    )


async def list_user_agent_workspaces(
    db: AsyncSession,
    organization_workspace_id: str,
    user_id: str,
) -> list[tuple[AgentWorkspace, AgentWorkspaceMembership]]:
    organization_membership = (
        await db.execute(
            select(WorkspaceMembership.id).where(
                WorkspaceMembership.workspace_id == organization_workspace_id,
                WorkspaceMembership.user_id == user_id,
                WorkspaceMembership.status == "active",
                WorkspaceMembership.role.in_(("owner", "admin", "member")),
            )
        )
    ).scalar_one_or_none()
    if organization_membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace access denied")
    return list(
        (
            await db.execute(
                select(AgentWorkspace, AgentWorkspaceMembership)
                .join(
                    AgentWorkspaceMembership,
                    AgentWorkspaceMembership.agent_workspace_id == AgentWorkspace.id,
                )
                .where(
                    AgentWorkspace.organization_workspace_id == organization_workspace_id,
                    AgentWorkspace.status == "active",
                    AgentWorkspaceMembership.user_id == user_id,
                    AgentWorkspaceMembership.status == "active",
                )
                .order_by(AgentWorkspace.key.asc())
            )
        ).all()
    )


async def get_agent_workspace_lead(
    db: AsyncSession,
    agent_workspace_id: str,
) -> tuple[AgentWorkspaceMembership, User] | None:
    return (
        await db.execute(
            select(AgentWorkspaceMembership, User)
            .join(User, User.id == AgentWorkspaceMembership.user_id)
            .where(
                AgentWorkspaceMembership.agent_workspace_id == agent_workspace_id,
                AgentWorkspaceMembership.business_role == "lead",
                AgentWorkspaceMembership.status == "active",
            )
        )
    ).one_or_none()


async def create_agent_workspace(
    db: AsyncSession,
    organization_workspace_id: str,
    key: str,
    name: str,
    agent_profile: AgentProfile,
) -> AgentWorkspace:
    organization = await db.get(Workspace, organization_workspace_id)
    if organization is None or organization.status != "active":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization workspace not found")
    if organization.type != "organization":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent workspaces require an organization workspace",
        )
    if agent_profile not in WORKSPACE_AGENT_PROFILES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Workspace requires a supported agent profile",
        )
    normalized_key = key.strip().lower().replace(" ", "-")
    normalized_name = name.strip()
    if not normalized_key or not normalized_name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Key and name are required")

    workspace = AgentWorkspace(
        organization_workspace_id=organization_workspace_id,
        key=normalized_key,
        name=normalized_name,
        agent_profile=agent_profile.value,
    )
    db.add(workspace)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent workspace key already exists") from exc
    return workspace


async def add_agent_workspace_member(
    db: AsyncSession,
    agent_workspace_id: str,
    user_id: str,
    business_role: str,
) -> AgentWorkspaceMembership:
    if business_role not in AGENT_WORKSPACE_ROLES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid business role")
    agent_workspace = await db.get(AgentWorkspace, agent_workspace_id)
    if agent_workspace is None or agent_workspace.status != "active":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent workspace not found")
    # Serialize assignments for one principal. This closes the race between two
    # administrators assigning the same account to different Agent Workspaces.
    user = (
        await db.execute(select(User).where(User.id == user_id).with_for_update())
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active user not found")
    organization_membership = (
        await db.execute(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == agent_workspace.organization_workspace_id,
                WorkspaceMembership.user_id == user_id,
                WorkspaceMembership.status == "active",
                WorkspaceMembership.role.in_(("owner", "admin", "member")),
            )
        )
    ).scalar_one_or_none()
    if organization_membership is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User must be an active organization workspace member",
        )

    active_elsewhere = (
        await db.execute(
            select(AgentWorkspaceMembership.id)
            .join(
                AgentWorkspace,
                AgentWorkspace.id == AgentWorkspaceMembership.agent_workspace_id,
            )
            .where(
                AgentWorkspaceMembership.user_id == user_id,
                AgentWorkspaceMembership.status == "active",
                AgentWorkspaceMembership.agent_workspace_id != agent_workspace_id,
                AgentWorkspace.organization_workspace_id
                == agent_workspace.organization_workspace_id,
                AgentWorkspace.status == "active",
            )
        )
    ).scalar_one_or_none()
    if active_elsewhere is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already assigned to another active Agent Workspace",
        )

    if business_role == "lead":
        await db.execute(
            update(AgentWorkspaceMembership)
            .where(
                AgentWorkspaceMembership.agent_workspace_id == agent_workspace_id,
                AgentWorkspaceMembership.business_role == "lead",
                AgentWorkspaceMembership.status == "active",
                AgentWorkspaceMembership.user_id != user_id,
            )
            .values(business_role="member", updated_at=datetime.now(UTC))
        )
        await db.flush()

    existing = (
        await db.execute(
            select(AgentWorkspaceMembership).where(
                AgentWorkspaceMembership.agent_workspace_id == agent_workspace_id,
                AgentWorkspaceMembership.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.business_role == "lead"
            and existing.status == "active"
            and business_role != "lead"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Assign a replacement lead before changing the current lead's role",
            )
        existing.business_role = business_role
        existing.status = "active"
        existing.updated_at = datetime.now(UTC)
        await db.flush()
        return existing

    membership = AgentWorkspaceMembership(
        agent_workspace_id=agent_workspace_id,
        user_id=user_id,
        business_role=business_role,
    )
    db.add(membership)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent workspace membership exists") from exc
    return membership


async def assign_agent_workspace_lead_by_email(
    db: AsyncSession,
    organization_workspace_id: str,
    agent_workspace_id: str,
    email: str,
) -> tuple[AgentWorkspaceMembership, User]:
    await require_agent_workspace(db, organization_workspace_id, agent_workspace_id)
    user = (
        await db.execute(select(User).where(User.email == email.strip().lower(), User.is_active.is_(True)))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active user not found")

    membership = await add_agent_workspace_member(db, agent_workspace_id, user.id, "lead")
    return membership, user


async def update_agent_workspace(
    db: AsyncSession,
    organization_workspace_id: str,
    agent_workspace_id: str,
    *,
    name: str | None,
    workspace_status: str | None,
) -> AgentWorkspace:
    workspace = await require_agent_workspace(db, organization_workspace_id, agent_workspace_id)
    if name is not None:
        workspace.name = name
    if workspace_status is not None:
        workspace.status = workspace_status
    workspace.updated_at = datetime.now(UTC)
    await db.flush()
    return workspace


async def add_agent_workspace_member_by_email(
    db: AsyncSession,
    organization_workspace_id: str,
    agent_workspace_id: str,
    email: str,
    business_role: str,
) -> AgentWorkspaceMembership:
    await require_agent_workspace(db, organization_workspace_id, agent_workspace_id)
    user = (
        await db.execute(select(User).where(User.email == email.strip().lower(), User.is_active.is_(True)))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active user not found")
    return await add_agent_workspace_member(db, agent_workspace_id, user.id, business_role)


async def list_agent_workspace_members(
    db: AsyncSession,
    organization_workspace_id: str,
    agent_workspace_id: str,
) -> list[tuple[AgentWorkspaceMembership, User]]:
    await require_agent_workspace(db, organization_workspace_id, agent_workspace_id)
    rows = await db.execute(
        select(AgentWorkspaceMembership, User)
        .join(User, User.id == AgentWorkspaceMembership.user_id)
        .where(
            AgentWorkspaceMembership.agent_workspace_id == agent_workspace_id,
            AgentWorkspaceMembership.status != "revoked",
        )
        .order_by(AgentWorkspaceMembership.business_role.asc(), User.display_name.asc())
    )
    return list(rows.all())


async def revoke_agent_workspace_member(
    db: AsyncSession,
    organization_workspace_id: str,
    agent_workspace_id: str,
    membership_id: str,
) -> AgentWorkspaceMembership:
    await require_agent_workspace(db, organization_workspace_id, agent_workspace_id)
    membership = await db.get(AgentWorkspaceMembership, membership_id)
    if membership is None or membership.agent_workspace_id != agent_workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent workspace membership not found")
    if membership.business_role == "lead" and membership.status == "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Assign a replacement lead before revoking the current lead",
        )
    membership.status = "revoked"
    membership.updated_at = datetime.now(UTC)
    await db.flush()
    return membership


async def link_agent_workspace_conversation(
    db: AsyncSession,
    *,
    organization_workspace_id: str,
    agent_workspace_id: str,
    conversation_id: str,
    classification: str,
    linked_by_user_id: str,
    channel_kind: str = "project",
) -> AgentWorkspaceConversation:
    if channel_kind not in {"announcement", "team", "project", "release"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid workspace channel kind",
        )
    agent_workspace = await require_agent_workspace(db, organization_workspace_id, agent_workspace_id)
    expected_classification = PROFILE_CLASSIFICATION.get(AgentProfile(agent_workspace.agent_profile))
    if expected_classification is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Executive workspaces consume validated briefs, not raw conversations",
        )
    if classification != expected_classification:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Conversation classification must match the agent workspace profile",
        )
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.workspace_id != organization_workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if conversation.type != "group":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only group conversations can be linked to an agent workspace",
        )

    existing = (
        await db.execute(
            select(AgentWorkspaceConversation).where(
                AgentWorkspaceConversation.conversation_id == conversation_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.agent_workspace_id == agent_workspace_id:
            return existing
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conversation is already linked to another agent workspace",
        )

    mapping = AgentWorkspaceConversation(
        agent_workspace_id=agent_workspace_id,
        conversation_id=conversation_id,
        classification=classification,
        channel_kind=channel_kind,
        linked_by_user_id=linked_by_user_id,
    )
    db.add(mapping)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conversation is already linked to an agent workspace",
        ) from exc
    return mapping


async def list_agent_workspace_conversations(
    db: AsyncSession,
    organization_workspace_id: str,
    agent_workspace_id: str,
) -> list[AgentWorkspaceConversation]:
    await require_agent_workspace(db, organization_workspace_id, agent_workspace_id)
    return list(
        (
            await db.execute(
                select(AgentWorkspaceConversation)
                .where(AgentWorkspaceConversation.agent_workspace_id == agent_workspace_id)
                .order_by(AgentWorkspaceConversation.created_at.asc())
            )
        )
        .scalars()
        .all()
    )


async def unlink_agent_workspace_conversation(
    db: AsyncSession,
    organization_workspace_id: str,
    agent_workspace_id: str,
    mapping_id: str,
) -> AgentWorkspaceConversation:
    await require_agent_workspace(db, organization_workspace_id, agent_workspace_id)
    mapping = await db.get(AgentWorkspaceConversation, mapping_id)
    if mapping is None or mapping.agent_workspace_id != agent_workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation mapping not found")
    await db.delete(mapping)
    await db.flush()
    return mapping
