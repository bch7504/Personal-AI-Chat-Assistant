import logging
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.config import get_settings
from src.db import session as db_session
from src.db.models import Reminder, Task, User, Workspace
from src.services.scheduler import scheduler
from src.websocket.manager import manager

logger = logging.getLogger(__name__)

_REMINDER_ACTIVE_TASK_STATUSES = {"pending", "in_progress", "blocked", "changes_requested"}
_DEFAULT_TASK_REMINDER_LEAD_MINUTES = 30


def _as_aware(value: datetime, timezone_name: str) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=ZoneInfo(timezone_name))


def task_reminders_enabled(preferences: dict | None) -> bool:
    """Auto reminders are opt-in; old profiles must not suddenly receive notifications."""

    return (preferences or {}).get("auto_task_reminders") is True


def task_reminder_lead_minutes(preferences: dict | None) -> int:
    """Read the canonical integer preference while accepting the legacy UI string."""

    values = preferences or {}
    canonical = values.get("default_reminder_lead_minutes")
    if isinstance(canonical, int) and not isinstance(canonical, bool):
        return max(0, min(canonical, 10_080))

    legacy = values.get("default_reminder_lead")
    if isinstance(legacy, str):
        match = re.search(r"(\d+)", legacy)
        if match:
            amount = int(match.group(1))
            if "hour" in legacy.casefold():
                amount *= 60
            elif "day" in legacy.casefold():
                amount *= 1_440
            return max(0, min(amount, 10_080))
    return _DEFAULT_TASK_REMINDER_LEAD_MINUTES


def _reminder_payload(reminder: Reminder) -> dict:
    return {
        "id": reminder.id,
        "workspace_id": reminder.workspace_id,
        "task_id": reminder.task_id,
        "calendar_event_id": reminder.calendar_event_id,
        "title": reminder.title,
        "message": reminder.message,
        "due_at": reminder.due_at.isoformat(),
        "fire_at": reminder.fire_at.isoformat(),
        "lead_minutes": reminder.lead_minutes,
        "status": reminder.status,
        "source": reminder.source,
        "created_at": reminder.created_at.isoformat(),
        "updated_at": reminder.updated_at.isoformat(),
    }


def _install_scheduler_job(reminder: Reminder) -> None:
    scheduler.add_job(
        _fire_reminder_job,
        "date",
        run_date=reminder.fire_at,
        args=[reminder.id],
        id=reminder.id,
        replace_existing=True,
    )


async def schedule_reminder(
    *,
    workspace_id: str,
    owner_id: str,
    title: str,
    due_at_iso: str | datetime,
    lead_minutes: int = 30,
    message: str = "",
    source: str = "manual",
) -> Reminder:
    if not workspace_id or not owner_id:
        raise ValueError("Reminder workspace and owner are required")
    due_at = due_at_iso if isinstance(due_at_iso, datetime) else datetime.fromisoformat(due_at_iso)
    if due_at.tzinfo is None:
        # The agent/LLM sometimes emits a date/time with no UTC offset - treat it as Hanoi
        # time (not the server's local zone) rather than storing an ambiguous naive value.
        due_at = due_at.replace(tzinfo=ZoneInfo(get_settings().scheduler_timezone))
    fire_at = due_at - timedelta(minutes=lead_minutes)
    now = datetime.now(UTC)
    if due_at.astimezone(UTC) <= now:
        raise ValueError("Reminder due time must be in the future")
    if fire_at.astimezone(UTC) <= now:
        raise ValueError("Reminder notification time must be in the future")

    async with db_session.async_session_maker() as db:
        reminder = Reminder(
            workspace_id=workspace_id,
            owner_id=owner_id,
            title=title,
            message=message,
            due_at=due_at,
            fire_at=fire_at,
            lead_minutes=lead_minutes,
            source=source,
        )
        db.add(reminder)
        await db.commit()
        await db.refresh(reminder)

    scheduler.add_job(_fire_reminder_job, "date", run_date=fire_at, args=[reminder.id], id=reminder.id)
    return reminder


async def reconcile_task_reminder(task_id: str) -> Reminder | None:
    """Make one private auto reminder match the task's current, authorized lifecycle state."""

    job_to_remove: str | None = None
    event_type = "reminder_updated"
    reminder: Reminder | None = None
    owner_id: str | None = None

    async with db_session.async_session_maker() as db:
        task = await db.get(Task, task_id)
        existing = await db.scalar(select(Reminder).where(Reminder.task_id == task_id))
        if task is None:
            if existing is not None:
                job_to_remove = existing.id
                owner_id = existing.owner_id
                await db.delete(existing)
                await db.commit()
            if job_to_remove:
                remove_scheduler_job(job_to_remove)
                if owner_id:
                    await manager.broadcast_to_users(
                        [owner_id],
                        {"type": "reminder_deleted", "reminder_id": job_to_remove},
                    )
            return None

        if existing is not None and existing.owner_id != task.owner_id:
            # A reminder is private state. Reassignment must remove it from the former owner's
            # Personal Space instead of moving that private row across owners.
            former_owner_id = existing.owner_id
            former_reminder_id = existing.id
            await db.delete(existing)
            await db.commit()
            remove_scheduler_job(former_reminder_id)
            await manager.broadcast_to_users(
                [former_owner_id],
                {"type": "reminder_deleted", "reminder_id": former_reminder_id},
            )
            existing = None

        owner = await db.get(User, task.owner_id)
        owner_id = task.owner_id
        timezone_name = owner.timezone if owner and owner.timezone else get_settings().scheduler_timezone
        due_at = _as_aware(task.due_at, timezone_name) if task.due_at is not None else None
        eligible = (
            owner is not None
            and owner.is_active
            and task_reminders_enabled(owner.preferences)
            and task.auto_reminder_enabled
            and task.status in _REMINDER_ACTIVE_TASK_STATUSES
            and due_at is not None
            and due_at.astimezone(UTC) > datetime.now(UTC)
        )

        if not eligible:
            if existing is not None and existing.status != "cancelled":
                existing.status = "cancelled"
                await db.commit()
                await db.refresh(existing)
                reminder = existing
                job_to_remove = existing.id
            elif existing is not None:
                job_to_remove = existing.id
            if job_to_remove:
                remove_scheduler_job(job_to_remove)
            if reminder is not None:
                await manager.broadcast_to_users(
                    [task.owner_id],
                    {"type": "reminder_updated", "reminder": _reminder_payload(reminder)},
                )
            return reminder

        personal_workspace_id = await db.scalar(
            select(Workspace.id).where(
                Workspace.type == "personal",
                Workspace.personal_owner_user_id == task.owner_id,
                Workspace.status == "active",
            )
        )
        if personal_workspace_id is None:
            logger.warning("Cannot create task reminder without Personal Space: task=%s", task_id)
            return None

        lead_minutes = task_reminder_lead_minutes(owner.preferences)
        now = datetime.now(UTC)
        fire_at = due_at - timedelta(minutes=lead_minutes)
        if fire_at.astimezone(UTC) <= now:
            # The task was accepted/edited inside its normal lead window. Notify promptly instead
            # of rejecting the reminder or silently missing it.
            fire_at = min(due_at, now + timedelta(seconds=1))

        if existing is None:
            event_type = "reminder_created"
            reminder = Reminder(
                workspace_id=personal_workspace_id,
                owner_id=task.owner_id,
                task_id=task.id,
                title=task.title,
                message=f"Task deadline - {lead_minutes} minutes notice",
                due_at=due_at,
                fire_at=fire_at,
                lead_minutes=lead_minutes,
                status="scheduled",
                source="proactive",
            )
            db.add(reminder)
        else:
            reminder = existing
            reminder.workspace_id = personal_workspace_id
            reminder.owner_id = task.owner_id
            reminder.title = task.title
            reminder.message = f"Task deadline - {lead_minutes} minutes notice"
            reminder.due_at = due_at
            reminder.fire_at = fire_at
            reminder.lead_minutes = lead_minutes
            reminder.status = "scheduled"
            reminder.source = "proactive"
        await db.commit()
        await db.refresh(reminder)

    _install_scheduler_job(reminder)
    await manager.broadcast_to_users(
        [owner_id],
        {"type": event_type, "reminder": _reminder_payload(reminder)},
    )
    return reminder


async def reconcile_calendar_event_reminder(
    *,
    owner_id: str,
    calendar_event_id: str,
    title: str | None = None,
    start_at: str | datetime | None = None,
    enabled: bool = True,
    create_if_missing: bool = False,
    lead_minutes: int | None = None,
    source: str = "agent",
) -> Reminder | None:
    """Create or synchronize one private Orbit reminder for a Google Calendar event.

    Calendar remains the source of truth for the event time/title. A linked reminder may be
    created only during an explicit confirmation (`create_if_missing=True`); later Calendar
    updates merely reconcile an existing row and never opt the user in silently.
    """

    if not owner_id or not calendar_event_id:
        raise ValueError("Calendar reminder owner and event id are required")
    if lead_minutes is not None and not 0 <= lead_minutes <= 10_080:
        raise ValueError("Reminder lead time must be between 0 and 10080 minutes")

    deleted: tuple[str, str] | None = None
    event_type = "reminder_updated"
    reminder: Reminder | None = None
    async with db_session.async_session_maker() as db:
        existing = await db.scalar(
            select(Reminder).where(
                Reminder.owner_id == owner_id,
                Reminder.calendar_event_id == calendar_event_id,
            )
        )
        if not enabled:
            if existing is not None:
                deleted = (existing.id, existing.owner_id)
                await db.delete(existing)
                await db.commit()
        else:
            if existing is None and not create_if_missing:
                return None

            owner = await db.get(User, owner_id)
            if owner is None or not owner.is_active:
                return None
            timezone_name = owner.timezone or get_settings().scheduler_timezone
            due_at: datetime | None
            if start_at is None:
                due_at = _as_aware(existing.due_at, timezone_name) if existing is not None else None
            else:
                parsed = start_at if isinstance(start_at, datetime) else datetime.fromisoformat(start_at)
                due_at = _as_aware(parsed, timezone_name)
            if due_at is None or due_at.astimezone(UTC) <= datetime.now(UTC):
                if existing is not None:
                    deleted = (existing.id, existing.owner_id)
                    await db.delete(existing)
                    await db.commit()
            else:
                personal_workspace_id = await db.scalar(
                    select(Workspace.id).where(
                        Workspace.type == "personal",
                        Workspace.personal_owner_user_id == owner_id,
                        Workspace.status == "active",
                    )
                )
                if personal_workspace_id is None:
                    logger.warning(
                        "Cannot create event reminder without Personal Space: owner=%s event=%s",
                        owner_id,
                        calendar_event_id,
                    )
                    return None

                effective_lead = (
                    lead_minutes
                    if lead_minutes is not None
                    else existing.lead_minutes if existing is not None else _DEFAULT_TASK_REMINDER_LEAD_MINUTES
                )
                now = datetime.now(UTC)
                fire_at = due_at - timedelta(minutes=effective_lead)
                if fire_at.astimezone(UTC) <= now:
                    fire_at = min(due_at, now + timedelta(seconds=1))

                if existing is None:
                    event_type = "reminder_created"
                    reminder = Reminder(
                        workspace_id=personal_workspace_id,
                        owner_id=owner_id,
                        calendar_event_id=calendar_event_id,
                        title=(title or "Calendar event").strip(),
                        message=f"Calendar event - {effective_lead} minutes notice",
                        due_at=due_at,
                        fire_at=fire_at,
                        lead_minutes=effective_lead,
                        status="scheduled",
                        source=source,
                    )
                    db.add(reminder)
                else:
                    reminder = existing
                    reminder.workspace_id = personal_workspace_id
                    if title and title.strip():
                        reminder.title = title.strip()
                    reminder.message = f"Calendar event - {effective_lead} minutes notice"
                    reminder.due_at = due_at
                    reminder.fire_at = fire_at
                    reminder.lead_minutes = effective_lead
                    reminder.status = "scheduled"
                await db.commit()
                await db.refresh(reminder)

    if deleted is not None:
        reminder_id, reminder_owner_id = deleted
        remove_scheduler_job(reminder_id)
        await manager.broadcast_to_users(
            [reminder_owner_id],
            {"type": "reminder_deleted", "reminder_id": reminder_id},
        )
        return None
    if reminder is None:
        return None
    _install_scheduler_job(reminder)
    await manager.broadcast_to_users(
        [owner_id],
        {"type": event_type, "reminder": _reminder_payload(reminder)},
    )
    return reminder


async def remove_calendar_event_reminder(owner_id: str, calendar_event_id: str) -> None:
    await reconcile_calendar_event_reminder(
        owner_id=owner_id,
        calendar_event_id=calendar_event_id,
        enabled=False,
    )


async def remove_all_calendar_event_reminders(owner_id: str) -> int:
    """Remove linked reminders when a user disconnects their Google Calendar."""

    async with db_session.async_session_maker() as db:
        reminders = list(
            (
                await db.execute(
                    select(Reminder).where(
                        Reminder.owner_id == owner_id,
                        Reminder.calendar_event_id.is_not(None),
                    )
                )
            ).scalars()
        )
        removed = [(reminder.id, reminder.owner_id) for reminder in reminders]
        for reminder in reminders:
            await db.delete(reminder)
        if reminders:
            await db.commit()
    for reminder_id, reminder_owner_id in removed:
        remove_scheduler_job(reminder_id)
        await manager.broadcast_to_users(
            [reminder_owner_id],
            {"type": "reminder_deleted", "reminder_id": reminder_id},
        )
    return len(removed)


async def reconcile_user_task_reminders(user_id: str) -> int:
    """Apply a changed global preference to all tasks owned by one user."""

    async with db_session.async_session_maker() as db:
        task_ids = list((await db.execute(select(Task.id).where(Task.owner_id == user_id))).scalars())
    for task_id in task_ids:
        await reconcile_task_reminder(task_id)
    return len(task_ids)


async def reconcile_active_task_reminders(batch_size: int = 500) -> int:
    """Periodically repair task/reminder drift caused by imports or out-of-band writes."""

    safe_batch_size = max(1, min(batch_size, 2_000))
    processed: set[str] = set()
    last_task_id = ""
    while True:
        async with db_session.async_session_maker() as db:
            active_ids = list(
                (
                    await db.execute(
                        select(Task.id)
                        .where(
                            Task.id > last_task_id,
                            Task.due_at.is_not(None),
                            Task.status.in_(_REMINDER_ACTIVE_TASK_STATUSES),
                        )
                        .order_by(Task.id)
                        .limit(safe_batch_size)
                    )
                ).scalars()
            )
        if not active_ids:
            break
        for task_id in active_ids:
            await reconcile_task_reminder(task_id)
            processed.add(task_id)
        last_task_id = active_ids[-1]

    # Include linked reminders for completed/ineligible tasks so the sweep also cancels stale jobs.
    async with db_session.async_session_maker() as db:
        linked_ids = list(
            (await db.execute(select(Reminder.task_id).where(Reminder.task_id.is_not(None)))).scalars()
        )
    for task_id in linked_ids:
        if task_id and task_id not in processed:
            await reconcile_task_reminder(task_id)
            processed.add(task_id)
    return len(processed)


async def remove_task_reminder(task_id: str) -> None:
    """Remove the durable scheduler job before its task row is deleted."""

    async with db_session.async_session_maker() as db:
        reminder = await db.scalar(select(Reminder).where(Reminder.task_id == task_id))
        if reminder is None:
            return
        reminder_id = reminder.id
        owner_id = reminder.owner_id
        await db.delete(reminder)
        await db.commit()
    remove_scheduler_job(reminder_id)
    await manager.broadcast_to_users(
        [owner_id],
        {"type": "reminder_deleted", "reminder_id": reminder_id},
    )


async def _fire_reminder_job(reminder_id: str) -> None:
    """APScheduler job callback executed when a reminder's lead time elapses."""
    async with db_session.async_session_maker() as db:
        reminder = await db.get(Reminder, reminder_id)
        if reminder is None or reminder.status != "scheduled":
            return
        if reminder.task_id is not None:
            task = await db.get(Task, reminder.task_id)
            owner = await db.get(User, reminder.owner_id)
            timezone_name = owner.timezone if owner and owner.timezone else get_settings().scheduler_timezone
            task_due_at = (
                _as_aware(task.due_at, timezone_name)
                if task is not None and task.due_at is not None
                else None
            )
            lifecycle_valid = (
                task is not None
                and owner is not None
                and owner.is_active
                and task.owner_id == reminder.owner_id
                and task_reminders_enabled(owner.preferences)
                and task.auto_reminder_enabled
                and task.status in _REMINDER_ACTIVE_TASK_STATUSES
                and task_due_at is not None
            )
            deadline_changed = lifecycle_valid and task_due_at.astimezone(UTC) != _as_aware(
                reminder.due_at, timezone_name
            ).astimezone(UTC)
            if not lifecycle_valid or deadline_changed:
                reminder.status = "cancelled"
                await db.commit()
                if deadline_changed and task is not None:
                    await reconcile_task_reminder(task.id)
                return
        reminder.status = "fired"
        await db.commit()
        owner_id, workspace_id, title, message = (
            reminder.owner_id,
            reminder.workspace_id,
            reminder.title,
            reminder.message,
        )
        task_id = reminder.task_id
        calendar_event_id = reminder.calendar_event_id

    logger.info("Reminder fired: %s (%s)", title, reminder_id)
    if owner_id:
        fired_reminder = {
            "id": reminder_id,
            "workspace_id": workspace_id,
            "title": title,
            "message": message,
        }
        if task_id is not None:
            fired_reminder["task_id"] = task_id
        if calendar_event_id is not None:
            fired_reminder["calendar_event_id"] = calendar_event_id
        await manager.broadcast_to_users(
            [owner_id],
            {
                "type": "reminder_fired",
                "workspace_id": workspace_id,
                "reminder": fired_reminder,
            },
        )


async def list_reminders(
    owner_id: str,
    workspace_id: str,
    limit: int = 200,
    offset: int = 0,
) -> list[Reminder]:
    async with db_session.async_session_maker() as db:
        result = await db.execute(
            select(Reminder)
            .where(Reminder.owner_id == owner_id, Reminder.workspace_id == workspace_id)
            .order_by(Reminder.fire_at)
            .offset(max(0, offset))
            .limit(max(1, min(limit, 500)))
        )
        return list(result.scalars().all())


def remove_scheduler_job(reminder_id: str) -> None:
    try:
        scheduler.remove_job(reminder_id)
    except Exception:  # noqa: BLE001 - job may already have fired/been removed
        pass


async def cancel_reminder(reminder_id: str, owner_id: str, workspace_id: str) -> bool:
    async with db_session.async_session_maker() as db:
        reminder = (
            await db.execute(
                select(Reminder).where(
                    Reminder.id == reminder_id,
                    Reminder.owner_id == owner_id,
                    Reminder.workspace_id == workspace_id,
                )
            )
        ).scalar_one_or_none()
        if reminder is None:
            return False
        if reminder.task_id is not None:
            raise ValueError("Task reminders are managed from the task's reminder settings")
        if reminder.calendar_event_id is not None:
            raise ValueError("Calendar reminders are managed from the linked event")
        if reminder.status == "scheduled":
            remove_scheduler_job(reminder_id)
        reminder.status = "cancelled"
        await db.commit()
        await db.refresh(reminder)
        payload = _reminder_payload(reminder)
    await manager.broadcast_to_users(
        [owner_id], {"type": "reminder_updated", "reminder": payload}
    )
    return True


async def update_reminder(
    reminder_id: str,
    *,
    owner_id: str,
    workspace_id: str,
    title: str | None = None,
    due_at_iso: str | datetime | None = None,
    lead_minutes: int | None = None,
    message: str | None = None,
) -> Reminder | None:
    """Update an independent reminder and atomically reschedule its durable job."""

    if all(value is None for value in (title, due_at_iso, lead_minutes, message)):
        raise ValueError("At least one reminder field must be updated")
    if title is not None and not title.strip():
        raise ValueError("Reminder title cannot be empty")
    if lead_minutes is not None and not 0 <= lead_minutes <= 10_080:
        raise ValueError("Reminder lead time must be between 0 and 10080 minutes")

    async with db_session.async_session_maker() as db:
        reminder = await db.scalar(
            select(Reminder).where(
                Reminder.id == reminder_id,
                Reminder.owner_id == owner_id,
                Reminder.workspace_id == workspace_id,
            )
        )
        if reminder is None:
            return None
        if reminder.task_id is not None:
            raise ValueError("Task reminders are managed from the task's reminder settings")
        if reminder.calendar_event_id is not None:
            raise ValueError("Calendar reminders are managed from the linked event")

        timezone_name = get_settings().scheduler_timezone
        due_at = reminder.due_at
        if due_at_iso is not None:
            due_at = due_at_iso if isinstance(due_at_iso, datetime) else datetime.fromisoformat(due_at_iso)
        due_at = _as_aware(due_at, timezone_name)

        effective_lead = lead_minutes if lead_minutes is not None else reminder.lead_minutes
        fire_at = due_at - timedelta(minutes=effective_lead)
        now = datetime.now(UTC)
        if due_at.astimezone(UTC) <= now:
            raise ValueError("Reminder due time must be in the future")
        if fire_at.astimezone(UTC) <= now:
            raise ValueError("Reminder notification time must be in the future")

        if title is not None:
            reminder.title = title.strip()
        if message is not None:
            reminder.message = message
        reminder.due_at = due_at
        reminder.fire_at = fire_at
        reminder.lead_minutes = effective_lead
        reminder.status = "scheduled"
        await db.commit()
        await db.refresh(reminder)
        payload = _reminder_payload(reminder)

    _install_scheduler_job(reminder)
    await manager.broadcast_to_users(
        [owner_id], {"type": "reminder_updated", "reminder": payload}
    )
    return reminder


async def snooze_reminder(
    reminder_id: str,
    *,
    owner_id: str,
    workspace_id: str,
    minutes: int,
) -> Reminder | None:
    """Delay the next notification without changing what the reminder is due for."""

    if not 1 <= minutes <= 10_080:
        raise ValueError("Snooze duration must be between 1 and 10080 minutes")
    async with db_session.async_session_maker() as db:
        reminder = await db.scalar(
            select(Reminder).where(
                Reminder.id == reminder_id,
                Reminder.owner_id == owner_id,
                Reminder.workspace_id == workspace_id,
            )
        )
        if reminder is None:
            return None
        if reminder.task_id is not None:
            raise ValueError("Task reminders are managed from the task's reminder settings")
        reminder.fire_at = datetime.now(UTC) + timedelta(minutes=minutes)
        reminder.status = "scheduled"
        await db.commit()
        await db.refresh(reminder)
        payload = _reminder_payload(reminder)

    _install_scheduler_job(reminder)
    await manager.broadcast_to_users(
        [owner_id], {"type": "reminder_updated", "reminder": payload}
    )
    return reminder
