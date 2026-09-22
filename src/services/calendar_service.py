import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from starlette.concurrency import run_in_threadpool

from src.config import get_settings
from src.services import google_credentials, reminder_service
from src.websocket.manager import manager

logger = logging.getLogger(__name__)
_PRIMARY = "primary"

# Fixed heuristic for suggest_alternative_slots (v1, not user-configurable): only offer
# alternatives inside a plain working-hours window, searched a few days ahead. Revisit as a
# per-user setting if this turns out to matter in practice.
_WORK_DAY_START_HOUR = 8
_WORK_DAY_END_HOUR = 20
_SEARCH_DAYS_AHEAD = 3

# Common relative ranges the agent's list_calendar_events tool resolves deterministically here
# instead of leaving the LLM to freehand-compute time_min_iso/time_max_iso for phrases like "hôm
# nay"/"tuần này" - the LLM reliably got "this week" wrong (picking "now" as the start instead of
# the start of the week, silently excluding earlier-this-week events already past). Same reasoning/
# pattern as chat_service.py's deterministic MessageScope resolution ("today"/"this_week"/...).
SCOPE_CHOICES = ("today", "this_week", "next_7_days", "next_30_days")


def _local_now() -> datetime:
    return datetime.now(ZoneInfo(get_settings().calendar_timezone))


def resolve_scope(scope: str) -> tuple[str, str]:
    """Deterministic (time_min_iso, time_max_iso) for one of SCOPE_CHOICES. "today"/"this_week"
    cover the whole local day/week (Monday 00:00 through the following Monday 00:00) - including
    the part already past - since "tuần này" means the whole current week, not just what's left of
    it. "next_7_days"/"next_30_days" are forward-looking from right now, matching their name."""
    now = _local_now()
    if scope == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif scope == "this_week":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
    elif scope == "next_7_days":
        start, end = now, now + timedelta(days=7)
    elif scope == "next_30_days":
        start, end = now, now + timedelta(days=30)
    else:
        raise ValueError(f"Unknown calendar scope: {scope!r} (expected one of {SCOPE_CHOICES})")
    return start.isoformat(), end.isoformat()


def get_calendar_service():
    """Legacy test seam retained while runtime credentials are now resolved per user."""
    raise RuntimeError("A user-specific Google Calendar service is required")


_DEFAULT_SERVICE_FACTORY = get_calendar_service


async def _service(user_id: str) -> Resource:
    if get_calendar_service is not _DEFAULT_SERVICE_FACTORY:
        return get_calendar_service()
    credentials = await google_credentials.get_credentials(user_id)
    return await run_in_threadpool(build, "calendar", "v3", credentials=credentials)


async def authorize_calendar_access(user_id: str, workspace_id: str | None = None) -> tuple[str, list[str]]:
    """Compatibility seam; access is now established by the user's encrypted OAuth credential."""
    await google_credentials.get_credentials(user_id)
    return workspace_id or "", [user_id]


async def list_events(user_id: str, time_min_iso: str, time_max_iso: str, max_results: int = 50) -> list[dict]:
    service = await _service(user_id)

    def call():
        return (
            service.events()
            .list(
                calendarId=_PRIMARY,
                timeMin=time_min_iso,
                timeMax=time_max_iso,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

    return (await run_in_threadpool(call)).get("items", [])


async def find_conflicts(user_id: str, start_iso: str, end_iso: str) -> list[dict]:
    """Existing events overlapping [start_iso, end_iso). Google Calendar's timeMin/timeMax
    semantics (an event qualifies when its end is after timeMin AND its start is before timeMax)
    already express exactly the overlap test we need - no extra interval math required here."""
    return await list_events(user_id, start_iso, end_iso)


def _merge_busy_intervals(events: list[dict]) -> list[tuple[datetime, datetime]]:
    """Sorted, merged busy intervals from timed events (all-day events, which only have a "date"
    field and no precise time, are skipped here - known v1 limitation, not a bug: they still show
    up as a conflict via find_conflicts, they just aren't accounted for when picking free gaps)."""
    intervals = sorted(
        (
            (datetime.fromisoformat(e["start"]["dateTime"]).replace(tzinfo=None),
             datetime.fromisoformat(e["end"]["dateTime"]).replace(tzinfo=None))
            for e in events
            if "dateTime" in e.get("start", {}) and "dateTime" in e.get("end", {})
        ),
        key=lambda iv: iv[0],
    )
    merged: list[tuple[datetime, datetime]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


async def suggest_alternative_slots(
    user_id: str, start_iso: str, end_iso: str, count: int = 2
) -> list[dict]:
    """Best-effort free-slot search: up to `count` gaps of the same duration as
    [start_iso, end_iso), at/after the requested start time, inside working hours
    (_WORK_DAY_START_HOUR-_WORK_DAY_END_HOUR local) over the next _SEARCH_DAYS_AHEAD days.
    Pure interval scan, no LLM call - this is the tool "self-checking" its own proposal, not the
    agent reasoning about it. Returns fewer than `count` (possibly none) if the window is full;
    never raises for that."""
    start = datetime.fromisoformat(start_iso).replace(tzinfo=None)
    end = datetime.fromisoformat(end_iso).replace(tzinfo=None)
    duration = end - start

    window_start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    window_end = window_start + timedelta(days=_SEARCH_DAYS_AHEAD)
    busy_items = await list_events(
        user_id, window_start.isoformat(), window_end.isoformat(), max_results=100
    )
    busy = _merge_busy_intervals(busy_items)

    candidates: list[dict] = []
    day = window_start
    while len(candidates) < count and day < window_end:
        day_open = day.replace(hour=_WORK_DAY_START_HOUR, minute=0)
        day_close = day.replace(hour=_WORK_DAY_END_HOUR, minute=0)
        cursor = max(day_open, start) if day.date() == start.date() else day_open

        for busy_start, busy_end in busy:
            if not (busy_start.date() <= day.date() <= busy_end.date()):
                continue
            if cursor + duration <= busy_start:
                candidates.append({"start": cursor.isoformat(), "end": (cursor + duration).isoformat()})
                if len(candidates) >= count:
                    break
            cursor = max(cursor, busy_end)

        if len(candidates) < count and cursor + duration <= day_close:
            candidates.append({"start": cursor.isoformat(), "end": (cursor + duration).isoformat()})

        day += timedelta(days=1)

    return candidates[:count]


async def create_event(
    user_id: str,
    summary: str,
    start_iso: str,
    end_iso: str,
    description: str = "",
    attendees: list[str] | None = None,
    timezone: str | None = None,
) -> dict:
    service = await _service(user_id)
    tz = timezone or get_settings().calendar_timezone
    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_iso, "timeZone": tz},
        "end": {"dateTime": end_iso, "timeZone": tz},
        "attendees": [{"email": value} for value in (attendees or [])],
    }
    return await run_in_threadpool(lambda: service.events().insert(calendarId=_PRIMARY, body=body).execute())


async def update_event(
    user_id: str,
    event_id: str,
    summary: str | None = None,
    start_iso: str | None = None,
    end_iso: str | None = None,
    description: str | None = None,
    timezone: str | None = None,
) -> dict:
    service = await _service(user_id)
    tz = timezone or get_settings().calendar_timezone
    body: dict = {}
    if summary is not None:
        body["summary"] = summary
    if description is not None:
        body["description"] = description
    if start_iso is not None:
        body["start"] = {"dateTime": start_iso, "timeZone": tz}
    if end_iso is not None:
        body["end"] = {"dateTime": end_iso, "timeZone": tz}
    return await run_in_threadpool(
        lambda: service.events().patch(calendarId=_PRIMARY, eventId=event_id, body=body).execute()
    )


async def delete_event(user_id: str, event_id: str) -> None:
    service = await _service(user_id)
    await run_in_threadpool(lambda: service.events().delete(calendarId=_PRIMARY, eventId=event_id).execute())


async def broadcast_change(user_id: str, event_type: str, payload: dict) -> None:
    await manager.broadcast_to_users([user_id], {"type": event_type, **payload})


def to_out_dict(event: dict) -> dict:
    start = event.get("start", {})
    end = event.get("end", {})
    return {
        "id": event["id"],
        "title": event.get("summary", "(No title)"),
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "url": event.get("htmlLink"),
    }


async def _fetch_changes(user_id: str, sync_token: str | None) -> tuple[list[dict], str | None]:
    service = await _service(user_id)
    kwargs: dict = {"calendarId": _PRIMARY, "singleEvents": True}
    if sync_token:
        kwargs["syncToken"] = sync_token
    else:
        kwargs["timeMin"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    items: list[dict] = []
    page_token = None
    next_sync_token = None
    while True:
        response = await run_in_threadpool(lambda: service.events().list(**kwargs, pageToken=page_token).execute())
        items.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            next_sync_token = response.get("nextSyncToken")
            break
    return items, next_sync_token


async def _poll_one_user(user_id: str) -> None:
    sync_token = await google_credentials.get_sync_token(user_id)
    try:
        items, next_sync_token = await _fetch_changes(user_id, sync_token)
    except google_credentials.CalendarNotConnectedError:
        return
    except HttpError as exc:
        if sync_token and exc.resp.status == 410:
            try:
                items, next_sync_token = await _fetch_changes(user_id, None)
            except Exception:  # noqa: BLE001 - one poll must not stop the scheduler
                logger.exception("Calendar full resync failed for user %s", user_id)
                return
        else:
            logger.exception("Calendar poll failed for user %s", user_id)
            return
    except Exception:  # noqa: BLE001 - one poll must not stop the scheduler
        logger.exception("Calendar poll failed for user %s", user_id)
        return

    for event in items:
        if event.get("status") == "cancelled":
            await reminder_service.remove_calendar_event_reminder(user_id, event["id"])
            await broadcast_change(user_id, "calendar_event_deleted", {"event_id": event["id"]})
        else:
            event_out = to_out_dict(event)
            await reminder_service.reconcile_calendar_event_reminder(
                owner_id=user_id,
                calendar_event_id=event_out["id"],
                title=event_out["title"],
                start_at=event_out["start"],
            )
            await broadcast_change(user_id, "calendar_event_updated", {"event": to_out_dict(event)})
    await google_credentials.set_sync_token(user_id, next_sync_token)


async def poll_calendar_changes() -> None:
    connected = set(await google_credentials.list_connected_user_ids())
    for user_id in [value for value in list(manager.active) if value in connected]:
        try:
            await _poll_one_user(user_id)
        except Exception:  # noqa: BLE001 - isolate users within a polling tick
            logger.exception("Calendar poll failed for user %s", user_id)
