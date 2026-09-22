"""Read the structured Delivery handoff addressed to this QA workspace."""

from __future__ import annotations

from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.contracts import SourceReference, ToolResult, ToolResultStatus
from src.agents.schemas.quality import QualityReadScope
from src.db.models import ReleaseCandidate


async def get_release_candidate(
    *, scope: QualityReadScope, db: AsyncSession
) -> ToolResult:
    target = scope.context.request.target_agent_workspace_id
    if target is None:
        raise ValueError("Quality target workspace is missing")
    candidate = (
        await db.execute(
            select(ReleaseCandidate)
            .where(
                ReleaseCandidate.organization_workspace_id
                == scope.context.actor.organization_workspace_id,
                ReleaseCandidate.quality_agent_workspace_id == target,
                ReleaseCandidate.release_key == scope.release_id,
                ReleaseCandidate.status != "draft",
            )
            .order_by(ReleaseCandidate.updated_at.desc(), ReleaseCandidate.id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if candidate is None:
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            payload={"release_candidate": None},
        )
    captured_at = candidate.updated_at
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=UTC)
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={
            "release_candidate": {
                "id": candidate.id,
                "release_key": candidate.release_key,
                "version": candidate.version,
                "build_number": candidate.build_number,
                "commit_sha": candidate.commit_sha,
                "environment": candidate.environment,
                "handoff_status": candidate.status,
                "quality_policy_version": candidate.quality_policy_version,
                "row_version": candidate.row_version,
            }
        },
        sources=(
            SourceReference(
                resource_id=candidate.id,
                resource_type="release_candidate",
                agent_workspace_id=target,
                classification="handoff",
                captured_at=captured_at,
            ),
        ),
    )
