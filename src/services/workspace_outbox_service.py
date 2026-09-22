"""Transactional outbox for durable cross-workspace handoff events."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import src.db.session as db_session
from src.db.models import ReleaseCandidate, WorkspaceOutboxEvent
from src.services.audit_service import record_audit_event

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


async def enqueue_workspace_event(
    db: AsyncSession,
    *,
    workspace_id: str,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
) -> WorkspaceOutboxEvent:
    """Stage an event in the caller's transaction; never commits independently."""

    existing = (
        await db.execute(select(WorkspaceOutboxEvent).where(WorkspaceOutboxEvent.idempotency_key == idempotency_key))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    event = WorkspaceOutboxEvent(
        workspace_id=workspace_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=payload,
        idempotency_key=idempotency_key,
        status="pending",
        available_at=datetime.now(UTC),
    )
    db.add(event)
    try:
        await db.flush()
    except IntegrityError:
        # A concurrent writer may have won the idempotency race. Let the caller
        # retry its whole transaction instead of committing a partial handoff.
        raise
    return event


async def _validate_handoff_event(db: AsyncSession, event: WorkspaceOutboxEvent) -> None:
    """Fail closed when the durable aggregate disappeared or left its workspace."""

    if event.aggregate_type != "release_candidate":
        raise ValueError(f"unsupported aggregate type: {event.aggregate_type}")
    candidate = await db.get(ReleaseCandidate, event.aggregate_id)
    if candidate is None or candidate.organization_workspace_id != event.workspace_id:
        raise ValueError("release candidate aggregate is unavailable")


async def process_workspace_outbox_events(*, batch_size: int = 50) -> int:
    """Process a bounded batch with retry/dead-letter behavior.

    ReleaseCandidate is the durable shared source of truth. Processing validates
    the handoff envelope and records delivery; consumers can safely replay from
    the idempotent event without coupling the two agent runtimes.
    """

    processed = 0
    now = datetime.now(UTC)
    async with db_session.async_session_maker() as db:
        statement = (
            select(WorkspaceOutboxEvent)
            .where(
                WorkspaceOutboxEvent.status.in_(("pending", "failed")),
                or_(
                    WorkspaceOutboxEvent.available_at.is_(None),
                    WorkspaceOutboxEvent.available_at <= now,
                ),
            )
            .order_by(WorkspaceOutboxEvent.created_at.asc(), WorkspaceOutboxEvent.id.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        events = list((await db.execute(statement)).scalars().all())
        for event in events:
            event.status = "processing"
            event.attempts += 1
            try:
                await _validate_handoff_event(db, event)
                event.status = "processed"
                event.processed_at = datetime.now(UTC)
                event.last_error = None
                await record_audit_event(
                    db,
                    actor=None,
                    action="workspace_outbox.processed",
                    target_type=event.aggregate_type,
                    target_id=event.aggregate_id,
                    workspace_id=event.workspace_id,
                    metadata={"event_type": event.event_type, "attempts": event.attempts},
                )
                processed += 1
            except Exception as exc:  # noqa: BLE001 - retry boundary by design
                event.last_error = str(exc)[:2_000]
                if event.attempts >= MAX_ATTEMPTS:
                    event.status = "dead_letter"
                else:
                    event.status = "failed"
                    event.available_at = datetime.now(UTC) + timedelta(seconds=min(300, 2**event.attempts))
                logger.exception("Workspace outbox event failed", extra={"event_id": event.id})
        await db.commit()
    return processed
