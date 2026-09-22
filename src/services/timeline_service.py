from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Conversation, ConversationParticipant, Message, Reminder, Task, User
from src.models.schemas import MessageScope
from src.models.timeline_schemas import PersonalTimelineOut, TimelineItem, TimelineSourceStatus
from src.services import calendar_service, chat_service, consent_service, task_visibility_service
from src.services.google_credentials import CalendarNotConnectedError


def _as_utc(value: datetime, timezone: ZoneInfo) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone)
    return value.astimezone(UTC)


def _aware(value: datetime, timezone: ZoneInfo) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(timezone)


def _calendar_datetime(value: str | None, timezone: ZoneInfo) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _aware(parsed, timezone)


async def _message_items(
    db: AsyncSession,
    *,
    user: User,
    workspace_id: str,
    start: datetime,
    end: datetime,
    timezone: ZoneInfo,
    conversation_id: str | None,
    limit: int,
) -> list[TimelineItem]:
    conversation_stmt = (
        select(Conversation.id)
        .join(ConversationParticipant, ConversationParticipant.conversation_id == Conversation.id)
        .where(
            Conversation.workspace_id == workspace_id,
            ConversationParticipant.user_id == user.id,
            ConversationParticipant.revoked_at.is_(None),
        )
        .order_by(Conversation.updated_at.desc())
        .limit(20)
    )
    if conversation_id:
        conversation_stmt = conversation_stmt.where(Conversation.id == conversation_id)
    conversation_ids = list((await db.execute(conversation_stmt)).scalars())
    allowed_ids: list[str] = []
    scope = MessageScope(kind="custom_range", since=start, until=end)
    for current_id in conversation_ids:
        try:
            await chat_service.assert_ai_permission(db, current_id, user.id)
        except Exception:  # not enabled/granted for this conversation
            continue
        view = await consent_service.build_authorized_message_view(
            db, current_id, min(limit, 50), user_id=user.id, scope=scope
        )
        allowed_ids.extend(view.source_message_ids)
        if len(allowed_ids) >= limit:
            break
    if not allowed_ids:
        return []
    rows = (
        await db.execute(
            select(Message, User)
            .join(User, User.id == Message.sender_id)
            .where(Message.id.in_(allowed_ids[:limit]))
            .order_by(Message.created_at)
        )
    ).all()
    return [
        TimelineItem(
            id=f"message:{message.id}",
            kind="message",
            occurred_at=_aware(message.created_at, timezone),
            title=f"Tin nhắn từ {sender.display_name}",
            detail=message.content[:500],
            status="sent",
            source_id=message.id,
            conversation_id=message.conversation_id,
            source_message_ids=[message.id],
        )
        for message, sender in rows
    ]


async def get_personal_timeline(
    db: AsyncSession,
    *,
    user: User,
    workspace_id: str,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
    include_messages: bool = False,
    include_assigned_tasks: bool = False,
    include_overdue_tasks: bool = False,
    include_completed_tasks: bool = True,
    conversation_id: str | None = None,
    limit: int = 200,
) -> PersonalTimelineOut:
    try:
        timezone = ZoneInfo(user.timezone)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("Asia/Ho_Chi_Minh")
    now = datetime.now(timezone)
    local_start = _aware(from_at, timezone) if from_at else now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = _aware(to_at, timezone) if to_at else local_start + timedelta(days=7)
    if local_start >= local_end:
        raise ValueError("from_at must be before to_at")
    if local_end - local_start > timedelta(days=90):
        raise ValueError("timeline range cannot exceed 90 days")
    start_utc, end_utc = _as_utc(local_start, timezone), _as_utc(local_end, timezone)

    task_statement = (
        task_visibility_service.visible_assigned_tasks_statement(user.id)
        if include_assigned_tasks
        else select(Task).where(
            Task.owner_id == user.id,
            Task.workspace_id == workspace_id,
        )
    )
    task_statement = task_statement.where(
        Task.due_at.is_not(None),
        Task.due_at <= end_utc,
        Task.status.not_in({"dismissed", "invalidated"}),
    )
    if not include_overdue_tasks:
        task_statement = task_statement.where(Task.due_at >= start_utc)
    if not include_completed_tasks:
        task_statement = task_statement.where(Task.status != "completed")
    tasks = list(
        (
            await db.execute(
                task_statement.order_by(Task.due_at.asc(), Task.id.asc()).limit(limit)
            )
        ).scalars()
    )
    reminders = list(
        (
            await db.execute(
                select(Reminder).where(
                    Reminder.owner_id == user.id,
                    Reminder.workspace_id == workspace_id,
                    Reminder.fire_at >= start_utc,
                    Reminder.fire_at <= end_utc,
                    Reminder.status != "cancelled",
                )
            )
        ).scalars()
    )
    items = [
        TimelineItem(
            id=f"task:{task.id}",
            kind="task",
            occurred_at=_aware(task.due_at, timezone),
            title=task.title,
            status=task.status,
            source_id=task.id,
            conversation_id=task.conversation_id,
            source_message_ids=task.source_message_ids or [],
            detail=f"Ưu tiên {task.priority}",
            priority=task.priority,
            blocked_reason=task.blocked_reason,
            overdue=(
                _aware(task.due_at, timezone) < now
                and task.status not in {"completed", "dismissed", "invalidated"}
            ),
            scope="workspace" if task.agent_workspace_id else "personal",
            auto_reminder_enabled=task.auto_reminder_enabled,
        )
        for task in tasks
        if task.due_at is not None
    ]
    items.extend(
        TimelineItem(
            id=f"reminder:{reminder.id}",
            kind="reminder",
            occurred_at=_aware(reminder.fire_at, timezone),
            end_at=_aware(reminder.due_at, timezone),
            title=reminder.title,
            detail=reminder.message,
            status=reminder.status,
            source_id=reminder.id,
            linked_task_id=reminder.task_id,
            linked_calendar_event_id=reminder.calendar_event_id,
            reminder_lead_minutes=reminder.lead_minutes,
        )
        for reminder in reminders
    )
    sources = [
        TimelineSourceStatus(source="task", status="ok", item_count=len(tasks)),
        TimelineSourceStatus(source="reminder", status="ok", item_count=len(reminders)),
    ]

    if include_messages:
        try:
            messages = await _message_items(
                db,
                user=user,
                workspace_id=workspace_id,
                start=local_start,
                end=local_end,
                timezone=timezone,
                conversation_id=conversation_id,
                limit=min(limit, 100),
            )
            items.extend(messages)
            sources.append(TimelineSourceStatus(source="message", status="ok", item_count=len(messages)))
        except Exception:  # timeline remains useful when one source cannot be read
            sources.append(
                TimelineSourceStatus(source="message", status="unavailable", detail="Không thể tải nguồn chat")
            )

    try:
        calendar_events = await calendar_service.list_events(
            user.id, start_utc.isoformat(), end_utc.isoformat(), min(limit, 100)
        )
        calendar_count = 0
        for event in calendar_events:
            output = calendar_service.to_out_dict(event)
            start = _calendar_datetime(output["start"], timezone)
            if start is None:
                continue
            items.append(
                TimelineItem(
                    id=f"calendar:{output['id']}",
                    kind="calendar",
                    occurred_at=start,
                    end_at=_calendar_datetime(output["end"], timezone),
                    title=output["title"],
                    status=event.get("status", "confirmed"),
                    source_id=output["id"],
                    url=output["url"],
                )
            )
            calendar_count += 1
        sources.append(TimelineSourceStatus(source="calendar", status="ok", item_count=calendar_count))
    except CalendarNotConnectedError:
        sources.append(TimelineSourceStatus(source="calendar", status="not_connected"))
    except Exception:
        sources.append(
            TimelineSourceStatus(source="calendar", status="unavailable", detail="Google Calendar tạm lỗi")
        )

    items.sort(key=lambda item: (item.occurred_at, item.kind, item.id))
    return PersonalTimelineOut(
        workspace_id=workspace_id,
        timezone=timezone.key,
        from_at=local_start,
        to_at=local_end,
        items=items[:limit],
        sources=sources,
    )
