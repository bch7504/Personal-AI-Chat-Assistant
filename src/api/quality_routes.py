"""Quality Assurance Workspace Agent read and controlled work-item APIs."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
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
from src.agents.policies.resource_guard import AgentResourceDeniedError, enforce_agent_resource_access
from src.agents.profiles.quality_assurance_runner import (
    QualityPreparationError,
    prepare_quality_invocation,
    resolve_quality_read_scope,
)
from src.agents.runtime import get_quality_assurance_runtime
from src.agents.runtime.contracts import (
    AgentRuntimeRequest,
    AgentRuntimeStatus,
    RuntimeActor,
    RuntimeAuthorization,
    RuntimeTarget,
    snapshot_sha256,
)
from src.agents.schemas.quality import (
    QualityStatus,
    QualityWorkItem,
    QualityWorkItemType,
    quality_status_transition_allowed,
)
from src.agents.tools.quality_analysis import (
    get_defect_register,
    get_release_gate_evidence,
    get_requirement_traceability,
    get_test_execution_summary,
)
from src.agents.tools.quality_brief import build_quality_brief
from src.agents.tools.quality_handoff import get_release_candidate
from src.agents.tools.quality_messages import search_quality_messages
from src.agents.tools.quality_people import get_quality_people
from src.agents.tools.quality_work_items import get_quality_work_items
from src.auth.dependencies import get_current_user
from src.config import get_settings
from src.db.models import (
    AgentWorkspaceMembership,
    Conversation,
    ConversationParticipant,
    ReleaseCandidate,
    Task,
    User,
)
from src.db.session import get_db
from src.models.quality_schemas import (
    QualityBriefRequest,
    QualityCapabilitiesOut,
    QualityGroupCapability,
    QualityWorkItemCreateRequest,
    QualityWorkItemOut,
    QualityWorkItemStatusRequest,
)
from src.services import guardrail_service, reminder_service, usage_service
from src.services.audit_service import record_audit_event
from src.services.quality_control_service import load_quality_control_plane
from src.services.quality_workspace_service import QualityDataError
from src.services.workspace_agent_memory_service import (
    WorkspaceAgentThreadDeniedError,
    append_turn,
    load_history,
    resolve_thread,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _work_item_out(item: Task) -> QualityWorkItemOut:
    return QualityWorkItemOut(
        id=item.id,
        conversation_id=item.conversation_id,
        release_id=item.release_target,
        title=item.title,
        work_item_type=item.work_item_type,
        severity=item.severity,
        quality_status=item.quality_status,
        required=bool(item.quality_required),
        owner_id=item.owner_id,
        row_version=item.row_version,
    )


def _task_status(quality_status: str) -> str:
    return {
        "open": "pending",
        "testing": "in_progress",
        "passed": "completed",
        "failed": "blocked",
        "blocked": "blocked",
    }[quality_status]


async def _prepare(
    db: AsyncSession,
    *,
    current_user: User,
    workspace_id: str,
    agent_workspace_id: str,
    message: str,
    release_id: str,
    selected_conversation_id: str | None,
):
    invocation = AgentInvocationRequest(
        message=message,
        requested_scope=RequestedScope.WORKSPACE,
        target_agent_workspace_id=agent_workspace_id,
    )
    prepared = await prepare_quality_invocation(
        db,
        user_id=current_user.id,
        organization_workspace_id=workspace_id,
        invocation=invocation,
        settings=get_settings(),
    )
    scope = await resolve_quality_read_scope(
        db,
        prepared=prepared,
        release_id=release_id,
        selected_conversation_id=selected_conversation_id,
    )
    return prepared, scope


async def _audit(
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


@router.get(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/quality/capabilities",
    response_model=QualityCapabilitiesOut,
)
async def get_quality_capabilities(
    workspace_id: str,
    agent_workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QualityCapabilitiesOut:
    try:
        prepared, scope = await _prepare(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            message="List Quality capabilities",
            release_id="capability-probe",
            selected_conversation_id=None,
        )
        for resource_id in scope.effective_group_ids:
            await enforce_agent_resource_access(db, context=prepared.context, resource_id=resource_id)
    except (AgentScopeDeniedError, AgentResourceDeniedError, QualityPreparationError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Quality access is unavailable") from None

    group_rows = (
        await db.execute(
            select(Conversation.id, Conversation.name)
            .where(Conversation.id.in_(scope.effective_group_ids))
            .order_by(Conversation.name.asc(), Conversation.id.asc())
        )
    ).all()
    release_statement = select(Task.release_target).where(
        Task.workspace_id == workspace_id,
        Task.agent_workspace_id == agent_workspace_id,
        Task.conversation_id.in_(scope.effective_group_ids),
        Task.work_item_type.is_not(None),
        Task.release_target.is_not(None),
    )
    if prepared.context.actor.business_role == BusinessRole.MEMBER:
        release_statement = release_statement.where(Task.owner_id == current_user.id)
    release_rows = (
        await db.execute(release_statement.distinct().order_by(Task.release_target.asc()))
    ).scalars().all()
    is_lead = prepared.context.actor.business_role == BusinessRole.LEAD
    # Release handoffs are workspace-level governance metadata. A QA member
    # discovers releases through their own assigned work items; only a QA Lead
    # receives the complete handoff index.
    handoff_release_rows: list[str] = []
    if is_lead:
        handoff_release_rows = (
            await db.execute(
                select(ReleaseCandidate.release_key)
                .where(
                    ReleaseCandidate.organization_workspace_id == workspace_id,
                    ReleaseCandidate.quality_agent_workspace_id == agent_workspace_id,
                    ReleaseCandidate.status != "draft",
                )
                .distinct()
                .order_by(ReleaseCandidate.release_key.asc())
            )
        ).scalars().all()
    return QualityCapabilitiesOut(
        current_user_business_role="lead" if is_lead else "member",
        view_scope="workspace" if is_lead else "member",
        can_select_group=is_lead,
        can_manage_control_plane=is_lead,
        can_execute_tests=True,
        can_submit_evidence=True,
        can_report_defects=True,
        can_verify_evidence=is_lead,
        can_decide_release=is_lead,
        can_update_own_work_items=True,
        can_propose_actions=True,
        groups=[QualityGroupCapability(id=row.id, name=row.name or "Untitled group") for row in group_rows],
        release_ids=sorted(set((*release_rows, *handoff_release_rows))),
    )


@router.post(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/quality/brief",
    response_model=ToolResult,
)
async def get_quality_brief(
    workspace_id: str,
    agent_workspace_id: str,
    request: QualityBriefRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ToolResult:
    try:
        prepared, scope = await _prepare(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            message=request.message,
            release_id=request.release_id,
            selected_conversation_id=request.selected_conversation_id,
        )
        input_decision = guardrail_service.evaluate_workspace_request(
            request.message,
            profile="quality_assurance",
            # Terse replies are allowed only inside an already bound QA thread;
            # explicit outside-domain topics remain blocked in both modes.
            allow_ambiguous=request.thread_id is not None,
        )
        if not input_decision.allowed:
            await _audit(
                db,
                actor=current_user,
                workspace_id=workspace_id,
                agent_workspace_id=agent_workspace_id,
                action="quality_conversation.policy_response",
                metadata={
                    "profile": "quality_assurance",
                    "category": input_decision.category,
                    "data_accessed": False,
                    "llm_calls": 0,
                },
            )
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                payload={
                    "agent_response": input_decision.response,
                    "thread_id": None,
                    "policy": {
                        "category": input_decision.category,
                        "data_accessed": False,
                        "llm_calls": 0,
                    },
                },
            )
        if await usage_service.is_over_budget(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Daily AI token allowance exceeded for this account",
            )
        for resource_id in scope.effective_group_ids:
            await enforce_agent_resource_access(db, context=prepared.context, resource_id=resource_id)
        async def revalidate_resource(resource_id: str) -> None:
            await enforce_agent_resource_access(db, context=prepared.context, resource_id=resource_id)

        work_item_result = await get_quality_work_items(
            scope=scope,
            db=db,
            revalidate_resource=revalidate_resource,
        )
        items = tuple(
            QualityWorkItem.model_validate(item) for item in work_item_result.payload["items"]
        )
        result = build_quality_brief(scope=scope, items=items)
        evidence_result = await search_quality_messages(
            scope=scope,
            db=db,
            revalidate_resource=revalidate_resource,
            query=request.message,
            from_at=datetime.now(UTC) - timedelta(days=30),
            to_at=datetime.now(UTC),
        )
        people_result = await get_quality_people(scope=scope, db=db, items=items)
        defect_result = await get_defect_register(scope=scope, items=items)
        execution_result = await get_test_execution_summary(scope=scope, items=items)
        gate_result = await get_release_gate_evidence(scope=scope, items=items)
        traceability_result = await get_requirement_traceability(scope=scope, items=items)
        control_plane = await load_quality_control_plane(
            db,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            release_id=request.release_id,
            conversation_ids=scope.effective_group_ids,
        )
        component_results = (
            work_item_result,
            evidence_result,
            people_result,
            defect_result,
            execution_result,
            gate_result,
            traceability_result,
        )
        component_gaps = tuple(
            dict.fromkeys(
                gap
                for component_result in component_results
                for gap in component_result.data_gaps
            )
        )
        result = result.model_copy(
            update={
                "status": (
                    ToolResultStatus.PARTIAL
                    if component_gaps
                    or any(
                        component_result.status != ToolResultStatus.SUCCESS
                        for component_result in component_results
                    )
                    else result.status
                ),
                "payload": {
                    **result.payload,
                    "message_evidence": evidence_result.payload["evidence"],
                    "people": people_result.payload["people"],
                    "defect_register": defect_result.payload,
                    "test_execution": execution_result.payload,
                    "gate_evidence": gate_result.payload,
                    "requirement_traceability": traceability_result.payload,
                },
                "sources": tuple(dict.fromkeys((*result.sources, *evidence_result.sources))),
                "data_gaps": tuple(dict.fromkeys((*result.data_gaps, *component_gaps))),
            }
        )
        if control_plane["domain_present"]:
            normalized_assessment = control_plane["assessment"]
            normalized_readiness = normalized_assessment["release_readiness"]
            normalized_gaps = tuple(
                gap
                for gap in result.data_gaps
                if "traceability" not in gap.lower()
                and "authorized quality work items" not in gap.lower()
            )
            brief = {
                **result.payload["brief"],
                "headline": (
                    f"Release {request.release_id}: {normalized_readiness}; "
                    f"{len(normalized_assessment['critical_defects'])} critical defect(s), "
                    f"{len(normalized_assessment['blocked_tests'])} blocked test(s)."
                ),
                "release_readiness": normalized_readiness,
                "data_gaps": list(normalized_gaps),
            }
            result = result.model_copy(
                update={
                    "status": (
                        ToolResultStatus.PARTIAL
                        if normalized_gaps
                        else ToolResultStatus.SUCCESS
                    ),
                    "payload": {
                        **result.payload,
                        "assessment": normalized_assessment,
                        "brief": brief,
                        "requirement_traceability": control_plane["traceability"],
                        "quality_control_plane": control_plane,
                    },
                    "data_gaps": normalized_gaps,
                }
            )
        handoff_result = await get_release_candidate(scope=scope, db=db)
        if handoff_result.payload["release_candidate"] is not None:
            result = result.model_copy(
                update={
                    "payload": {
                        **result.payload,
                        "release_candidate": handoff_result.payload["release_candidate"],
                    },
                    "sources": (*result.sources, *handoff_result.sources),
                    "data_gaps": tuple(
                        dict.fromkeys((*result.data_gaps, *handoff_result.data_gaps))
                    ),
                }
            )
    except (AgentScopeDeniedError, AgentResourceDeniedError, QualityPreparationError):
        await _audit(
            db,
            actor=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            action="quality_brief.denied",
            metadata={"profile": "quality_assurance", "release_id": request.release_id},
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Quality access is unavailable") from None
    except QualityDataError:
        logger.exception("Invalid Quality data", extra={"agent_workspace_id": agent_workspace_id})
        await _audit(
            db,
            actor=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            action="quality_brief.data_error",
            metadata={"profile": "quality_assurance", "release_id": request.release_id},
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Quality data requires correction") from None

    now = datetime.now(UTC)
    runtime_metadata: dict[str, object] = {}
    try:
        memory_thread = await resolve_thread(
            db,
            thread_id=request.thread_id,
            organization_workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            owner_id=current_user.id,
            profile=AgentProfile.QUALITY_ASSURANCE,
            authorization_scope_hash=prepared.context.authorization.consent_scope_hash,
        )
        history = await load_history(db, thread=memory_thread)
    except WorkspaceAgentThreadDeniedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Quality memory thread is unavailable",
        ) from None
    try:
        runtime_request = AgentRuntimeRequest(
            run_id=uuid4().hex,
            trace_id=prepared.context.trace_id,
            requested_at=now,
            target=RuntimeTarget(
                organization_workspace_id=workspace_id,
                agent_workspace_id=agent_workspace_id,
                profile=AgentProfile.QUALITY_ASSURANCE,
                runtime_version=get_settings().quality_assurance_runtime_version,
            ),
            actor=RuntimeActor(
                user_id=current_user.id,
                business_role=prepared.context.actor.business_role,
            ),
            authorization=RuntimeAuthorization(
                decision=PolicyDecision.ALLOW,
                authorized_at=now,
                expires_at=now + timedelta(minutes=1),
                snapshot_sha256=snapshot_sha256(result),
            ),
            message=request.message,
            history=history,
            snapshot=result,
        )
        runtime_response = await get_quality_assurance_runtime().run(runtime_request)
        result = result.model_copy(
            update={
                "status": (
                    ToolResultStatus.PARTIAL
                    if runtime_response.status == AgentRuntimeStatus.DEGRADED
                    else result.status
                ),
                "payload": {**result.payload, "agent_response": runtime_response.answer},
                "data_gaps": tuple(dict.fromkeys((*result.data_gaps, *runtime_response.data_gaps))),
            }
        )
        runtime_metadata = runtime_response.runtime.model_dump()
        await usage_service.log_usage(
            provider=runtime_response.runtime.model_provider,
            model=runtime_response.runtime.model_name,
            usage_metadata=runtime_response.runtime.synthesis_usage.model_dump(),
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
    except Exception:  # noqa: BLE001 - keep the validated deterministic brief available.
        logger.exception("Quality runtime failed", extra={"trace_id": prepared.context.trace_id})
        result = result.model_copy(
            update={
                "status": ToolResultStatus.PARTIAL,
                "payload": {
                    **result.payload,
                    "agent_response": "Quality brief is available, but its presentation runtime is unavailable.",
                },
                "data_gaps": tuple(dict.fromkeys((*result.data_gaps, "QUALITY_AGENT_RUNTIME_FAILED"))),
            }
        )
    await append_turn(
        db,
        thread=memory_thread,
        user_message=request.message,
        assistant_message=str(result.payload["agent_response"]),
    )
    result = result.model_copy(
        update={"payload": {**result.payload, "thread_id": memory_thread.id}}
    )
    await _audit(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        action="quality_brief.generated",
        metadata={
            "profile": "quality_assurance",
            "release_id": request.release_id,
            "view_scope": scope.view_scope.value,
            "status": result.status.value,
            "source_count": len(result.sources),
            "runtime": runtime_metadata,
        },
    )
    return result


@router.post(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/quality/work-items",
    response_model=QualityWorkItemOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_quality_work_item(
    workspace_id: str,
    agent_workspace_id: str,
    request: QualityWorkItemCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QualityWorkItemOut:
    try:
        prepared, scope = await _prepare(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            message="Create a Quality work item",
            release_id=request.release_id,
            selected_conversation_id=request.conversation_id,
        )
    except (AgentScopeDeniedError, AgentResourceDeniedError, QualityPreparationError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Quality access is unavailable") from None
    if prepared.context.actor.business_role != BusinessRole.LEAD or scope.selected_conversation_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only a Quality lead can create work items")

    owner_id = request.owner_id or current_user.id
    owner_allowed = (
        await db.execute(
            select(AgentWorkspaceMembership.id)
            .join(
                ConversationParticipant,
                ConversationParticipant.user_id == AgentWorkspaceMembership.user_id,
            )
            .where(
                AgentWorkspaceMembership.agent_workspace_id == agent_workspace_id,
                AgentWorkspaceMembership.user_id == owner_id,
                AgentWorkspaceMembership.status == "active",
                AgentWorkspaceMembership.business_role.in_(("lead", "member")),
                ConversationParticipant.conversation_id == request.conversation_id,
                ConversationParticipant.revoked_at.is_(None),
                ConversationParticipant.hidden_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if owner_allowed is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Owner must be an active Quality workspace member in the source group",
        )
    task = Task(
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        conversation_id=request.conversation_id,
        owner_id=owner_id,
        title=request.title,
        status=_task_status(request.quality_status),
        blocked_reason=("Quality check failed or blocked" if request.quality_status in {"failed", "blocked"} else None),
        source="manual",
        work_item_type=request.work_item_type,
        severity=request.severity,
        quality_status=request.quality_status,
        release_target=request.release_id,
        quality_required=request.required,
    )
    db.add(task)
    await db.flush()
    await _audit(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        action="quality_work_item.created",
        metadata={
            "work_item_id": task.id,
            "release_id": request.release_id,
            "work_item_type": request.work_item_type,
        },
    )
    await reminder_service.reconcile_task_reminder(task.id)
    await db.refresh(task)
    return _work_item_out(task)


@router.patch(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/quality/work-items/{work_item_id}/status",
    response_model=QualityWorkItemOut,
)
async def update_quality_work_item_status(
    workspace_id: str,
    agent_workspace_id: str,
    work_item_id: str,
    request: QualityWorkItemStatusRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QualityWorkItemOut:
    invocation = AgentInvocationRequest(
        message="Update a Quality work item",
        requested_scope=RequestedScope.WORKSPACE,
        target_agent_workspace_id=agent_workspace_id,
    )
    try:
        prepared = await prepare_quality_invocation(
            db,
            user_id=current_user.id,
            organization_workspace_id=workspace_id,
            invocation=invocation,
            settings=get_settings(),
        )
    except (AgentScopeDeniedError, QualityPreparationError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Quality access is unavailable") from None
    filters = [
        Task.id == work_item_id,
        Task.workspace_id == workspace_id,
        Task.agent_workspace_id == agent_workspace_id,
        Task.conversation_id.in_(prepared.context.authorization.allowed_resource_ids),
        Task.work_item_type.is_not(None),
    ]
    if prepared.context.actor.business_role == BusinessRole.MEMBER:
        filters.append(Task.owner_id == current_user.id)
    item = (
        await db.execute(select(Task).where(*filters))
    ).scalar_one_or_none()
    if item is None or item.conversation_id is None or item.release_target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quality work item not found")
    if item.row_version != request.expected_row_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Quality work item was updated by another actor; reload before retrying",
        )
    try:
        await enforce_agent_resource_access(db, context=prepared.context, resource_id=item.conversation_id)
    except AgentResourceDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Quality access is unavailable") from None
    if not quality_status_transition_allowed(
        QualityWorkItemType(item.work_item_type),
        QualityStatus(item.quality_status),
        QualityStatus(request.quality_status),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invalid Quality work-item state transition",
        )
    blocked_reason = (
        "Quality check failed or blocked" if request.quality_status in {"failed", "blocked"} else None
    )
    update_result = await db.execute(
        update(Task)
        .where(
            *filters,
            Task.row_version == request.expected_row_version,
        )
        .values(
            quality_status=request.quality_status,
            status=_task_status(request.quality_status),
            blocked_reason=blocked_reason,
            row_version=Task.row_version + 1,
            updated_at=datetime.now(UTC),
        )
        .execution_options(synchronize_session=False)
    )
    if update_result.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Quality work item was updated by another actor; reload before retrying",
        )
    await db.refresh(item)
    await _audit(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        action="quality_work_item.status_updated",
        metadata={
            "work_item_id": item.id,
            "quality_status": request.quality_status,
            "previous_row_version": request.expected_row_version,
            "row_version": item.row_version,
        },
    )
    await reminder_service.reconcile_task_reminder(item.id)
    return _work_item_out(item)
