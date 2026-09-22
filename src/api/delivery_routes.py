"""Read-only Product Delivery API.

The route is deliberately separate from ``/chat`` until a shared model/runtime
adapter exists.  It executes the strict Delivery contract end-to-end using
only scoped DB facts and never enables a side effect.
"""

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.context_builder import AgentScopeDeniedError
from src.agents.contracts import (
    AgentInvocationRequest,
    AgentProfile,
    BusinessRole,
    PolicyDecision,
    RequestedScope,
    ToolResult,
    ToolResultStatus,
)
from src.agents.delivery_orchestration.contracts import (
    DeliveryExecutionMode,
    DeliveryIntent,
    DeliveryRoutingDecision,
    DeliverySpecialist,
)
from src.agents.delivery_orchestration.request_router import (
    constrain_delivery_route,
)
from src.agents.delivery_orchestration.semantic_router import resolve_delivery_route
from src.agents.delivery_orchestration.workspace_responder import build_workspace_only_response
from src.agents.policies.resource_guard import AgentResourceDeniedError, enforce_agent_resource_access
from src.agents.profiles.product_delivery_runner import (
    ProductDeliveryPreparationError,
    prepare_product_delivery_invocation,
    resolve_prepared_delivery_read_scope,
)
from src.agents.runtime import get_product_delivery_runtime
from src.agents.runtime.contracts import (
    AgentRuntimeRequest,
    AgentRuntimeStatus,
    RuntimeActor,
    RuntimeAuthorization,
    RuntimeTarget,
    snapshot_sha256,
)
from src.agents.schemas.delivery import (
    DeliveryCapacitySummary,
    DeliveryDecision,
    DeliveryDependency,
    DeliveryFlowMetrics,
    DeliveryItem,
    DeliveryPortfolioAssessment,
    DeliveryReleaseStatus,
    DeliveryRisk,
    DeliveryViewScope,
)
from src.agents.tools.delivery_analysis import (
    get_delivery_capacity_summary,
    get_delivery_flow_metrics,
    get_delivery_portfolio_health,
    get_delivery_risks,
)
from src.agents.tools.delivery_brief import as_delivery_brief_result, build_delivery_payload, to_workspace_brief
from src.auth.dependencies import get_current_user
from src.config import get_settings
from src.db.models import (
    AgentWorkspace,
    AgentWorkspaceMembership,
    Conversation,
    ConversationParticipant,
    DeliveryAgentRun,
    DeliveryAgentWorkflow,
    DeliveryCheckpointTask,
    DeliveryDecisionRecord,
    DeliveryDependencyRecord,
    DeliveryMilestone,
    DeliveryWorkflowEventRecord,
    Message,
    Task,
    User,
)
from src.db.session import get_db
from src.models.delivery_checkpoint_schemas import (
    DeliveryCheckpointAssessmentOut,
    DeliveryCheckpointCreateRequest,
    DeliveryCheckpointOut,
    DeliveryCheckpointQualityReviewRequest,
)
from src.models.delivery_schemas import (
    DeliveryBriefRequest,
    DeliveryCapabilitiesOut,
    DeliveryDashboardGroup,
    DeliveryDashboardGroupMember,
    DeliveryDashboardLastMessage,
    DeliveryDashboardMember,
    DeliveryDashboardOut,
    DeliveryDashboardWorkItem,
    DeliveryDashboardWorkStats,
    DeliveryDecisionCreateRequest,
    DeliveryDecisionOut,
    DeliveryDecisionStatusRequest,
    DeliveryDependencyCreateRequest,
    DeliveryDependencyOut,
    DeliveryDependencyStatusRequest,
    DeliveryGroupCapability,
    DeliveryTaskCreateRequest,
    DeliveryTaskReviewItemOut,
    DeliveryTaskReviewRequest,
)
from src.models.delivery_workflow_schemas import (
    DeliveryWorkflowCancelRequest,
    DeliveryWorkflowEventOut,
    DeliveryWorkflowOut,
    DeliveryWorkflowRunOut,
)
from src.models.task_schemas import TaskOut
from src.models.workspace_agent_schemas import (
    WorkspaceAgentMessageOut,
    WorkspaceAgentThreadSummaryOut,
)
from src.services import guardrail_service, reminder_service, usage_service
from src.services.audit_service import record_audit_event
from src.services.delivery_checkpoint_service import read_delivery_checkpoint_progress
from src.services.delivery_tool_gateway import DeliveryToolGateway
from src.services.delivery_workflow_service import (
    complete_delivery_workflow,
    create_delivery_workflow,
    fail_delivery_workflow,
    mark_delivery_workflow_running,
)
from src.services.delivery_workspace_service import DeliveryScopeError
from src.services.workspace_agent_memory_service import (
    WorkspaceAgentThreadDeniedError,
    append_turn,
    discard_thread,
    get_thread_messages,
    list_thread_summaries,
    load_history,
    resolve_thread,
)
from src.services.workspace_agent_memory_service import (
    delete_thread as delete_workspace_agent_thread,
)
from src.websocket.manager import manager

router = APIRouter()
logger = logging.getLogger(__name__)


async def _broadcast_delivery_progress(
    *,
    user_id: str,
    workspace_id: str,
    agent_workspace_id: str,
    request_id: str | None,
    phase: str,
    **payload,
) -> None:
    """Push non-authoritative execution telemetry to the requesting UI.

    Business results still come only from the signed runtime response. A broken
    WebSocket must never fail the underlying Delivery request.
    """

    if not request_id:
        return
    try:
        await manager.broadcast_to_users(
            [user_id],
            {
                "type": "workspace_agent_progress",
                "request_id": request_id,
                "workspace_id": workspace_id,
                "agent_workspace_id": agent_workspace_id,
                "phase": phase,
                "occurred_at": datetime.now(UTC).isoformat(),
                **payload,
            },
        )
    except Exception:  # noqa: BLE001 - telemetry is strictly best effort.
        logger.exception("Unable to broadcast Delivery progress", extra={"phase": phase})


def _enrich_dependency_rows(
    rows: list[dict[str, Any]],
    *,
    groups: list[dict[str, Any]],
    people: list[dict[str, Any]],
    work_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach business labels before dependency evidence reaches an LLM."""

    group_names = {str(item.get("id") or ""): str(item.get("name") or "Untitled group") for item in groups}
    people_names = {str(item.get("user_id") or ""): str(item.get("display_name") or "") for item in people}
    task_titles = {str(item.get("id") or ""): str(item.get("title") or "") for item in work_items}
    enriched: list[dict[str, Any]] = []
    for row in rows:
        source_group_id = next(
            (
                str(source.get("resource_id") or "")
                for source in row.get("sources", [])
                if isinstance(source, dict) and source.get("resource_type") == "conversation"
            ),
            "",
        )
        enriched.append(
            {
                **row,
                "group_name": group_names.get(source_group_id, "Untitled group"),
                "owner_name": people_names.get(str(row.get("assignee_id") or "")) or None,
                "predecessor_task_title": task_titles.get(str(row.get("predecessor_task_id") or "")) or None,
                "successor_task_title": task_titles.get(str(row.get("successor_task_id") or "")) or None,
            }
        )
    return enriched


def _enrich_work_item_rows(
    rows: list[dict[str, Any]],
    *,
    groups: list[dict[str, Any]],
    people: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach authorized business labels used by specialist artifacts."""

    group_names = {str(item.get("id") or ""): str(item.get("name") or "Untitled group") for item in groups}
    people_names = {str(item.get("user_id") or ""): str(item.get("display_name") or "") for item in people}
    enriched: list[dict[str, Any]] = []
    for row in rows:
        group_id = next(
            (
                str(source.get("resource_id") or "")
                for source in row.get("sources", [])
                if isinstance(source, dict) and source.get("resource_type") == "conversation"
            ),
            "",
        )
        enriched.append(
            {
                **row,
                "group_name": group_names.get(group_id, "Untitled group"),
                "owner_name": people_names.get(str(row.get("assignee_id") or row.get("owner_id") or "")) or None,
            }
        )
    return enriched


_DEPENDENCY_TRANSITIONS = {
    "open": frozenset({"blocked", "resolved", "invalidated"}),
    "blocked": frozenset({"open", "resolved", "invalidated"}),
    "resolved": frozenset({"open", "invalidated"}),
    "invalidated": frozenset(),
}
_DECISION_TRANSITIONS = {
    "pending": frozenset({"decided", "invalidated"}),
    "decided": frozenset({"superseded"}),
    "superseded": frozenset(),
    "invalidated": frozenset(),
}


async def _prepare_checkpoint_scope(
    db: AsyncSession,
    *,
    current_user: User,
    workspace_id: str,
    agent_workspace_id: str,
    selected_conversation_id: str | None = None,
):
    try:
        return await _prepare_delivery_scope(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            message="Manage the authorized Product Delivery checkpoint plan",
            selected_conversation_id=selected_conversation_id,
        )
    except (AgentScopeDeniedError, AgentResourceDeniedError, ProductDeliveryPreparationError, ValueError):
        raise HTTPException(status_code=403, detail="Delivery checkpoint is unavailable") from None


@router.post(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/checkpoints",
    response_model=DeliveryCheckpointOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_delivery_checkpoint(
    workspace_id: str,
    agent_workspace_id: str,
    request: DeliveryCheckpointCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeliveryCheckpointOut:
    prepared, scope = await _prepare_checkpoint_scope(
        db,
        current_user=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        selected_conversation_id=request.source_conversation_id,
    )
    if prepared.context.actor.business_role != BusinessRole.LEAD:
        raise HTTPException(status_code=403, detail="Only a Delivery Lead can define checkpoints")
    if request.source_conversation_id not in scope.effective_group_ids:
        raise HTTPException(status_code=404, detail="Source group was not found")
    tasks = list(
        (
            await db.execute(
                select(Task).where(
                    Task.id.in_(request.required_task_ids),
                    Task.workspace_id == workspace_id,
                    Task.agent_workspace_id == agent_workspace_id,
                    Task.conversation_id == request.source_conversation_id,
                    Task.status.not_in(("dismissed", "invalidated")),
                )
            )
        )
        .scalars()
        .all()
    )
    if {task.id for task in tasks} != set(request.required_task_ids):
        raise HTTPException(status_code=422, detail="Every checkpoint task must exist in the selected group")
    checkpoint = DeliveryMilestone(
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        conversation_id=request.source_conversation_id,
        title=request.title,
        status="pending",
        owner_id=current_user.id,
        due_at=request.due_at,
        plan_key=request.plan_key,
    )
    db.add(checkpoint)
    await db.flush()
    db.add_all(
        DeliveryCheckpointTask(
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            conversation_id=request.source_conversation_id,
            milestone_id=checkpoint.id,
            task_id=task_id,
            required=True,
            created_by_user_id=current_user.id,
        )
        for task_id in request.required_task_ids
    )
    await record_audit_event(
        db,
        actor=current_user,
        action="delivery_checkpoint.created",
        target_type="delivery_checkpoint",
        target_id=checkpoint.id,
        workspace_id=workspace_id,
        metadata={
            "agent_workspace_id": agent_workspace_id,
            "conversation_id": request.source_conversation_id,
            "plan_key": request.plan_key,
            "required_task_count": len(request.required_task_ids),
        },
    )
    await db.commit()
    await db.refresh(checkpoint)
    return DeliveryCheckpointOut.model_validate(checkpoint)


@router.get(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/checkpoints",
    response_model=list[DeliveryCheckpointAssessmentOut],
)
async def list_delivery_checkpoint_progress(
    workspace_id: str,
    agent_workspace_id: str,
    selected_conversation_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DeliveryCheckpointAssessmentOut]:
    _prepared, scope = await _prepare_checkpoint_scope(
        db,
        current_user=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        selected_conversation_id=selected_conversation_id,
    )
    result = await read_delivery_checkpoint_progress(db, scope=scope)
    return [DeliveryCheckpointAssessmentOut.model_validate(item) for item in result.payload["checkpoint_progress"]]


@router.patch(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/checkpoints/{checkpoint_id}/quality-review",
    response_model=DeliveryCheckpointOut,
)
async def review_delivery_checkpoint_quality(
    workspace_id: str,
    agent_workspace_id: str,
    checkpoint_id: str,
    request: DeliveryCheckpointQualityReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeliveryCheckpointOut:
    prepared, scope = await _prepare_checkpoint_scope(
        db,
        current_user=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
    )
    if prepared.context.actor.business_role != BusinessRole.LEAD:
        raise HTTPException(status_code=403, detail="Only a Delivery Lead can review checkpoint quality")
    checkpoint = (
        await db.execute(
            select(DeliveryMilestone).where(
                DeliveryMilestone.id == checkpoint_id,
                DeliveryMilestone.workspace_id == workspace_id,
                DeliveryMilestone.agent_workspace_id == agent_workspace_id,
                DeliveryMilestone.conversation_id.in_(scope.effective_group_ids),
            )
        )
    ).scalar_one_or_none()
    if checkpoint is None:
        raise HTTPException(status_code=404, detail="Delivery checkpoint not found")
    now = datetime.now(UTC)
    values = {
        "quality_review_status": request.quality_review_status,
        "quality_review_note": request.quality_review_note,
        "quality_reviewed_by_user_id": current_user.id if request.quality_review_status != "pending" else None,
        "quality_reviewed_at": now if request.quality_review_status != "pending" else None,
        "row_version": DeliveryMilestone.row_version + 1,
        "updated_at": now,
    }
    updated = await db.execute(
        update(DeliveryMilestone)
        .where(
            DeliveryMilestone.id == checkpoint.id,
            DeliveryMilestone.row_version == request.expected_row_version,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if updated.rowcount != 1:
        raise HTTPException(status_code=409, detail="Checkpoint changed; reload before reviewing")
    await record_audit_event(
        db,
        actor=current_user,
        action="delivery_checkpoint.quality_reviewed",
        target_type="delivery_checkpoint",
        target_id=checkpoint.id,
        workspace_id=workspace_id,
        metadata={
            "agent_workspace_id": agent_workspace_id,
            "quality_review_status": request.quality_review_status,
        },
    )
    await db.commit()
    await db.refresh(checkpoint)
    return DeliveryCheckpointOut.model_validate(checkpoint)


def _enabled_delivery_specialists(settings) -> frozenset[DeliverySpecialist]:
    flags = {
        DeliverySpecialist.TASK_INTELLIGENCE: settings.product_delivery_task_specialist_enabled,
        DeliverySpecialist.RISK_DEPENDENCY: settings.product_delivery_risk_specialist_enabled,
        DeliverySpecialist.PLANNING_FORECAST: settings.product_delivery_planning_specialist_enabled,
        DeliverySpecialist.EVIDENCE_KNOWLEDGE: settings.product_delivery_evidence_specialist_enabled,
        DeliverySpecialist.CAPACITY_FLOW: settings.product_delivery_capacity_specialist_enabled,
    }
    return frozenset(specialist for specialist, enabled in flags.items() if enabled)


async def _record_delivery_audit(
    db: AsyncSession,
    *,
    actor: User,
    workspace_id: str,
    agent_workspace_id: str,
    action: str,
    metadata: dict[str, object],
) -> None:
    await record_audit_event(
        db,
        actor=actor,
        action=action,
        target_type="agent_workspace",
        target_id=agent_workspace_id,
        workspace_id=workspace_id,
        metadata=metadata,
    )
    await db.commit()


async def _prepare_delivery_scope(
    db: AsyncSession,
    *,
    current_user: User,
    workspace_id: str,
    agent_workspace_id: str,
    message: str,
    selected_conversation_id: str | None,
):
    invocation = AgentInvocationRequest(
        message=message,
        requested_scope=RequestedScope.WORKSPACE,
        target_agent_workspace_id=agent_workspace_id,
    )
    prepared = await prepare_product_delivery_invocation(
        db,
        user_id=current_user.id,
        organization_workspace_id=workspace_id,
        invocation=invocation,
        settings=get_settings(),
    )
    try:
        scope = await resolve_prepared_delivery_read_scope(
            db,
            prepared=prepared,
            requested_conversation_id=selected_conversation_id,
        )
    except DeliveryScopeError as exc:
        raise ProductDeliveryPreparationError("Delivery source scope is unavailable") from exc
    return prepared, scope


def _delivery_thread_scope_hash(*, consent_scope_hash: str | None, scope) -> str:
    """Bind conversational memory to the exact server-resolved Delivery view.

    Consent alone is insufficient because a Lead can switch between the whole
    workspace and one group without changing the consent grant.  Including the
    effective groups prevents history from one selector scope entering another.
    """

    canonical = "|".join(
        (
            "delivery-thread-scope-v1",
            consent_scope_hash or "",
            scope.view_scope.value,
            *sorted(scope.effective_group_ids),
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@router.get(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/threads",
    response_model=list[WorkspaceAgentThreadSummaryOut],
)
async def list_delivery_threads(
    workspace_id: str,
    agent_workspace_id: str,
    selected_conversation_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WorkspaceAgentThreadSummaryOut]:
    """List the caller's resumable Product Delivery short-term conversations."""

    prepared, scope = await _prepare_delivery_scope(
        db,
        current_user=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        message="Mở lịch sử trò chuyện Product Delivery.",
        selected_conversation_id=selected_conversation_id,
    )
    scope_hash = _delivery_thread_scope_hash(
        consent_scope_hash=prepared.context.authorization.consent_scope_hash,
        scope=scope,
    )
    rows = await list_thread_summaries(
        db,
        organization_workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        owner_id=current_user.id,
        profile=AgentProfile.PRODUCT_DELIVERY,
        authorization_scope_hash=scope_hash,
    )
    return [WorkspaceAgentThreadSummaryOut.model_validate(row) for row in rows]


@router.get(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/threads/{thread_id}/messages",
    response_model=list[WorkspaceAgentMessageOut],
)
async def read_delivery_thread_messages(
    workspace_id: str,
    agent_workspace_id: str,
    thread_id: str,
    selected_conversation_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WorkspaceAgentMessageOut]:
    """Open one thread only when it still matches the caller's current authorization scope."""

    prepared, scope = await _prepare_delivery_scope(
        db,
        current_user=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        message="Mở lại cuộc trò chuyện Product Delivery.",
        selected_conversation_id=selected_conversation_id,
    )
    scope_hash = _delivery_thread_scope_hash(
        consent_scope_hash=prepared.context.authorization.consent_scope_hash,
        scope=scope,
    )
    try:
        rows = await get_thread_messages(
            db,
            thread_id=thread_id,
            organization_workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            owner_id=current_user.id,
            profile=AgentProfile.PRODUCT_DELIVERY,
            authorization_scope_hash=scope_hash,
        )
    except WorkspaceAgentThreadDeniedError as exc:
        raise HTTPException(status_code=404, detail="Conversation history is unavailable") from exc
    workflow_ids = tuple(dict.fromkeys(row.workflow_id for row in rows if row.workflow_id))
    workflows_by_id: dict[str, DeliveryAgentWorkflow] = {}
    runs_by_workflow: dict[str, list[DeliveryAgentRun]] = {}
    if workflow_ids:
        workflows = list(
            (await db.execute(select(DeliveryAgentWorkflow).where(DeliveryAgentWorkflow.id.in_(workflow_ids))))
            .scalars()
            .all()
        )
        workflows_by_id = {workflow.id: workflow for workflow in workflows}
        runs = list(
            (
                await db.execute(
                    select(DeliveryAgentRun)
                    .where(DeliveryAgentRun.workflow_id.in_(workflow_ids))
                    .order_by(DeliveryAgentRun.created_at.asc(), DeliveryAgentRun.id.asc())
                )
            )
            .scalars()
            .all()
        )
        for run in runs:
            runs_by_workflow.setdefault(run.workflow_id, []).append(run)

    def run_history(workflow_id: str | None) -> dict[str, Any] | None:
        workflow = workflows_by_id.get(workflow_id or "")
        if workflow is None:
            return None
        planned_runs = runs_by_workflow.get(workflow.id, [])
        specialists = [run for run in planned_runs if run.specialist != "supervisor"]
        supervisor = next((run for run in planned_runs if run.specialist == "supervisor"), None)
        result_json = workflow.result_json or {}
        planned_order = {specialist: index for index, specialist in enumerate(result_json.get("specialists", []))}
        specialists.sort(
            key=lambda run: (
                planned_order.get(run.specialist, len(planned_order)),
                run.created_at,
                run.id,
            )
        )
        communication = result_json.get("agent_communication", {})
        steps: list[dict[str, Any]] = [
            {
                "kind": "routing",
                "status": "succeeded",
                "title": "Phân tích yêu cầu và lập workflow",
                "detail": f"Đã chọn {workflow.execution_mode} cho intent {workflow.workflow_type}.",
                "started_at": workflow.created_at,
                "completed_at": workflow.created_at,
            }
        ]
        steps.extend(
            {
                "kind": "specialist",
                "specialist": run.specialist,
                "status": run.status,
                "title": run.specialist,
                "detail": "",
                "depends_on": list((run.lineage_json or {}).get("depends_on", [])),
                "tools": list(
                    communication.get(run.specialist, {}).get("tool_calls")
                    or (run.lineage_json or {}).get("allowed_tools", [])
                ),
                "model_name": run.model_name,
                "started_at": run.started_at,
                "completed_at": run.completed_at,
                "error_code": run.error_code,
            }
            for run in specialists
        )
        if supervisor is not None:
            steps.append(
                {
                    "kind": "synthesis",
                    "status": supervisor.status,
                    "title": "Workspace Agent tổng hợp kết quả",
                    "detail": f"Nhận kết quả từ {len(specialists)} agent chuyên biệt.",
                    "model_name": supervisor.model_name,
                    "started_at": supervisor.started_at,
                    "completed_at": supervisor.completed_at,
                    "error_code": supervisor.error_code,
                }
            )
        return {
            "workflow_id": workflow.id,
            "intent": workflow.workflow_type,
            "execution_mode": workflow.execution_mode,
            "status": workflow.status,
            "created_at": workflow.created_at,
            "completed_at": workflow.completed_at,
            "steps": steps,
        }

    return [
        WorkspaceAgentMessageOut(
            id=row.id,
            sequence_number=row.sequence_number,
            role=row.role,
            content=row.content,
            created_at=row.created_at,
            run_history=run_history(row.workflow_id),
        )
        for row in rows
    ]


@router.delete(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/threads/{thread_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_delivery_thread(
    workspace_id: str,
    agent_workspace_id: str,
    thread_id: str,
    selected_conversation_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete only the caller's private Delivery Agent chat history in the active scope."""

    prepared, scope = await _prepare_delivery_scope(
        db,
        current_user=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        message="Xóa lịch sử trò chuyện Product Delivery.",
        selected_conversation_id=selected_conversation_id,
    )
    scope_hash = _delivery_thread_scope_hash(
        consent_scope_hash=prepared.context.authorization.consent_scope_hash,
        scope=scope,
    )
    try:
        await delete_workspace_agent_thread(
            db,
            thread_id=thread_id,
            organization_workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            owner_id=current_user.id,
            profile=AgentProfile.PRODUCT_DELIVERY,
            authorization_scope_hash=scope_hash,
        )
    except WorkspaceAgentThreadDeniedError as exc:
        raise HTTPException(status_code=404, detail="Conversation history is unavailable") from exc
    await record_audit_event(
        db,
        current_user,
        action="workspace_agent_thread.deleted",
        target_type="workspace_agent_thread",
        target_id=thread_id,
        workspace_id=workspace_id,
        metadata={
            "agent_workspace_id": agent_workspace_id,
            "agent_profile": AgentProfile.PRODUCT_DELIVERY.value,
            "scope": scope.view_scope.value,
        },
    )
    await db.commit()


async def _respond_without_business_data(
    db: AsyncSession,
    *,
    current_user: User,
    workspace_id: str,
    agent_workspace_id: str,
    request: DeliveryBriefRequest,
    prepared,
    scope,
    routing,
    answer_override: str | None = None,
    memory_thread=None,
    history=None,
) -> ToolResult:
    """Handle conversational turns without tools, snapshots or specialist runs."""

    thread_scope_hash = _delivery_thread_scope_hash(
        consent_scope_hash=prepared.context.authorization.consent_scope_hash,
        scope=scope,
    )
    if memory_thread is None:
        try:
            memory_thread = await resolve_thread(
                db,
                thread_id=request.thread_id,
                organization_workspace_id=workspace_id,
                agent_workspace_id=agent_workspace_id,
                owner_id=current_user.id,
                profile=AgentProfile.PRODUCT_DELIVERY,
                authorization_scope_hash=thread_scope_hash,
            )
        except WorkspaceAgentThreadDeniedError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Delivery memory thread is unavailable",
            ) from None

    fallback_answer = build_workspace_only_response(
        intent=routing.intent,
        role=prepared.context.actor.business_role,
        authorized_group_count=len(scope.effective_group_ids),
    )
    clarification_hint = routing.clarification_question or ""
    if routing.intent == DeliveryIntent.CLARIFICATION and answer_override:
        clarification_hint = answer_override
        answer_override = None
    if routing.intent == DeliveryIntent.POLICY_REFUSAL and answer_override is None:
        answer_override = fallback_answer
    answer = answer_override or fallback_answer
    llm_calls = 0
    conversation_llm_attempts = 0
    conversation_llm_successes = 0
    conversation_model_attempts: list[dict] = []
    synthesis_model = ""
    synthesis_fallback = False
    fallback_reason = ""
    result_status = ToolResultStatus.SUCCESS
    data_gaps: tuple[str, ...] = ()

    # Policy refusals remain deterministic and never send hostile input to a
    # model. Other authorized conversational turns use exactly one Workspace
    # LLM with no specialist and no business-data snapshot.
    if answer_override is None:
        if history is None:
            history = await load_history(db, thread=memory_thread)
        now = datetime.now(UTC)
        conversation_snapshot = ToolResult(
            status=ToolResultStatus.SUCCESS,
            payload={
                "workspace_conversation_context": {
                    "authorized_group_count": len(scope.effective_group_ids),
                    "clarification_hint": clarification_hint,
                }
            },
        )
        try:
            runtime_response = await get_product_delivery_runtime().run(
                AgentRuntimeRequest(
                    run_id=uuid4().hex,
                    trace_id=prepared.context.trace_id,
                    requested_at=now,
                    target=RuntimeTarget(
                        organization_workspace_id=workspace_id,
                        agent_workspace_id=agent_workspace_id,
                        profile=AgentProfile.PRODUCT_DELIVERY,
                        runtime_version=get_settings().workspace_agent_runtime_version,
                    ),
                    actor=RuntimeActor(
                        user_id=current_user.id,
                        business_role=prepared.context.actor.business_role,
                    ),
                    authorization=RuntimeAuthorization(
                        decision=PolicyDecision.ALLOW,
                        authorized_at=now,
                        expires_at=now + timedelta(minutes=1),
                        snapshot_sha256=snapshot_sha256(conversation_snapshot),
                        scope_hash=prepared.context.authorization.consent_scope_hash,
                    ),
                    message=request.message,
                    history=history,
                    snapshot=conversation_snapshot,
                    interaction_mode="workspace_conversation",
                    interaction_intent=routing.intent.value,
                    routing_plan_version=routing.plan_version,
                )
            )
            answer = runtime_response.answer
            llm_calls = runtime_response.runtime.llm_calls
            conversation_llm_attempts = runtime_response.runtime.llm_attempts
            conversation_llm_successes = runtime_response.runtime.llm_successes
            conversation_model_attempts = list(runtime_response.runtime.model_attempts)
            synthesis_model = runtime_response.runtime.model_name
            synthesis_fallback = runtime_response.runtime.synthesis_fallback
            fallback_reason = runtime_response.runtime.fallback_reason
            if synthesis_fallback:
                result_status = ToolResultStatus.PARTIAL
                data_gaps = ("LLM_SYNTHESIS_UNAVAILABLE",)
            await usage_service.log_usage(
                provider=runtime_response.runtime.model_provider,
                model=runtime_response.runtime.model_name,
                usage_metadata=runtime_response.runtime.synthesis_usage.model_dump(),
                user_id=current_user.id,
                workspace_id=workspace_id,
            )
        except Exception:  # noqa: BLE001 - keep the policy-owned fallback available.
            logger.exception(
                "Workspace conversation runtime failed",
                extra={"trace_id": prepared.context.trace_id},
            )
            llm_calls = 1
            conversation_llm_attempts = 1
            synthesis_fallback = True
            fallback_reason = "WORKSPACE_CONVERSATION_RUNTIME_FAILED"
            result_status = ToolResultStatus.PARTIAL
            data_gaps = ("LLM_SYNTHESIS_UNAVAILABLE",)
    await append_turn(
        db,
        thread=memory_thread,
        user_message=request.message,
        assistant_message=answer,
    )
    response_thread_id = memory_thread.id if request.persist_history else None
    if not request.persist_history:
        await discard_thread(db, thread=memory_thread)
    routing_model_attempts = [
        attempt.model_dump(mode="json") for attempt in routing.routing_llm_attempts
    ]
    routing_llm_successes = sum(
        attempt.status == "succeeded" for attempt in routing.routing_llm_attempts
    )
    orchestration = {
        "execution_mode": DeliveryExecutionMode.WORKSPACE_ONLY.value,
        "intent": routing.intent.value,
        "plan_version": routing.plan_version,
        "workflow_id": None,
        "workflow_status": "not_applicable",
        "specialists_requested": [],
        "specialists_completed": [],
        "specialists_failed": [],
        "specialist_fallbacks": {},
        "evidence_branch_executed": False,
        "llm_calls": llm_calls,
        "llm_attempted": bool(conversation_llm_attempts or routing.routing_llm_attempts),
        "llm_attempts_total": conversation_llm_attempts + len(routing.routing_llm_attempts),
        "llm_successes_total": conversation_llm_successes + routing_llm_successes,
        "routing_strategy": routing.routing_strategy,
        "routing_llm_attempts": routing_model_attempts,
        "routing_llm_successes": routing_llm_successes,
        "conversation_llm_attempts": conversation_llm_attempts,
        "conversation_llm_successes": conversation_llm_successes,
        "conversation_model_attempts": conversation_model_attempts,
        "synthesis_model": synthesis_model,
        "synthesis_fallback": synthesis_fallback,
        "fallback_reason": fallback_reason,
        "specialist_model": "",
        "data_accessed": False,
    }
    await _record_delivery_audit(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        action="delivery_conversation.responded",
        metadata={
            "profile": "product_delivery",
            "view_scope": scope.view_scope.value,
            "intent": routing.intent.value,
            "execution_mode": DeliveryExecutionMode.WORKSPACE_ONLY.value,
            "specialist_count": 0,
            "llm_calls": llm_calls,
            "llm_attempted": bool(conversation_llm_attempts or routing.routing_llm_attempts),
            "routing_strategy": routing.routing_strategy,
            "routing_llm_attempts": routing_model_attempts,
            "conversation_llm_attempts": conversation_llm_attempts,
            "synthesis_model": synthesis_model,
            "synthesis_fallback": synthesis_fallback,
            "fallback_reason": fallback_reason,
            "data_accessed": False,
        },
    )
    return ToolResult(
        status=result_status,
        payload={
            "agent_response": answer,
            "orchestration": orchestration,
            "specialist_results": [],
            "thread_id": response_thread_id,
        },
        data_gaps=data_gaps,
    )


_DASHBOARD_TERMINAL_STATUSES = frozenset({"completed", "dismissed", "invalidated"})


def _dashboard_timestamp(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _dashboard_work_stats(items: list[Task] | list[DeliveryMilestone], *, now: datetime) -> DeliveryDashboardWorkStats:
    active = [item for item in items if item.status not in {"dismissed", "invalidated"}]
    completed = sum(item.status == "completed" for item in active)
    overdue = sum(
        item.status not in _DASHBOARD_TERMINAL_STATUSES
        and item.due_at is not None
        and _dashboard_timestamp(item.due_at) < now
        for item in active
    )
    due_soon = sum(
        item.status not in _DASHBOARD_TERMINAL_STATUSES
        and item.due_at is not None
        and now <= _dashboard_timestamp(item.due_at) <= now + timedelta(days=7)
        for item in active
    )
    total = len(active)
    return DeliveryDashboardWorkStats(
        total=total,
        completed=completed,
        in_progress=sum(item.status == "in_progress" for item in active),
        pending=sum(item.status in {"pending", "suggested"} for item in active),
        blocked=sum(item.status == "blocked" for item in active),
        overdue=overdue,
        due_soon=due_soon,
        unassigned=sum(item.owner_id is None for item in active),
        completion_percent=round((completed / total) * 100) if total else 0,
        submitted=sum(item.status == "submitted" for item in active),
        changes_requested=sum(item.status == "changes_requested" for item in active),
    )


def _dashboard_work_item(item: Task | DeliveryMilestone, *, people_by_id: dict[str, User]) -> DeliveryDashboardWorkItem:
    assignee = people_by_id.get(item.owner_id) if item.owner_id else None
    return DeliveryDashboardWorkItem(
        id=item.id,
        title=item.title,
        status=item.status,
        assignee_id=item.owner_id,
        assignee_name=assignee.display_name if assignee else None,
        due_at=_dashboard_timestamp(item.due_at) if item.due_at is not None else None,
        blocked_reason=item.blocked_reason,
        requires_review=bool(getattr(item, "requires_review", False)),
        submission_note=getattr(item, "submission_note", None),
        evidence_urls=list(getattr(item, "evidence_urls", None) or []),
        submitted_at=getattr(item, "submitted_at", None),
        review_note=getattr(item, "review_note", None),
    )


@router.get(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/capabilities",
    response_model=DeliveryCapabilitiesOut,
)
async def get_delivery_capabilities(
    workspace_id: str,
    agent_workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeliveryCapabilitiesOut:
    """Return the actor's explicit role/capability envelope and authorized groups."""

    try:
        prepared, scope = await _prepare_delivery_scope(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            message="List available Delivery groups",
            selected_conversation_id=None,
        )
        for resource_id in scope.effective_group_ids:
            await enforce_agent_resource_access(db, context=prepared.context, resource_id=resource_id)
    except (AgentScopeDeniedError, AgentResourceDeniedError, ProductDeliveryPreparationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delivery access is unavailable for this request",
        ) from None

    rows = (
        await db.execute(
            select(Conversation.id, Conversation.name)
            .where(
                Conversation.workspace_id == workspace_id,
                Conversation.type == "group",
                Conversation.id.in_(scope.effective_group_ids),
            )
            .order_by(Conversation.name.asc(), Conversation.id.asc())
        )
    ).all()
    is_lead = prepared.context.actor.business_role == BusinessRole.LEAD
    return DeliveryCapabilitiesOut(
        current_user_business_role="lead" if is_lead else "member",
        view_scope="workspace" if is_lead else "member",
        can_select_group=bool(scope.effective_group_ids),
        can_manage_control_plane=is_lead,
        can_manage_release_handoffs=is_lead,
        can_update_own_tasks=True,
        can_propose_actions=True,
        can_create_team_tasks=is_lead,
        can_review_task_submissions=is_lead,
        groups=[DeliveryGroupCapability(id=row.id, name=row.name or "Untitled group") for row in rows],
    )


@router.post(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/tasks",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_delivery_team_task(
    workspace_id: str,
    agent_workspace_id: str,
    request: DeliveryTaskCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    """Let a Delivery Lead create an explicit, scoped assignment for a group member."""

    prepared, scope = await _prepare_checkpoint_scope(
        db,
        current_user=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        selected_conversation_id=request.source_conversation_id,
    )
    if prepared.context.actor.business_role != BusinessRole.LEAD:
        raise HTTPException(status_code=403, detail="Only a Delivery Lead can assign team tasks")
    if request.source_conversation_id not in scope.effective_group_ids:
        raise HTTPException(status_code=404, detail="Source group was not found")
    membership = await db.scalar(
        select(AgentWorkspaceMembership).where(
            AgentWorkspaceMembership.agent_workspace_id == agent_workspace_id,
            AgentWorkspaceMembership.user_id == request.owner_id,
            AgentWorkspaceMembership.status == "active",
            AgentWorkspaceMembership.business_role.in_(("lead", "member")),
        )
    )
    participant = await db.scalar(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == request.source_conversation_id,
            ConversationParticipant.user_id == request.owner_id,
        )
    )
    owner = await db.get(User, request.owner_id)
    if membership is None or participant is None or owner is None or not owner.is_active:
        raise HTTPException(status_code=422, detail="Task owner must be an active member of the selected group")
    task = Task(
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        conversation_id=request.source_conversation_id,
        owner_id=request.owner_id,
        title=request.title,
        due_at=request.due_at,
        priority=request.priority,
        status="pending",
        source="manual",
        requires_review=request.requires_review,
    )
    db.add(task)
    await db.flush()
    await record_audit_event(
        db,
        actor=current_user,
        action="delivery_task.created",
        target_type="task",
        target_id=task.id,
        workspace_id=workspace_id,
        metadata={
            "agent_workspace_id": agent_workspace_id,
            "conversation_id": request.source_conversation_id,
            "owner_id": request.owner_id,
            "requires_review": request.requires_review,
        },
    )
    await db.commit()
    await db.refresh(task)
    await reminder_service.reconcile_task_reminder(task.id)
    output = TaskOut.model_validate(task)
    await manager.broadcast_to_users(
        list({current_user.id, task.owner_id}),
        {"type": "task_created", "task": output.model_dump(mode="json")},
    )
    return output


@router.get(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/task-reviews",
    response_model=list[DeliveryTaskReviewItemOut],
)
async def list_delivery_task_reviews(
    workspace_id: str,
    agent_workspace_id: str,
    selected_conversation_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DeliveryTaskReviewItemOut]:
    prepared, scope = await _prepare_checkpoint_scope(
        db,
        current_user=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        selected_conversation_id=selected_conversation_id,
    )
    if prepared.context.actor.business_role != BusinessRole.LEAD:
        raise HTTPException(status_code=403, detail="Only a Delivery Lead can review task submissions")
    rows = (
        await db.execute(
            select(Task, User, Conversation)
            .join(User, User.id == Task.owner_id)
            .join(Conversation, Conversation.id == Task.conversation_id)
            .where(
                Task.workspace_id == workspace_id,
                Task.agent_workspace_id == agent_workspace_id,
                Task.conversation_id.in_(scope.effective_group_ids),
                Task.requires_review.is_(True),
                Task.status == "submitted",
            )
            .order_by(Task.submitted_at.asc(), Task.due_at.asc(), Task.id.asc())
        )
    ).all()
    return [
        DeliveryTaskReviewItemOut(
            id=task.id,
            conversation_id=conversation.id,
            conversation_name=conversation.name or "Untitled group",
            owner_id=owner.id,
            owner_name=owner.display_name,
            title=task.title,
            priority=task.priority,
            status=task.status,
            due_at=task.due_at,
            submission_note=task.submission_note,
            evidence_urls=list(task.evidence_urls or []),
            submitted_at=task.submitted_at,
            review_note=task.review_note,
            row_version=task.row_version,
        )
        for task, owner, conversation in rows
    ]


@router.patch(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/tasks/{task_id}/review",
    response_model=TaskOut,
)
async def review_delivery_task_submission(
    workspace_id: str,
    agent_workspace_id: str,
    task_id: str,
    request: DeliveryTaskReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    prepared, scope = await _prepare_checkpoint_scope(
        db,
        current_user=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
    )
    if prepared.context.actor.business_role != BusinessRole.LEAD:
        raise HTTPException(status_code=403, detail="Only a Delivery Lead can review task submissions")
    task = await db.scalar(
        select(Task).where(
            Task.id == task_id,
            Task.workspace_id == workspace_id,
            Task.agent_workspace_id == agent_workspace_id,
            Task.conversation_id.in_(scope.effective_group_ids),
            Task.requires_review.is_(True),
        )
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task submission not found")
    if task.status != "submitted":
        raise HTTPException(status_code=409, detail="Only submitted tasks can be reviewed")
    now = datetime.now(UTC)
    accepted = request.decision == "accepted"
    result = await db.execute(
        update(Task)
        .where(Task.id == task.id, Task.row_version == request.expected_row_version, Task.status == "submitted")
        .values(
            status="completed" if accepted else "changes_requested",
            reviewed_by_user_id=current_user.id,
            reviewed_at=now,
            review_note=request.review_note,
            completed_at=now if accepted else None,
            row_version=Task.row_version + 1,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail="Task changed; reload before reviewing")
    await record_audit_event(
        db,
        actor=current_user,
        action="delivery_task.reviewed",
        target_type="task",
        target_id=task.id,
        workspace_id=workspace_id,
        metadata={
            "agent_workspace_id": agent_workspace_id,
            "decision": request.decision,
            "has_review_note": bool(request.review_note),
        },
    )
    await db.commit()
    await db.refresh(task)
    await reminder_service.reconcile_task_reminder(task.id)
    reviewed = task
    output = TaskOut.model_validate(reviewed)
    await manager.broadcast_to_users(
        list({current_user.id, reviewed.owner_id}),
        {"type": "task_reviewed", "task": output.model_dump(mode="json")},
    )
    return output


@router.get(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/release-targets",
    response_model=list[DeliveryGroupCapability],
)
async def get_delivery_release_targets(
    workspace_id: str,
    agent_workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DeliveryGroupCapability]:
    try:
        prepared, _scope = await _prepare_delivery_scope(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            message="List Quality handoff targets",
            selected_conversation_id=None,
        )
        if prepared.context.actor.business_role != BusinessRole.LEAD:
            raise HTTPException(status_code=403, detail="Release targets are unavailable")
    except (AgentScopeDeniedError, AgentResourceDeniedError, ProductDeliveryPreparationError):
        raise HTTPException(status_code=403, detail="Release targets are unavailable") from None
    rows = (
        await db.execute(
            select(AgentWorkspace.id, AgentWorkspace.name)
            .where(
                AgentWorkspace.organization_workspace_id == workspace_id,
                AgentWorkspace.agent_profile == AgentProfile.QUALITY_ASSURANCE.value,
                AgentWorkspace.status == "active",
            )
            .order_by(AgentWorkspace.name.asc(), AgentWorkspace.id.asc())
        )
    ).all()
    return [DeliveryGroupCapability(id=row.id, name=row.name or "Quality Assurance") for row in rows]


@router.get(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/dashboard",
    response_model=DeliveryDashboardOut,
)
async def get_delivery_dashboard(
    workspace_id: str,
    agent_workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeliveryDashboardOut:
    """Return a deterministic, role-scoped workspace dashboard without invoking the LLM."""

    try:
        prepared, scope = await _prepare_delivery_scope(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            message="Load Product Delivery workspace dashboard",
            selected_conversation_id=None,
        )
        for resource_id in scope.effective_group_ids:
            await enforce_agent_resource_access(db, context=prepared.context, resource_id=resource_id)
    except (AgentScopeDeniedError, AgentResourceDeniedError, ProductDeliveryPreparationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delivery access is unavailable for this request",
        ) from None

    if prepared.context.actor.business_role not in {BusinessRole.LEAD, BusinessRole.MEMBER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delivery access is unavailable for this request",
        )

    now = datetime.now(UTC)
    group_ids = tuple(scope.effective_group_ids)
    empty_stats = _dashboard_work_stats([], now=now)
    if not group_ids:
        return DeliveryDashboardOut(
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            current_user_business_role=prepared.context.actor.business_role.value,
            total_groups=0,
            total_members=0,
            blocked_groups=0,
            at_risk_groups=0,
            task_stats=empty_stats,
            milestone_stats=empty_stats,
            members=[],
            groups=[],
            generated_at=now,
        )

    conversations = list(
        (
            await db.execute(
                select(Conversation)
                .where(
                    Conversation.workspace_id == workspace_id,
                    Conversation.type == "group",
                    Conversation.id.in_(group_ids),
                )
                .order_by(Conversation.name.asc(), Conversation.id.asc())
            )
        )
        .scalars()
        .all()
    )
    participant_rows = list(
        (
            await db.execute(
                select(ConversationParticipant, User)
                .join(User, User.id == ConversationParticipant.user_id)
                .where(
                    ConversationParticipant.conversation_id.in_(group_ids),
                    ConversationParticipant.principal_kind == "workspace_user",
                    ConversationParticipant.revoked_at.is_(None),
                    User.is_active.is_(True),
                )
                .order_by(User.display_name.asc(), User.id.asc())
            )
        ).all()
    )
    people_by_id = {user.id: user for _, user in participant_rows}
    person_ids = tuple(people_by_id)
    membership_rows = (
        (
            await db.execute(
                select(AgentWorkspaceMembership).where(
                    AgentWorkspaceMembership.agent_workspace_id == agent_workspace_id,
                    AgentWorkspaceMembership.user_id.in_(person_ids),
                    AgentWorkspaceMembership.status == "active",
                )
            )
        )
        .scalars()
        .all()
        if person_ids
        else []
    )
    business_roles = {membership.user_id: membership.business_role for membership in membership_rows}

    task_statement = select(Task).where(
        Task.workspace_id == workspace_id,
        Task.agent_workspace_id == agent_workspace_id,
        Task.conversation_id.in_(group_ids),
    )
    milestone_statement = select(DeliveryMilestone).where(
        DeliveryMilestone.workspace_id == workspace_id,
        DeliveryMilestone.agent_workspace_id == agent_workspace_id,
        DeliveryMilestone.conversation_id.in_(group_ids),
    )
    if scope.view_scope == DeliveryViewScope.MEMBER:
        task_statement = task_statement.where(Task.owner_id == current_user.id)
        milestone_statement = milestone_statement.where(DeliveryMilestone.owner_id == current_user.id)
    tasks = list(
        (await db.execute(task_statement.order_by(Task.due_at.is_(None), Task.due_at.asc(), Task.id.asc())))
        .scalars()
        .all()
    )
    milestones = list(
        (
            await db.execute(
                milestone_statement.order_by(
                    DeliveryMilestone.due_at.is_(None),
                    DeliveryMilestone.due_at.asc(),
                    DeliveryMilestone.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    message_rows = list(
        (
            await db.execute(
                select(Message, User)
                .join(User, User.id == Message.sender_id)
                .where(Message.conversation_id.in_(group_ids))
                .order_by(Message.created_at.desc(), Message.id.desc())
            )
        ).all()
    )

    participants_by_group: dict[str, list[tuple[ConversationParticipant, User]]] = {
        group_id: [] for group_id in group_ids
    }
    member_groups: dict[str, list[DeliveryGroupCapability]] = {user_id: [] for user_id in person_ids}
    group_names = {conversation.id: conversation.name or "Untitled group" for conversation in conversations}
    for participant, user in participant_rows:
        participants_by_group.setdefault(participant.conversation_id, []).append((participant, user))
        member_groups[user.id].append(
            DeliveryGroupCapability(
                id=participant.conversation_id,
                name=group_names.get(participant.conversation_id, "Untitled group"),
            )
        )

    tasks_by_group: dict[str, list[Task]] = {group_id: [] for group_id in group_ids}
    milestones_by_group: dict[str, list[DeliveryMilestone]] = {group_id: [] for group_id in group_ids}
    for task in tasks:
        if task.conversation_id is not None:
            tasks_by_group.setdefault(task.conversation_id, []).append(task)
    for milestone in milestones:
        milestones_by_group.setdefault(milestone.conversation_id, []).append(milestone)

    message_count_by_group = {group_id: 0 for group_id in group_ids}
    last_message_by_group: dict[str, tuple[Message, User]] = {}
    for message, sender in message_rows:
        message_count_by_group[message.conversation_id] = message_count_by_group.get(message.conversation_id, 0) + 1
        last_message_by_group.setdefault(message.conversation_id, (message, sender))

    dashboard_groups: list[DeliveryDashboardGroup] = []
    blocked_groups = 0
    at_risk_groups = 0
    for conversation in conversations:
        group_tasks = tasks_by_group.get(conversation.id, [])
        group_milestones = milestones_by_group.get(conversation.id, [])
        task_stats = _dashboard_work_stats(group_tasks, now=now)
        milestone_stats = _dashboard_work_stats(group_milestones, now=now)
        is_blocked = task_stats.blocked > 0 or milestone_stats.blocked > 0
        is_at_risk = is_blocked or task_stats.overdue > 0 or milestone_stats.overdue > 0
        blocked_groups += int(is_blocked)
        at_risk_groups += int(is_at_risk)
        last_message_row = last_message_by_group.get(conversation.id)
        activity_times = [_dashboard_timestamp(conversation.updated_at)]
        activity_times.extend(_dashboard_timestamp(item.updated_at) for item in group_tasks)
        activity_times.extend(_dashboard_timestamp(item.updated_at) for item in group_milestones)
        if last_message_row:
            activity_times.append(_dashboard_timestamp(last_message_row[0].created_at))
        dashboard_groups.append(
            DeliveryDashboardGroup(
                id=conversation.id,
                name=conversation.name or "Untitled group",
                ai_enabled=conversation.ai_enabled,
                member_count=len(participants_by_group.get(conversation.id, [])),
                message_count=message_count_by_group.get(conversation.id, 0),
                members=[
                    DeliveryDashboardGroupMember(
                        user_id=user.id,
                        display_name=user.display_name,
                        email=user.email,
                        job_title=user.job_title,
                        business_role=business_roles.get(user.id),
                        resource_role=participant.resource_role,
                    )
                    for participant, user in participants_by_group.get(conversation.id, [])
                ],
                task_stats=task_stats,
                milestone_stats=milestone_stats,
                tasks=[_dashboard_work_item(item, people_by_id=people_by_id) for item in group_tasks],
                milestones=[_dashboard_work_item(item, people_by_id=people_by_id) for item in group_milestones],
                last_message=(
                    DeliveryDashboardLastMessage(
                        sender_name=last_message_row[1].display_name,
                        excerpt=last_message_row[0].content[:300],
                        created_at=_dashboard_timestamp(last_message_row[0].created_at),
                    )
                    if last_message_row
                    else None
                ),
                updated_at=max(activity_times),
            )
        )

    dashboard_members = [
        DeliveryDashboardMember(
            user_id=user.id,
            display_name=user.display_name,
            email=user.email,
            job_title=user.job_title,
            business_role=business_roles.get(user.id),
            groups=sorted(member_groups.get(user.id, []), key=lambda group: (group.name, group.id)),
            task_stats=(
                _dashboard_work_stats([task for task in tasks if task.owner_id == user.id], now=now)
                if scope.view_scope != DeliveryViewScope.MEMBER or user.id == current_user.id
                else None
            ),
            milestone_count=(
                sum(milestone.owner_id == user.id for milestone in milestones)
                if scope.view_scope != DeliveryViewScope.MEMBER or user.id == current_user.id
                else None
            ),
        )
        for user in sorted(
            people_by_id.values(),
            key=lambda user: (business_roles.get(user.id) != "lead", user.display_name, user.id),
        )
    ]
    return DeliveryDashboardOut(
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        current_user_business_role=prepared.context.actor.business_role.value,
        total_groups=len(dashboard_groups),
        total_members=len(dashboard_members),
        blocked_groups=blocked_groups,
        at_risk_groups=at_risk_groups,
        task_stats=_dashboard_work_stats(tasks, now=now),
        milestone_stats=_dashboard_work_stats(milestones, now=now),
        members=dashboard_members,
        groups=dashboard_groups,
        generated_at=now,
    )


async def _validate_delivery_control_references(
    db: AsyncSession,
    *,
    workspace_id: str,
    agent_workspace_id: str,
    conversation_id: str,
    owner_id: str | None,
    task_ids: tuple[str, ...] = (),
) -> None:
    if owner_id is not None:
        participant = (
            await db.execute(
                select(ConversationParticipant.user_id).where(
                    ConversationParticipant.conversation_id == conversation_id,
                    ConversationParticipant.user_id == owner_id,
                    ConversationParticipant.revoked_at.is_(None),
                    ConversationParticipant.hidden_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if participant is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Control owner is outside the source group",
            )
    distinct_task_ids = tuple(dict.fromkeys(task_id for task_id in task_ids if task_id))
    if distinct_task_ids:
        rows = (
            (
                await db.execute(
                    select(Task.id).where(
                        Task.id.in_(distinct_task_ids),
                        Task.workspace_id == workspace_id,
                        Task.agent_workspace_id == agent_workspace_id,
                        Task.conversation_id == conversation_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        if set(rows) != set(distinct_task_ids):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Dependency task is outside the Delivery source scope",
            )


@router.post(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/dependencies",
    response_model=DeliveryDependencyOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_delivery_dependency(
    workspace_id: str,
    agent_workspace_id: str,
    request: DeliveryDependencyCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeliveryDependencyOut:
    try:
        prepared, scope = await _prepare_delivery_scope(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            message="Create a Delivery dependency",
            selected_conversation_id=request.source_conversation_id,
        )
        if prepared.context.actor.business_role != BusinessRole.LEAD:
            raise HTTPException(status_code=403, detail="Dependency management is unavailable")
        await enforce_agent_resource_access(db, context=prepared.context, resource_id=request.source_conversation_id)
        if request.source_conversation_id not in scope.effective_group_ids:
            raise AgentResourceDeniedError("Dependency source is outside Delivery scope")
    except (AgentScopeDeniedError, AgentResourceDeniedError, ProductDeliveryPreparationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delivery dependency management is unavailable",
        ) from None
    if request.due_at is not None and request.due_at.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="due_at must include a timezone",
        )
    if request.predecessor_task_id is not None and request.predecessor_task_id == request.successor_task_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A dependency cannot link a task to itself",
        )
    await _validate_delivery_control_references(
        db,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        conversation_id=request.source_conversation_id,
        owner_id=request.owner_id,
        task_ids=(request.predecessor_task_id, request.successor_task_id),
    )
    now = datetime.now(UTC)
    record = DeliveryDependencyRecord(
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        conversation_id=request.source_conversation_id,
        title=request.title,
        owner_id=request.owner_id,
        predecessor_task_id=request.predecessor_task_id,
        successor_task_id=request.successor_task_id,
        due_at=request.due_at,
        created_by_user_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    await db.flush()
    await _record_delivery_audit(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        action="delivery_dependency.created",
        metadata={"dependency_id": record.id, "source_conversation_id": record.conversation_id},
    )
    await db.refresh(record)
    return DeliveryDependencyOut.model_validate(record)


@router.patch(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/dependencies/{dependency_id}",
    response_model=DeliveryDependencyOut,
)
async def update_delivery_dependency(
    workspace_id: str,
    agent_workspace_id: str,
    dependency_id: str,
    request: DeliveryDependencyStatusRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeliveryDependencyOut:
    try:
        prepared, scope = await _prepare_delivery_scope(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            message="Update a Delivery dependency",
            selected_conversation_id=None,
        )
        if prepared.context.actor.business_role != BusinessRole.LEAD:
            raise HTTPException(status_code=403, detail="Dependency management is unavailable")
    except (AgentScopeDeniedError, AgentResourceDeniedError, ProductDeliveryPreparationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Delivery dependency management is unavailable"
        ) from None
    record = (
        await db.execute(
            select(DeliveryDependencyRecord).where(
                DeliveryDependencyRecord.id == dependency_id,
                DeliveryDependencyRecord.workspace_id == workspace_id,
                DeliveryDependencyRecord.agent_workspace_id == agent_workspace_id,
                DeliveryDependencyRecord.conversation_id.in_(scope.effective_group_ids),
            )
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dependency not found")
    await enforce_agent_resource_access(db, context=prepared.context, resource_id=record.conversation_id)
    if record.row_version != request.expected_row_version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Dependency was updated concurrently")
    if request.status not in _DEPENDENCY_TRANSITIONS[record.status]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invalid dependency state transition")
    record.status = request.status
    record.row_version += 1
    record.updated_at = datetime.now(UTC)
    await _record_delivery_audit(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        action="delivery_dependency.status_updated",
        metadata={"dependency_id": record.id, "status": record.status, "row_version": record.row_version},
    )
    await db.refresh(record)
    return DeliveryDependencyOut.model_validate(record)


@router.post(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/decisions",
    response_model=DeliveryDecisionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_delivery_decision(
    workspace_id: str,
    agent_workspace_id: str,
    request: DeliveryDecisionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeliveryDecisionOut:
    try:
        prepared, scope = await _prepare_delivery_scope(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            message="Create a Delivery decision",
            selected_conversation_id=request.source_conversation_id,
        )
        if prepared.context.actor.business_role != BusinessRole.LEAD:
            raise HTTPException(status_code=403, detail="Decision management is unavailable")
        await enforce_agent_resource_access(db, context=prepared.context, resource_id=request.source_conversation_id)
        if request.source_conversation_id not in scope.effective_group_ids:
            raise AgentResourceDeniedError("Decision source is outside Delivery scope")
    except (AgentScopeDeniedError, AgentResourceDeniedError, ProductDeliveryPreparationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Delivery decision management is unavailable"
        ) from None
    if request.due_at is not None and request.due_at.tzinfo is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="due_at must include a timezone")
    await _validate_delivery_control_references(
        db,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        conversation_id=request.source_conversation_id,
        owner_id=request.owner_id,
    )
    now = datetime.now(UTC)
    record = DeliveryDecisionRecord(
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        conversation_id=request.source_conversation_id,
        title=request.title,
        owner_id=request.owner_id,
        due_at=request.due_at,
        options=request.options,
        created_by_user_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    await db.flush()
    await _record_delivery_audit(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        action="delivery_decision.created",
        metadata={"decision_id": record.id, "source_conversation_id": record.conversation_id},
    )
    await db.refresh(record)
    return DeliveryDecisionOut.model_validate(record)


@router.patch(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/decisions/{decision_id}",
    response_model=DeliveryDecisionOut,
)
async def update_delivery_decision(
    workspace_id: str,
    agent_workspace_id: str,
    decision_id: str,
    request: DeliveryDecisionStatusRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeliveryDecisionOut:
    try:
        prepared, scope = await _prepare_delivery_scope(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            message="Update a Delivery decision",
            selected_conversation_id=None,
        )
        if prepared.context.actor.business_role != BusinessRole.LEAD:
            raise HTTPException(status_code=403, detail="Decision management is unavailable")
    except (AgentScopeDeniedError, AgentResourceDeniedError, ProductDeliveryPreparationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Delivery decision management is unavailable"
        ) from None
    record = (
        await db.execute(
            select(DeliveryDecisionRecord).where(
                DeliveryDecisionRecord.id == decision_id,
                DeliveryDecisionRecord.workspace_id == workspace_id,
                DeliveryDecisionRecord.agent_workspace_id == agent_workspace_id,
                DeliveryDecisionRecord.conversation_id.in_(scope.effective_group_ids),
            )
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Decision not found")
    await enforce_agent_resource_access(db, context=prepared.context, resource_id=record.conversation_id)
    if record.row_version != request.expected_row_version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Decision was updated concurrently")
    if request.status not in _DECISION_TRANSITIONS[record.status]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invalid decision state transition")
    if request.status == "decided" and not request.outcome:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A decided item requires an outcome"
        )
    if request.status != "decided" and request.outcome is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Outcome is valid only for a decided item"
        )
    record.status = request.status
    record.outcome = request.outcome
    record.row_version += 1
    record.updated_at = datetime.now(UTC)
    await _record_delivery_audit(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        action="delivery_decision.status_updated",
        metadata={"decision_id": record.id, "status": record.status, "row_version": record.row_version},
    )
    await db.refresh(record)
    return DeliveryDecisionOut.model_validate(record)


async def _authorized_delivery_workflow(
    db: AsyncSession,
    *,
    actor: User,
    workspace_id: str,
    agent_workspace_id: str,
    workflow_id: str,
) -> tuple[DeliveryAgentWorkflow, BusinessRole]:
    try:
        prepared, _scope = await _prepare_delivery_scope(
            db,
            current_user=actor,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            message="Inspect Product Delivery workflow",
            selected_conversation_id=None,
        )
    except (AgentScopeDeniedError, AgentResourceDeniedError, ProductDeliveryPreparationError):
        raise HTTPException(status_code=403, detail="Delivery workflow is unavailable") from None
    workflow = (
        await db.execute(
            select(DeliveryAgentWorkflow).where(
                DeliveryAgentWorkflow.id == workflow_id,
                DeliveryAgentWorkflow.workspace_id == workspace_id,
                DeliveryAgentWorkflow.agent_workspace_id == agent_workspace_id,
            )
        )
    ).scalar_one_or_none()
    role = prepared.context.actor.business_role
    if workflow is None or (role != BusinessRole.LEAD and workflow.actor_user_id != actor.id):
        # Do not disclose whether a workflow outside the caller's capability exists.
        raise HTTPException(status_code=404, detail="Delivery workflow was not found")
    return workflow, role


async def _delivery_workflow_out(
    db: AsyncSession,
    workflow: DeliveryAgentWorkflow,
) -> DeliveryWorkflowOut:
    runs = list(
        (
            await db.execute(
                select(DeliveryAgentRun)
                .where(DeliveryAgentRun.workflow_id == workflow.id)
                .order_by(DeliveryAgentRun.created_at.asc(), DeliveryAgentRun.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return DeliveryWorkflowOut.model_validate(workflow).model_copy(
        update={"runs": [DeliveryWorkflowRunOut.model_validate(run) for run in runs]}
    )


@router.get(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/workflows",
    response_model=list[DeliveryWorkflowOut],
)
async def list_delivery_workflows(
    workspace_id: str,
    agent_workspace_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DeliveryWorkflowOut]:
    try:
        prepared, _scope = await _prepare_delivery_scope(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            message="List Product Delivery workflows",
            selected_conversation_id=None,
        )
    except (AgentScopeDeniedError, AgentResourceDeniedError, ProductDeliveryPreparationError):
        raise HTTPException(status_code=403, detail="Delivery workflows are unavailable") from None
    statement = select(DeliveryAgentWorkflow).where(
        DeliveryAgentWorkflow.workspace_id == workspace_id,
        DeliveryAgentWorkflow.agent_workspace_id == agent_workspace_id,
    )
    if prepared.context.actor.business_role != BusinessRole.LEAD:
        statement = statement.where(DeliveryAgentWorkflow.actor_user_id == current_user.id)
    workflows = list(
        (await db.execute(statement.order_by(DeliveryAgentWorkflow.created_at.desc()).limit(limit))).scalars().all()
    )
    return [await _delivery_workflow_out(db, workflow) for workflow in workflows]


@router.get(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/workflows/{workflow_id}",
    response_model=DeliveryWorkflowOut,
)
async def get_delivery_workflow(
    workspace_id: str,
    agent_workspace_id: str,
    workflow_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeliveryWorkflowOut:
    workflow, _role = await _authorized_delivery_workflow(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        workflow_id=workflow_id,
    )
    return await _delivery_workflow_out(db, workflow)


@router.get(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/workflows/{workflow_id}/events",
    response_model=list[DeliveryWorkflowEventOut],
)
async def get_delivery_workflow_events(
    workspace_id: str,
    agent_workspace_id: str,
    workflow_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DeliveryWorkflowEventOut]:
    await _authorized_delivery_workflow(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        workflow_id=workflow_id,
    )
    events = list(
        (
            await db.execute(
                select(DeliveryWorkflowEventRecord)
                .where(DeliveryWorkflowEventRecord.workflow_id == workflow_id)
                .order_by(DeliveryWorkflowEventRecord.created_at.asc(), DeliveryWorkflowEventRecord.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return [DeliveryWorkflowEventOut.model_validate(event) for event in events]


@router.post(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/workflows/{workflow_id}/cancel",
    response_model=DeliveryWorkflowOut,
)
async def cancel_delivery_workflow(
    workspace_id: str,
    agent_workspace_id: str,
    workflow_id: str,
    request: DeliveryWorkflowCancelRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeliveryWorkflowOut:
    workflow, _role = await _authorized_delivery_workflow(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        workflow_id=workflow_id,
    )
    if workflow.status not in {"created", "running", "waiting_evidence", "waiting_approval"}:
        raise HTTPException(status_code=409, detail="Delivery workflow is already terminal")
    now = datetime.now(UTC)
    changed = await db.execute(
        update(DeliveryAgentWorkflow)
        .where(
            DeliveryAgentWorkflow.id == workflow_id,
            DeliveryAgentWorkflow.row_version == request.expected_row_version,
            DeliveryAgentWorkflow.status.in_(("created", "running", "waiting_evidence", "waiting_approval")),
        )
        .values(
            status="cancelled",
            completed_at=now,
            updated_at=now,
            row_version=DeliveryAgentWorkflow.row_version + 1,
        )
    )
    if changed.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Delivery workflow was updated concurrently")
    await db.execute(
        update(DeliveryAgentRun)
        .where(
            DeliveryAgentRun.workflow_id == workflow_id,
            DeliveryAgentRun.status.in_(("pending", "running", "retry_scheduled")),
        )
        .values(status="cancelled", completed_at=now, updated_at=now)
    )
    db.add(
        DeliveryWorkflowEventRecord(
            workflow_id=workflow_id,
            event_type="delivery.workflow.cancelled",
            payload={"actor_user_id": current_user.id},
            created_at=now,
        )
    )
    await _record_delivery_audit(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        action="delivery_workflow.cancelled",
        metadata={"workflow_id": workflow_id},
    )
    await db.refresh(workflow)
    return await _delivery_workflow_out(db, workflow)


@router.post(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/brief",
    response_model=ToolResult,
)
@router.post(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/delivery/chat",
    response_model=ToolResult,
)
async def get_delivery_brief(
    workspace_id: str,
    agent_workspace_id: str,
    request: DeliveryBriefRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ToolResult:
    """Handle a role-scoped conversational or business Delivery turn."""

    try:
        prepared, scope = await _prepare_delivery_scope(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            message=request.message,
            selected_conversation_id=request.selected_conversation_id,
        )
    except (AgentScopeDeniedError, AgentResourceDeniedError, ProductDeliveryPreparationError):
        await _record_delivery_audit(
            db,
            actor=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            action="delivery_brief.denied",
            metadata={"profile": "product_delivery"},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delivery access is unavailable for this request",
        ) from None

    input_decision = guardrail_service.evaluate_workspace_request(
        request.message,
        profile="product_delivery",
        # Unknown wording may still be a valid Delivery follow-up. The semantic
        # router may clarify it, but explicit non-Delivery topics fail here.
        allow_ambiguous=True,
    )
    if not input_decision.allowed:
        out_of_scope = input_decision.category == "out_of_domain"
        return await _respond_without_business_data(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            request=request,
            prepared=prepared,
            scope=scope,
            routing=DeliveryRoutingDecision(
                execution_mode=DeliveryExecutionMode.WORKSPACE_ONLY,
                intent=(
                    DeliveryIntent.OUT_OF_SCOPE
                    if out_of_scope
                    else DeliveryIntent.POLICY_REFUSAL
                ),
                reason_code=f"INPUT_GUARDRAIL_{input_decision.category.upper()}",
            ),
            answer_override=(None if out_of_scope else input_decision.response),
        )

    if await usage_service.is_over_budget(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily AI token allowance exceeded for this account",
        )

    settings = get_settings()
    if not settings.product_delivery_hybrid_router_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Product Delivery adaptive routing is not enabled",
        )
    thread_scope_hash = _delivery_thread_scope_hash(
        consent_scope_hash=prepared.context.authorization.consent_scope_hash,
        scope=scope,
    )
    try:
        memory_thread = await resolve_thread(
            db,
            thread_id=request.thread_id,
            organization_workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            owner_id=current_user.id,
            profile=AgentProfile.PRODUCT_DELIVERY,
            authorization_scope_hash=thread_scope_hash,
        )
        history = await load_history(db, thread=memory_thread)
    except WorkspaceAgentThreadDeniedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delivery memory thread is unavailable",
        ) from None
    routing_groups = tuple(
        {"id": row.id, "name": row.name or "Untitled group"}
        for row in (
            await db.execute(
                select(Conversation.id, Conversation.name)
                .where(Conversation.id.in_(scope.effective_group_ids))
                .order_by(Conversation.name.asc(), Conversation.id.asc())
            )
        ).all()
    )
    try:
        routing = constrain_delivery_route(
            await resolve_delivery_route(
                request.message,
                history=history,
                authorized_groups=routing_groups,
                capacity_enabled=settings.product_delivery_capacity_specialist_enabled,
            ),
            enabled_specialists=_enabled_delivery_specialists(settings),
            allow_multi=settings.product_delivery_multi_specialist_workflows_enabled,
            max_specialists=settings.product_delivery_max_specialists_per_workflow,
        )
    except ValueError:
        logger.exception("Delivery routing has no enabled specialist")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No enabled Product Delivery specialist can handle this request",
        ) from None

    await _broadcast_delivery_progress(
        user_id=current_user.id,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        request_id=request.client_request_id,
        phase="route_selected",
        intent=routing.intent.value,
        execution_mode=routing.execution_mode.value,
        specialists=[specialist.value for specialist in routing.specialists],
        reason_code=routing.reason_code,
    )

    if routing.execution_mode == DeliveryExecutionMode.WORKSPACE_ONLY:
        return await _respond_without_business_data(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            request=request,
            prepared=prepared,
            scope=scope,
            routing=routing,
            answer_override=routing.clarification_question,
            memory_thread=memory_thread,
            history=history,
        )

    if not settings.product_delivery_supervisor_enabled or not settings.product_delivery_specialist_llm_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Product Delivery specialist orchestration is not enabled",
        )

    tool_gateway = DeliveryToolGateway(db=db, prepared=prepared, scope=scope)
    now = datetime.now(UTC)
    period_start = now - timedelta(days=request.period_days)
    try:
        tool_bundle = await tool_gateway.read_bundle(
            message=request.message,
            from_at=period_start,
            to_at=now,
        )
        task_result = tool_bundle.tasks
        milestone_result = tool_bundle.milestones
        message_result = tool_bundle.messages
        people_result = tool_bundle.people
        dependency_result = tool_bundle.dependencies
        decision_result = tool_bundle.decisions
        release_result = tool_bundle.releases
        checkpoint_result = tool_bundle.checkpoints
    except AgentResourceDeniedError:
        await _record_delivery_audit(
            db,
            actor=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            action="delivery_brief.revoked",
            metadata={"profile": "product_delivery"},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delivery access is unavailable for this request",
        ) from None
    if task_result.status == ToolResultStatus.ERROR:
        await _record_delivery_audit(
            db,
            actor=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            action="delivery_brief.tool_error",
            metadata={"profile": "product_delivery", "tool": "get_delivery_tasks"},
        )
        return task_result

    items = tuple(DeliveryItem.model_validate(item) for item in task_result.payload["items"])
    milestones = tuple(DeliveryItem.model_validate(item) for item in milestone_result.payload["milestones"])
    dependencies = tuple(
        DeliveryDependency.model_validate(item) for item in dependency_result.payload.get("dependencies", [])
    )
    decisions = tuple(DeliveryDecision.model_validate(item) for item in decision_result.payload.get("decisions", []))
    releases = tuple(DeliveryReleaseStatus.model_validate(item) for item in release_result.payload.get("releases", []))
    risk_result = await get_delivery_risks(
        scope=scope,
        items=items,
        milestones=milestones,
        dependencies=dependencies,
        releases=releases,
        now=now,
    )
    capacity_result = await get_delivery_capacity_summary(scope=scope, items=items, now=now)
    flow_result = await get_delivery_flow_metrics(scope=scope, items=items)
    health_result = await get_delivery_portfolio_health(
        scope=scope,
        items=items,
        milestones=milestones,
        dependencies=dependencies,
        decisions=decisions,
        releases=releases,
        now=now,
    )
    control_gaps = tuple(
        code
        for result_item, code in (
            (dependency_result, "DELIVERY_DEPENDENCIES_UNAVAILABLE"),
            (decision_result, "DELIVERY_DECISIONS_UNAVAILABLE"),
            (release_result, "DELIVERY_RELEASE_STATUS_UNAVAILABLE"),
            (checkpoint_result, "DELIVERY_CHECKPOINT_PROGRESS_UNAVAILABLE"),
        )
        if result_item.status == ToolResultStatus.ERROR
    )
    payload = build_delivery_payload(
        scope=scope,
        items=items,
        milestones=milestones,
        dependencies=dependencies,
        decisions_needed=decisions,
        risks=tuple(DeliveryRisk.model_validate(item) for item in risk_result.payload["risks"]),
        releases=releases,
        portfolio_health=DeliveryPortfolioAssessment.model_validate(health_result.payload["portfolio_health"]),
        capacity=DeliveryCapacitySummary.model_validate(capacity_result.payload["capacity"]),
        flow_metrics=DeliveryFlowMetrics.model_validate(flow_result.payload["flow_metrics"]),
        period_start=period_start,
        period_end=now,
        generated_at=now,
        expires_at=now + timedelta(minutes=15),
        data_gaps=tuple(
            dict.fromkeys(
                (
                    *task_result.data_gaps,
                    *milestone_result.data_gaps,
                    *flow_result.data_gaps,
                    *health_result.data_gaps,
                    *control_gaps,
                    *checkpoint_result.data_gaps,
                )
            )
        ),
    )
    result = as_delivery_brief_result(payload=payload, checked_at=now)
    scoped_groups = (
        await db.execute(
            select(Conversation.id, Conversation.name)
            .where(Conversation.id.in_(scope.effective_group_ids))
            .order_by(Conversation.name.asc(), Conversation.id.asc())
        )
    ).all()
    group_payload = [{"id": row.id, "name": row.name or "Untitled group"} for row in scoped_groups]
    people_payload = people_result.payload.get("people", [])
    work_item_payload = task_result.payload.get("items", [])
    enriched_work_item_payload = _enrich_work_item_rows(
        work_item_payload,
        groups=group_payload,
        people=people_payload,
    )
    dependency_payload = _enrich_dependency_rows(
        dependency_result.payload.get("dependencies", []),
        groups=group_payload,
        people=people_payload,
        work_items=work_item_payload,
    )
    selected_group = next(
        (
            group
            for group in group_payload
            if group["id"] == (request.selected_conversation_id or routing.target_group_id)
        ),
        None,
    )
    analysis_target = {
        "group_id": selected_group["id"] if selected_group else None,
        "group_name": selected_group["name"] if selected_group else routing.target_group_name,
        "selector": routing.target_selector,
        "source": (
            "ui_selection"
            if request.selected_conversation_id
            else "semantic_conversation"
            if routing.target_group_id or routing.target_selector
            else None
        ),
    }
    scope_context = {
        "mode": (
            "selected_group"
            if selected_group is not None
            else "member_authorized_groups"
            if scope.view_scope == DeliveryViewScope.MEMBER
            else "workspace"
        ),
        "selection_verified": selected_group is not None,
        "selected_group": selected_group,
        "analysis_target": analysis_target,
        "effective_group_count": len(group_payload),
    }
    extra_data_gaps = tuple(dict.fromkeys((*message_result.data_gaps, *people_result.data_gaps)))
    result = result.model_copy(
        update={
            "status": (
                ToolResultStatus.PARTIAL
                if extra_data_gaps or message_result.status == ToolResultStatus.ERROR
                else result.status
            ),
            "payload": {
                **result.payload,
                "groups": group_payload,
                "scope_context": scope_context,
                "people": people_payload,
                "message_evidence": message_result.payload.get("evidence", []),
                "portfolio_health": health_result.payload["portfolio_health"],
                "risks": risk_result.payload["risks"],
                "dependencies": dependency_payload,
                "decisions": decision_result.payload.get("decisions", []),
                "releases": release_result.payload.get("releases", []),
                "capacity": capacity_result.payload["capacity"],
                "flow_metrics": flow_result.payload["flow_metrics"],
                "checkpoint_progress": checkpoint_result.payload.get("checkpoint_progress", []),
            },
            "sources": tuple(
                (
                    *result.sources,
                    *message_result.sources,
                    *release_result.sources,
                )
            ),
            "data_gaps": tuple(dict.fromkeys((*result.data_gaps, *extra_data_gaps))),
        }
    )
    if scope.view_scope == DeliveryViewScope.WORKSPACE:
        candidate = to_workspace_brief(
            payload=payload,
            scope=scope,
            brief_id=uuid4().hex,
            trace_id=prepared.context.trace_id,
        )
        result = result.model_copy(
            update={
                "payload": {
                    **result.payload,
                    "workspace_brief_candidate": candidate.model_dump(mode="json"),
                }
            }
        )

    # Re-authorize immediately before creating runtime/workflow capability.
    # A membership or consent change during reads must fail closed rather than
    # sending a now-stale snapshot to any specialist.
    try:
        dispatch_prepared, dispatch_scope = await _prepare_delivery_scope(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            message=request.message,
            selected_conversation_id=request.selected_conversation_id,
        )
    except (AgentScopeDeniedError, AgentResourceDeniedError, ProductDeliveryPreparationError):
        await _record_delivery_audit(
            db,
            actor=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            action="delivery_brief.dispatch_denied",
            metadata={"profile": "product_delivery"},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delivery access changed before specialist dispatch",
        ) from None
    if (
        dispatch_prepared.context.authorization.consent_scope_hash != prepared.context.authorization.consent_scope_hash
        or dispatch_scope.view_scope != scope.view_scope
        or dispatch_scope.effective_group_ids != scope.effective_group_ids
    ):
        await _record_delivery_audit(
            db,
            actor=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            action="delivery_brief.dispatch_scope_changed",
            metadata={"profile": "product_delivery"},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Delivery scope changed; retry the request with a fresh authorization",
        )
    prepared = dispatch_prepared
    scope = dispatch_scope

    runtime_metadata: dict[str, object] = {}
    try:
        # The API result contains transport/handoff duplication that is useful
        # to callers but wasteful for an LLM. Bind a compact, authorized view
        # to the only model-visible tool to keep token usage bounded.
        agent_snapshot = result.model_copy(
            update={
                "payload": {
                    "brief": result.payload["brief"],
                    "work_items": enriched_work_item_payload,
                    "milestones": milestone_result.payload.get("milestones", []),
                    "groups": result.payload["groups"],
                    "scope_context": result.payload["scope_context"],
                    "analysis_target": analysis_target,
                    "people": result.payload["people"],
                    "message_evidence": result.payload["message_evidence"],
                    "portfolio_health": result.payload["portfolio_health"],
                    "risks": result.payload["risks"],
                    "dependencies": result.payload["dependencies"],
                    "decisions": result.payload["decisions"],
                    "releases": result.payload["releases"],
                    "capacity": result.payload["capacity"],
                    "flow_metrics": result.payload["flow_metrics"],
                    "checkpoint_progress": result.payload["checkpoint_progress"],
                }
            }
        )
        await _broadcast_delivery_progress(
            user_id=current_user.id,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            request_id=request.client_request_id,
            phase="context_ready",
            source_count=len(agent_snapshot.sources),
            data_gap_count=len(agent_snapshot.data_gaps),
        )
        orchestration = None
        workflow = None
        workflow, orchestration = await create_delivery_workflow(
            db,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            actor_user_id=current_user.id,
            actor_role=prepared.context.actor.business_role.value,
            message=request.message,
            authorization_scope_hash=prepared.context.authorization.consent_scope_hash,
            route=routing,
            snapshot=agent_snapshot,
            timeout_seconds=settings.product_delivery_workflow_timeout_seconds,
        )
        await mark_delivery_workflow_running(db, workflow_id=workflow.id)
        await _broadcast_delivery_progress(
            user_id=current_user.id,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            request_id=request.client_request_id,
            phase="specialist_dispatch_started",
            workflow_id=workflow.id,
            intent=orchestration.intent.value,
            execution_mode=orchestration.execution_mode.value,
            specialists=[
                {
                    "name": task.specialist.value,
                    "depends_on": [dependency.value for dependency in task.depends_on],
                    "tools": list(task.allowed_tools),
                    "status": "running" if not task.depends_on else "queued",
                }
                for task in orchestration.child_tasks
            ],
        )
        runtime_request = AgentRuntimeRequest(
            run_id=uuid4().hex,
            trace_id=prepared.context.trace_id,
            requested_at=now,
            target=RuntimeTarget(
                organization_workspace_id=workspace_id,
                agent_workspace_id=agent_workspace_id,
                profile=AgentProfile.PRODUCT_DELIVERY,
                runtime_version=get_settings().workspace_agent_runtime_version,
            ),
            actor=RuntimeActor(
                user_id=current_user.id,
                business_role=prepared.context.actor.business_role,
            ),
            authorization=RuntimeAuthorization(
                decision=PolicyDecision.ALLOW,
                authorized_at=now,
                expires_at=now + timedelta(minutes=1),
                snapshot_sha256=snapshot_sha256(agent_snapshot),
                scope_hash=prepared.context.authorization.consent_scope_hash,
            ),
            message=request.message,
            history=history,
            snapshot=agent_snapshot,
            orchestration=orchestration,
            progress_request_id=request.client_request_id,
        )
        runtime_response = await get_product_delivery_runtime().run(runtime_request)
        await _broadcast_delivery_progress(
            user_id=current_user.id,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            request_id=request.client_request_id,
            phase="specialists_completed",
            workflow_id=workflow.id if workflow is not None else None,
            specialists_completed=list(runtime_response.runtime.specialists_completed),
            specialists_failed=list(runtime_response.runtime.specialists_failed),
            llm_calls=runtime_response.runtime.llm_calls,
        )
        if workflow is not None:
            workflow = await complete_delivery_workflow(
                db,
                workflow_id=workflow.id,
                results=runtime_response.runtime.specialist_results,
                answer=runtime_response.answer,
                usage=runtime_response.usage.model_dump(mode="json"),
                synthesis_model_name=runtime_response.runtime.model_name,
            )
        orchestration_payload = {
            "execution_mode": runtime_response.runtime.execution_mode,
            "intent": runtime_response.runtime.intent,
            "plan_version": runtime_response.runtime.plan_version,
            "workflow_id": runtime_response.runtime.workflow_id or None,
            "workflow_status": workflow.status if workflow is not None else None,
            "specialists_requested": list(runtime_response.runtime.specialists_requested),
            "specialists_completed": list(runtime_response.runtime.specialists_completed),
            "specialists_failed": list(runtime_response.runtime.specialists_failed),
            "specialist_llm_attempts": runtime_response.runtime.specialist_llm_attempts,
            "specialist_fallbacks": runtime_response.runtime.specialist_fallbacks,
            "specialist_model_attempts": runtime_response.runtime.specialist_model_attempts,
            "evidence_branch_executed": runtime_response.runtime.evidence_branch_executed,
            "llm_calls": runtime_response.runtime.llm_calls,
            "routing_strategy": routing.routing_strategy,
            "routing_llm_attempts": [
                attempt.model_dump(mode="json") for attempt in routing.routing_llm_attempts
            ],
            "routing_llm_successes": sum(
                attempt.status == "succeeded" for attempt in routing.routing_llm_attempts
            ),
            "synthesis_model": runtime_response.runtime.model_name,
            "specialist_model": runtime_response.runtime.specialist_model_name,
            "synthesis_fallback": runtime_response.runtime.synthesis_fallback,
            "fallback_reason": runtime_response.runtime.fallback_reason,
        }
        is_task_lookup = routing.intent == DeliveryIntent.TASK_LOOKUP
        public_base_payload = {} if is_task_lookup else result.payload
        public_base_gaps = () if is_task_lookup else result.data_gaps
        public_task_group_progress = next(
            (
                item.metrics.get("group_progress", [])
                for item in runtime_response.runtime.specialist_results
                if item.specialist == DeliverySpecialist.TASK_INTELLIGENCE
                and isinstance(item.metrics.get("group_progress"), list)
            ),
            [],
        )
        public_meeting_plan = next(
            (
                item.artifact.model_dump(mode="json")
                for item in runtime_response.runtime.specialist_results
                if item.artifact is not None and item.artifact.artifact_type == "meeting_plan.v1"
            ),
            None,
        )
        result = result.model_copy(
            update={
                "status": (
                    ToolResultStatus.PARTIAL
                    if runtime_response.status == AgentRuntimeStatus.DEGRADED
                    else ToolResultStatus.SUCCESS
                    if is_task_lookup
                    else result.status
                ),
                "payload": {
                    **public_base_payload,
                    "agent_response": runtime_response.answer,
                    "orchestration": orchestration_payload,
                    "task_group_progress": public_task_group_progress,
                    "meeting_plan": public_meeting_plan,
                    "specialist_results": [
                        item.model_dump(mode="json") for item in runtime_response.runtime.specialist_results
                    ],
                },
                "sources": runtime_response.sources if is_task_lookup else result.sources,
                "data_gaps": tuple(dict.fromkeys((*public_base_gaps, *runtime_response.data_gaps))),
            }
        )
        await usage_service.log_usage(
            provider=runtime_response.runtime.model_provider,
            model=runtime_response.runtime.model_name,
            usage_metadata=runtime_response.runtime.synthesis_usage.model_dump(),
            user_id=current_user.id,
            workspace_id=workspace_id,
        )
        if runtime_response.runtime.specialist_usage.total_tokens > 0:
            await usage_service.log_usage(
                provider=runtime_response.runtime.specialist_model_provider,
                model=runtime_response.runtime.specialist_model_name,
                usage_metadata=runtime_response.runtime.specialist_usage.model_dump(),
                user_id=current_user.id,
                workspace_id=workspace_id,
            )
        if runtime_response.runtime.verifier_applied:
            await usage_service.log_usage(
                provider=runtime_response.runtime.verifier_model_provider,
                model=runtime_response.runtime.verifier_model_name,
                usage_metadata=runtime_response.runtime.verifier_usage.model_dump(),
                user_id=current_user.id,
                workspace_id=workspace_id,
            )
        runtime_metadata = runtime_response.runtime.model_dump(mode="json")
        await _broadcast_delivery_progress(
            user_id=current_user.id,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            request_id=request.client_request_id,
            phase="synthesis_completed",
            workflow_id=workflow.id if workflow is not None else None,
            model=runtime_response.runtime.model_name,
            fallback=runtime_response.runtime.synthesis_fallback,
        )
    except Exception as exc:  # noqa: BLE001 - retain the validated brief rather than leaking an LLM error.
        logger.exception("Delivery agentic runtime failed", extra={"trace_id": prepared.context.trace_id})
        await _broadcast_delivery_progress(
            user_id=current_user.id,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            request_id=request.client_request_id,
            phase="failed",
            error_code="DELIVERY_AGENT_RUNTIME_FAILED",
        )
        failed_thread_id = memory_thread.id
        failed_workflow_id = workflow.id if "workflow" in locals() and workflow is not None else None
        await db.rollback()
        await db.refresh(current_user)
        if failed_workflow_id is not None:
            try:
                await fail_delivery_workflow(
                    db,
                    workflow_id=failed_workflow_id,
                    error_code="DELIVERY_AGENT_RUNTIME_FAILED",
                )
            except Exception:  # noqa: BLE001 - preserve the deterministic brief.
                logger.exception(
                    "Unable to persist failed Delivery workflow",
                    extra={"workflow_id": failed_workflow_id},
                )
        try:
            memory_thread = await resolve_thread(
                db,
                thread_id=failed_thread_id,
                organization_workspace_id=workspace_id,
                agent_workspace_id=agent_workspace_id,
                owner_id=current_user.id,
                profile=AgentProfile.PRODUCT_DELIVERY,
                authorization_scope_hash=thread_scope_hash,
            )
        except WorkspaceAgentThreadDeniedError:
            memory_thread = await resolve_thread(
                db,
                thread_id=None,
                organization_workspace_id=workspace_id,
                agent_workspace_id=agent_workspace_id,
                owner_id=current_user.id,
                profile=AgentProfile.PRODUCT_DELIVERY,
                authorization_scope_hash=thread_scope_hash,
            )
        result = result.model_copy(
            update={
                "status": ToolResultStatus.PARTIAL,
                "payload": {
                    **result.payload,
                    "orchestration": (
                        {
                            "execution_mode": orchestration.execution_mode.value,
                            "intent": orchestration.intent.value,
                            "plan_version": orchestration.plan_version,
                            "workflow_id": failed_workflow_id,
                            "workflow_status": "failed",
                            "specialists_requested": [task.specialist.value for task in orchestration.child_tasks],
                            "specialists_completed": [],
                            "specialists_failed": [],
                            "specialist_llm_attempts": 0,
                            "specialist_fallbacks": {},
                            "evidence_branch_executed": False,
                            "llm_calls": 0,
                            "synthesis_model": "",
                            "specialist_model": "",
                            "synthesis_fallback": True,
                            "fallback_reason": (
                                "DELIVERY_AGENT_RUNTIME_TIMEOUT"
                                if isinstance(exc, TimeoutError)
                                else "DELIVERY_AGENT_RUNTIME_FAILED"
                            ),
                        }
                        if "orchestration" in locals() and orchestration is not None
                        else None
                    ),
                    "agent_response": "Dữ liệu Delivery đã sẵn sàng, nhưng lớp AI đang tạm thời không khả dụng.",
                },
                "data_gaps": tuple(dict.fromkeys((*result.data_gaps, "DELIVERY_AGENT_RUNTIME_FAILED"))),
            }
        )
        runtime_metadata = {
            "execution_mode": (
                orchestration.execution_mode.value if "orchestration" in locals() and orchestration is not None else ""
            ),
            "intent": (orchestration.intent.value if "orchestration" in locals() and orchestration is not None else ""),
            "workflow_id": failed_workflow_id,
            "fallback_reason": (
                "DELIVERY_AGENT_RUNTIME_TIMEOUT" if isinstance(exc, TimeoutError) else "DELIVERY_AGENT_RUNTIME_FAILED"
            ),
        }

    await append_turn(
        db,
        thread=memory_thread,
        user_message=request.message,
        assistant_message=str(result.payload["agent_response"]),
        assistant_workflow_id=(workflow.id if "workflow" in locals() and workflow is not None else None),
    )
    response_thread_id = memory_thread.id if request.persist_history else None
    if not request.persist_history:
        await discard_thread(db, thread=memory_thread)
    result = result.model_copy(update={"payload": {**result.payload, "thread_id": response_thread_id}})
    await _record_delivery_audit(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        action="delivery_brief.generated",
        metadata={
            "profile": "product_delivery",
            "view_scope": scope.view_scope.value,
            "status": result.status.value,
            "source_count": len(result.sources),
            "runtime": runtime_metadata,
        },
    )
    return result
