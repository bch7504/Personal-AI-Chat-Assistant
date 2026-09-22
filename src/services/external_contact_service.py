from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ExternalContact, User, WorkspaceMembership
from src.models.relationship_schemas import ExternalContactCreate
from src.services.workspace_service import resolve_workspace_for_user


async def _require_contact_editor(db: AsyncSession, user: User, workspace_id: str) -> None:
    workspace = await resolve_workspace_for_user(db, user.id, workspace_id)
    if workspace.type == "personal":
        return
    membership = (
        await db.execute(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user.id,
                WorkspaceMembership.status == "active",
            )
        )
    ).scalar_one_or_none()
    if membership is None or membership.role == "guest":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Contact management access denied")


async def list_external_contacts(
    db: AsyncSession,
    user: User,
    workspace_id: str,
) -> list[ExternalContact]:
    await resolve_workspace_for_user(db, user.id, workspace_id)
    return list(
        (
            await db.execute(
                select(ExternalContact)
                .where(
                    ExternalContact.workspace_id == workspace_id,
                    ExternalContact.status != "revoked",
                )
                .order_by(ExternalContact.display_name.asc())
            )
        )
        .scalars()
        .all()
    )


async def create_external_contact(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    payload: ExternalContactCreate,
) -> ExternalContact:
    await _require_contact_editor(db, user, workspace_id)
    normalized_email = str(payload.email).lower()
    existing = (
        await db.execute(
            select(ExternalContact).where(
                ExternalContact.workspace_id == workspace_id,
                ExternalContact.email == normalized_email,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status == "revoked":
            existing.status = "active"
            existing.display_name = payload.display_name
            existing.organization = payload.organization
            existing.updated_at = datetime.now(UTC)
            await db.flush()
            return existing
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="External contact already exists")

    contact = ExternalContact(
        workspace_id=workspace_id,
        email=normalized_email,
        display_name=payload.display_name,
        organization=payload.organization,
        status="active",
        created_by_user_id=user.id,
    )
    db.add(contact)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="External contact already exists") from exc
    return contact
