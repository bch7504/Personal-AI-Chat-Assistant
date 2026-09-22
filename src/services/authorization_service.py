from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    Conversation,
    ConversationParticipant,
    ExternalContact,
    SupportAccessGrant,
    User,
    Workspace,
    WorkspaceMembership,
)
from src.services.audit_service import record_audit_event


def require_platform_admin(user: User) -> User:
    if user.platform_role != "platform_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin access required",
        )
    return user


async def require_workspace_role(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    allowed_roles: set[str] | frozenset[str],
) -> WorkspaceMembership | None:
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None or workspace.status != "active":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    if workspace.type == "personal":
        if workspace.personal_owner_user_id == user.id and "owner" in allowed_roles:
            return None
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace access denied",
        )
    membership = (
        await db.execute(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user.id,
                WorkspaceMembership.status == "active",
                WorkspaceMembership.role.in_(allowed_roles),
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace access denied",
        )
    return membership


async def require_workspace_member(
    db: AsyncSession,
    user: User,
    workspace_id: str,
) -> WorkspaceMembership | None:
    return await require_workspace_role(db, user, workspace_id, {"owner", "admin", "member", "guest"})


_RESOURCE_ROLE_RANK = {"viewer": 1, "participant": 2, "manager": 3}


async def require_conversation_access(
    db: AsyncSession,
    user: User,
    conversation_id: str,
    minimum_resource_role: str = "viewer",
) -> ConversationParticipant | None:
    """Authorize one request against current account, membership and participant state."""
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account has been disabled")
    if minimum_resource_role not in _RESOURCE_ROLE_RANK:
        raise ValueError(f"Unknown resource role: {minimum_resource_role}")

    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    participant = (
        await db.execute(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.revoked_at.is_(None),
                (ConversationParticipant.user_id == user.id)
                | (
                    ConversationParticipant.external_contact_id.in_(
                        select(ExternalContact.id).where(ExternalContact.linked_user_id == user.id)
                    )
                ),
            )
        )
    ).scalar_one_or_none()
    if participant is None:
        # A platform admin needs an explicit, request-time support grant and never gets an implicit bypass.
        if user.platform_role == "platform_admin" and minimum_resource_role == "viewer":
            await require_support_scope(db, user, conversation.workspace_id, "conversation:read")
            return None
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    if participant.principal_kind == "workspace_user":
        membership = (
            await db.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == conversation.workspace_id,
                    WorkspaceMembership.user_id == user.id,
                    WorkspaceMembership.status == "active",
                )
            )
        ).scalar_one_or_none()
        if membership is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace access denied")
    elif participant.principal_kind != "external_contact":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conversation access denied")

    if _RESOURCE_ROLE_RANK.get(participant.resource_role, 0) < _RESOURCE_ROLE_RANK[minimum_resource_role]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conversation access denied")
    return participant


async def get_authorized_participant_ids(db: AsyncSession, conversation_id: str) -> list[str]:
    """Return current active user principals; revoked/inactive memberships are excluded."""
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    participants = (
        (
            await db.execute(
                select(ConversationParticipant).where(
                    ConversationParticipant.conversation_id == conversation_id,
                    ConversationParticipant.revoked_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    ids: list[str] = []
    for participant in participants:
        user_id = participant.user_id
        if user_id is None and participant.external_contact_id is not None:
            contact = await db.get(ExternalContact, participant.external_contact_id)
            user_id = contact.linked_user_id if contact is not None else None
        if user_id is None:
            continue
        user = await db.get(User, user_id)
        if user is None or not user.is_active:
            continue
        if participant.principal_kind == "workspace_user":
            membership = (
                await db.execute(
                    select(WorkspaceMembership.id).where(
                        WorkspaceMembership.workspace_id == conversation.workspace_id,
                        WorkspaceMembership.user_id == user_id,
                        WorkspaceMembership.status == "active",
                    )
                )
            ).scalar_one_or_none()
            if membership is None:
                continue
        if user_id not in ids:
            ids.append(user_id)
    return ids


async def request_support_access(
    db: AsyncSession,
    platform_admin: User,
    workspace_id: str,
    requested_scope: str,
    reason: str,
    duration_minutes: int,
    scope_json: dict | None = None,
) -> SupportAccessGrant:
    require_platform_admin(platform_admin)
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    grant = SupportAccessGrant(
        platform_admin_id=platform_admin.id,
        workspace_id=workspace_id,
        requested_scope=requested_scope,
        scope_json=scope_json or {"scope": requested_scope, "duration_minutes": duration_minutes},
        reason=reason,
        status="requested",
        expires_at=datetime.now(UTC) + timedelta(minutes=duration_minutes),
    )
    db.add(grant)
    await db.flush()
    await record_audit_event(
        db,
        actor=platform_admin,
        action="platform.support_access_requested",
        target_type="support_access_grant",
        target_id=grant.id,
        workspace_id=workspace_id,
        metadata={"scope": requested_scope, "duration_minutes": duration_minutes},
    )
    return grant


async def approve_support_access(
    db: AsyncSession,
    owner: User,
    workspace_id: str,
    grant_id: str,
) -> SupportAccessGrant:
    await require_workspace_role(db, owner, workspace_id, {"owner"})
    grant = await db.get(SupportAccessGrant, grant_id)
    if grant is None or grant.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Support access grant not found")
    if grant.platform_admin_id == owner.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admins cannot approve their own support access",
        )
    if grant.status != "requested":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Support access grant is not pending")
    now = datetime.now(UTC)
    request_expires_at = grant.expires_at
    if request_expires_at.tzinfo is None:
        request_expires_at = request_expires_at.replace(tzinfo=UTC)
    if request_expires_at <= now:
        grant.status = "expired"
        await db.flush()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Support access request has expired")
    duration_minutes = int(grant.scope_json.get("duration_minutes", 30))
    grant.status = "approved"
    grant.approved_by_owner_id = owner.id
    grant.approved_at = now
    grant.expires_at = now + timedelta(minutes=max(5, min(duration_minutes, 60)))
    await db.flush()
    await record_audit_event(
        db,
        actor=owner,
        action="workspace.support_access_approved",
        target_type="support_access_grant",
        target_id=grant.id,
        workspace_id=workspace_id,
        metadata={"scope": grant.requested_scope},
    )
    return grant


async def reject_support_access(
    db: AsyncSession,
    owner: User,
    workspace_id: str,
    grant_id: str,
) -> SupportAccessGrant:
    await require_workspace_role(db, owner, workspace_id, {"owner"})
    grant = await db.get(SupportAccessGrant, grant_id)
    if grant is None or grant.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Support access grant not found")
    if grant.status != "requested":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Support access grant is not pending")
    grant.status = "rejected"
    grant.approved_by_owner_id = owner.id
    await db.flush()
    await record_audit_event(
        db,
        actor=owner,
        action="workspace.support_access_rejected",
        target_type="support_access_grant",
        target_id=grant.id,
        workspace_id=workspace_id,
        metadata={"scope": grant.requested_scope},
    )
    return grant


async def revoke_support_access(
    db: AsyncSession,
    owner: User,
    workspace_id: str,
    grant_id: str,
) -> SupportAccessGrant:
    await require_workspace_role(db, owner, workspace_id, {"owner"})
    grant = await db.get(SupportAccessGrant, grant_id)
    if grant is None or grant.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Support access grant not found")
    if grant.status != "approved" or grant.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Support access grant is not active")
    grant.status = "revoked"
    grant.revoked_at = datetime.now(UTC)
    await db.flush()
    await record_audit_event(
        db,
        actor=owner,
        action="workspace.support_access_revoked",
        target_type="support_access_grant",
        target_id=grant.id,
        workspace_id=workspace_id,
        metadata={"scope": grant.requested_scope},
    )
    return grant


async def require_support_scope(
    db: AsyncSession,
    platform_admin: User,
    workspace_id: str,
    scope: str,
) -> SupportAccessGrant:
    require_platform_admin(platform_admin)
    accepted_scopes = [scope]
    if scope == "personal_data:read":
        accepted_scopes.append("personal_data:manage")
    grant = (
        (
            await db.execute(
                select(SupportAccessGrant)
                .where(
                    SupportAccessGrant.platform_admin_id == platform_admin.id,
                    SupportAccessGrant.workspace_id == workspace_id,
                    SupportAccessGrant.requested_scope.in_(accepted_scopes),
                    SupportAccessGrant.status == "approved",
                    SupportAccessGrant.approved_at.is_not(None),
                    SupportAccessGrant.expires_at > datetime.now(UTC),
                    SupportAccessGrant.revoked_at.is_(None),
                )
                .order_by(SupportAccessGrant.approved_at.desc())
            )
        )
        .scalars()
        .first()
    )
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active support access grant required",
        )
    return grant
