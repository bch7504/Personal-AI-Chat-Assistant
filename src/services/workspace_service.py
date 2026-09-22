from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import User, Workspace, WorkspaceMembership


async def get_personal_workspace(db: AsyncSession, user_id: str) -> Workspace | None:
    return (
        await db.execute(
            select(Workspace).where(
                Workspace.type == "personal",
                Workspace.personal_owner_user_id == user_id,
                Workspace.status == "active",
            )
        )
    ).scalar_one_or_none()


async def ensure_personal_workspace(db: AsyncSession, user: User) -> Workspace:
    """Return the user's internal Personal Space, creating or repairing it if needed.

    Personal features are addressed by the authenticated user, never by a
    client-supplied workspace id. The workspace row is an internal isolation
    namespace and must therefore exist for every account. Locking the user row
    serializes concurrent first-login repairs where row locks are supported.
    """
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    existing = (
        await db.execute(
            select(Workspace).where(
                Workspace.type == "personal",
                Workspace.personal_owner_user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status != "active":
            existing.status = "active"
            existing.updated_at = datetime.now(UTC)
            await db.flush()
        return existing

    workspace = Workspace(
        type="personal",
        name=f"{user.display_name}'s Personal Space",
        personal_owner_user_id=user.id,
    )
    db.add(workspace)
    await db.flush()
    return workspace


async def create_personal_workspace(db: AsyncSession, user: User) -> Workspace:
    """Backward-compatible name for existing provisioning callers."""
    return await ensure_personal_workspace(db, user)


async def create_organization_workspace(db: AsyncSession, name: str, owner_user_id: str) -> Workspace:
    owner = await db.get(User, owner_user_id)
    if owner is None or not owner.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active workspace owner not found")
    workspace = Workspace(type="organization", name=name.strip())
    db.add(workspace)
    await db.flush()
    db.add(
        WorkspaceMembership(
            workspace_id=workspace.id,
            user_id=owner_user_id,
            role="owner",
            status="active",
            invited_by_user_id=owner_user_id,
        )
    )
    await db.flush()
    return workspace


async def require_active_owner_after_change(
    db: AsyncSession,
    workspace_id: str,
    excluded_membership_id: str | None = None,
) -> None:
    stmt = select(func.count(WorkspaceMembership.id)).where(
        WorkspaceMembership.workspace_id == workspace_id,
        WorkspaceMembership.role == "owner",
        WorkspaceMembership.status == "active",
    )
    if excluded_membership_id is not None:
        stmt = stmt.where(WorkspaceMembership.id != excluded_membership_id)
    owner_count = (await db.execute(stmt)).scalar_one()
    if owner_count < 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Organization workspace must retain at least one active owner",
        )


async def update_membership_role(
    db: AsyncSession,
    membership_id: str,
    new_role: str,
) -> WorkspaceMembership:
    membership = await db.get(WorkspaceMembership, membership_id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace membership not found")
    if membership.role == "owner" and new_role != "owner":
        await require_active_owner_after_change(db, membership.workspace_id, membership.id)
    membership.role = new_role
    membership.updated_at = datetime.now(UTC)
    await db.flush()
    return membership


async def add_workspace_member(
    db: AsyncSession,
    workspace_id: str,
    user_id: str,
    role: str,
    invited_by_user_id: str | None,
) -> WorkspaceMembership:
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    if workspace.type != "organization":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Personal workspaces cannot have memberships",
        )
    if role not in {"owner", "admin", "member", "guest"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid workspace role")
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active user not found")
    existing = (
        await db.execute(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status == "active":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is already a workspace member")
        existing.role = role
        existing.status = "active"
        existing.invited_by_user_id = invited_by_user_id
        existing.joined_at = datetime.now(UTC)
        existing.updated_at = datetime.now(UTC)
        await db.flush()
        return existing
    membership = WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=user_id,
        role=role,
        status="active",
        invited_by_user_id=invited_by_user_id,
    )
    db.add(membership)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is already a workspace member") from exc
    return membership


async def add_workspace_member_by_email(
    db: AsyncSession,
    workspace_id: str,
    email: str,
    role: str,
    invited_by_user_id: str,
) -> WorkspaceMembership:
    user = (await db.execute(select(User).where(func.lower(User.email) == email.strip().lower()))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active account uses this email. Ask the person to register first.",
        )
    return await add_workspace_member(db, workspace_id, user.id, role, invited_by_user_id)


async def ensure_workspace_member_by_email(
    db: AsyncSession,
    workspace_id: str,
    email: str,
    invited_by_user_id: str,
) -> tuple[WorkspaceMembership, User]:
    """Explicitly enroll an admin-selected business user in an organization.

    This is used by the platform workspace provisioning flow: selecting a lead or
    member is the administrator's explicit membership decision, not an implicit
    side effect of a user-controlled agent request.
    """
    user = (
        await db.execute(select(User).where(func.lower(User.email) == email.strip().lower()))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active user not found")
    if user.platform_role == "platform_admin":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Platform administrators cannot be workspace leads or members",
        )

    existing = (
        await db.execute(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        membership = await add_workspace_member(
            db,
            workspace_id,
            user.id,
            "member",
            invited_by_user_id,
        )
        return membership, user

    if existing.status != "active" or existing.role == "guest":
        existing.status = "active"
        existing.role = "member"
        existing.invited_by_user_id = invited_by_user_id
        existing.joined_at = datetime.now(UTC)
        existing.updated_at = datetime.now(UTC)
        await db.flush()
    return existing, user


async def list_workspace_members(
    db: AsyncSession,
    workspace_id: str,
) -> list[tuple[WorkspaceMembership, User]]:
    rows = await db.execute(
        select(WorkspaceMembership, User)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.status == "active",
            User.is_active.is_(True),
        )
        .order_by(
            WorkspaceMembership.role.asc(),
            User.display_name.asc(),
        )
    )
    return list(rows.all())


async def list_workspace_user_ids(db: AsyncSession, workspace_id: str) -> list[str]:
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None or workspace.status != "active":
        return []
    if workspace.type == "personal":
        return [workspace.personal_owner_user_id] if workspace.personal_owner_user_id else []
    return list(
        (
            await db.execute(
                select(WorkspaceMembership.user_id).where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.status == "active",
                )
            )
        )
        .scalars()
        .all()
    )


async def list_user_workspaces(db: AsyncSession, user_id: str) -> list[Workspace]:
    result = await db.execute(
        select(Workspace)
        .outerjoin(
            WorkspaceMembership,
            and_(
                WorkspaceMembership.workspace_id == Workspace.id,
                WorkspaceMembership.user_id == user_id,
                WorkspaceMembership.status == "active",
            ),
        )
        .where(
            Workspace.status == "active",
            or_(
                and_(Workspace.type == "personal", Workspace.personal_owner_user_id == user_id),
                and_(Workspace.type == "organization", WorkspaceMembership.id.is_not(None)),
            ),
        )
        .order_by(Workspace.created_at.asc())
    )
    return list(result.scalars().all())


async def resolve_personal_workspace_for_user(db: AsyncSession, user_id: str) -> Workspace:
    """Resolve Personal scope from the authenticated principal only."""
    workspace = await get_personal_workspace(db, user_id)
    if workspace is None:
        # This is an account-provisioning invariant violation, not a value the
        # client can or should repair by supplying an organization workspace id.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Personal Space provisioning is incomplete",
        )
    return workspace


async def resolve_workspace_for_user(
    db: AsyncSession,
    user_id: str,
    workspace_id: str | None = None,
) -> Workspace:
    """Resolve a workspace only after checking the caller's current membership."""
    if workspace_id is not None:
        workspace = await db.get(Workspace, workspace_id)
        if workspace is None or workspace.status != "active":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        if workspace.type == "personal":
            allowed = workspace.personal_owner_user_id == user_id
        else:
            allowed = (
                await db.execute(
                    select(WorkspaceMembership.id).where(
                        WorkspaceMembership.workspace_id == workspace_id,
                        WorkspaceMembership.user_id == user_id,
                        WorkspaceMembership.status == "active",
                    )
                )
            ).scalar_one_or_none() is not None
        if not allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace access denied")
        return workspace

    return await resolve_personal_workspace_for_user(db, user_id)
