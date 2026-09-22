from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ContactRelationship, ExternalContact, User, WorkspaceMembership
from src.models.relationship_schemas import RelationshipCreate, RelationshipOut, RelationshipUpdate
from src.services.workspace_service import resolve_workspace_for_user


async def _resolve_subject(
    db: AsyncSession,
    workspace_id: str,
    owner: User,
    subject_kind: str,
    subject_id: str,
) -> tuple[User | None, ExternalContact | None]:
    workspace = await resolve_workspace_for_user(db, owner.id, workspace_id)
    if subject_kind == "workspace_user":
        if subject_id == owner.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A relationship cannot point to yourself")
        if workspace.type != "organization":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Internal relationships require an organization workspace",
            )
        owner_membership = (
            await db.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.user_id == owner.id,
                    WorkspaceMembership.status == "active",
                )
            )
        ).scalar_one_or_none()
        if owner_membership is None or owner_membership.role == "guest":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace directory access denied")
        subject_membership = (
            await db.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.user_id == subject_id,
                    WorkspaceMembership.status == "active",
                )
            )
        ).scalar_one_or_none()
        subject = await db.get(User, subject_id)
        if subject_membership is None or subject is None or not subject.is_active:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")
        return subject, None

    contact = await db.get(ExternalContact, subject_id)
    if contact is None or contact.workspace_id != workspace_id or contact.status == "revoked":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External contact not found")
    return None, contact


async def _to_out(db: AsyncSession, relationship: ContactRelationship) -> RelationshipOut:
    if relationship.subject_kind == "workspace_user":
        subject = await db.get(User, relationship.subject_user_id)
        if subject is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relationship subject not found")
        subject_id = subject.id
        display_name = subject.display_name
        email = subject.email
        organization = None
    else:
        contact = await db.get(ExternalContact, relationship.subject_external_contact_id)
        if contact is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relationship subject not found")
        subject_id = contact.id
        display_name = contact.display_name
        email = contact.email
        organization = contact.organization
    return RelationshipOut(
        id=relationship.id,
        workspace_id=relationship.workspace_id,
        subject_kind=relationship.subject_kind,
        subject_id=subject_id,
        display_name=display_name,
        email=email,
        organization=organization,
        relationship_type=relationship.relationship_type,
        custom_label=relationship.custom_label,
        strength=relationship.strength,
        status=relationship.status,
        source=relationship.source,
        notes=relationship.notes,
        last_interaction_at=relationship.last_interaction_at,
        confirmed_at=relationship.confirmed_at,
        created_at=relationship.created_at,
        updated_at=relationship.updated_at,
    )


async def list_relationships(
    db: AsyncSession,
    owner: User,
    workspace_id: str,
    *,
    query: str | None = None,
    include_archived: bool = False,
) -> list[RelationshipOut]:
    await resolve_workspace_for_user(db, owner.id, workspace_id)
    stmt = select(ContactRelationship).where(
        ContactRelationship.workspace_id == workspace_id,
        ContactRelationship.owner_user_id == owner.id,
    )
    if not include_archived:
        stmt = stmt.where(ContactRelationship.status == "active")
    relationships = list((await db.execute(stmt.order_by(ContactRelationship.updated_at.desc()))).scalars().all())
    items = [await _to_out(db, relationship) for relationship in relationships]
    if query:
        needle = query.strip().casefold()
        items = [
            item
            for item in items
            if needle
            in " ".join(
                filter(
                    None,
                    [item.display_name, item.email, item.organization, item.custom_label, item.relationship_type],
                )
            ).casefold()
        ]
    return items


async def create_relationship(
    db: AsyncSession,
    owner: User,
    workspace_id: str,
    payload: RelationshipCreate,
) -> ContactRelationship:
    subject_user, contact = await _resolve_subject(
        db,
        workspace_id,
        owner,
        payload.subject_kind,
        payload.subject_id,
    )
    subject_clause = (
        ContactRelationship.subject_user_id == subject_user.id
        if subject_user is not None
        else ContactRelationship.subject_external_contact_id == contact.id
    )
    existing = (
        await db.execute(
            select(ContactRelationship).where(
                ContactRelationship.workspace_id == workspace_id,
                ContactRelationship.owner_user_id == owner.id,
                subject_clause,
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if existing is not None:
        if existing.status != "archived":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Relationship already exists")
        existing.relationship_type = payload.relationship_type
        existing.custom_label = payload.custom_label
        existing.strength = payload.strength
        existing.notes = payload.notes
        existing.status = "active"
        existing.source = "manual"
        existing.confirmed_at = now
        existing.updated_at = now
        await db.flush()
        return existing

    relationship = ContactRelationship(
        workspace_id=workspace_id,
        owner_user_id=owner.id,
        subject_kind=payload.subject_kind,
        subject_user_id=subject_user.id if subject_user else None,
        subject_external_contact_id=contact.id if contact else None,
        relationship_type=payload.relationship_type,
        custom_label=payload.custom_label,
        strength=payload.strength,
        notes=payload.notes,
        status="active",
        source="manual",
        confirmed_at=now,
    )
    db.add(relationship)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Relationship already exists") from exc
    return relationship


async def update_relationship(
    db: AsyncSession,
    owner: User,
    workspace_id: str,
    relationship_id: str,
    payload: RelationshipUpdate,
) -> ContactRelationship:
    await resolve_workspace_for_user(db, owner.id, workspace_id)
    relationship = (
        await db.execute(
            select(ContactRelationship).where(
                ContactRelationship.id == relationship_id,
                ContactRelationship.workspace_id == workspace_id,
                ContactRelationship.owner_user_id == owner.id,
            )
        )
    ).scalar_one_or_none()
    if relationship is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relationship not found")
    updates = payload.model_dump(exclude_unset=True)
    resulting_type = updates.get("relationship_type", relationship.relationship_type)
    resulting_label = updates.get("custom_label", relationship.custom_label)
    if resulting_type == "other" and not resulting_label:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="custom_label is required when relationship_type is other",
        )
    if resulting_type != "other":
        updates["custom_label"] = None
    for field, value in updates.items():
        setattr(relationship, field, value)
    relationship.updated_at = datetime.now(UTC)
    await db.flush()
    return relationship


async def archive_relationship(
    db: AsyncSession,
    owner: User,
    workspace_id: str,
    relationship_id: str,
) -> ContactRelationship:
    return await update_relationship(
        db,
        owner,
        workspace_id,
        relationship_id,
        RelationshipUpdate(status="archived"),
    )


async def relationship_to_out(db: AsyncSession, relationship: ContactRelationship) -> RelationshipOut:
    return await _to_out(db, relationship)
