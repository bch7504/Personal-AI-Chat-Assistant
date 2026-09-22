"""Durable sender for Lead-approved Product Delivery group reminders."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select

from src.db import session as db_session
from src.db.models import (
    AgentWorkspace,
    AgentWorkspaceConversation,
    AgentWorkspaceMembership,
    Conversation,
    ConversationParticipant,
    DeliveryGroupSchedule,
    Message,
    User,
)
from src.services.audit_service import record_audit_event
from src.websocket.manager import manager

logger = logging.getLogger(__name__)


async def process_due_delivery_group_schedules(*, batch_size: int = 50) -> int:
    """Send due one-shot reminders after revalidating every authorization edge."""

    now = datetime.now(UTC)
    notifications: list[tuple[list[str], dict]] = []
    sent = 0
    async with db_session.async_session_maker() as db:
        schedules = list(
            (
                await db.execute(
                    select(DeliveryGroupSchedule)
                    .where(
                        DeliveryGroupSchedule.status == "scheduled",
                        DeliveryGroupSchedule.scheduled_for <= now,
                    )
                    .order_by(DeliveryGroupSchedule.scheduled_for.asc(), DeliveryGroupSchedule.id.asc())
                    .limit(batch_size)
                )
            )
            .scalars()
            .all()
        )
        for schedule in schedules:
            authorized = (
                await db.execute(
                    select(AgentWorkspaceMembership.id)
                    .join(AgentWorkspace, AgentWorkspace.id == AgentWorkspaceMembership.agent_workspace_id)
                    .join(
                        AgentWorkspaceConversation,
                        AgentWorkspaceConversation.agent_workspace_id == AgentWorkspace.id,
                    )
                    .join(Conversation, Conversation.id == AgentWorkspaceConversation.conversation_id)
                    .join(User, User.id == AgentWorkspaceMembership.user_id)
                    .where(
                        AgentWorkspace.id == schedule.agent_workspace_id,
                        AgentWorkspace.organization_workspace_id == schedule.workspace_id,
                        AgentWorkspace.agent_profile == "product_delivery",
                        AgentWorkspace.status == "active",
                        AgentWorkspaceMembership.user_id == schedule.approved_by_user_id,
                        AgentWorkspaceMembership.business_role == "lead",
                        AgentWorkspaceMembership.status == "active",
                        AgentWorkspaceConversation.conversation_id == schedule.conversation_id,
                        Conversation.workspace_id == schedule.workspace_id,
                        Conversation.type == "group",
                        User.is_active.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if authorized is None:
                schedule.status = "failed"
                schedule.last_error = "AUTHORIZATION_REVALIDATION_FAILED"
                continue
            message = Message(
                conversation_id=schedule.conversation_id,
                sender_id=schedule.approved_by_user_id,
                content=(
                    f"[Workspace Agent · Scheduled · Lead approved]\n"
                    f"{schedule.title}\n{schedule.content}"
                ),
            )
            db.add(message)
            await db.flush()
            schedule.status = "sent"
            schedule.sent_message_id = message.id
            schedule.last_error = None
            schedule.updated_at = now
            participant_ids = list(
                (
                    await db.execute(
                        select(ConversationParticipant.user_id).where(
                            ConversationParticipant.conversation_id == schedule.conversation_id,
                            ConversationParticipant.user_id.is_not(None),
                            ConversationParticipant.revoked_at.is_(None),
                            ConversationParticipant.hidden_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            notifications.append(
                (
                    participant_ids,
                    {
                        "type": "new_message",
                        "conversation_id": schedule.conversation_id,
                        "message": {
                            "id": message.id,
                            "conversation_id": message.conversation_id,
                            "sender_id": message.sender_id,
                            "content": message.content,
                            "created_at": message.created_at.isoformat(),
                        },
                    },
                )
            )
            await record_audit_event(
                db,
                actor=None,
                action="delivery_group_schedule.sent",
                target_type="delivery_group_schedule",
                target_id=schedule.id,
                workspace_id=schedule.workspace_id,
                metadata={
                    "agent_workspace_id": schedule.agent_workspace_id,
                    "conversation_id": schedule.conversation_id,
                    "message_id": message.id,
                },
            )
            sent += 1
        await db.commit()

    for participant_ids, event in notifications:
        try:
            await manager.broadcast_to_users(participant_ids, event)
        except Exception:  # noqa: BLE001 - persisted messages remain available on refresh.
            logger.exception("Delivery group schedule WebSocket broadcast failed")
    return sent
