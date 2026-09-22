from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.db.models import User
from src.db.session import get_db
from src.models.people_schemas import PeopleInsightOut, PeoplePreferenceUpdate
from src.models.relationship_schemas import (
    ExternalContactCreate,
    ExternalContactOut,
    RelationshipCreate,
    RelationshipOut,
    RelationshipUpdate,
)
from src.services.audit_service import record_audit_event
from src.services.external_contact_service import create_external_contact, list_external_contacts
from src.services.people_intelligence_service import list_people_insights, update_people_preference
from src.services.relationship_service import (
    archive_relationship,
    create_relationship,
    list_relationships,
    relationship_to_out,
    update_relationship,
)

router = APIRouter()


@router.get("/{workspace_id}/people-insights", response_model=list[PeopleInsightOut])
async def get_people_insights(
    workspace_id: str,
    q: str | None = Query(default=None, max_length=120),
    segment: Literal["all", "pinned", "frequent", "recent", "follow_up", "directory"] = "all",
    limit: int = Query(default=100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PeopleInsightOut]:
    return await list_people_insights(
        db,
        current_user,
        workspace_id,
        query=q,
        segment=segment,
        limit=limit,
    )


@router.patch("/{workspace_id}/people-insights/{subject_user_id}", response_model=PeopleInsightOut)
async def edit_people_preference(
    workspace_id: str,
    subject_user_id: str,
    request: PeoplePreferenceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PeopleInsightOut:
    preference = await update_people_preference(db, current_user, workspace_id, subject_user_id, request)
    await record_audit_event(
        db,
        actor=current_user,
        action="people.preference_updated",
        target_type="people_preference",
        target_id=preference.id,
        workspace_id=workspace_id,
        metadata={"fields": sorted(request.model_fields_set)},
    )
    await db.commit()
    insights = await list_people_insights(db, current_user, workspace_id, limit=500)
    return next(item for item in insights if item.user_id == subject_user_id)


@router.get("/{workspace_id}/external-contacts", response_model=list[ExternalContactOut])
async def get_external_contacts(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ExternalContactOut]:
    contacts = await list_external_contacts(db, current_user, workspace_id)
    return [ExternalContactOut.model_validate(contact) for contact in contacts]


@router.post(
    "/{workspace_id}/external-contacts",
    response_model=ExternalContactOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_external_contact(
    workspace_id: str,
    request: ExternalContactCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExternalContactOut:
    contact = await create_external_contact(db, current_user, workspace_id, request)
    await record_audit_event(
        db,
        actor=current_user,
        action="external_contact.created",
        target_type="external_contact",
        target_id=contact.id,
        workspace_id=workspace_id,
        metadata={"source": "manual"},
    )
    await db.commit()
    await db.refresh(contact)
    return ExternalContactOut.model_validate(contact)


@router.get("/{workspace_id}/relationships", response_model=list[RelationshipOut])
async def get_relationships(
    workspace_id: str,
    q: str | None = Query(default=None, max_length=120),
    include_archived: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RelationshipOut]:
    return await list_relationships(
        db,
        current_user,
        workspace_id,
        query=q,
        include_archived=include_archived,
    )


@router.post(
    "/{workspace_id}/relationships",
    response_model=RelationshipOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_relationship(
    workspace_id: str,
    request: RelationshipCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RelationshipOut:
    relationship = await create_relationship(db, current_user, workspace_id, request)
    await record_audit_event(
        db,
        actor=current_user,
        action="relationship.created",
        target_type="contact_relationship",
        target_id=relationship.id,
        workspace_id=workspace_id,
        metadata={"relationship_type": relationship.relationship_type, "source": relationship.source},
    )
    await db.commit()
    await db.refresh(relationship)
    return await relationship_to_out(db, relationship)


@router.patch("/{workspace_id}/relationships/{relationship_id}", response_model=RelationshipOut)
async def edit_relationship(
    workspace_id: str,
    relationship_id: str,
    request: RelationshipUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RelationshipOut:
    relationship = await update_relationship(db, current_user, workspace_id, relationship_id, request)
    await record_audit_event(
        db,
        actor=current_user,
        action="relationship.updated",
        target_type="contact_relationship",
        target_id=relationship.id,
        workspace_id=workspace_id,
        metadata={"fields": sorted(request.model_fields_set)},
    )
    await db.commit()
    await db.refresh(relationship)
    return await relationship_to_out(db, relationship)


@router.delete(
    "/{workspace_id}/relationships/{relationship_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_relationship(
    workspace_id: str,
    relationship_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    relationship = await archive_relationship(db, current_user, workspace_id, relationship_id)
    await record_audit_event(
        db,
        actor=current_user,
        action="relationship.archived",
        target_type="contact_relationship",
        target_id=relationship.id,
        workspace_id=workspace_id,
        metadata={"source": "user_action"},
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
