from typing import Annotated, Literal

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from langgraph.types import interrupt

from src.agents.state import AgentState
from src.services import calendar_service, guardrail_service, reminder_service
from src.services.google_credentials import CalendarNotConnectedError


def _agent_identity(state: AgentState | None) -> tuple[str, str]:
    user_id = (state or {}).get("user_id")
    workspace_id = (state or {}).get("workspace_id")
    if not user_id or not workspace_id:
        raise ValueError("Authenticated user and workspace context are required")
    return user_id, workspace_id


@tool
async def create_calendar_event(
    summary: str,
    start_iso: str,
    end_iso: str,
    description: str = "",
    attendees: list[str] | None = None,
    state: Annotated[AgentState, InjectedState] = None,  # type: ignore[assignment]
) -> str:
    """Draft a Google Calendar event. Requires the user's explicit confirmation before it is
    actually created.

    Args:
        summary: Event title.
        start_iso: Event start time as an ISO 8601 datetime string.
        end_iso: Event end time as an ISO 8601 datetime string.
        description: Optional event details.
        attendees: Optional list of attendee email addresses.
    """
    policy = guardrail_service.evaluate_action_content(f"{summary}\n{description}")
    if not policy.allowed:
        return policy.response
    user_id, _workspace_id = _agent_identity(state)
    try:
        conflicts = await calendar_service.find_conflicts(user_id, start_iso, end_iso)
    except CalendarNotConnectedError:
        return "Connect Google Calendar from the Calendar page before creating an event."

    draft = {
        "summary": summary,
        "start": start_iso,
        "end": end_iso,
        "description": description,
        "attendees": attendees or [],
        "create_reminder": True,
        "reminder_lead_minutes": 30,
    }
    if conflicts:
        # Propose & Verify: surface what it clashes with plus up to 2 free alternatives in the
        # same confirmation step, instead of silently double-booking or blocking outright - the
        # user still decides (pick an alternative, keep the original time anyway, or cancel).
        draft["conflicts"] = [calendar_service.to_out_dict(e) for e in conflicts]
        draft["alternatives"] = await calendar_service.suggest_alternative_slots(user_id, start_iso, end_iso)

    decision = interrupt({"type": "calendar_event", "draft": draft})
    if not decision or not decision.get("approved"):
        return "Calendar event was not created (user declined)."

    draft.update(decision.get("edits") or {})
    policy = guardrail_service.evaluate_action_content(
        f"{draft.get('summary', '')}\n{draft.get('description', '')}"
    )
    if not policy.allowed:
        return policy.response
    try:
        created = await calendar_service.create_event(
            user_id,
            draft["summary"],
            draft["start"],
            draft["end"],
            draft["description"],
            draft["attendees"],
        )
    except CalendarNotConnectedError:
        return "Connect Google Calendar from the Calendar page before creating an event."
    await calendar_service.broadcast_change(
        user_id, "calendar_event_created", {"event": calendar_service.to_out_dict(created)}
    )
    reminder = None
    if draft.get("create_reminder", True):
        reminder = await reminder_service.reconcile_calendar_event_reminder(
            owner_id=user_id,
            calendar_event_id=str(created.get("id") or ""),
            title=str(created.get("summary") or draft["summary"]),
            start_at=(created.get("start") or {}).get("dateTime") or draft["start"],
            create_if_missing=True,
            lead_minutes=int(draft.get("reminder_lead_minutes", 30)),
            source="agent",
        )
    suffix = " Orbit reminder linked." if reminder is not None else ""
    return f"Event created: {created.get('htmlLink', created.get('id'))}.{suffix}".rstrip(".") + "."


@tool
async def list_calendar_events(
    scope: Literal["today", "this_week", "next_7_days", "next_30_days"] | None = None,
    time_min_iso: str | None = None,
    time_max_iso: str | None = None,
    max_results: int = 10,
    state: Annotated[AgentState, InjectedState] = None,  # type: ignore[assignment]
) -> str:
    """List existing calendar events in a time range. Read-only, no confirmation needed.

    Args:
        scope: A deterministic common relative range: today, this_week, next_7_days,
            or next_30_days. Prefer this over calculating ISO boundaries yourself.
        time_min_iso: Start of a specific range as an ISO 8601 datetime string.
        time_max_iso: End of a specific range as an ISO 8601 datetime string.
        max_results: Maximum number of events to return.
    """
    if scope:
        time_min_iso, time_max_iso = calendar_service.resolve_scope(scope)
    elif not time_min_iso or not time_max_iso:
        return "Cần cung cấp khoảng thời gian bằng scope hoặc đầy đủ time_min_iso và time_max_iso."

    user_id, _workspace_id = _agent_identity(state)
    try:
        items = await calendar_service.list_events(user_id, time_min_iso, time_max_iso, max_results)
    except CalendarNotConnectedError:
        return "Connect Google Calendar from the Calendar page before listing events."
    if not items:
        return "No events found in that range."
    return "\n".join(
        "- " + guardrail_service.sanitize_untrusted_text(str(e.get("summary") or ""))
        + f" (id={guardrail_service.sanitize_untrusted_text(str(e.get('id') or ''))}, "
        + f"{e['start'].get('dateTime', e['start'].get('date'))})" for e in items
    )


@tool
async def update_calendar_event(
    event_id: str,
    summary: str | None = None,
    start_iso: str | None = None,
    end_iso: str | None = None,
    description: str | None = None,
    state: Annotated[AgentState, InjectedState] = None,  # type: ignore[assignment]
) -> str:
    """Draft changes to an existing Google Calendar event (found via list_calendar_events).
    Requires the user's explicit confirmation before they take effect. Only pass the fields
    that should change; the rest stay as-is.

    Args:
        event_id: The id of the event to update, from list_calendar_events.
        summary: New title, if changing.
        start_iso: New start time as an ISO 8601 datetime string, if changing.
        end_iso: New end time as an ISO 8601 datetime string, if changing.
        description: New details, if changing.
    """
    draft = {"event_id": event_id, "summary": summary, "start": start_iso, "end": end_iso, "description": description}
    policy = guardrail_service.evaluate_action_content(f"{summary or ''}\n{description or ''}")
    if not policy.allowed:
        return policy.response
    decision = interrupt({"type": "calendar_event_update", "draft": draft})
    if not decision or not decision.get("approved"):
        return "Calendar event was not updated (user declined)."

    draft.update(decision.get("edits") or {})
    policy = guardrail_service.evaluate_action_content(
        f"{draft.get('summary') or ''}\n{draft.get('description') or ''}"
    )
    if not policy.allowed:
        return policy.response
    user_id, workspace_id = _agent_identity(state)
    try:
        updated = await calendar_service.update_event(
            user_id,
            draft["event_id"],
            draft["summary"],
            draft["start"],
            draft["end"],
            draft["description"],
        )
    except CalendarNotConnectedError:
        return "Connect Google Calendar from the Calendar page before updating an event."
    await calendar_service.broadcast_change(
        user_id, "calendar_event_updated", {"event": calendar_service.to_out_dict(updated)}
    )
    updated_out = calendar_service.to_out_dict(updated)
    await reminder_service.reconcile_calendar_event_reminder(
        owner_id=user_id,
        calendar_event_id=draft["event_id"],
        title=updated_out.get("title"),
        start_at=updated_out.get("start"),
    )
    return f"Event updated: {updated.get('htmlLink', updated.get('id'))}"


@tool
async def delete_calendar_event(
    event_id: str,
    state: Annotated[AgentState, InjectedState] = None,  # type: ignore[assignment]
) -> str:
    """Draft the deletion of an existing Google Calendar event (found via list_calendar_events).
    Requires the user's explicit confirmation before it is actually deleted.

    Args:
        event_id: The id of the event to delete, from list_calendar_events.
    """
    decision = interrupt({"type": "calendar_event_delete", "draft": {"event_id": event_id}})
    if not decision or not decision.get("approved"):
        return "Calendar event was not deleted (user declined)."

    user_id, workspace_id = _agent_identity(state)
    try:
        await calendar_service.delete_event(user_id, event_id)
    except CalendarNotConnectedError:
        return "Connect Google Calendar from the Calendar page before deleting an event."
    await calendar_service.broadcast_change(user_id, "calendar_event_deleted", {"event_id": event_id})
    await reminder_service.remove_calendar_event_reminder(user_id, event_id)
    return "Event deleted."
