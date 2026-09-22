from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from langgraph.types import interrupt

from src.agents.state import AgentState
from src.services import guardrail_service, reminder_service


def _agent_identity(state: AgentState | None) -> tuple[str, str]:
    user_id = (state or {}).get("user_id")
    workspace_id = (state or {}).get("workspace_id")
    if not user_id or not workspace_id:
        raise ValueError("Authenticated user and workspace context are required")
    return user_id, workspace_id


@tool
async def create_reminder(
    title: str,
    due_at_iso: str,
    lead_minutes: int = 30,
    message: str = "",
    state: Annotated[AgentState, InjectedState] = None,  # type: ignore[assignment]
) -> str:
    """Draft a reminder that fires lead_minutes before due_at_iso. Requires the user's
    explicit confirmation before it is actually scheduled.

    Args:
        title: Short title of the reminder.
        due_at_iso: When the reminded-about thing is due, as an ISO 8601 datetime string.
        lead_minutes: How many minutes before due_at_iso to fire the reminder.
        message: Optional extra detail to show alongside the reminder.
    """
    draft = {"title": title, "due_at": due_at_iso, "lead_minutes": lead_minutes, "message": message}
    policy = guardrail_service.evaluate_action_content(f"{title}\n{message}")
    if not policy.allowed:
        return policy.response
    decision = interrupt({"type": "reminder", "draft": draft})
    if not decision or not decision.get("approved"):
        return "Reminder was not scheduled (user declined)."

    draft.update(decision.get("edits") or {})
    policy = guardrail_service.evaluate_action_content(
        f"{draft.get('title', '')}\n{draft.get('message', '')}"
    )
    if not policy.allowed:
        return policy.response
    user_id, workspace_id = _agent_identity(state)
    reminder = await reminder_service.schedule_reminder(
        workspace_id=workspace_id,
        owner_id=user_id,
        title=draft["title"],
        due_at_iso=draft["due_at"],
        lead_minutes=draft["lead_minutes"],
        message=draft["message"],
        source="agent",
    )
    safe_title = guardrail_service.sanitize_untrusted_text(draft["title"])
    return f"Reminder '{safe_title}' scheduled to fire at {reminder.fire_at.isoformat()}."


@tool
async def list_reminders(
    state: Annotated[AgentState, InjectedState] = None,  # type: ignore[assignment]
) -> str:
    """List currently scheduled reminders. Read-only, no confirmation needed."""
    user_id, workspace_id = _agent_identity(state)
    reminders = await reminder_service.list_reminders(owner_id=user_id, workspace_id=workspace_id)
    if not reminders:
        return "No reminders scheduled."
    return "\n".join(
        f"- id={r.id}: {guardrail_service.sanitize_untrusted_text(r.title)} "
        f"({guardrail_service.sanitize_untrusted_text(r.status)}, due {r.due_at.isoformat()})"
        for r in reminders
    )


@tool
async def update_reminder(
    reminder_id: str,
    title: str | None = None,
    due_at_iso: str | None = None,
    lead_minutes: int | None = None,
    message: str | None = None,
    state: Annotated[AgentState, InjectedState] = None,  # type: ignore[assignment]
) -> str:
    """Update an independent reminder by id. Call list_reminders first if the id is unknown.
    Requires explicit user confirmation."""

    draft = {
        "reminder_id": reminder_id,
        "title": title,
        "due_at": due_at_iso,
        "lead_minutes": lead_minutes,
        "message": message,
    }
    policy = guardrail_service.evaluate_action_content(f"{title or ''}\n{message or ''}")
    if not policy.allowed:
        return policy.response
    decision = interrupt({"type": "reminder_update", "draft": draft})
    if not decision or not decision.get("approved"):
        return "Reminder was not updated (user declined)."
    draft.update(decision.get("edits") or {})
    user_id, workspace_id = _agent_identity(state)
    try:
        reminder = await reminder_service.update_reminder(
            draft["reminder_id"],
            owner_id=user_id,
            workspace_id=workspace_id,
            title=draft.get("title"),
            due_at_iso=draft.get("due_at"),
            lead_minutes=draft.get("lead_minutes"),
            message=draft.get("message"),
        )
    except ValueError as exc:
        return str(exc)
    if reminder is None:
        return "Reminder not found."
    safe_title = guardrail_service.sanitize_untrusted_text(reminder.title)
    return f"Reminder '{safe_title}' updated; it will fire at {reminder.fire_at.isoformat()}."


@tool
async def cancel_reminder(
    reminder_id: str,
    state: Annotated[AgentState, InjectedState] = None,  # type: ignore[assignment]
) -> str:
    """Cancel an independent reminder by id. Call list_reminders first if its id is unknown.
    Requires explicit user confirmation."""

    decision = interrupt({"type": "reminder_cancel", "draft": {"reminder_id": reminder_id}})
    if not decision or not decision.get("approved"):
        return "Reminder was not cancelled (user declined)."
    user_id, workspace_id = _agent_identity(state)
    try:
        cancelled = await reminder_service.cancel_reminder(
            reminder_id, owner_id=user_id, workspace_id=workspace_id
        )
    except ValueError as exc:
        return str(exc)
    return "Reminder cancelled." if cancelled else "Reminder not found."


@tool
async def snooze_reminder(
    reminder_id: str,
    minutes: int,
    state: Annotated[AgentState, InjectedState] = None,  # type: ignore[assignment]
) -> str:
    """Snooze an independent reminder by id for 1 to 10080 minutes. Requires explicit user
    confirmation."""

    decision = interrupt(
        {"type": "reminder_snooze", "draft": {"reminder_id": reminder_id, "minutes": minutes}}
    )
    if not decision or not decision.get("approved"):
        return "Reminder was not snoozed (user declined)."
    edits = decision.get("edits") or {}
    reminder_id = edits.get("reminder_id", reminder_id)
    minutes = edits.get("minutes", minutes)
    user_id, workspace_id = _agent_identity(state)
    try:
        reminder = await reminder_service.snooze_reminder(
            reminder_id,
            owner_id=user_id,
            workspace_id=workspace_id,
            minutes=minutes,
        )
    except ValueError as exc:
        return str(exc)
    if reminder is None:
        return "Reminder not found."
    return f"Reminder snoozed until {reminder.fire_at.isoformat()}."
