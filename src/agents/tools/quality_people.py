"""Minimal, scoped people resolver for QA owners and verifiers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.contracts import ToolResult, ToolResultStatus
from src.agents.schemas.quality import QualityPerson, QualityReadScope, QualityWorkItem
from src.db.models import User


async def get_quality_people(
    *,
    scope: QualityReadScope,
    db: AsyncSession,
    items: tuple[QualityWorkItem, ...],
) -> ToolResult:
    """Resolve only people already referenced by scoped QA facts."""

    if scope.context.request.target_agent_workspace_id is None:
        raise ValueError("Quality target workspace is missing")
    owner_ids = tuple(sorted({item.owner_id for item in items if item.owner_id}))
    if not owner_ids:
        return ToolResult(status=ToolResultStatus.SUCCESS, payload={"people": []})
    rows = (
        (
            await db.execute(
                select(User)
                .where(User.id.in_(owner_ids), User.is_active.is_(True))
                .order_by(User.display_name.asc(), User.id.asc())
            )
        )
        .scalars()
        .all()
    )
    people = tuple(
        QualityPerson(user_id=user.id, display_name=user.display_name, job_title=user.job_title or "")
        for user in rows
    )
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={"people": [person.model_dump(mode="json") for person in people]},
    )
