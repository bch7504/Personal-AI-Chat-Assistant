"""Read-only Quality tools backed by the normalized control plane."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.contracts import SourceReference, ToolResult, ToolResultStatus
from src.agents.schemas.quality import QualityReadScope
from src.services.quality_control_service import load_quality_control_plane


def _sources(scope: QualityReadScope, payload: dict) -> tuple[SourceReference, ...]:
    captured_by_conversation: dict[str, datetime] = {}
    for collection in ("requirements", "test_cases", "test_runs", "defects", "evidence"):
        for record in payload[collection]:
            conversation_id = record["conversation_id"]
            captured = record.get("updated_at") or record.get("created_at") or datetime.now(UTC)
            if captured.tzinfo is None:
                captured = captured.replace(tzinfo=UTC)
            captured_by_conversation[conversation_id] = max(
                captured_by_conversation.get(conversation_id, captured), captured
            )
    target = scope.context.request.target_agent_workspace_id
    if target is None:
        return ()
    return tuple(
        SourceReference(
            resource_id=conversation_id,
            resource_type="conversation",
            agent_workspace_id=target,
            classification="quality",
            captured_at=captured,
        )
        for conversation_id, captured in sorted(captured_by_conversation.items())
    )


async def get_quality_control_plane(*, scope: QualityReadScope, db: AsyncSession) -> ToolResult:
    payload = await load_quality_control_plane(
        db,
        workspace_id=scope.context.actor.organization_workspace_id,
        agent_workspace_id=scope.context.request.target_agent_workspace_id or "",
        release_id=scope.release_id,
        conversation_ids=scope.effective_group_ids,
    )
    gaps = () if payload["domain_present"] else ("NORMALIZED_QUALITY_DATA_NOT_CAPTURED",)
    return ToolResult(
        status=ToolResultStatus.PARTIAL if gaps else ToolResultStatus.SUCCESS,
        payload=payload,
        sources=_sources(scope, payload),
        data_gaps=gaps,
    )


async def get_quality_policy(*, scope: QualityReadScope, db: AsyncSession) -> ToolResult:
    result = await get_quality_control_plane(scope=scope, db=db)
    return result.model_copy(update={"payload": {"policy": result.payload["policy"]}})


async def get_quality_evidence_catalog(*, scope: QualityReadScope, db: AsyncSession) -> ToolResult:
    result = await get_quality_control_plane(scope=scope, db=db)
    return result.model_copy(update={"payload": {"evidence": result.payload["evidence"]}})


async def get_quality_waivers(*, scope: QualityReadScope, db: AsyncSession) -> ToolResult:
    result = await get_quality_control_plane(scope=scope, db=db)
    return result.model_copy(update={"payload": {"waivers": result.payload["waivers"]}})
