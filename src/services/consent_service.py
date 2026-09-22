"""Build the only conversation-message view that AI code is allowed to consume.

Conversation membership answers whether a human may read a chat.  It does not answer whether an
external model may process every participant's content.  This module enforces the stricter,
author-controlled rule before any text reaches a planner/tool prompt.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.db.models import (
    AIPermission,
    Conversation,
    ConversationParticipant,
    ExternalContact,
    Message,
    User,
)
from src.models.schemas import MessageScope
from src.services.authorization_service import get_authorized_participant_ids, require_conversation_access


@dataclass(frozen=True)
class AuthorizedMessageView:
    conversation_id: str
    text: str
    source_message_ids: list[str]
    included_participant_ids: list[str]
    included_participant_names: list[str]
    excluded_participant_ids: list[str]
    excluded_participant_names: list[str]
    included_message_count: int
    window_message_count: int
    consent_scope_hash: str

    @property
    def coverage(self) -> float:
        if self.window_message_count == 0:
            return 1.0
        return self.included_message_count / self.window_message_count


async def _participant_permission_rows(
    db: AsyncSession, conversation_id: str
) -> tuple[list[User], dict[str, AIPermission]]:
    authorized_ids = await get_authorized_participant_ids(db, conversation_id)
    users = list(
        (
            await db.execute(
                select(User).where(User.id.in_(authorized_ids), User.is_active.is_(True)).order_by(User.id)
            )
        )
        .scalars()
        .all()
    )
    permissions = list(
        (
            await db.execute(
                select(AIPermission).where(AIPermission.conversation_id == conversation_id)
            )
        )
        .scalars()
        .all()
    )
    return users, {permission.user_id: permission for permission in permissions}


def _scope_hash(users: list[User], permissions: dict[str, AIPermission]) -> str:
    parts: list[str] = []
    for user in users:
        permission = permissions.get(user.id)
        if permission is None:
            parts.append(f"{user.id}:0:0:none")
        else:
            updated_at = permission.updated_at.isoformat() if permission.updated_at else "none"
            parts.append(
                f"{user.id}:{int(permission.granted)}:{int(permission.contribution_allowed)}:{updated_at}"
            )
    return sha256("|".join(parts).encode("utf-8")).hexdigest()


async def get_consent_scope_hash(db: AsyncSession, conversation_id: str) -> str:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is not None and conversation.type == "group":
        return sha256(
            f"group:{conversation.id}:{int(conversation.ai_enabled)}:{conversation.ai_policy_version}".encode()
        ).hexdigest()
    users, permissions = await _participant_permission_rows(db, conversation_id)
    return _scope_hash(users, permissions)


async def validate_authorized_source_ids(
    db: AsyncSession,
    conversation_id: str,
    source_message_ids: list[str],
) -> bool:
    if not source_message_ids:
        return False
    conversation = await db.get(Conversation, conversation_id)
    users, permissions = await _participant_permission_rows(db, conversation_id)
    if conversation is not None and conversation.type == "group":
        if not conversation.ai_enabled:
            return False
        allowed_ids = {user.id for user in users}
    else:
        allowed_ids = {
            user.id
            for user in users
            if (permission := permissions.get(user.id)) is not None and permission.contribution_allowed
        }
    rows = (
        await db.execute(
            select(Message.id, Message.sender_id).where(
                Message.conversation_id == conversation_id,
                Message.id.in_(source_message_ids),
            )
        )
    ).all()
    return len(rows) == len(set(source_message_ids)) and all(sender_id in allowed_ids for _, sender_id in rows)


async def build_authorized_message_view(
    db: AsyncSession,
    conversation_id: str,
    limit: int,
    *,
    user_id: str | None = None,
    scope: MessageScope | None = None,
) -> AuthorizedMessageView:
    conversation = await db.get(Conversation, conversation_id)
    users, permissions = await _participant_permission_rows(db, conversation_id)
    if conversation is not None and conversation.type == "group" and conversation.ai_enabled:
        allowed_ids = {user.id for user in users}
    else:
        allowed_ids = {
            user.id
            for user in users
            if (permission := permissions.get(user.id)) is not None and permission.contribution_allowed
        }

    base = select(Message, User).join(User, User.id == Message.sender_id).where(
        Message.conversation_id == conversation_id
    )
    selected_scope = scope or MessageScope(kind="latest_n", count=limit)
    timezone = ZoneInfo(get_settings().calendar_timezone)
    now_local = datetime.now(timezone)
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    if selected_scope.kind == "latest_n":
        query = base.order_by(Message.created_at.desc(), Message.id.desc()).limit(selected_scope.count or limit)
        rows = list((await db.execute(query)).all())
        rows.reverse()
    elif selected_scope.kind == "unread":
        participant = None
        if user_id:
            participant = (
                await db.execute(
                    select(ConversationParticipant).where(
                        ConversationParticipant.conversation_id == conversation_id,
                        ConversationParticipant.user_id == user_id,
                        ConversationParticipant.revoked_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
        query = base
        if participant is not None:
            query = query.where(Message.created_at > participant.last_read_at, Message.sender_id != user_id)
        else:
            query = query.where(False)
        # Start at the newest unread message and walk backwards, capped at 200. Reverse the
        # selected window before formatting so the model still receives natural chronology.
        unread_limit = min(selected_scope.count or limit or 200, 200)
        rows = list(
            (
                await db.execute(
                    query.order_by(Message.created_at.desc(), Message.id.desc()).limit(unread_limit)
                )
            ).all()
        )
        rows.reverse()
    else:
        since: datetime | None = None
        until: datetime | None = None
        if selected_scope.kind == "today":
            since = today_start
        elif selected_scope.kind == "yesterday":
            since, until = today_start - timedelta(days=1), today_start
        elif selected_scope.kind == "this_week":
            since = today_start - timedelta(days=today_start.weekday())
        elif selected_scope.kind == "rolling_hours":
            since = now_local - timedelta(hours=selected_scope.hours or 1)
        elif selected_scope.kind == "custom_range":
            since, until = selected_scope.since, selected_scope.until
        query = base
        if since is not None:
            query = query.where(Message.created_at >= _as_utc(since, timezone))
        if until is not None:
            query = query.where(Message.created_at <= _as_utc(until, timezone))
        rows = list((await db.execute(query.order_by(Message.created_at, Message.id).limit(500))).all())
    eligible_rows = [(message, sender) for message, sender in rows if sender.id in allowed_ids]

    included_users = [user for user in users if user.id in allowed_ids]
    excluded_users = [user for user in users if user.id not in allowed_ids]
    return AuthorizedMessageView(
        conversation_id=conversation_id,
        text="\n".join(
            f"{sender.display_name} [{message.created_at.astimezone(timezone).isoformat()}]: {message.content}"
            for message, sender in eligible_rows
        ),
        source_message_ids=[message.id for message, _ in eligible_rows],
        included_participant_ids=[user.id for user in included_users],
        included_participant_names=[user.display_name for user in included_users],
        excluded_participant_ids=[user.id for user in excluded_users],
        excluded_participant_names=[user.display_name for user in excluded_users],
        included_message_count=len(eligible_rows),
        window_message_count=len(rows),
        consent_scope_hash=(
            sha256(
                f"group:{conversation.id}:{int(conversation.ai_enabled)}:{conversation.ai_policy_version}".encode()
            ).hexdigest()
            if conversation is not None and conversation.type == "group"
            else _scope_hash(users, permissions)
        ),
    )


def _as_utc(value: datetime, default_timezone: ZoneInfo) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=default_timezone)
    return value.astimezone(UTC)


def _escape_ilike(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def search_authorized_messages(
    db: AsyncSession,
    conversation_id: str,
    query: str,
    limit: int = 20,
) -> str:
    if not query.strip():
        return ""
    conversation = await db.get(Conversation, conversation_id)
    users, permissions = await _participant_permission_rows(db, conversation_id)
    if conversation is not None and conversation.type == "group" and conversation.ai_enabled:
        allowed_ids = {user.id for user in users}
    else:
        allowed_ids = {
            user.id
            for user in users
            if (permission := permissions.get(user.id)) is not None and permission.contribution_allowed
        }
    safe_limit = max(1, min(limit, 50))
    rows = list(
        (
            await db.execute(
                select(Message, User)
                .join(User, User.id == Message.sender_id)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.sender_id.in_(allowed_ids),
                    Message.content.ilike(f"%{_escape_ilike(query)}%", escape="\\"),
                )
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(safe_limit)
            )
        ).all()
    )
    rows.reverse()
    timezone = ZoneInfo(get_settings().calendar_timezone)
    return "\n".join(
        f"{sender.display_name} [{message.created_at.astimezone(timezone).isoformat()}]: {message.content}"
        for message, sender in rows
    )


async def search_authorized_messages_for_user(
    db: AsyncSession,
    *,
    user_id: str,
    query: str,
    limit: int = 20,
) -> str:
    """Search every currently accessible conversation while preserving author-side AI consent.

    This is the Personal Agent's global chat-search boundary. Conversation membership alone is
    insufficient: group AI must be enabled, or the caller must have granted AI access in a direct
    conversation, and only messages from authors who allowed contribution are returned.
    """

    if not query.strip():
        return ""
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        return ""
    linked_contacts = select(ExternalContact.id).where(ExternalContact.linked_user_id == user_id)
    candidate_ids = list(
        (
            await db.execute(
                select(ConversationParticipant.conversation_id)
                .where(
                    ConversationParticipant.revoked_at.is_(None),
                    ConversationParticipant.hidden_at.is_(None),
                    or_(
                        ConversationParticipant.user_id == user_id,
                        ConversationParticipant.external_contact_id.in_(linked_contacts),
                    ),
                )
                .distinct()
                .limit(200)
            )
        ).scalars()
    )
    safe_limit = max(1, min(limit, 50))
    matches: list[tuple[Message, User, Conversation]] = []
    pattern = f"%{_escape_ilike(query)}%"
    for conversation_id in candidate_ids:
        try:
            await require_conversation_access(db, user, conversation_id, "viewer")
        except HTTPException:
            continue
        conversation = await db.get(Conversation, conversation_id)
        if conversation is None:
            continue
        users, permissions = await _participant_permission_rows(db, conversation_id)
        if conversation.type == "group":
            if not conversation.ai_enabled:
                continue
            allowed_ids = {participant.id for participant in users}
        else:
            caller_permission = permissions.get(user_id)
            if caller_permission is None or not caller_permission.granted:
                continue
            allowed_ids = {
                participant.id
                for participant in users
                if (permission := permissions.get(participant.id)) is not None
                and permission.contribution_allowed
            }
        if not allowed_ids:
            continue
        rows = (
            await db.execute(
                select(Message, User)
                .join(User, User.id == Message.sender_id)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.sender_id.in_(allowed_ids),
                    Message.content.ilike(pattern, escape="\\"),
                )
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(safe_limit)
            )
        ).all()
        matches.extend((message, sender, conversation) for message, sender in rows)

    matches.sort(key=lambda row: (row[0].created_at, row[0].id), reverse=True)
    timezone = ZoneInfo(get_settings().calendar_timezone)
    return "\n".join(
        f"[{conversation.name or conversation.id}] {sender.display_name} "
        f"[{message.created_at.astimezone(timezone).isoformat()}]: {message.content}"
        for message, sender, conversation in matches[:safe_limit]
    )
