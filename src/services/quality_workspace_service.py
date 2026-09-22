"""Fail-closed, release-scoped Quality Assurance repository."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.contracts import SourceReference
from src.agents.schemas.quality import (
    QualityReadScope,
    QualitySeverity,
    QualityStatus,
    QualityViewScope,
    QualityWorkItem,
    QualityWorkItemType,
)
from src.db.models import Task


class QualityDataError(RuntimeError):
    """Raised when persisted QA data violates the typed domain contract."""


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def list_quality_work_items(
    db: AsyncSession, *, scope: QualityReadScope
) -> tuple[QualityWorkItem, ...]:
    if not scope.effective_group_ids:
        return ()
    statement = select(Task).where(
        Task.workspace_id == scope.context.actor.organization_workspace_id,
        Task.agent_workspace_id == scope.context.request.target_agent_workspace_id,
        Task.conversation_id.in_(scope.effective_group_ids),
        Task.release_target == scope.release_id,
        Task.work_item_type.is_not(None),
    )
    if scope.view_scope == QualityViewScope.MEMBER:
        statement = statement.where(Task.owner_id == scope.context.actor.user_id)
    rows = (
        (await db.execute(statement.order_by(Task.updated_at.desc(), Task.id.asc())))
        .scalars()
        .all()
    )
    items: list[QualityWorkItem] = []
    for row in rows:
        if row.conversation_id is None:
            raise QualityDataError("A Quality work item is missing its source conversation")
        try:
            items.append(
                QualityWorkItem(
                    id=row.id,
                    title=row.title,
                    work_item_type=QualityWorkItemType(row.work_item_type),
                    severity=QualitySeverity(row.severity) if row.severity else None,
                    quality_status=QualityStatus(row.quality_status),
                    release_id=row.release_target,
                    required=bool(row.quality_required),
                    owner_id=row.owner_id,
                    sources=(
                        SourceReference(
                            resource_id=row.conversation_id,
                            resource_type="conversation",
                            agent_workspace_id=scope.context.request.target_agent_workspace_id,
                            classification="quality",
                            captured_at=_aware(row.updated_at),
                        ),
                    ),
                )
            )
        except (TypeError, ValueError) as exc:
            raise QualityDataError(f"Invalid Quality work item {row.id}") from exc
    return tuple(items)

