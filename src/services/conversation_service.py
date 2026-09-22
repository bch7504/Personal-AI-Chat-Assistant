from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Conversation, ConversationParticipant, ExternalContact, User, WorkspaceMembership
from src.services.authorization_service import (
    get_authorized_participant_ids,
    require_conversation_access,
)

_RESOURCE_ROLES = {"manager", "participant", "viewer"}


async def add_workspace_participant(
    db: AsyncSession,
    actor: User,
    conversation_id: str,
    user_id: str,
    resource_role: str = "participant",
) -> ConversationParticipant:
    if resource_role not in _RESOURCE_ROLES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid resource role")
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    await require_conversation_access(db, actor, conversation_id, "manager")
    target = await db.get(User, user_id)
    if target is None or not target.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    membership = (
        await db.execute(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == conversation.workspace_id,
                WorkspaceMembership.user_id == user_id,
                WorkspaceMembership.status == "active",
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is outside the workspace")
    existing = (
        await db.execute(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.revoked_at is not None:
            existing.revoked_at = None
            existing.resource_role = resource_role
            await db.flush()
            return existing
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Participant already exists")
    participant = ConversationParticipant(
        conversation_id=conversation_id,
        principal_kind="workspace_user",
        user_id=user_id,
        resource_role=resource_role,
        invited_by_user_id=actor.id,
    )
    db.add(participant)
    await db.flush()
    return participant


async def add_external_participant(
    db: AsyncSession,
    actor: User,
    conversation_id: str,
    external_contact_id: str,
    resource_role: str = "participant",
) -> ConversationParticipant:
    if resource_role not in _RESOURCE_ROLES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid resource role")
    conversation = await db.get(Conversation, conversation_id)
    contact = await db.get(ExternalContact, external_contact_id)
    if conversation is None or contact is None or contact.workspace_id != conversation.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    await require_conversation_access(db, actor, conversation_id, "manager")
    participant = ConversationParticipant(
        conversation_id=conversation_id,
        principal_kind="external_contact",
        external_contact_id=external_contact_id,
        resource_role=resource_role,
        invited_by_user_id=actor.id,
    )
    db.add(participant)
    await db.flush()
    return participant


async def revoke_participant(
    db: AsyncSession,
    actor: User,
    participant_id: str,
) -> ConversationParticipant:
    participant = await db.get(ConversationParticipant, participant_id)
    if participant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participant not found")
    await require_conversation_access(db, actor, participant.conversation_id, "manager")
    participant.revoked_at = datetime.now(UTC)
    await db.flush()
    return participant


__all__ = [
    "add_external_participant",
    "add_workspace_participant",
    "get_authorized_participant_ids",
    "revoke_participant",
]
