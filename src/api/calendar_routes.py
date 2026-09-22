import html
import inspect
import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from oauthlib.oauth2 import OAuth2Error
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from src.auth.dependencies import get_current_user
from src.config import get_settings
from src.db.models import EventCandidate, User
from src.db.session import get_db
from src.models.calendar_schemas import (
    CalendarConnectionStatusOut,
    CalendarEventCreateRequest,
    CalendarEventOut,
    CalendarEventUpdateRequest,
    EventBackfillOut,
    EventBackfillRequest,
    EventCandidateConfirmRequest,
    EventCandidateOut,
)
from src.services import (
    calendar_service,
    consent_service,
    event_extraction_service,
    google_credentials,
    reminder_service,
)
from src.services.authorization_service import require_conversation_access
from src.services.google_credentials import CalendarNotConnectedError

logger = logging.getLogger(__name__)
router = APIRouter()
public_router = APIRouter()


async def _resolve_calendar_call(value):
    """Resolve async Calendar operations while preserving simple synchronous test doubles."""
    return await value if inspect.isawaitable(value) else value


def _to_out(event: dict) -> CalendarEventOut:
    return CalendarEventOut(**calendar_service.to_out_dict(event))


def _candidate_out(candidate: EventCandidate) -> EventCandidateOut:
    return EventCandidateOut.model_validate(candidate, from_attributes=True)


def _not_connected() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "calendar_not_connected", "message": "Google Calendar not connected"},
    )


async def _candidate_for_manager(db: AsyncSession, candidate_id: str, current_user: User) -> EventCandidate:
    candidate = await db.get(EventCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event candidate not found")
    await require_conversation_access(db, current_user, candidate.conversation_id, "manager")
    return candidate


@router.get("/calendar/connection", response_model=CalendarConnectionStatusOut)
async def get_calendar_connection(
    current_user: User = Depends(get_current_user),
) -> CalendarConnectionStatusOut:
    return CalendarConnectionStatusOut(**(await google_credentials.get_connection_info(current_user.id)))


@router.get("/calendar/oauth/url")
async def calendar_oauth_url(current_user: User = Depends(get_current_user)) -> dict:
    try:
        google_credentials.validate_configuration()
        return {
            "url": google_credentials.build_authorization_url(current_user.id),
            "storage_ready": True,
        }
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from None


@router.delete("/calendar/connection", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_calendar(current_user: User = Depends(get_current_user)) -> None:
    await google_credentials.disconnect(current_user.id)
    await reminder_service.remove_all_calendar_event_reminders(current_user.id)


@public_router.get("/calendar/oauth/callback", response_class=HTMLResponse)
async def calendar_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    def page(ok: bool, message: str, status_code: int = 200) -> HTMLResponse:
        origin = json.dumps(get_settings().frontend_origin)
        message_json = json.dumps(message)
        safe_message = html.escape(message)
        document = f"""<!doctype html><meta charset=\"utf-8\"><title>Google Calendar</title>
<body style=\"font-family:system-ui;padding:2rem;text-align:center\"><p>{safe_message}</p>
<script>if(window.opener)window.opener.postMessage({{type:'calendar_oauth',ok:{str(ok).lower()},message:{message_json}}},{origin});
setTimeout(function(){{window.close()}},800);</script></body>"""
        return HTMLResponse(document, status_code=status_code)

    if error or not code or not state:
        return page(False, f"Connection failed: {error or 'missing parameters'}.", 400)
    try:
        user_id = google_credentials.read_oauth_state(state)
    except google_credentials.OAuthStateError:
        return page(False, "This connection attempt is invalid or expired.", 400)
    try:
        credentials = await run_in_threadpool(google_credentials.exchange_code, code)
    except OAuth2Error as exc:
        logger.exception("Google Calendar OAuth token exchange failed")
        if exc.error == "invalid_client":
            message = "Google rejected the Calendar OAuth client credentials. Check the Calendar client secret on the server."
        elif exc.error == "invalid_grant":
            message = "Google authorization expired or was already used. Please connect again."
        else:
            message = "Google could not complete Calendar authorization. Please try again."
        return page(False, message, 502)
    except Warning:
        logger.exception("Google Calendar OAuth returned previously granted scopes")
        return page(
            False,
            "Google returned an older Calendar permission. Remove Orbit access from your Google Account, then connect again.",
            502,
        )
    except Exception:  # noqa: BLE001 - callback returns a safe page, details stay in logs
        logger.exception("Google Calendar OAuth exchange failed")
        return page(False, "Google Calendar token exchange failed unexpectedly. Check the server logs.", 502)
    try:
        await google_credentials.save_credentials(user_id, credentials)
    except CalendarNotConnectedError:
        logger.exception("Google Calendar did not return a refresh token")
        return page(False, "Google did not return offline Calendar access. Revoke Orbit access in your Google Account, then connect again.", 502)
    except (RuntimeError, ValueError):
        logger.exception("Google Calendar credential encryption failed")
        return page(False, "The server credential encryption key is invalid. Update CREDENTIAL_ENCRYPTION_KEY on Render.", 502)
    except SQLAlchemyError:
        logger.exception("Google Calendar credential database write failed")
        return page(False, "Orbit could not save the Calendar connection in its database. Check the Render migration logs.", 502)
    except Exception:  # noqa: BLE001 - callback returns a safe page, details stay in logs
        logger.exception("Google Calendar credential save failed")
        return page(False, "Orbit could not securely save the Google Calendar connection. Check the server logs.", 502)
    return page(True, "Google Calendar connected. You can close this window.")


@router.get("/calendar/candidates", response_model=list[EventCandidateOut])
async def list_event_candidates(
    conversation_id: str = Query(...),
    include_terminal: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EventCandidateOut]:
    await require_conversation_access(db, current_user, conversation_id, "viewer")
    statement = select(EventCandidate).where(EventCandidate.conversation_id == conversation_id)
    if not include_terminal:
        statement = statement.where(EventCandidate.status == "suggested")
    candidates = list(
        (await db.execute(statement.order_by(EventCandidate.updated_at.desc()).limit(100))).scalars().all()
    )
    return [_candidate_out(candidate) for candidate in candidates]


@router.post("/calendar/candidates/{candidate_id}/confirm", response_model=EventCandidateOut)
async def confirm_event_candidate(
    candidate_id: str,
    request: EventCandidateConfirmRequest = Body(default=EventCandidateConfirmRequest()),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EventCandidateOut:
    candidate = await _candidate_for_manager(db, candidate_id, current_user)
    if candidate.status != "suggested":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Candidate is no longer actionable")
    current_hash = await consent_service.get_consent_scope_hash(db, candidate.conversation_id)
    sources_valid = await consent_service.validate_authorized_source_ids(
        db, candidate.conversation_id, candidate.source_message_ids
    )
    if current_hash != candidate.authorization_scope_hash or not sources_valid:
        candidate.status = "invalidated"
        candidate.invalidated_reason = "group_ai_policy_changed"
        await db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="AI policy changed; extract again")

    target = await db.get(EventCandidate, candidate.target_candidate_id) if candidate.target_candidate_id else None
    if candidate.operation != "create" and (
        target is None or not target.calendar_event_id or target.calendar_owner_user_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The manager who owns the original calendar event must confirm this change",
        )
    try:
        if candidate.operation == "create":
            if candidate.missing_fields or candidate.start_at is None or candidate.end_at is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Candidate is incomplete: {', '.join(candidate.missing_fields)}",
                )
            changed = await _resolve_calendar_call(calendar_service.create_event(
                current_user.id,
                candidate.title,
                candidate.start_at.isoformat(),
                candidate.end_at.isoformat(),
                f"Extracted from group conversation {candidate.conversation_id}.",
                candidate.attendees,
                current_user.timezone,
            ))
            candidate.calendar_event_id = changed.get("id")
            candidate.calendar_owner_user_id = current_user.id
            event_type = "calendar_event_created"
            payload = {"event": calendar_service.to_out_dict(changed)}
        elif candidate.operation == "update":
            if candidate.missing_fields or candidate.start_at is None or candidate.end_at is None:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Update is incomplete")
            changed = await _resolve_calendar_call(calendar_service.update_event(
                current_user.id,
                target.calendar_event_id,
                candidate.title,
                candidate.start_at.isoformat(),
                candidate.end_at.isoformat(),
                f"Updated from group conversation {candidate.conversation_id}.",
                current_user.timezone,
            ))
            candidate.calendar_event_id = target.calendar_event_id
            candidate.calendar_owner_user_id = current_user.id
            target.status = "superseded"
            event_type = "calendar_event_updated"
            payload = {"event": calendar_service.to_out_dict(changed)}
        else:
            await _resolve_calendar_call(
                calendar_service.delete_event(current_user.id, target.calendar_event_id)
            )
            candidate.calendar_event_id = target.calendar_event_id
            candidate.calendar_owner_user_id = current_user.id
            target.status = "cancelled"
            event_type = "calendar_event_deleted"
            payload = {"event_id": target.calendar_event_id}
    except CalendarNotConnectedError:
        raise _not_connected() from None
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Google Calendar error: {exc}") from None

    candidate.status = "confirmed"
    await db.commit()
    await db.refresh(candidate)
    if candidate.operation == "create" and request.create_reminder:
        await reminder_service.reconcile_calendar_event_reminder(
            owner_id=current_user.id,
            calendar_event_id=candidate.calendar_event_id,
            title=candidate.title,
            start_at=candidate.start_at,
            create_if_missing=True,
            lead_minutes=request.reminder_lead_minutes,
            source="proactive",
        )
    elif candidate.operation == "update":
        await reminder_service.reconcile_calendar_event_reminder(
            owner_id=current_user.id,
            calendar_event_id=candidate.calendar_event_id,
            title=candidate.title,
            start_at=candidate.start_at,
        )
    elif candidate.operation == "cancel":
        await reminder_service.remove_calendar_event_reminder(
            current_user.id,
            candidate.calendar_event_id,
        )
    await calendar_service.broadcast_change(current_user.id, event_type, payload)
    return _candidate_out(candidate)


@router.post("/calendar/candidates/{candidate_id}/dismiss", response_model=EventCandidateOut)
async def dismiss_event_candidate(
    candidate_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EventCandidateOut:
    candidate = await _candidate_for_manager(db, candidate_id, current_user)
    if candidate.status != "suggested":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Candidate is no longer actionable")
    candidate.status = "dismissed"
    await db.commit()
    await db.refresh(candidate)
    return _candidate_out(candidate)


@router.post("/conversations/{conversation_id}/event-backfill", response_model=EventBackfillOut)
async def backfill_event_candidates(
    conversation_id: str,
    request: EventBackfillRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EventBackfillOut:
    await require_conversation_access(db, current_user, conversation_id, "manager")
    return EventBackfillOut(
        **(
            await event_extraction_service.process_event_backfill_batch(
                conversation_id,
                request.batch_size,
                requested_by_user_id=current_user.id,
            )
        )
    )


@router.get("/calendar/events", response_model=list[CalendarEventOut])
async def list_events(
    time_min: str | None = Query(default=None),
    time_max: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
) -> list[CalendarEventOut]:
    now = datetime.now(UTC)
    try:
        items = await calendar_service.list_events(
            current_user.id,
            time_min or now.isoformat(),
            time_max or (now + timedelta(days=60)).isoformat(),
            100,
        )
    except CalendarNotConnectedError:
        raise _not_connected() from None
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Google Calendar error: {exc}") from None
    return [_to_out(event) for event in items]


@router.post("/calendar/events", response_model=CalendarEventOut, status_code=status.HTTP_201_CREATED)
async def create_event(
    request: CalendarEventCreateRequest,
    current_user: User = Depends(get_current_user),
) -> CalendarEventOut:
    try:
        created = await calendar_service.create_event(
            current_user.id,
            request.summary,
            request.start_iso.isoformat(),
            request.end_iso.isoformat(),
            request.description,
            [str(value) for value in (request.attendees or [])],
            current_user.timezone,
        )
    except CalendarNotConnectedError:
        raise _not_connected() from None
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Google Calendar error: {exc}") from None
    out = _to_out(created)
    if request.create_reminder:
        await reminder_service.reconcile_calendar_event_reminder(
            owner_id=current_user.id,
            calendar_event_id=out.id,
            title=out.title,
            start_at=out.start,
            create_if_missing=True,
            lead_minutes=request.reminder_lead_minutes,
            source="manual",
        )
    await calendar_service.broadcast_change(current_user.id, "calendar_event_created", {"event": out.model_dump()})
    return out


@router.patch("/calendar/events/{event_id}", response_model=CalendarEventOut)
async def update_event(
    event_id: str,
    request: CalendarEventUpdateRequest,
    current_user: User = Depends(get_current_user),
) -> CalendarEventOut:
    try:
        updated = await calendar_service.update_event(
            current_user.id,
            event_id,
            request.summary,
            request.start_iso.isoformat() if request.start_iso else None,
            request.end_iso.isoformat() if request.end_iso else None,
            request.description,
            current_user.timezone,
        )
    except CalendarNotConnectedError:
        raise _not_connected() from None
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Google Calendar error: {exc}") from None
    out = _to_out(updated)
    await reminder_service.reconcile_calendar_event_reminder(
        owner_id=current_user.id,
        calendar_event_id=out.id,
        title=out.title,
        start_at=out.start,
    )
    await calendar_service.broadcast_change(current_user.id, "calendar_event_updated", {"event": out.model_dump()})
    return out


@router.delete("/calendar/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(event_id: str, current_user: User = Depends(get_current_user)) -> None:
    try:
        await calendar_service.delete_event(current_user.id, event_id)
    except CalendarNotConnectedError:
        raise _not_connected() from None
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Google Calendar error: {exc}") from None
    await calendar_service.broadcast_change(current_user.id, "calendar_event_deleted", {"event_id": event_id})
    await reminder_service.remove_calendar_event_reminder(current_user.id, event_id)
