from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.config import get_settings
from src.db.models import (
    AgentWorkspace,
    AgentWorkspaceMembership,
    Conversation,
    ConversationParticipant,
    Task,
    User,
    Workspace,
    WorkspaceMembership,
)
from src.db.session import get_db
from src.models.task_schemas import (
    TaskCreateRequest,
    TaskOut,
    TaskSubmissionRequest,
    UpdateTaskRequest,
    UpdateTaskStatusRequest,
)
from src.services import consent_service, reminder_service
from src.services.audit_service import record_audit_event
from src.services.authorization_service import require_conversation_access
from src.services.workspace_service import resolve_workspace_for_user
from src.websocket.manager import manager

router = APIRouter()

_PRIORITY_RANK = {"High": 0, "Medium": 1, "Low": 2}
_OWNER_TRANSITIONS = {
    "suggested": {"pending", "dismissed"},
    "pending": {"in_progress", "blocked", "completed", "dismissed"},
    "in_progress": {"pending", "blocked", "completed"},
    "blocked": {"pending", "in_progress"},
    "submitted": set(),
    "changes_requested": {"in_progress", "blocked"},
    "completed": {"in_progress"},
    "dismissed": set(),
    "invalidated": set(),
}


def _to_out(
    task: Task,
    *,
    due_at_override=None,
    workspace: Workspace | None = None,
    agent_workspace: AgentWorkspace | None = None,
    conversation: Conversation | None = None,
) -> TaskOut:
    due_at = due_at_override if due_at_override is not None else task.due_at
    if due_at is not None and due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=ZoneInfo(get_settings().calendar_timezone))
    return TaskOut(
        id=task.id,
        workspace_id=task.workspace_id,
        owner_id=task.owner_id,
        conversation_id=task.conversation_id,
        agent_workspace_id=task.agent_workspace_id,
        workspace_type=workspace.type if workspace is not None else None,
        workspace_name=workspace.name if workspace is not None else None,
        agent_workspace_name=agent_workspace.name if agent_workspace is not None else None,
        agent_profile=agent_workspace.agent_profile if agent_workspace is not None else None,
        conversation_name=conversation.name if conversation is not None else None,
        title=task.title,
        due_at=due_at,
        auto_reminder_enabled=task.auto_reminder_enabled,
        priority=task.priority,
        status=task.status,
        blocked_reason=task.blocked_reason,
        source=task.source,
        source_message_ids=task.source_message_ids,
        consent_scope_hash=task.consent_scope_hash,
        invalidated_reason=task.invalidated_reason,
        requires_review=task.requires_review,
        submission_note=task.submission_note,
        evidence_urls=list(task.evidence_urls or []),
        submitted_by_user_id=task.submitted_by_user_id,
        submitted_at=task.submitted_at,
        reviewed_by_user_id=task.reviewed_by_user_id,
        reviewed_at=task.reviewed_at,
        review_note=task.review_note,
        row_version=task.row_version,
        created_at=task.created_at,
        updated_at=task.updated_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
    )


async def _get_own_task_or_404(task_id: str, current_user: User, db: AsyncSession) -> Task:
    task = (
        await db.execute(select(Task).where(Task.id == task_id, Task.owner_id == current_user.id))
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    await resolve_workspace_for_user(db, current_user.id, task.workspace_id)
    if task.agent_workspace_id is not None:
        active_agent_membership = await db.scalar(
            select(AgentWorkspaceMembership.id)
            .join(AgentWorkspace, AgentWorkspace.id == AgentWorkspaceMembership.agent_workspace_id)
            .where(
                AgentWorkspaceMembership.agent_workspace_id == task.agent_workspace_id,
                AgentWorkspaceMembership.user_id == current_user.id,
                AgentWorkspaceMembership.status == "active",
                AgentWorkspace.organization_workspace_id == task.workspace_id,
                AgentWorkspace.status == "active",
            )
        )
        if active_agent_membership is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if task.conversation_id is not None:
        await require_conversation_access(db, current_user, task.conversation_id, "participant")
    return task


async def _require_current_ai_provenance(task: Task, db: AsyncSession) -> None:
    if task.source not in {"ai_extracted", "proactive"}:
        return
    if (
        task.source == "proactive"
        and task.source_message_ids is None
        and task.consent_scope_hash is None
        and task.source_sender_id is None
    ):
        # Backward compatibility for suggestions created before provenance fields existed.
        # Current proactive_service always writes all three fields, so new records cannot use this path.
        return
    if task.conversation_id is None or not task.source_message_ids or not task.consent_scope_hash:
        task.status = "invalidated"
        task.invalidated_reason = "missing_ai_provenance"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This AI candidate no longer has verifiable source context",
        )

    current_hash = await consent_service.get_consent_scope_hash(db, task.conversation_id)
    sources_allowed = await consent_service.validate_authorized_source_ids(
        db,
        task.conversation_id,
        task.source_message_ids,
    )
    if current_hash != task.consent_scope_hash or not sources_allowed:
        task.status = "invalidated"
        task.invalidated_reason = "source_consent_changed"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This AI candidate is stale because its source consent changed",
        )


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    workspace_id: str | None = Query(default=None),
    scope: Literal["personal", "all"] = Query(default="personal"),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TaskOut]:
    if scope == "all" and workspace_id is not None:
        raise HTTPException(status_code=422, detail="workspace_id cannot be combined with scope=all")

    statement = (
        select(Task, Workspace, AgentWorkspace, Conversation)
        .join(Workspace, Workspace.id == Task.workspace_id)
        .outerjoin(
            AgentWorkspace,
            and_(
                AgentWorkspace.id == Task.agent_workspace_id,
                AgentWorkspace.organization_workspace_id == Workspace.id,
            ),
        )
        .outerjoin(Conversation, Conversation.id == Task.conversation_id)
    )
    if scope == "all":
        statement = (
            statement
            .outerjoin(
                WorkspaceMembership,
                and_(
                    WorkspaceMembership.workspace_id == Workspace.id,
                    WorkspaceMembership.user_id == current_user.id,
                    WorkspaceMembership.status == "active",
                ),
            )
            .outerjoin(
                AgentWorkspaceMembership,
                and_(
                    AgentWorkspaceMembership.agent_workspace_id == Task.agent_workspace_id,
                    AgentWorkspaceMembership.user_id == current_user.id,
                    AgentWorkspaceMembership.status == "active",
                ),
            )
            .outerjoin(
                ConversationParticipant,
                and_(
                    ConversationParticipant.conversation_id == Task.conversation_id,
                    ConversationParticipant.user_id == current_user.id,
                    ConversationParticipant.principal_kind == "workspace_user",
                    ConversationParticipant.revoked_at.is_(None),
                ),
            )
            .where(
                Task.owner_id == current_user.id,
                Workspace.status == "active",
                or_(
                    and_(
                        Workspace.type == "personal",
                        Workspace.personal_owner_user_id == current_user.id,
                    ),
                    and_(
                        Workspace.type == "organization",
                        WorkspaceMembership.id.is_not(None),
                        or_(
                            Task.agent_workspace_id.is_(None),
                            and_(
                                AgentWorkspace.status == "active",
                                AgentWorkspaceMembership.id.is_not(None),
                            ),
                        ),
                        or_(
                            Task.conversation_id.is_(None),
                            ConversationParticipant.id.is_not(None),
                        ),
                    ),
                ),
            )
        )
    else:
        workspace = await resolve_workspace_for_user(db, current_user.id, workspace_id)
        statement = statement.where(
            Task.owner_id == current_user.id,
            Task.workspace_id == workspace.id,
            Task.agent_workspace_id.is_(None),
        )

    rows = (
        await db.execute(
            statement
            .order_by(
                Task.due_at.is_(None),
                Task.due_at.asc(),
                case((Task.priority == "High", 0), (Task.priority == "Medium", 1), else_=2),
                Task.created_at.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return [
        _to_out(task, workspace=workspace, agent_workspace=agent_workspace, conversation=conversation)
        for task, workspace, agent_workspace, conversation in rows
    ]


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    request: TaskCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    workspace = await resolve_workspace_for_user(db, current_user.id, request.workspace_id)
    if request.conversation_id is not None:
        await require_conversation_access(db, current_user, request.conversation_id, "viewer")
        conversation = await db.get(Conversation, request.conversation_id)
        if conversation is None or conversation.workspace_id != workspace.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="conversation_id does not belong to the selected workspace",
            )
    if request.source == "ai_extracted":
        if request.conversation_id is None or not request.source_message_ids or not request.consent_scope_hash:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="AI-extracted candidates require conversation provenance and a consent snapshot",
            )
        current_hash = await consent_service.get_consent_scope_hash(db, request.conversation_id)
        if current_hash != request.consent_scope_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conversation AI consent changed; extract the candidate again",
            )
        if not await consent_service.validate_authorized_source_ids(
            db, request.conversation_id, request.source_message_ids
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Candidate provenance includes a message that AI is not allowed to process",
            )

        existing = (
            await db.execute(
                select(Task).where(
                    Task.owner_id == current_user.id,
                    Task.workspace_id == workspace.id,
                    Task.conversation_id == request.conversation_id,
                    Task.source == "ai_extracted",
                    Task.status == "suggested",
                    Task.title == request.title,
                    Task.consent_scope_hash == request.consent_scope_hash,
                    Task.source_message_ids == request.source_message_ids,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return _to_out(existing)
    due_at = request.due_at
    if due_at is not None and due_at.tzinfo is None:
        # Same ambiguity reminder_service/proactive_service already guard against: a naive due_at
        # (no UTC offset - e.g. AIPanel's "Extract tasks" posting the LLM's raw due_at straight
        # here) would otherwise let Postgres/asyncpg interpret it using the DB server's own session
        # timezone, which only happens to match calendar_timezone by coincidence on a given machine
        # (verified: local Postgres here defaults to Asia/Bangkok, not something this app controls) -
        # explicit is correct everywhere, not just on this machine.
        due_at = due_at.replace(tzinfo=ZoneInfo(get_settings().calendar_timezone))
    task = Task(
        workspace_id=workspace.id,
        owner_id=current_user.id,
        conversation_id=request.conversation_id,
        # This general endpoint is owned by Personal Agent/manual personal
        # task flows.  A source conversation is provenance, not authority to
        # promote the task into a shared Agent Workspace. Workspace work items
        # are created only by the specialist Delivery/Quality boundaries.
        agent_workspace_id=None,
        title=request.title,
        due_at=due_at,
        priority=request.priority,
        status="pending" if request.source == "manual" else "suggested",
        source=request.source,
        source_message_ids=request.source_message_ids if request.source == "ai_extracted" else None,
        consent_scope_hash=request.consent_scope_hash if request.source == "ai_extracted" else None,
        requires_review=request.requires_review,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    await reminder_service.reconcile_task_reminder(task.id)
    out = _to_out(task, due_at_override=due_at)
    await manager.broadcast_to_users([current_user.id], {"type": "task_created", "task": out.model_dump(mode="json")})
    return out


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: str,
    request: UpdateTaskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    """Update owner-controlled deadline and private reminder settings."""

    task = await _get_own_task_or_404(task_id, current_user, db)
    if task.row_version != request.expected_row_version:
        raise HTTPException(status_code=409, detail="Task changed; reload before updating")

    changed_fields = request.model_fields_set
    if "due_at" in changed_fields:
        if task.agent_workspace_id is not None:
            raise HTTPException(
                status_code=403,
                detail="Workspace task deadlines are managed through the Workspace Agent workflow",
            )
        due_at = request.due_at
        if due_at is not None and due_at.tzinfo is None:
            due_at = due_at.replace(
                tzinfo=ZoneInfo(current_user.timezone or get_settings().calendar_timezone)
            )
        task.due_at = due_at
    if "auto_reminder_enabled" in changed_fields:
        task.auto_reminder_enabled = bool(request.auto_reminder_enabled)

    task.row_version += 1
    await record_audit_event(
        db,
        actor=current_user,
        action="task.settings_updated",
        target_type="task",
        target_id=task.id,
        workspace_id=task.workspace_id,
        metadata={
            "deadline_updated": "due_at" in changed_fields,
            "auto_reminder_enabled": task.auto_reminder_enabled,
            "agent_workspace_id": task.agent_workspace_id,
        },
    )
    await db.commit()
    await db.refresh(task)
    await reminder_service.reconcile_task_reminder(task.id)
    out = _to_out(task)
    await manager.broadcast_to_users(
        [current_user.id], {"type": "task_updated", "task": out.model_dump(mode="json")}
    )
    return out


@router.patch("/tasks/{task_id}/status", response_model=TaskOut)
async def update_task_status(
    task_id: str,
    request: UpdateTaskStatusRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    task = await _get_own_task_or_404(task_id, current_user, db)
    previous_status = task.status
    if task.status == "invalidated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This AI candidate is no longer valid because its source consent changed",
        )
    if request.expected_row_version is not None and task.row_version != request.expected_row_version:
        raise HTTPException(status_code=409, detail="Task changed; reload before updating")
    if request.status in {"submitted", "changes_requested"}:
        raise HTTPException(status_code=422, detail="Use the submission and Lead review workflows")
    if request.status != task.status and request.status not in _OWNER_TRANSITIONS.get(task.status, set()):
        raise HTTPException(status_code=409, detail="Task transition is not allowed")
    if task.status == "suggested" and request.status in {"pending", "in_progress", "completed"}:
        await _require_current_ai_provenance(task, db)
    if request.status == "blocked" and request.blocked_reason is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A blocked task requires a blocked_reason",
        )
    if task.requires_review and request.status == "completed" and task.status != "completed":
        raise HTTPException(status_code=409, detail="This task requires evidence submission and Lead review")
    now = datetime.now(UTC)
    task.status = request.status
    if request.status in {"in_progress", "blocked", "completed"} and task.started_at is None:
        task.started_at = now
    task.completed_at = now if request.status == "completed" else None
    task.blocked_reason = request.blocked_reason if request.status == "blocked" else None
    if request.status == "in_progress" and previous_status == "changes_requested":
        task.reviewed_by_user_id = None
        task.reviewed_at = None
    task.row_version += 1
    await record_audit_event(
        db,
        actor=current_user,
        action="task.status_updated",
        target_type="task",
        target_id=task.id,
        workspace_id=task.workspace_id,
        metadata={"status": request.status, "agent_workspace_id": task.agent_workspace_id},
    )
    await db.commit()
    await db.refresh(task)
    await reminder_service.reconcile_task_reminder(task.id)
    out = _to_out(task)
    await manager.broadcast_to_users([current_user.id], {"type": "task_updated", "task": out.model_dump(mode="json")})

    return out


@router.post("/tasks/{task_id}/submission", response_model=TaskOut)
async def submit_task_for_review(
    task_id: str,
    request: TaskSubmissionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    """Submit evidence without allowing the owner or an LLM to self-approve quality."""

    task = await _get_own_task_or_404(task_id, current_user, db)
    if not task.requires_review:
        raise HTTPException(status_code=409, detail="This task does not require Lead review")
    if task.row_version != request.expected_row_version:
        raise HTTPException(status_code=409, detail="Task changed; reload before submitting")
    if task.status not in {"pending", "in_progress", "changes_requested"}:
        raise HTTPException(status_code=409, detail="Task is not ready for submission")
    now = datetime.now(UTC)
    task.status = "submitted"
    task.submission_note = request.submission_note
    task.evidence_urls = list(request.evidence_urls)
    task.submitted_by_user_id = current_user.id
    task.submitted_at = now
    task.reviewed_by_user_id = None
    task.reviewed_at = None
    task.review_note = None
    task.blocked_reason = None
    task.started_at = task.started_at or now
    task.completed_at = None
    task.row_version += 1
    await record_audit_event(
        db,
        actor=current_user,
        action="task.submitted",
        target_type="task",
        target_id=task.id,
        workspace_id=task.workspace_id,
        metadata={
            "agent_workspace_id": task.agent_workspace_id,
            "evidence_count": len(task.evidence_urls),
            "has_submission_note": bool(task.submission_note),
        },
    )
    await db.commit()
    await db.refresh(task)
    await reminder_service.reconcile_task_reminder(task.id)
    out = _to_out(task)
    recipients = {current_user.id}
    if task.agent_workspace_id:
        lead_id = await db.scalar(
            select(AgentWorkspaceMembership.user_id).where(
                AgentWorkspaceMembership.agent_workspace_id == task.agent_workspace_id,
                AgentWorkspaceMembership.business_role == "lead",
                AgentWorkspaceMembership.status == "active",
            )
        )
        if lead_id:
            recipients.add(lead_id)
    await manager.broadcast_to_users(
        list(recipients),
        {"type": "task_submitted", "task": out.model_dump(mode="json")},
    )
    return out


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    task = await _get_own_task_or_404(task_id, current_user, db)
    if task.requires_review and (task.submitted_at is not None or task.reviewed_at is not None):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A governed task cannot be deleted after it has entered review",
        )
    await record_audit_event(
        db,
        actor=current_user,
        action="task.deleted",
        target_type="task",
        target_id=task.id,
        workspace_id=task.workspace_id,
        metadata={"status": task.status, "agent_workspace_id": task.agent_workspace_id},
    )
    await reminder_service.remove_task_reminder(task.id)
    await db.delete(task)
    await db.commit()
    await manager.broadcast_to_users([current_user.id], {"type": "task_deleted", "task_id": task_id})
