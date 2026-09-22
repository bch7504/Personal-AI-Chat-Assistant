"""Unified, deterministic gateway for supported workspace-specialist agents."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.contracts import AgentProfile, ToolResult
from src.api.delivery_routes import get_delivery_brief
from src.api.quality_routes import get_quality_brief
from src.auth.dependencies import get_current_user
from src.db.models import AgentWorkspace, User
from src.db.session import get_db
from src.models.delivery_schemas import DeliveryBriefRequest
from src.models.quality_schemas import QualityBriefRequest
from src.models.workspace_agent_schemas import WorkspaceAgentInvokeRequest

router = APIRouter()


@router.post(
    "/workspaces/{workspace_id}/agent-router/invoke",
    response_model=ToolResult,
)
async def invoke_workspace_agent(
    workspace_id: str,
    request: WorkspaceAgentInvokeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ToolResult:
    """Resolve the profile from trusted DB state and dispatch through its full policy pipeline."""

    target = (
        await db.execute(
            select(AgentWorkspace).where(
                AgentWorkspace.id == request.target_agent_workspace_id,
                AgentWorkspace.organization_workspace_id == workspace_id,
                AgentWorkspace.status == "active",
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace agent is unavailable",
        )

    if target.agent_profile == AgentProfile.PRODUCT_DELIVERY.value:
        return await get_delivery_brief(
            workspace_id=workspace_id,
            agent_workspace_id=target.id,
            request=DeliveryBriefRequest(
                message=request.message,
                selected_conversation_id=request.selected_conversation_id,
                period_days=request.period_days,
                thread_id=request.thread_id,
            ),
            current_user=current_user,
            db=db,
        )
    if target.agent_profile == AgentProfile.QUALITY_ASSURANCE.value:
        if request.release_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="release_id is required for Quality Assurance",
            )
        return await get_quality_brief(
            workspace_id=workspace_id,
            agent_workspace_id=target.id,
            request=QualityBriefRequest(
                message=request.message,
                release_id=request.release_id,
                selected_conversation_id=request.selected_conversation_id,
                thread_id=request.thread_id,
            ),
            current_user=current_user,
            db=db,
        )
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="This workspace agent profile is not supported by the unified router",
    )
