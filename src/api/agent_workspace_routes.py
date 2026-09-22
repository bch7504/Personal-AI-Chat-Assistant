from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.db.models import User
from src.db.session import get_db
from src.models.agent_workspace_schemas import (
    AgentWorkspaceConversationCreate,
    AgentWorkspaceConversationOut,
    AgentWorkspaceCreate,
    AgentWorkspaceLeadUpdate,
    AgentWorkspaceMemberCreate,
    AgentWorkspaceMemberOut,
    AgentWorkspaceOut,
    AgentWorkspaceUpdate,
)
from src.services.agent_workspace_service import (
    add_agent_workspace_member_by_email,
    assign_agent_workspace_lead_by_email,
    create_agent_workspace,
    get_agent_workspace_lead,
    link_agent_workspace_conversation,
    list_agent_workspace_conversations,
    list_agent_workspace_members,
    list_agent_workspaces,
    list_user_agent_workspaces,
    revoke_agent_workspace_member,
    unlink_agent_workspace_conversation,
    update_agent_workspace,
)
from src.services.audit_service import record_audit_event
from src.services.authorization_service import require_platform_admin
from src.services.company_service import get_or_create_company_workspace
from src.services.workspace_service import ensure_workspace_member_by_email

router = APIRouter()


async def _require_agent_workspace_admin(
    db: AsyncSession,
    current_user: User,
    workspace_id: str,
) -> None:
    require_platform_admin(current_user)
    company = await get_or_create_company_workspace(db)
    if workspace_id != company.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company workspace not found")
    await db.commit()


async def _agent_workspace_out(db: AsyncSession, agent_workspace) -> AgentWorkspaceOut:
    lead = await get_agent_workspace_lead(db, agent_workspace.id)
    data = AgentWorkspaceOut.model_validate(agent_workspace)
    if lead is None:
        return data
    _, user = lead
    return data.model_copy(
        update={
            "lead_user_id": user.id,
            "lead_email": user.email,
            "lead_display_name": user.display_name,
        }
    )


@router.post(
    "/{workspace_id}/agent-workspaces",
    response_model=AgentWorkspaceOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_agent(
    workspace_id: str,
    request: AgentWorkspaceCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentWorkspaceOut:
    await _require_agent_workspace_admin(db, current_user, workspace_id)
    agent_workspace = await create_agent_workspace(
        db,
        workspace_id,
        request.key,
        request.name,
        request.agent_profile,
    )
    await ensure_workspace_member_by_email(
        db,
        workspace_id,
        str(request.lead_email),
        current_user.id,
    )
    _, lead_user = await assign_agent_workspace_lead_by_email(
        db,
        workspace_id,
        agent_workspace.id,
        str(request.lead_email),
    )
    await record_audit_event(
        db,
        actor=current_user,
        action="agent_workspace.created",
        target_type="agent_workspace",
        target_id=agent_workspace.id,
        workspace_id=workspace_id,
        metadata={
            "agent_profile": agent_workspace.agent_profile,
            "key": agent_workspace.key,
            "lead_user_id": lead_user.id,
        },
    )
    await db.commit()
    await db.refresh(agent_workspace)
    return await _agent_workspace_out(db, agent_workspace)


@router.get("/{workspace_id}/agent-workspaces", response_model=list[AgentWorkspaceOut])
async def get_workspace_agents(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AgentWorkspaceOut]:
    await _require_agent_workspace_admin(db, current_user, workspace_id)
    workspaces = await list_agent_workspaces(db, workspace_id)
    return [await _agent_workspace_out(db, workspace) for workspace in workspaces]


@router.get(
    "/{workspace_id}/agent-workspaces/available",
    response_model=list[AgentWorkspaceOut],
)
async def get_available_workspace_agents(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AgentWorkspaceOut]:
    rows = await list_user_agent_workspaces(db, workspace_id, current_user.id)
    outputs: list[AgentWorkspaceOut] = []
    for workspace, membership in rows:
        output = await _agent_workspace_out(db, workspace)
        outputs.append(
            output.model_copy(update={"current_user_business_role": membership.business_role})
        )
    return outputs


@router.patch(
    "/{workspace_id}/agent-workspaces/{agent_workspace_id}/lead",
    response_model=AgentWorkspaceMemberOut,
)
async def change_workspace_agent_lead(
    workspace_id: str,
    agent_workspace_id: str,
    request: AgentWorkspaceLeadUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentWorkspaceMemberOut:
    await _require_agent_workspace_admin(db, current_user, workspace_id)
    await ensure_workspace_member_by_email(
        db,
        workspace_id,
        str(request.email),
        current_user.id,
    )
    membership, user = await assign_agent_workspace_lead_by_email(
        db,
        workspace_id,
        agent_workspace_id,
        str(request.email),
    )
    await record_audit_event(
        db,
        actor=current_user,
        action="agent_workspace.lead_assigned",
        target_type="agent_workspace_membership",
        target_id=membership.id,
        workspace_id=workspace_id,
        metadata={"agent_workspace_id": agent_workspace_id, "lead_user_id": user.id},
    )
    await db.commit()
    await db.refresh(membership)
    return AgentWorkspaceMemberOut(
        id=membership.id,
        agent_workspace_id=membership.agent_workspace_id,
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        business_role=membership.business_role,
        status=membership.status,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
    )


@router.patch(
    "/{workspace_id}/agent-workspaces/{agent_workspace_id}",
    response_model=AgentWorkspaceOut,
)
async def change_workspace_agent(
    workspace_id: str,
    agent_workspace_id: str,
    request: AgentWorkspaceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentWorkspaceOut:
    await _require_agent_workspace_admin(db, current_user, workspace_id)
    agent_workspace = await update_agent_workspace(
        db,
        workspace_id,
        agent_workspace_id,
        name=request.name,
        workspace_status=request.status,
    )
    await record_audit_event(
        db,
        actor=current_user,
        action="agent_workspace.updated",
        target_type="agent_workspace",
        target_id=agent_workspace.id,
        workspace_id=workspace_id,
        metadata=request.model_dump(exclude_none=True),
    )
    await db.commit()
    await db.refresh(agent_workspace)
    return await _agent_workspace_out(db, agent_workspace)


@router.post(
    "/{workspace_id}/agent-workspaces/{agent_workspace_id}/members",
    response_model=AgentWorkspaceMemberOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_workspace_agent_member(
    workspace_id: str,
    agent_workspace_id: str,
    request: AgentWorkspaceMemberCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentWorkspaceMemberOut:
    await _require_agent_workspace_admin(db, current_user, workspace_id)
    await ensure_workspace_member_by_email(
        db,
        workspace_id,
        str(request.email),
        current_user.id,
    )
    membership = await add_agent_workspace_member_by_email(
        db,
        workspace_id,
        agent_workspace_id,
        str(request.email),
        request.business_role,
    )
    user = await db.get(User, membership.user_id)
    await record_audit_event(
        db,
        actor=current_user,
        action="agent_workspace.member_upserted",
        target_type="agent_workspace_membership",
        target_id=membership.id,
        workspace_id=workspace_id,
        metadata={"member_user_id": membership.user_id, "business_role": membership.business_role},
    )
    await db.commit()
    await db.refresh(membership)
    return AgentWorkspaceMemberOut(
        id=membership.id,
        agent_workspace_id=membership.agent_workspace_id,
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        business_role=membership.business_role,
        status=membership.status,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
    )


@router.get(
    "/{workspace_id}/agent-workspaces/{agent_workspace_id}/members",
    response_model=list[AgentWorkspaceMemberOut],
)
async def get_workspace_agent_members(
    workspace_id: str,
    agent_workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AgentWorkspaceMemberOut]:
    await _require_agent_workspace_admin(db, current_user, workspace_id)
    rows = await list_agent_workspace_members(db, workspace_id, agent_workspace_id)
    return [
        AgentWorkspaceMemberOut(
            id=membership.id,
            agent_workspace_id=membership.agent_workspace_id,
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            business_role=membership.business_role,
            status=membership.status,
            created_at=membership.created_at,
            updated_at=membership.updated_at,
        )
        for membership, user in rows
    ]


@router.delete(
    "/{workspace_id}/agent-workspaces/{agent_workspace_id}/members/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_workspace_agent_member(
    workspace_id: str,
    agent_workspace_id: str,
    membership_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_agent_workspace_admin(db, current_user, workspace_id)
    membership = await revoke_agent_workspace_member(db, workspace_id, agent_workspace_id, membership_id)
    await record_audit_event(
        db,
        actor=current_user,
        action="agent_workspace.member_revoked",
        target_type="agent_workspace_membership",
        target_id=membership.id,
        workspace_id=workspace_id,
        metadata={"member_user_id": membership.user_id},
    )
    await db.commit()


@router.post(
    "/{workspace_id}/agent-workspaces/{agent_workspace_id}/conversations",
    response_model=AgentWorkspaceConversationOut,
    status_code=status.HTTP_201_CREATED,
)
async def link_workspace_agent_conversation(
    workspace_id: str,
    agent_workspace_id: str,
    request: AgentWorkspaceConversationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentWorkspaceConversationOut:
    await _require_agent_workspace_admin(db, current_user, workspace_id)
    mapping = await link_agent_workspace_conversation(
        db,
        organization_workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        conversation_id=request.conversation_id,
        classification=request.classification,
        linked_by_user_id=current_user.id,
    )
    await record_audit_event(
        db,
        actor=current_user,
        action="agent_workspace.conversation_linked",
        target_type="agent_workspace_conversation",
        target_id=mapping.id,
        workspace_id=workspace_id,
        metadata={
            "agent_workspace_id": agent_workspace_id,
            "conversation_id": mapping.conversation_id,
            "classification": mapping.classification,
        },
    )
    await db.commit()
    await db.refresh(mapping)
    return AgentWorkspaceConversationOut.model_validate(mapping)


@router.get(
    "/{workspace_id}/agent-workspaces/{agent_workspace_id}/conversations",
    response_model=list[AgentWorkspaceConversationOut],
)
async def get_workspace_agent_conversations(
    workspace_id: str,
    agent_workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AgentWorkspaceConversationOut]:
    await _require_agent_workspace_admin(db, current_user, workspace_id)
    mappings = await list_agent_workspace_conversations(db, workspace_id, agent_workspace_id)
    return [AgentWorkspaceConversationOut.model_validate(mapping) for mapping in mappings]


@router.delete(
    "/{workspace_id}/agent-workspaces/{agent_workspace_id}/conversations/{mapping_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unlink_workspace_agent_conversation(
    workspace_id: str,
    agent_workspace_id: str,
    mapping_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_agent_workspace_admin(db, current_user, workspace_id)
    mapping = await unlink_agent_workspace_conversation(db, workspace_id, agent_workspace_id, mapping_id)
    await record_audit_event(
        db,
        actor=current_user,
        action="agent_workspace.conversation_unlinked",
        target_type="agent_workspace_conversation",
        target_id=mapping.id,
        workspace_id=workspace_id,
        metadata={"agent_workspace_id": agent_workspace_id, "conversation_id": mapping.conversation_id},
    )
    await db.commit()
