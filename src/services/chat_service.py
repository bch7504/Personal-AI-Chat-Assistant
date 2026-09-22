from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    AgentWorkspaceConversation,
    AIPermission,
    Conversation,
    ConversationParticipant,
    EventCandidate,
    EventExtractionCursor,
    Message,
    Task,
    User,
    WorkspaceMembership,
)
from src.models.auth_schemas import UserPublic
from src.models.chat_schemas import ConversationReadReceiptOut, ConversationSummary, MessageOut
from src.services.authorization_service import (
    get_authorized_participant_ids,
    require_conversation_access,
    require_workspace_member,
)
from src.services.workspace_service import resolve_workspace_for_user


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def serialize_message(message: Message, sender: User) -> MessageOut:
    return MessageOut(
        id=message.id,
        conversation_id=message.conversation_id,
        sender_id=message.sender_id,
        sender_name=sender.display_name,
        content=message.content,
        created_at=_iso(message.created_at),
    )


async def assert_participant(db: AsyncSession, conversation_id: str, user_id: str) -> ConversationParticipant:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conversation access denied")
    participant = await require_conversation_access(db, user, conversation_id)
    if participant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conversation access denied")
    return participant


async def get_participant_ids(db: AsyncSession, conversation_id: str) -> list[str]:
    return await get_authorized_participant_ids(db, conversation_id)


async def get_ai_permission(db: AsyncSession, conversation_id: str, user_id: str) -> AIPermission | None:
    return (
        await db.execute(
            select(AIPermission).where(
                AIPermission.conversation_id == conversation_id,
                AIPermission.user_id == user_id,
            )
        )
    ).scalar_one_or_none()


async def set_ai_permission(
    db: AsyncSession,
    conversation_id: str,
    user_id: str,
    granted: bool | None = None,
    contribution_allowed: bool | None = None,
) -> AIPermission:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is not None and conversation.type == "group":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Group AI is controlled by a conversation manager",
        )
    permission = await get_ai_permission(db, conversation_id, user_id)
    changed = permission is None
    contribution_revoked = False
    if permission is None:
        permission = AIPermission(
            conversation_id=conversation_id,
            user_id=user_id,
            granted=bool(granted),
            contribution_allowed=bool(contribution_allowed),
        )
        db.add(permission)
    else:
        if granted is not None and permission.granted != granted:
            permission.granted = granted
            changed = True
        if contribution_allowed is not None and permission.contribution_allowed != contribution_allowed:
            contribution_revoked = permission.contribution_allowed and not contribution_allowed
            permission.contribution_allowed = contribution_allowed
            changed = True
    if changed:
        permission.updated_at = datetime.now(UTC)

    # A manual extraction depends on the complete authorized view, so any real scope change makes
    # its unconfirmed candidates stale.  A proactive candidate only depends on its source author
    # and is invalidated specifically when that author revokes contribution processing.
    if changed:
        await db.execute(
            update(Task)
            .where(
                Task.conversation_id == conversation_id,
                Task.status == "suggested",
                Task.source == "ai_extracted",
            )
            .values(status="invalidated", invalidated_reason="consent_scope_changed")
        )
    if contribution_revoked:
        await db.execute(
            update(Task)
            .where(
                Task.conversation_id == conversation_id,
                Task.status == "suggested",
                Task.source_sender_id == user_id,
            )
            .values(status="invalidated", invalidated_reason="source_consent_revoked")
        )
    await db.commit()
    await db.refresh(permission)
    return permission


async def assert_ai_permission(db: AsyncSession, conversation_id: str, user_id: str) -> None:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if conversation.type == "group":
        if not conversation.ai_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="AI is not enabled by this conversation's manager",
            )
        return
    permission = await get_ai_permission(db, conversation_id, user_id)
    if permission is None or not permission.granted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="AI permission not granted for this conversation"
        )


async def set_group_ai_policy(
    db: AsyncSession,
    conversation_id: str,
    actor: User,
    enabled: bool,
) -> Conversation:
    """Change the one group-wide AI policy; only a conversation manager may do this."""
    await require_conversation_access(db, actor, conversation_id, "manager")
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if conversation.type != "group":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Group AI policy only applies to group conversations",
        )
    if conversation.ai_enabled == enabled:
        return conversation

    now = datetime.now(UTC)
    conversation.ai_enabled = enabled
    conversation.ai_policy_version += 1
    conversation.ai_enabled_by_user_id = actor.id if enabled else None
    conversation.ai_enabled_at = now if enabled else None
    # Any unconfirmed output was derived under the previous authorization policy.  Confirmed
    # tasks/calendar events are domain records and are not silently deleted.
    await db.execute(
        update(Task)
        .where(Task.conversation_id == conversation_id, Task.status == "suggested")
        .values(status="invalidated", invalidated_reason="group_ai_policy_changed")
    )
    cursor = await db.get(EventExtractionCursor, conversation_id)
    if cursor is not None:
        cursor.last_message_created_at = None
        cursor.last_message_id = None
        cursor.processed_message_count = 0
        cursor.status = "idle"
        cursor.last_error = None
    await db.execute(
        update(EventCandidate)
        .where(EventCandidate.conversation_id == conversation_id, EventCandidate.status == "suggested")
        .values(status="invalidated", invalidated_reason="group_ai_policy_changed")
    )
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def create_message(db: AsyncSession, conversation_id: str, sender_id: str, content: str) -> Message:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    now = datetime.now(UTC)
    message = Message(
        conversation_id=conversation_id,
        sender_id=sender_id,
        content=content,
        created_at=now,
    )
    db.add(message)
    conversation.updated_at = now
    await db.execute(
        update(ConversationParticipant)
        .where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.revoked_at.is_(None),
        )
        .values(hidden_at=None)
    )
    # Sending from a conversation means the sender has seen everything up to this point. Advancing
    # their read cursor prevents older inbound messages from resurfacing as unread after reload,
    # and makes an own last message consistently render in the normal/read style.
    await db.execute(
        update(ConversationParticipant)
        .where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == sender_id,
            ConversationParticipant.revoked_at.is_(None),
        )
        .values(last_read_at=now)
    )
    await db.commit()
    await db.refresh(message)
    return message


async def hide_conversation(db: AsyncSession, conversation_id: str, user_id: str) -> None:
    participant = await assert_participant(db, conversation_id, user_id)
    participant.hidden_at = datetime.now(UTC)
    await db.commit()


async def leave_group_conversation(
    db: AsyncSession, conversation_id: str, user: User
) -> tuple[list[str], bool]:
    participant = await assert_participant(db, conversation_id, user.id)
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if conversation.type != "group":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Direct conversations cannot be left")

    now = datetime.now(UTC)
    participant.revoked_at = now
    participant.hidden_at = now
    permission = await get_ai_permission(db, conversation_id, user.id)
    if permission is not None:
        await db.delete(permission)

    remaining = list(
        (
            await db.execute(
                select(ConversationParticipant)
                .where(
                    ConversationParticipant.conversation_id == conversation_id,
                    ConversationParticipant.user_id.is_not(None),
                    ConversationParticipant.user_id != user.id,
                    ConversationParticipant.revoked_at.is_(None),
                )
                .order_by(ConversationParticipant.joined_at, ConversationParticipant.id)
            )
        ).scalars()
    )
    if not remaining:
        await db.delete(conversation)
        await db.commit()
        return [], True

    if participant.resource_role == "manager" and not any(row.resource_role == "manager" for row in remaining):
        remaining[0].resource_role = "manager"
    conversation.ai_policy_version += 1
    conversation.updated_at = now
    await db.execute(
        update(Task)
        .where(Task.conversation_id == conversation_id, Task.status == "suggested")
        .values(status="invalidated", invalidated_reason="conversation_membership_changed")
    )
    await db.execute(
        update(EventCandidate)
        .where(EventCandidate.conversation_id == conversation_id, EventCandidate.status == "suggested")
        .values(status="invalidated", invalidated_reason="conversation_membership_changed")
    )
    await db.commit()
    return [row.user_id for row in remaining if row.user_id], False


async def mark_read(db: AsyncSession, conversation_id: str, user_id: str) -> datetime:
    participant = await assert_participant(db, conversation_id, user_id)
    read_at = datetime.now(UTC)
    participant.last_read_at = read_at
    await db.commit()
    return read_at


async def get_read_receipts(
    db: AsyncSession,
    conversation_id: str,
    *,
    exclude_user_id: str,
) -> list[ConversationReadReceiptOut]:
    """Return active participants' read cursors for rendering per-message seen avatars."""
    rows = (
        await db.execute(
            select(ConversationParticipant, User)
            .join(User, User.id == ConversationParticipant.user_id)
            .where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id != exclude_user_id,
                ConversationParticipant.revoked_at.is_(None),
            )
            .order_by(User.display_name, User.id)
        )
    ).all()
    return [
        ConversationReadReceiptOut(
            user_id=user.id,
            display_name=user.display_name,
            read_at=_iso(participant.last_read_at),
        )
        for participant, user in rows
    ]


async def get_first_unread_message_id(db: AsyncSession, conversation_id: str, user_id: str) -> str | None:
    """Return the oldest unread message from another participant."""
    participant = await assert_participant(db, conversation_id, user_id)
    return (
        await db.execute(
            select(Message.id)
            .where(
                Message.conversation_id == conversation_id,
                Message.created_at > participant.last_read_at,
                Message.sender_id != user_id,
            )
            .order_by(Message.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _assert_workspace_participants(
    db: AsyncSession,
    workspace_id: str,
    user_ids: set[str],
) -> None:
    if not user_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one participant is required")
    rows = (
        (
            await db.execute(
                select(WorkspaceMembership.user_id).where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.user_id.in_(user_ids),
                    WorkspaceMembership.status == "active",
                )
            )
        )
        .scalars()
        .all()
    )
    if set(rows) != user_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Participant is outside the workspace")


async def get_or_create_direct_conversation(
    db: AsyncSession,
    user_a_id: str,
    user_b_id: str,
    workspace_id: str | None = None,
) -> Conversation:
    if user_a_id == user_b_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot create a conversation with self")
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="workspace_id is required")
    workspace = await resolve_workspace_for_user(db, user_a_id, workspace_id)
    if workspace.type != "organization":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Direct conversations require an organization workspace",
        )
    await require_workspace_member(db, await db.get(User, user_a_id), workspace_id)
    await _assert_workspace_participants(db, workspace_id, {user_a_id, user_b_id})

    candidate_ids = (
        (
            await db.execute(
                select(ConversationParticipant.conversation_id)
                .join(Conversation, Conversation.id == ConversationParticipant.conversation_id)
                .where(
                    Conversation.workspace_id == workspace_id,
                    Conversation.type == "direct",
                    ConversationParticipant.user_id == user_a_id,
                    ConversationParticipant.revoked_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for cid in candidate_ids:
        participant_ids = (
            (
                await db.execute(
                    select(ConversationParticipant.user_id).where(
                        ConversationParticipant.conversation_id == cid,
                        ConversationParticipant.revoked_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        if set(participant_ids) == {user_a_id, user_b_id}:
            return await db.get(Conversation, cid)

    conversation = Conversation(workspace_id=workspace_id, type="direct", name=None, created_by=user_a_id)
    db.add(conversation)
    await db.flush()
    db.add_all(
        [
            ConversationParticipant(
                conversation_id=conversation.id,
                user_id=user_a_id,
                principal_kind="workspace_user",
                resource_role="manager",
                invited_by_user_id=user_a_id,
            ),
            ConversationParticipant(
                conversation_id=conversation.id,
                user_id=user_b_id,
                principal_kind="workspace_user",
                resource_role="participant",
                invited_by_user_id=user_a_id,
            ),
        ]
    )
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def create_group_conversation(
    db: AsyncSession,
    creator_id: str,
    member_ids: list[str],
    name: str,
    workspace_id: str | None = None,
    *,
    ai_enabled: bool = False,
    commit: bool = True,
) -> Conversation:
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="workspace_id is required")
    workspace = await resolve_workspace_for_user(db, creator_id, workspace_id)
    if workspace.type != "organization":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Group conversations require an organization workspace",
        )
    await _assert_workspace_participants(db, workspace_id, {creator_id, *member_ids})
    now = datetime.now(UTC)
    conversation = Conversation(
        workspace_id=workspace_id,
        type="group",
        name=name,
        created_by=creator_id,
        ai_enabled=ai_enabled,
        ai_policy_version=1 if ai_enabled else 0,
        ai_enabled_by_user_id=creator_id if ai_enabled else None,
        ai_enabled_at=now if ai_enabled else None,
    )
    db.add(conversation)
    await db.flush()
    all_member_ids = {creator_id, *member_ids}
    db.add_all(
        [
            ConversationParticipant(
                conversation_id=conversation.id,
                user_id=member_id,
                principal_kind="workspace_user",
                resource_role="manager" if member_id == creator_id else "participant",
                invited_by_user_id=creator_id,
            )
            for member_id in all_member_ids
        ]
    )
    if commit:
        await db.commit()
        await db.refresh(conversation)
    else:
        await db.flush()
    return conversation


async def build_conversation_summary(
    db: AsyncSession, conversation: Conversation, current_user_id: str
) -> ConversationSummary:
    participant_rows = (
        await db.execute(
            select(User, ConversationParticipant)
            .join(ConversationParticipant, ConversationParticipant.user_id == User.id)
            .where(
                ConversationParticipant.conversation_id == conversation.id,
                ConversationParticipant.revoked_at.is_(None),
            )
        )
    ).all()
    participants = [
        UserPublic(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=user.role,
            platform_role=user.platform_role,
        )
        for user, _ in participant_rows
    ]
    my_participant = next((cp for _, cp in participant_rows if cp.user_id == current_user_id), None)

    if conversation.type == "group":
        name = conversation.name or "Group"
    else:
        other = next((user for user, _ in participant_rows if user.id != current_user_id), None)
        name = other.display_name if other else "Direct message"

    last_message_row = (
        await db.execute(
            select(Message, User)
            .join(User, User.id == Message.sender_id)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    ).first()
    last_message = serialize_message(last_message_row[0], last_message_row[1]) if last_message_row else None

    unread_count = 0
    if my_participant is not None:
        unread_count = (
            await db.execute(
                select(func.count(Message.id)).where(
                    Message.conversation_id == conversation.id,
                    Message.created_at > my_participant.last_read_at,
                    Message.sender_id != current_user_id,
                )
            )
        ).scalar_one()

    if conversation.type == "group":
        ai_permission_granted = conversation.ai_enabled
    else:
        permission = await get_ai_permission(db, conversation.id, current_user_id)
        ai_permission_granted = permission.granted if permission is not None else False

    channel_mapping = (
        await db.execute(
            select(AgentWorkspaceConversation).where(
                AgentWorkspaceConversation.conversation_id == conversation.id,
            )
        )
    ).scalar_one_or_none()

    return ConversationSummary(
        id=conversation.id,
        workspace_id=conversation.workspace_id,
        type=conversation.type,
        name=name,
        participants=participants,
        last_message=last_message,
        unread_count=unread_count,
        ai_permission_granted=ai_permission_granted,
        updated_at=_iso(conversation.updated_at),
        my_resource_role=my_participant.resource_role if my_participant else None,
        ai_enabled=conversation.ai_enabled,
        scope="channel" if channel_mapping is not None else "personal",
        agent_workspace_id=channel_mapping.agent_workspace_id if channel_mapping is not None else None,
        channel_classification=channel_mapping.classification if channel_mapping is not None else None,
        channel_kind=channel_mapping.channel_kind if channel_mapping is not None else None,
    )
