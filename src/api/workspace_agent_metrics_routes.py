"""Source-scoped operational metrics for specialist agent workspaces."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.contracts import AgentProfile
from src.api.workspace_action_routes import _authorize
from src.auth.dependencies import get_current_user
from src.db.models import (
    DeliveryAgentRun,
    DeliveryAgentWorkflow,
    DeliveryDecisionRecord,
    DeliveryDependencyRecord,
    QualityDefect,
    QualityTestRun,
    ReleaseCandidate,
    UsageLog,
    User,
    WorkspaceActionProposalRecord,
    WorkspaceOutboxEvent,
)
from src.db.session import get_db

router = APIRouter()


async def _counts(db: AsyncSession, model, *filters) -> dict[str, int]:
    rows = (await db.execute(select(model.status, func.count(model.id)).where(*filters).group_by(model.status))).all()
    return {str(state): int(count) for state, count in rows}


@router.get("/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/operational-metrics")
async def get_workspace_agent_operational_metrics(
    workspace_id: str,
    agent_workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    profile, _prepared, scope = await _authorize(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        require_lead=True,
    )
    if profile == AgentProfile.PRODUCT_DELIVERY:
        domain = {
            "dependencies": await _counts(
                db,
                DeliveryDependencyRecord,
                DeliveryDependencyRecord.workspace_id == workspace_id,
                DeliveryDependencyRecord.agent_workspace_id == agent_workspace_id,
                DeliveryDependencyRecord.conversation_id.in_(scope.effective_group_ids),
            ),
            "decisions": await _counts(
                db,
                DeliveryDecisionRecord,
                DeliveryDecisionRecord.workspace_id == workspace_id,
                DeliveryDecisionRecord.agent_workspace_id == agent_workspace_id,
                DeliveryDecisionRecord.conversation_id.in_(scope.effective_group_ids),
            ),
            "release_candidates": await _counts(
                db,
                ReleaseCandidate,
                ReleaseCandidate.organization_workspace_id == workspace_id,
                ReleaseCandidate.delivery_agent_workspace_id == agent_workspace_id,
                ReleaseCandidate.source_conversation_id.in_(scope.effective_group_ids),
            ),
            "multi_agent_workflows": await _counts(
                db,
                DeliveryAgentWorkflow,
                DeliveryAgentWorkflow.workspace_id == workspace_id,
                DeliveryAgentWorkflow.agent_workspace_id == agent_workspace_id,
            ),
            "specialist_runs": await _counts(
                db,
                DeliveryAgentRun,
                DeliveryAgentRun.workflow_id.in_(
                    select(DeliveryAgentWorkflow.id).where(
                        DeliveryAgentWorkflow.workspace_id == workspace_id,
                        DeliveryAgentWorkflow.agent_workspace_id == agent_workspace_id,
                    )
                ),
            ),
        }
    else:
        domain = {
            "test_runs": await _counts(
                db,
                QualityTestRun,
                QualityTestRun.workspace_id == workspace_id,
                QualityTestRun.agent_workspace_id == agent_workspace_id,
                QualityTestRun.conversation_id.in_(scope.effective_group_ids),
            ),
            "defects": await _counts(
                db,
                QualityDefect,
                QualityDefect.workspace_id == workspace_id,
                QualityDefect.agent_workspace_id == agent_workspace_id,
                QualityDefect.conversation_id.in_(scope.effective_group_ids),
            ),
            "release_candidates": await _counts(
                db,
                ReleaseCandidate,
                ReleaseCandidate.organization_workspace_id == workspace_id,
                ReleaseCandidate.quality_agent_workspace_id == agent_workspace_id,
            ),
        }
    proposals = await _counts(
        db,
        WorkspaceActionProposalRecord,
        WorkspaceActionProposalRecord.workspace_id == workspace_id,
        WorkspaceActionProposalRecord.agent_workspace_id == agent_workspace_id,
    )
    outbox = await _counts(db, WorkspaceOutboxEvent, WorkspaceOutboxEvent.workspace_id == workspace_id)
    since = datetime.now(UTC) - timedelta(hours=24)
    usage = (
        await db.execute(
            select(
                func.count(UsageLog.id),
                func.coalesce(func.sum(UsageLog.total_tokens), 0),
            ).where(UsageLog.workspace_id == workspace_id, UsageLog.created_at >= since)
        )
    ).one()
    return {
        "workspace_id": workspace_id,
        "agent_workspace_id": agent_workspace_id,
        "profile": profile.value,
        "generated_at": datetime.now(UTC),
        "window_hours": 24,
        "domain": domain,
        "action_proposals": proposals,
        "outbox": outbox,
        "llm_usage": {"request_count": int(usage[0]), "total_tokens": int(usage[1])},
    }
