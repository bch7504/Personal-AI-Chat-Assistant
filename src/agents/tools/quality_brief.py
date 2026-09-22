"""Deterministic Quality brief builder."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.agents.contracts import AgentProfile, BriefType, ToolResult, ToolResultStatus, WorkspaceBrief
from src.agents.schemas.quality import QualityReadScope, QualityWorkItem, evaluate_release_readiness


def build_quality_brief(
    *, scope: QualityReadScope, items: tuple[QualityWorkItem, ...], generated_at: datetime | None = None
) -> ToolResult:
    now = generated_at or datetime.now(UTC)
    gaps = () if items else (f"No authorized Quality work items found for release {scope.release_id}",)
    assessment = evaluate_release_readiness(items, release_id=scope.release_id, extra_data_gaps=gaps)
    sources = tuple(dict.fromkeys(source for item in items for source in item.sources))
    oldest_source = min((source.captured_at for source in sources), default=now)
    brief = WorkspaceBrief(
        brief_id=uuid4().hex,
        trace_id=scope.context.trace_id,
        organization_workspace_id=scope.context.actor.organization_workspace_id,
        agent_workspace_id=scope.context.request.target_agent_workspace_id,
        brief_type=BriefType.QUALITY,
        producer_profile=AgentProfile.QUALITY_ASSURANCE,
        period_start=oldest_source,
        period_end=now,
        generated_at=now,
        expires_at=now + timedelta(minutes=15),
        headline=(
            f"Release {scope.release_id}: {assessment.release_readiness.value}; "
            f"{len(assessment.critical_defects)} critical defect(s), "
            f"{len(assessment.blocked_tests)} failed/blocked test(s)."
        ),
        facts=tuple(item.model_dump(mode="json") for item in items),
        risks=tuple(item.model_dump(mode="json") for item in assessment.risks),
        data_gaps=assessment.data_gaps,
        sources=sources,
        release_readiness=assessment.release_readiness,
    )
    return ToolResult(
        status=ToolResultStatus.PARTIAL if assessment.data_gaps else ToolResultStatus.SUCCESS,
        payload={
            "assessment": assessment.model_dump(mode="json"),
            "brief": brief.model_dump(mode="json"),
            "view_scope": scope.view_scope.value,
        },
        sources=sources,
        data_gaps=assessment.data_gaps,
    )

