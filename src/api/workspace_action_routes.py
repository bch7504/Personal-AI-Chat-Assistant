"""Durable human-in-the-loop proposals for specialist workspace mutations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.context_builder import AgentScopeDeniedError
from src.agents.contracts import AgentProfile, BusinessRole, action_payload_hash
from src.agents.policies.resource_guard import AgentResourceDeniedError
from src.agents.profiles.product_delivery_runner import ProductDeliveryPreparationError
from src.agents.profiles.quality_assurance_runner import QualityPreparationError
from src.api.delivery_routes import _prepare_delivery_scope
from src.api.quality_routes import _prepare as _prepare_quality_scope
from src.auth.dependencies import get_current_user
from src.db.models import (
    AgentWorkspace,
    AgentWorkspaceMembership,
    Conversation,
    ConversationParticipant,
    DeliveryAgentWorkflow,
    DeliveryDecisionRecord,
    DeliveryDependencyRecord,
    DeliveryGroupSchedule,
    Message,
    QualityDefect,
    QualityEvidence,
    QualityTestRun,
    Task,
    User,
    WorkspaceActionProposalRecord,
)
from src.db.session import get_db
from src.models.workspace_action_schemas import (
    WorkspaceActionProposalCreate,
    WorkspaceActionProposalDecision,
    WorkspaceActionProposalOut,
)
from src.services import reminder_service
from src.services.audit_service import record_audit_event
from src.websocket.manager import manager

router = APIRouter()


class _DeliveryDependencyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: str = Field(min_length=1)
    status: str = Field(pattern=r"^(open|blocked|resolved|invalidated)$")
    expected_row_version: int = Field(ge=1)


class _DeliveryDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: str = Field(min_length=1)
    status: str = Field(pattern=r"^(decided|superseded|invalidated)$")
    expected_row_version: int = Field(ge=1)
    outcome: str | None = Field(default=None, min_length=1, max_length=2_000)


class _QualityTransitionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_type: str = Field(pattern=r"^(test_run|defect|evidence)$")
    record_id: str = Field(min_length=1)
    status: str = Field(min_length=1, max_length=32)
    expected_row_version: int = Field(ge=1)


class _DeliveryTaskStatusPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: str = Field(min_length=1)
    status: str = Field(pattern=r"^(pending|in_progress|blocked|completed|dismissed)$")
    blocked_reason: str | None = Field(default=None, min_length=1, max_length=500)
    expected_row_version: int = Field(ge=1)


class _DeliveryTaskAssignmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: str = Field(min_length=1)
    owner_id: str = Field(min_length=1)
    expected_row_version: int = Field(ge=1)


class _DeliveryTaskDueDatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: str = Field(min_length=1)
    due_at: datetime | None = None
    expected_row_version: int = Field(ge=1)


class _DeliveryGroupUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=4_000)


class _DeliveryGroupReminderSchedulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=4_000)
    scheduled_for: datetime


_PAYLOAD_MODELS = {
    "delivery_dependency_status": _DeliveryDependencyPayload,
    "delivery_decision_status": _DeliveryDecisionPayload,
    "delivery_task_status": _DeliveryTaskStatusPayload,
    "delivery_task_assignment": _DeliveryTaskAssignmentPayload,
    "delivery_task_due_date": _DeliveryTaskDueDatePayload,
    "delivery_group_update": _DeliveryGroupUpdatePayload,
    "delivery_group_reminder_schedule": _DeliveryGroupReminderSchedulePayload,
    "quality_record_transition": _QualityTransitionPayload,
}
_PROFILE_ACTIONS = {
    AgentProfile.PRODUCT_DELIVERY: {
        "delivery_dependency_status",
        "delivery_decision_status",
        "delivery_task_status",
        "delivery_task_assignment",
        "delivery_task_due_date",
        "delivery_group_update",
        "delivery_group_reminder_schedule",
    },
    AgentProfile.QUALITY_ASSURANCE: {"quality_record_transition"},
}
_DEPENDENCY_TRANSITIONS = {
    "open": {"blocked", "resolved", "invalidated"},
    "blocked": {"open", "resolved", "invalidated"},
    "resolved": {"open", "invalidated"},
    "invalidated": set(),
}
_DECISION_TRANSITIONS = {
    "pending": {"decided", "invalidated"},
    "decided": {"superseded"},
    "superseded": set(),
    "invalidated": set(),
}
_TASK_TRANSITIONS = {
    "suggested": set(),
    "pending": {"in_progress", "blocked", "completed", "dismissed"},
    "in_progress": {"pending", "blocked", "completed"},
    "blocked": {"pending", "in_progress", "completed"},
    "submitted": set(),
    "changes_requested": {"in_progress", "blocked"},
    "completed": {"in_progress"},
    "dismissed": set(),
    "invalidated": set(),
}
_QUALITY_TRANSITIONS = {
    "test_run": (
        QualityTestRun,
        {
            "queued": {"running", "cancelled"},
            "running": {"passed", "failed", "blocked", "cancelled"},
            "failed": {"running"},
            "blocked": {"running"},
        },
    ),
    "defect": (
        QualityDefect,
        {
            "open": {"triaged", "in_progress", "closed"},
            "triaged": {"in_progress", "closed"},
            "in_progress": {"resolved", "closed"},
            "resolved": {"verified", "in_progress"},
            "verified": {"closed", "in_progress"},
        },
    ),
    "evidence": (
        QualityEvidence,
        {"pending": {"verified", "rejected"}, "rejected": {"pending"}},
    ),
}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _validated_payload(action: str, payload: dict[str, Any]) -> BaseModel:
    try:
        return _PAYLOAD_MODELS[action].model_validate(payload)
    except (KeyError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="Invalid action payload") from exc


async def _authorize(
    db: AsyncSession,
    *,
    actor: User,
    workspace_id: str,
    agent_workspace_id: str,
    require_lead: bool,
):
    workspace = (
        await db.execute(
            select(AgentWorkspace).where(
                AgentWorkspace.id == agent_workspace_id,
                AgentWorkspace.organization_workspace_id == workspace_id,
                AgentWorkspace.status == "active",
            )
        )
    ).scalar_one_or_none()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Agent workspace not found")
    try:
        profile = AgentProfile(workspace.agent_profile)
        if profile == AgentProfile.PRODUCT_DELIVERY:
            prepared, scope = await _prepare_delivery_scope(
                db,
                current_user=actor,
                workspace_id=workspace_id,
                agent_workspace_id=agent_workspace_id,
                message="Authorize durable workspace action",
                selected_conversation_id=None,
            )
        elif profile == AgentProfile.QUALITY_ASSURANCE:
            prepared, scope = await _prepare_quality_scope(
                db,
                current_user=actor,
                workspace_id=workspace_id,
                agent_workspace_id=agent_workspace_id,
                message="Authorize durable workspace action",
                release_id="action-proposal",
                selected_conversation_id=None,
            )
        else:
            raise HTTPException(status_code=403, detail="Workspace action is unavailable")
        if require_lead and prepared.context.actor.business_role != BusinessRole.LEAD:
            raise HTTPException(status_code=403, detail="Workspace action is unavailable")
    except (
        AgentScopeDeniedError,
        AgentResourceDeniedError,
        ProductDeliveryPreparationError,
        QualityPreparationError,
        ValueError,
    ):
        raise HTTPException(status_code=403, detail="Workspace action is unavailable") from None
    return profile, prepared, scope


async def _require_target_in_scope(
    db: AsyncSession,
    *,
    profile: AgentProfile,
    action: str,
    payload: BaseModel,
    workspace_id: str,
    agent_workspace_id: str,
    allowed_group_ids: tuple[str, ...],
):
    """Bind an untrusted proposal to a resource the proposer can currently access."""

    if profile == AgentProfile.PRODUCT_DELIVERY and action in {
        "delivery_group_update",
        "delivery_group_reminder_schedule",
    }:
        if payload.conversation_id not in allowed_group_ids:
            raise HTTPException(status_code=404, detail="Action target not found")
        target = (
            await db.execute(
                select(Conversation).where(
                    Conversation.id == payload.conversation_id,
                    Conversation.workspace_id == workspace_id,
                    Conversation.type == "group",
                )
            )
        ).scalar_one_or_none()
        if target is None:
            raise HTTPException(status_code=404, detail="Action target not found")
        return target

    if profile == AgentProfile.PRODUCT_DELIVERY:
        if action.startswith("delivery_task_"):
            model = Task
        elif action == "delivery_dependency_status":
            model = DeliveryDependencyRecord
        else:
            model = DeliveryDecisionRecord
        record_id = payload.record_id
    else:
        model, _transitions = _QUALITY_TRANSITIONS[payload.record_type]
        record_id = payload.record_id
    target = (
        await db.execute(
            select(model).where(
                model.id == record_id,
                model.workspace_id == workspace_id,
                model.agent_workspace_id == agent_workspace_id,
                model.conversation_id.in_(allowed_group_ids),
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Action target not found")
    return target


async def _require_assignment_candidate(
    db: AsyncSession,
    *,
    owner_id: str,
    agent_workspace_id: str,
    conversation_id: str,
) -> None:
    membership = (
        await db.execute(
            select(AgentWorkspaceMembership.id).where(
                AgentWorkspaceMembership.agent_workspace_id == agent_workspace_id,
                AgentWorkspaceMembership.user_id == owner_id,
                AgentWorkspaceMembership.status == "active",
            )
        )
    ).scalar_one_or_none()
    participant = (
        await db.execute(
            select(ConversationParticipant.user_id).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id == owner_id,
                ConversationParticipant.principal_kind == "workspace_user",
            )
        )
    ).scalar_one_or_none()
    if membership is None or participant is None:
        raise HTTPException(
            status_code=422,
            detail="Task owner must be an active Delivery member and source-group participant",
        )


async def _broadcast_action_message(db: AsyncSession, proposal: WorkspaceActionProposalRecord) -> None:
    result = proposal.result_json or {}
    if proposal.status != "executed" or result.get("record_type") != "messages":
        return
    message = await db.get(Message, result["record_id"])
    if message is None:
        return
    participant_ids = list(
        (
            await db.execute(
                select(ConversationParticipant.user_id).where(
                    ConversationParticipant.conversation_id == message.conversation_id,
                    ConversationParticipant.user_id.is_not(None),
                    ConversationParticipant.revoked_at.is_(None),
                    ConversationParticipant.hidden_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    await manager.broadcast_to_users(
        participant_ids,
        {
            "type": "new_message",
            "conversation_id": message.conversation_id,
            "message": {
                "id": message.id,
                "conversation_id": message.conversation_id,
                "sender_id": message.sender_id,
                "content": message.content,
                "created_at": message.created_at.isoformat(),
            },
        },
    )


@router.post(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/action-proposals",
    response_model=WorkspaceActionProposalOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_action_proposal(
    workspace_id: str,
    agent_workspace_id: str,
    request: WorkspaceActionProposalCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceActionProposalOut:
    profile, prepared, scope = await _authorize(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        require_lead=False,
    )
    if request.action not in _PROFILE_ACTIONS[profile]:
        raise HTTPException(status_code=422, detail="Action is not allowed for this agent profile")
    validated = _validated_payload(request.action, request.payload)
    if request.workflow_id is not None:
        if profile != AgentProfile.PRODUCT_DELIVERY:
            raise HTTPException(status_code=422, detail="Only Delivery actions can link a Delivery workflow")
        workflow = (
            await db.execute(
                select(DeliveryAgentWorkflow).where(
                    DeliveryAgentWorkflow.id == request.workflow_id,
                    DeliveryAgentWorkflow.workspace_id == workspace_id,
                    DeliveryAgentWorkflow.agent_workspace_id == agent_workspace_id,
                )
            )
        ).scalar_one_or_none()
        if workflow is None or (
            prepared.context.actor.business_role != BusinessRole.LEAD and workflow.actor_user_id != current_user.id
        ):
            raise HTTPException(status_code=404, detail="Delivery workflow was not found")
    target = await _require_target_in_scope(
        db,
        profile=profile,
        action=request.action,
        payload=validated,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        allowed_group_ids=scope.effective_group_ids,
    )
    if profile == AgentProfile.PRODUCT_DELIVERY and request.action in {
        "delivery_group_update",
        "delivery_group_reminder_schedule",
    }:
        if prepared.context.actor.business_role != BusinessRole.LEAD:
            raise HTTPException(status_code=403, detail="Only a Delivery Lead can message or schedule a group")
        if request.action == "delivery_group_reminder_schedule":
            if validated.scheduled_for.tzinfo is None:
                raise HTTPException(status_code=422, detail="scheduled_for must include a timezone")
            if validated.scheduled_for <= datetime.now(UTC):
                raise HTTPException(status_code=422, detail="scheduled_for must be in the future")
    if profile == AgentProfile.PRODUCT_DELIVERY and request.action.startswith("delivery_task_"):
        is_lead = prepared.context.actor.business_role == BusinessRole.LEAD
        if not is_lead and target.owner_id != current_user.id:
            raise HTTPException(status_code=404, detail="Action target not found")
        if request.action == "delivery_task_assignment":
            if not is_lead:
                raise HTTPException(status_code=403, detail="Only a Delivery Lead can assign tasks")
            await _require_assignment_candidate(
                db,
                owner_id=validated.owner_id,
                agent_workspace_id=agent_workspace_id,
                conversation_id=target.conversation_id,
            )
        if request.action == "delivery_task_status":
            if validated.status == "blocked" and not validated.blocked_reason:
                raise HTTPException(status_code=422, detail="A blocked task requires blocked_reason")
            if validated.status != "blocked" and validated.blocked_reason is not None:
                raise HTTPException(status_code=422, detail="blocked_reason is valid only for blocked tasks")
        if (
            request.action == "delivery_task_due_date"
            and validated.due_at is not None
            and validated.due_at.tzinfo is None
        ):
            raise HTTPException(status_code=422, detail="Task due_at must include a timezone")
    payload = validated.model_dump(mode="json")
    bound_key = f"{workspace_id}:{agent_workspace_id}:{current_user.id}:{request.idempotency_key}"
    existing = (
        await db.execute(
            select(WorkspaceActionProposalRecord).where(WorkspaceActionProposalRecord.idempotency_key == bound_key)
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.payload_hash != action_payload_hash(payload) or existing.action != request.action:
            raise HTTPException(status_code=409, detail="Idempotency key was used for another action")
        return WorkspaceActionProposalOut.model_validate(existing)
    now = datetime.now(UTC)
    proposal = WorkspaceActionProposalRecord(
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        agent_profile=profile.value,
        workflow_id=request.workflow_id,
        actor_user_id=current_user.id,
        action=request.action,
        payload=payload,
        payload_hash=action_payload_hash(payload),
        idempotency_key=bound_key,
        authorization_scope_hash=prepared.context.authorization.consent_scope_hash,
        expires_at=now + timedelta(minutes=request.expires_in_minutes),
        created_at=now,
        updated_at=now,
    )
    db.add(proposal)
    await db.flush()
    await record_audit_event(
        db,
        actor=current_user,
        action="workspace_action.proposed",
        target_type="workspace_action_proposal",
        target_id=proposal.id,
        workspace_id=workspace_id,
        metadata={"agent_workspace_id": agent_workspace_id, "action_name": request.action},
    )
    await db.commit()
    await db.refresh(proposal)
    return WorkspaceActionProposalOut.model_validate(proposal)


@router.get(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/action-proposals",
    response_model=list[WorkspaceActionProposalOut],
)
async def list_workspace_action_proposals(
    workspace_id: str,
    agent_workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WorkspaceActionProposalOut]:
    _profile, _prepared, _scope = await _authorize(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        require_lead=True,
    )
    proposals = list(
        (
            await db.execute(
                select(WorkspaceActionProposalRecord)
                .where(
                    WorkspaceActionProposalRecord.workspace_id == workspace_id,
                    WorkspaceActionProposalRecord.agent_workspace_id == agent_workspace_id,
                )
                .order_by(
                    WorkspaceActionProposalRecord.created_at.desc(),
                    WorkspaceActionProposalRecord.id.asc(),
                )
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    return [WorkspaceActionProposalOut.model_validate(item) for item in proposals]


async def _execute_delivery_action(
    db: AsyncSession,
    *,
    proposal: WorkspaceActionProposalRecord,
    scope,
    actor: User,
) -> dict[str, Any]:
    payload = _validated_payload(proposal.action, proposal.payload)
    if proposal.action in {"delivery_group_update", "delivery_group_reminder_schedule"}:
        if payload.conversation_id not in scope.effective_group_ids:
            raise HTTPException(status_code=404, detail="Action target not found")
        if proposal.action == "delivery_group_update":
            message = Message(
                conversation_id=payload.conversation_id,
                sender_id=actor.id,
                content=f"[Workspace Agent · Lead approved]\n{payload.content}",
            )
            db.add(message)
            await db.flush()
            return {
                "record_type": "messages",
                "record_id": message.id,
                "status": "sent",
                "conversation_id": payload.conversation_id,
                "action": proposal.action,
            }
        if payload.scheduled_for.tzinfo is None or payload.scheduled_for <= datetime.now(UTC):
            raise HTTPException(status_code=409, detail="Scheduled reminder time is no longer valid")
        schedule = DeliveryGroupSchedule(
            workspace_id=proposal.workspace_id,
            agent_workspace_id=proposal.agent_workspace_id,
            conversation_id=payload.conversation_id,
            created_by_user_id=proposal.actor_user_id,
            approved_by_user_id=actor.id,
            title=payload.title,
            content=payload.content,
            scheduled_for=payload.scheduled_for,
            idempotency_key=f"proposal:{proposal.id}",
        )
        db.add(schedule)
        await db.flush()
        return {
            "record_type": "delivery_group_schedules",
            "record_id": schedule.id,
            "status": "scheduled",
            "conversation_id": payload.conversation_id,
            "scheduled_for": payload.scheduled_for.isoformat(),
            "action": proposal.action,
        }
    if proposal.action.startswith("delivery_task_"):
        record = (
            await db.execute(
                select(Task).where(
                    Task.id == payload.record_id,
                    Task.workspace_id == proposal.workspace_id,
                    Task.agent_workspace_id == proposal.agent_workspace_id,
                    Task.conversation_id.in_(scope.effective_group_ids),
                )
            )
        ).scalar_one_or_none()
        if record is None:
            raise HTTPException(status_code=404, detail="Action target not found")
        values: dict[str, Any] = {
            "row_version": Task.row_version + 1,
            "updated_at": datetime.now(UTC),
        }
        result_status: str
        if proposal.action == "delivery_task_status":
            if payload.status not in _TASK_TRANSITIONS.get(record.status, set()):
                raise HTTPException(status_code=409, detail="Task transition is no longer valid")
            if payload.status == "blocked" and not payload.blocked_reason:
                raise HTTPException(status_code=422, detail="A blocked task requires blocked_reason")
            if record.requires_review and payload.status == "completed":
                raise HTTPException(
                    status_code=409,
                    detail="Review-required tasks must be completed through Lead review",
                )
            values.update(
                status=payload.status,
                blocked_reason=payload.blocked_reason if payload.status == "blocked" else None,
                completed_at=datetime.now(UTC) if payload.status == "completed" else None,
            )
            if payload.status in {"in_progress", "blocked", "completed"} and record.started_at is None:
                values["started_at"] = datetime.now(UTC)
            result_status = payload.status
        elif proposal.action == "delivery_task_assignment":
            await _require_assignment_candidate(
                db,
                owner_id=payload.owner_id,
                agent_workspace_id=proposal.agent_workspace_id,
                conversation_id=record.conversation_id,
            )
            values["owner_id"] = payload.owner_id
            result_status = record.status
        else:
            if payload.due_at is not None and payload.due_at.tzinfo is None:
                raise HTTPException(status_code=422, detail="Task due_at must include a timezone")
            values["due_at"] = payload.due_at
            result_status = record.status
        updated = await db.execute(
            update(Task)
            .where(Task.id == record.id, Task.row_version == payload.expected_row_version)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if updated.rowcount != 1:
            raise HTTPException(status_code=409, detail="Action target changed; create a new proposal")
        return {
            "record_type": "tasks",
            "record_id": record.id,
            "status": result_status,
            "action": proposal.action,
        }
    model = DeliveryDependencyRecord if proposal.action == "delivery_dependency_status" else DeliveryDecisionRecord
    record = (
        await db.execute(
            select(model).where(
                model.id == payload.record_id,
                model.workspace_id == proposal.workspace_id,
                model.agent_workspace_id == proposal.agent_workspace_id,
                model.conversation_id.in_(scope.effective_group_ids),
            )
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Action target not found")
    transitions = _DEPENDENCY_TRANSITIONS if proposal.action == "delivery_dependency_status" else _DECISION_TRANSITIONS
    if payload.status not in transitions.get(record.status, set()):
        raise HTTPException(status_code=409, detail="Action transition is no longer valid")
    values: dict[str, Any] = {
        "status": payload.status,
        "row_version": model.row_version + 1,
        "updated_at": datetime.now(UTC),
    }
    if proposal.action == "delivery_decision_status":
        if payload.status == "decided" and not payload.outcome:
            raise HTTPException(status_code=422, detail="Decision outcome is required")
        values["outcome"] = payload.outcome
    result = await db.execute(
        update(model)
        .where(model.id == record.id, model.row_version == payload.expected_row_version)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail="Action target changed; create a new proposal")
    return {"record_type": model.__tablename__, "record_id": record.id, "status": payload.status}


async def _execute_quality_action(
    db: AsyncSession,
    *,
    proposal: WorkspaceActionProposalRecord,
    scope,
    actor: User,
) -> dict[str, Any]:
    payload = _validated_payload(proposal.action, proposal.payload)
    model, transitions = _QUALITY_TRANSITIONS[payload.record_type]
    record = (
        await db.execute(
            select(model).where(
                model.id == payload.record_id,
                model.workspace_id == proposal.workspace_id,
                model.agent_workspace_id == proposal.agent_workspace_id,
                model.conversation_id.in_(scope.effective_group_ids),
            )
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Action target not found")
    status_field = "verification_status" if payload.record_type == "evidence" else "status"
    if payload.status not in transitions.get(getattr(record, status_field), set()):
        raise HTTPException(status_code=409, detail="Action transition is no longer valid")
    values: dict[str, Any] = {
        status_field: payload.status,
        "row_version": model.row_version + 1,
        "updated_at": datetime.now(UTC),
    }
    if payload.record_type == "evidence":
        values.update(
            verified_by_user_id=actor.id if payload.status == "verified" else None,
            verified_at=datetime.now(UTC) if payload.status == "verified" else None,
        )
    if payload.record_type == "test_run":
        if payload.status == "running":
            values.update(
                executed_by_user_id=actor.id,
                started_at=record.started_at or datetime.now(UTC),
                completed_at=None,
            )
        elif payload.status in {"passed", "failed", "blocked", "cancelled"}:
            values.update(completed_at=datetime.now(UTC))
    result = await db.execute(
        update(model)
        .where(model.id == record.id, model.row_version == payload.expected_row_version)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail="Action target changed; create a new proposal")
    return {"record_type": payload.record_type, "record_id": record.id, "status": payload.status}


@router.patch(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/action-proposals/{proposal_id}",
    response_model=WorkspaceActionProposalOut,
)
async def decide_workspace_action_proposal(
    workspace_id: str,
    agent_workspace_id: str,
    proposal_id: str,
    request: WorkspaceActionProposalDecision,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceActionProposalOut:
    profile, _lead_prepared, _lead_scope = await _authorize(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        require_lead=True,
    )
    proposal = (
        await db.execute(
            select(WorkspaceActionProposalRecord)
            .where(
                WorkspaceActionProposalRecord.id == proposal_id,
                WorkspaceActionProposalRecord.workspace_id == workspace_id,
                WorkspaceActionProposalRecord.agent_workspace_id == agent_workspace_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Action proposal not found")
    if proposal.agent_profile != profile.value:
        raise HTTPException(status_code=409, detail="Action proposal profile changed")
    proposal_actor = await db.get(User, proposal.actor_user_id)
    if proposal_actor is None or not proposal_actor.is_active:
        raise HTTPException(status_code=409, detail="Proposal actor is no longer authorized")
    try:
        actor_profile, actor_prepared, actor_scope = await _authorize(
            db,
            actor=proposal_actor,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            require_lead=False,
        )
    except HTTPException:
        raise HTTPException(status_code=409, detail="Proposal actor is no longer authorized") from None
    if actor_profile != profile:
        raise HTTPException(status_code=409, detail="Proposal actor profile changed")
    current_actor_scope_hash = actor_prepared.context.authorization.consent_scope_hash
    if proposal.authorization_scope_hash != current_actor_scope_hash:
        raise HTTPException(status_code=409, detail="Authorization scope changed; create a new proposal")
    if proposal.status != "pending" or proposal.row_version != request.expected_row_version:
        raise HTTPException(status_code=409, detail="Action proposal was already decided")
    if _aware(proposal.expires_at) <= datetime.now(UTC):
        proposal.status = "expired"
        proposal.row_version += 1
        await record_audit_event(
            db,
            actor=current_user,
            action="workspace_action.expired",
            target_type="workspace_action_proposal",
            target_id=proposal.id,
            workspace_id=workspace_id,
            metadata={"agent_workspace_id": agent_workspace_id, "action_name": proposal.action},
        )
        await db.commit()
        raise HTTPException(status_code=409, detail="Action proposal expired")
    if proposal.payload_hash != action_payload_hash(proposal.payload):
        raise HTTPException(status_code=409, detail="Action proposal payload integrity failed")
    now = datetime.now(UTC)
    proposal.decided_by_user_id = current_user.id
    proposal.decided_at = now
    if request.decision == "rejected":
        proposal.status = "rejected"
        result_json = {"decision": "rejected"}
    elif profile == AgentProfile.PRODUCT_DELIVERY:
        result_json = await _execute_delivery_action(
            db,
            proposal=proposal,
            scope=actor_scope,
            actor=current_user,
        )
        proposal.status = "executed"
        proposal.executed_at = now
    else:
        result_json = await _execute_quality_action(db, proposal=proposal, scope=actor_scope, actor=current_user)
        proposal.status = "executed"
        proposal.executed_at = now
    proposal.result_json = result_json
    proposal.row_version += 1
    await record_audit_event(
        db,
        actor=current_user,
        action=f"workspace_action.{proposal.status}",
        target_type="workspace_action_proposal",
        target_id=proposal.id,
        workspace_id=workspace_id,
        metadata={"agent_workspace_id": agent_workspace_id, "action_name": proposal.action},
    )
    await db.commit()
    await db.refresh(proposal)
    if proposal.status == "executed" and result_json.get("record_type") == "tasks":
        await reminder_service.reconcile_task_reminder(result_json["record_id"])
    await _broadcast_action_message(db, proposal)
    return WorkspaceActionProposalOut.model_validate(proposal)
