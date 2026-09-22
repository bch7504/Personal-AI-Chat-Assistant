from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.config import get_settings
from src.db.models import SupportAccessGrant, User, WorkspaceMembership
from src.db.session import get_db
from src.models.platform_schemas import SupportAccessGrantOut
from src.models.workspace_schemas import (
    OrganizationWorkspaceCreate,
    WorkspaceMemberCreate,
    WorkspaceMemberOut,
    WorkspaceOut,
)
from src.services.audit_service import record_audit_event
from src.services.authorization_service import (
    approve_support_access,
    reject_support_access,
    require_workspace_role,
    revoke_support_access,
)
from src.services.company_service import ensure_open_test_chat_membership
from src.services.workspace_service import (
    add_workspace_member_by_email,
    create_organization_workspace,
    list_user_workspaces,
    list_workspace_members,
)

router = APIRouter()


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    request: OrganizationWorkspaceCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceOut:
    if not get_settings().allow_self_service_organization_creation:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization workspaces are provisioned by platform administrators",
        )
    workspace = await create_organization_workspace(db, request.name, current_user.id)
    await db.commit()
    await db.refresh(workspace)
    output = WorkspaceOut.model_validate(workspace)
    return output.model_copy(update={"current_user_role": "owner"})


@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WorkspaceOut]:
    # Also upgrades already-signed-in accounts when public test chat is enabled;
    # they do not need to log out and back in after the deployment.
    if await ensure_open_test_chat_membership(db, current_user) is not None:
        await db.commit()
    workspaces = await list_user_workspaces(db, current_user.id)
    outputs: list[WorkspaceOut] = []
    for workspace in workspaces:
        if workspace.type == "personal":
            role = "owner"
        else:
            role = (
                await db.execute(
                    select(WorkspaceMembership.role).where(
                        WorkspaceMembership.workspace_id == workspace.id,
                        WorkspaceMembership.user_id == current_user.id,
                        WorkspaceMembership.status == "active",
                    )
                )
            ).scalar_one_or_none()
        outputs.append(WorkspaceOut.model_validate(workspace).model_copy(update={"current_user_role": role}))
    return outputs


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberOut])
async def get_workspace_members(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WorkspaceMemberOut]:
    await require_workspace_role(db, current_user, workspace_id, {"owner", "admin", "member"})
    members = await list_workspace_members(db, workspace_id)
    return [
        WorkspaceMemberOut(
            id=membership.id,
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=membership.role,
            status=membership.status,
            joined_at=membership.joined_at,
        )
        for membership, user in members
    ]


@router.post(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    workspace_id: str,
    request: WorkspaceMemberCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceMemberOut:
    allowed_roles = {"owner"} if request.role == "admin" else {"owner", "admin"}
    await require_workspace_role(db, current_user, workspace_id, allowed_roles)
    membership = await add_workspace_member_by_email(
        db,
        workspace_id,
        str(request.email),
        request.role,
        current_user.id,
    )
    user = await db.get(User, membership.user_id)
    await record_audit_event(
        db,
        actor=current_user,
        action="workspace.member_added",
        target_type="workspace_membership",
        target_id=membership.id,
        workspace_id=workspace_id,
        metadata={"member_user_id": membership.user_id, "role": membership.role},
    )
    await db.commit()
    await db.refresh(membership)
    return WorkspaceMemberOut(
        id=membership.id,
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=membership.role,
        status=membership.status,
        joined_at=membership.joined_at,
    )


@router.post(
    "/{workspace_id}/support-grants/{grant_id}/approve",
    response_model=SupportAccessGrantOut,
)
async def approve_support_grant(
    workspace_id: str,
    grant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SupportAccessGrantOut:
    grant = await approve_support_access(db, current_user, workspace_id, grant_id)
    await db.commit()
    await db.refresh(grant)
    return SupportAccessGrantOut.model_validate(grant)


@router.post(
    "/{workspace_id}/support-grants/{grant_id}/reject",
    response_model=SupportAccessGrantOut,
)
async def reject_support_grant(
    workspace_id: str,
    grant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SupportAccessGrantOut:
    grant = await reject_support_access(db, current_user, workspace_id, grant_id)
    await db.commit()
    await db.refresh(grant)
    return SupportAccessGrantOut.model_validate(grant)


@router.post(
    "/{workspace_id}/support-grants/{grant_id}/revoke",
    response_model=SupportAccessGrantOut,
)
async def revoke_support_grant(
    workspace_id: str,
    grant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SupportAccessGrantOut:
    grant = await revoke_support_access(db, current_user, workspace_id, grant_id)
    await db.commit()
    await db.refresh(grant)
    return SupportAccessGrantOut.model_validate(grant)


@router.get("/{workspace_id}/support-grants", response_model=list[SupportAccessGrantOut])
async def list_workspace_support_grants(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SupportAccessGrantOut]:
    await require_workspace_role(db, current_user, workspace_id, {"owner"})
    grants = (
        await db.execute(
            select(SupportAccessGrant)
            .where(SupportAccessGrant.workspace_id == workspace_id)
            .order_by(SupportAccessGrant.created_at.desc())
        )
    ).scalars().all()
    return [SupportAccessGrantOut.model_validate(grant) for grant in grants]
