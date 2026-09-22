"""Incremental and resumable calendar-fact extraction for AI-enabled group conversations."""

import json
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select

from src.config import get_settings
from src.db import session as db_session
from src.db.models import Conversation, EventCandidate, EventExtractionCursor, Message, User
from src.models.chat_content import text_only_chat_content
from src.services import consent_service, usage_service
from src.services.authorization_service import get_authorized_participant_ids
from src.services.llm import get_llm
from src.websocket.manager import manager

logger = logging.getLogger(__name__)

_EVENT_SIGNAL = re.compile(
    r"\b(họp|gặp|meeting|meet|call|demo|phỏng vấn|appointment|lịch|đặt lịch|dời|đổi giờ|"
    r"hoãn|hủy|huỷ|chốt|thứ\s*[2-7]|chủ nhật|hôm nay|ngày mai|tuần sau|tháng sau|"
    r"\d{1,2}[:h]\d{0,2}|\d{1,2}[/-]\d{1,2})\b",
    re.IGNORECASE,
)


def looks_like_event(text: str) -> bool:
    return bool(_EVENT_SIGNAL.search(text_only_chat_content(text)))


def _clean_json(text: str) -> dict:
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("event extraction output must be an object")
    return value


def _parse_datetime(value: object, timezone: str) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
    return parsed


async def _context_ending_at(db, conversation_id: str, message: Message, limit: int = 16):
    rows = (
        await db.execute(
            select(Message, User)
            .join(User, User.id == Message.sender_id)
            .where(
                Message.conversation_id == conversation_id,
                or_(
                    Message.created_at < message.created_at,
                    and_(Message.created_at == message.created_at, Message.id <= message.id),
                ),
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
    ).all()
    rows.reverse()
    return rows


def _candidate_summary(candidate: EventCandidate) -> dict:
    return {
        "id": candidate.id,
        "operation": candidate.operation,
        "title": candidate.title,
        "start_at": candidate.start_at.isoformat() if candidate.start_at else None,
        "end_at": candidate.end_at.isoformat() if candidate.end_at else None,
        "location": candidate.location,
        "attendees": candidate.attendees,
        "status": candidate.status,
        "calendar_event_id": candidate.calendar_event_id,
    }


async def _extract_event_candidate(
    *,
    conversation_id: str,
    message_id: str,
    force: bool = False,
    usage_user_id: str | None = None,
) -> EventCandidate | None:
    """Use a bounded message neighbourhood and durable candidates instead of rescanning history."""
    settings = get_settings()
    async with db_session.async_session_maker() as db:
        conversation = await db.get(Conversation, conversation_id)
        message = await db.get(Message, message_id)
        if (
            conversation is None
            or message is None
            or message.conversation_id != conversation_id
            or conversation.type != "group"
            or not conversation.ai_enabled
        ):
            return None
        if not force and not looks_like_event(message.content):
            return None
        scope_hash = await consent_service.get_consent_scope_hash(db, conversation_id)
        context_rows = await _context_ending_at(db, conversation_id, message)
        # A source message can contribute to only one active extraction result.  This makes retries
        # and overlapping backfill batches idempotent without relying on JSON containment SQL.
        prior = list(
            (
                await db.execute(
                    select(EventCandidate).where(EventCandidate.conversation_id == conversation_id)
                )
            )
            .scalars()
            .all()
        )
        if any(message_id in (item.source_message_ids or []) for item in prior):
            return None
        visible = [item for item in prior if item.status in {"suggested", "confirmed"}][-20:]
        candidates_by_id = {item.id: item for item in visible}

    context_text = "\n".join(
        f"[{row.created_at.isoformat()}] {sender.display_name}: {text_only_chat_content(row.content)}"
        for row, sender in context_rows
    )
    now = datetime.now(ZoneInfo(settings.calendar_timezone))
    prompt = (
        "Extract one calendar-event change from the final message and its nearby team-chat context. "
        "The group manager has enabled AI processing for the whole conversation, so the supplied "
        "turns are a continuous authorized context. Resolve pronouns and short replies from that "
        "context. Match reschedules/cancellations to an existing candidate when possible. Never "
        "invent a date, time, participant, or location. Output ONLY one JSON object with keys: "
        '"action" (none|create|update|cancel), "target_candidate_id" (existing id or null), '
        '"title" (string or null), "start_at" and "end_at" (ISO 8601 or null), '
        '"location" (string or null), "attendees" (array of names), "confidence" (0..1), and '
        '"missing_fields" (array chosen from title,start_at,end_at). Use update or cancel only when '
        "the target is clearly the same event. If uncertain choose none. "
        f"Current time: {now.isoformat()}. Existing candidates: "
        f"{json.dumps([_candidate_summary(item) for item in visible], ensure_ascii=False)}\n\n"
        f"Conversation context:\n{context_text}"
    )
    result = await get_llm().ainvoke(prompt)
    await usage_service.log_usage(
        provider=settings.llm_provider,
        model=settings.model_name,
        usage_metadata=getattr(result, "usage_metadata", {}),
        workspace_id=conversation.workspace_id,
        user_id=usage_user_id or message.sender_id,
    )
    try:
        data = _clean_json(str(result.content))
        action = data.get("action")
        confidence = float(data.get("confidence", 0))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if action not in {"create", "update", "cancel"} or confidence < 0.65:
        return None

    target = candidates_by_id.get(data.get("target_candidate_id"))
    if action in {"update", "cancel"} and target is None:
        return None
    try:
        start_at = _parse_datetime(data.get("start_at"), settings.calendar_timezone)
        end_at = _parse_datetime(data.get("end_at"), settings.calendar_timezone)
    except ValueError:
        return None
    title = (data.get("title") or (target.title if target else "Cuộc hẹn chưa đủ thông tin"))[:200]
    location = data.get("location") if data.get("location") is not None else (target.location if target else None)
    attendees = data.get("attendees") if isinstance(data.get("attendees"), list) else []
    if target:
        start_at = start_at or target.start_at
        end_at = end_at or target.end_at
        attendees = attendees or list(target.attendees or [])
    missing_fields = [field for field in ("title", "start_at", "end_at") if data.get(field) is None]
    if target:
        missing_fields = [
            field
            for field in missing_fields
            if getattr(target, field if field != "title" else "title", None) is None
        ]

    async with db_session.async_session_maker() as db:
        conversation = await db.get(Conversation, conversation_id)
        if conversation is None or not conversation.ai_enabled:
            return None
        if await consent_service.get_consent_scope_hash(db, conversation_id) != scope_hash:
            return None
        source_ids = [row.id for row, _ in context_rows]
        persisted_target = await db.get(EventCandidate, target.id) if target else None
        if action == "update" and persisted_target is not None and persisted_target.status == "suggested" and persisted_target.operation == "create":
            persisted_target.title = title
            persisted_target.start_at = start_at
            persisted_target.end_at = end_at
            persisted_target.location = location
            persisted_target.attendees = attendees
            persisted_target.confidence = max(persisted_target.confidence, confidence)
            persisted_target.missing_fields = missing_fields
            persisted_target.source_message_ids = list(dict.fromkeys([*persisted_target.source_message_ids, *source_ids]))
            persisted_target.authorization_scope_hash = scope_hash
            candidate = persisted_target
        elif action == "cancel" and persisted_target is not None and persisted_target.status == "suggested" and not persisted_target.calendar_event_id:
            persisted_target.status = "cancelled"
            persisted_target.source_message_ids = list(dict.fromkeys([*persisted_target.source_message_ids, *source_ids]))
            candidate = persisted_target
        else:
            candidate = EventCandidate(
                workspace_id=conversation.workspace_id,
                conversation_id=conversation_id,
                operation=action,
                target_candidate_id=persisted_target.id if persisted_target else None,
                title=title,
                start_at=start_at,
                end_at=end_at,
                location=location,
                attendees=attendees,
                confidence=confidence,
                missing_fields=missing_fields,
                source_message_ids=source_ids,
                authorization_scope_hash=scope_hash,
            )
            db.add(candidate)
        await db.commit()
        await db.refresh(candidate)
        participant_ids = await get_authorized_participant_ids(db, conversation_id)

    if participant_ids:
        await manager.broadcast_to_users(participant_ids, {"type": "event_candidate_changed", "id": candidate.id})
    return candidate


async def maybe_extract_event_candidate(
    *,
    conversation_id: str,
    message_id: str,
    force: bool = False,
    strict: bool = False,
    usage_user_id: str | None = None,
) -> EventCandidate | None:
    """Best-effort wrapper for message delivery; strict mode is used by managed backfill."""
    try:
        return await _extract_event_candidate(
            conversation_id=conversation_id,
            message_id=message_id,
            force=force,
            usage_user_id=usage_user_id,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Event extraction failed for message %s", message_id)
        if strict:
            raise
        return None


async def process_event_backfill_batch(
    conversation_id: str,
    batch_size: int = 200,
    *,
    requested_by_user_id: str | None = None,
) -> dict:
    """Process one bounded historical batch and persist a cursor for the next invocation."""
    batch_size = max(1, min(batch_size, 500))
    if requested_by_user_id and await usage_service.is_over_budget(requested_by_user_id):
        return {"status": "paused", "processed": 0, "extracted": 0, "has_more": True}
    async with db_session.async_session_maker() as db:
        conversation = await db.get(Conversation, conversation_id)
        if conversation is None or conversation.type != "group" or not conversation.ai_enabled:
            return {"status": "disabled", "processed": 0, "has_more": False}
        cursor = await db.get(EventExtractionCursor, conversation_id)
        if cursor is None:
            cursor = EventExtractionCursor(conversation_id=conversation_id, status="running")
            db.add(cursor)
            await db.flush()
        else:
            if cursor.status == "running":
                return {"status": "running", "processed": 0, "extracted": 0, "has_more": True}
            cursor.status = "running"
            cursor.last_error = None
        stmt = select(Message).where(Message.conversation_id == conversation_id)
        if cursor.last_message_created_at is not None and cursor.last_message_id is not None:
            stmt = stmt.where(
                or_(
                    Message.created_at > cursor.last_message_created_at,
                    and_(
                        Message.created_at == cursor.last_message_created_at,
                        Message.id > cursor.last_message_id,
                    ),
                )
            )
        rows = list(
            (
                await db.execute(
                    stmt.order_by(Message.created_at.asc(), Message.id.asc()).limit(batch_size + 1)
                )
            )
            .scalars()
            .all()
        )
        batch, has_more = rows[:batch_size], len(rows) > batch_size
        starting_scope_hash = await consent_service.get_consent_scope_hash(db, conversation_id)
        await db.commit()

    extracted = 0
    try:
        for message in batch:
            if looks_like_event(message.content):
                candidate = await maybe_extract_event_candidate(
                    conversation_id=conversation_id,
                    message_id=message.id,
                    force=True,
                    strict=True,
                    usage_user_id=requested_by_user_id,
                )
                extracted += int(candidate is not None)
        async with db_session.async_session_maker() as db:
            cursor = await db.get(EventExtractionCursor, conversation_id)
            if cursor is not None:
                if await consent_service.get_consent_scope_hash(db, conversation_id) != starting_scope_hash:
                    cursor.status = "idle"
                    await db.commit()
                    return {"status": "idle", "processed": 0, "extracted": 0, "has_more": True}
                if batch:
                    cursor.last_message_created_at = batch[-1].created_at
                    cursor.last_message_id = batch[-1].id
                    cursor.processed_message_count += len(batch)
                cursor.status = "idle" if has_more else "completed"
                await db.commit()
        return {"status": "idle" if has_more else "completed", "processed": len(batch), "extracted": extracted, "has_more": has_more}
    except Exception as exc:  # noqa: BLE001
        async with db_session.async_session_maker() as db:
            cursor = await db.get(EventExtractionCursor, conversation_id)
            if cursor is not None:
                cursor.status = "failed"
                cursor.last_error = str(exc)[:500]
                await db.commit()
        raise
