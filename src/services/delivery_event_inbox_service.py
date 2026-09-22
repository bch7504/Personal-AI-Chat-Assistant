"""Idempotent inbox boundary for future external Delivery workflow events."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.delivery_orchestration.contracts import canonical_payload_hash
from src.db.models import DeliveryEventInbox


async def accept_delivery_event_once(
    db: AsyncSession,
    *,
    consumer: str,
    message_id: str,
    payload: dict[str, Any],
) -> bool:
    """Record an external event exactly once inside the caller's transaction.

    Returns ``True`` for the first delivery and ``False`` for an identical
    replay. Reusing an ID with different content fails closed.
    """

    payload_hash = canonical_payload_hash(payload)
    existing = (
        await db.execute(
            select(DeliveryEventInbox).where(
                DeliveryEventInbox.consumer == consumer,
                DeliveryEventInbox.message_id == message_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise ValueError("Delivery event message_id was reused with different payload")
        return False
    db.add(
        DeliveryEventInbox(
            consumer=consumer,
            message_id=message_id,
            payload_hash=payload_hash,
            processed_at=datetime.now(UTC),
        )
    )
    await db.flush()
    return True
