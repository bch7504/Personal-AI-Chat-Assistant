"""Source-backed QA work-item and deterministic release-status tools."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.contracts import ToolResult, ToolResultStatus
from src.agents.schemas.quality import (
    QualityReadScope,
    QualityWorkItem,
    evaluate_release_readiness,
)
from src.services.quality_workspace_service import list_quality_work_items

QualityResourceRevalidator = Callable[[str], Awaitable[None]]


async def get_quality_work_items(
    *,
    scope: QualityReadScope,
    db: AsyncSession,
    revalidate_resource: QualityResourceRevalidator,
) -> ToolResult:
    """Read only rows authorized by the trusted QA scope."""

    for resource_id in scope.effective_group_ids:
        await revalidate_resource(resource_id)
    items = await list_quality_work_items(db, scope=scope)
    sources = tuple(dict.fromkeys(source for item in items for source in item.sources))
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={"items": [item.model_dump(mode="json") for item in items]},
        sources=sources,
    )


async def get_release_test_status(
    *,
    scope: QualityReadScope,
    items: tuple[QualityWorkItem, ...],
) -> ToolResult:
    """Expose the same deterministic gate used by the final brief producer."""

    assessment = evaluate_release_readiness(items, release_id=scope.release_id)
    sources = tuple(dict.fromkeys(source for item in items for source in item.sources))
    return ToolResult(
        status=ToolResultStatus.PARTIAL if assessment.data_gaps else ToolResultStatus.SUCCESS,
        payload={"assessment": assessment.model_dump(mode="json")},
        sources=sources,
        data_gaps=assessment.data_gaps,
    )
