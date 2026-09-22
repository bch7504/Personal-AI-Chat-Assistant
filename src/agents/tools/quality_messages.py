"""Bounded evidence search over authorized Quality conversations."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.contracts import SourceReference, ToolResult, ToolResultStatus
from src.agents.schemas.quality import QualityMessageEvidence, QualityReadScope
from src.db.models import Message, User

QualityResourceRevalidator = Callable[[str], Awaitable[None]]
_STOPWORDS = frozenset({"agent", "đánh", "giá", "hãy", "quality", "release", "workspace"})


def _terms(query: str) -> tuple[str, ...]:
    words = re.findall(r"[^\W_]+", query.casefold(), flags=re.UNICODE)
    return tuple(dict.fromkeys(word for word in words if len(word) >= 2 and word not in _STOPWORDS))[:8]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def search_quality_messages(
    *,
    scope: QualityReadScope,
    db: AsyncSession,
    revalidate_resource: QualityResourceRevalidator,
    query: str,
    from_at: datetime,
    to_at: datetime,
    limit: int = 20,
) -> ToolResult:
    """Search evidence without ever falling back to company-wide messages."""

    if from_at.tzinfo is None or to_at.tzinfo is None or from_at > to_at:
        raise ValueError("Quality message search requires a valid timezone-aware period")
    if not 1 <= limit <= 50:
        raise ValueError("Quality message search limit must be between 1 and 50")
    if not scope.effective_group_ids:
        return ToolResult(status=ToolResultStatus.SUCCESS, payload={"evidence": []})
    for resource_id in scope.effective_group_ids:
        await revalidate_resource(resource_id)

    statement = (
        select(Message, User)
        .join(User, User.id == Message.sender_id)
        .where(
            Message.conversation_id.in_(scope.effective_group_ids),
            Message.created_at >= from_at,
            Message.created_at <= to_at,
            User.is_active.is_(True),
        )
    )
    terms = tuple(dict.fromkeys((*_terms(scope.release_id), *_terms(query))))
    if terms:
        statement = statement.where(
            or_(*(Message.content.ilike(f"%{_escape_like(term)}%", escape="\\") for term in terms))
        )
    rows = list(
        (
            await db.execute(
                statement.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit)
            )
        ).all()
    )
    rows.reverse()
    evidence = tuple(
        QualityMessageEvidence(
            message_id=message.id,
            conversation_id=message.conversation_id,
            sender_id=user.id,
            sender_name=user.display_name,
            excerpt=message.content[:1_000],
            created_at=_aware(message.created_at),
            source=SourceReference(
                resource_id=message.conversation_id,
                resource_type="conversation",
                agent_workspace_id=scope.context.request.target_agent_workspace_id,
                classification="quality",
                captured_at=_aware(message.created_at),
            ),
        )
        for message, user in rows
    )
    sources = tuple(dict.fromkeys(item.source for item in evidence))
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={"evidence": [item.model_dump(mode="json") for item in evidence]},
        sources=sources,
    )
