"""Deterministic Delivery checkpoint rules; no quality inference is allowed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.contracts import BusinessRole, ToolResult, ToolResultStatus
from src.agents.schemas.delivery import DeliveryReadScope
from src.db.models import DeliveryCheckpointTask, DeliveryMilestone, Task
from src.models.delivery_checkpoint_schemas import (
    DeliveryCheckpointAssessmentOut,
    DeliveryCheckpointTaskOut,
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def assess_delivery_checkpoint(
    milestone: DeliveryMilestone,
    task_rows: list[tuple[Task, bool]],
    *,
    now: datetime,
) -> DeliveryCheckpointAssessmentOut:
    """Assess only objective schedule/completeness; Lead owns quality."""

    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    required = [(task, is_required) for task, is_required in task_rows if is_required]
    completed = [task for task, _required in required if task.status == "completed"]
    required_count = len(required)
    completed_count = len(completed)
    complete = required_count > 0 and completed_count == required_count
    percent = round((completed_count / required_count) * 100) if required_count else 0
    due_at = _aware(milestone.due_at) if milestone.due_at else None
    deadline_met: bool | None = None
    reasons: list[str] = []

    if required_count == 0 or due_at is None:
        schedule_status = "insufficient_data"
        reasons.append("CHECKPOINT_REQUIRED_TASKS_MISSING" if required_count == 0 else "CHECKPOINT_DEADLINE_MISSING")
    elif complete:
        completion_times = [
            _aware(task.completed_at or task.updated_at)
            for task in completed
        ]
        deadline_met = max(completion_times) <= due_at
        schedule_status = "completed_on_time" if deadline_met else "completed_late"
        reasons.append("REQUIRED_TASKS_COMPLETE")
        reasons.append("DEADLINE_MET" if deadline_met else "DEADLINE_MISSED")
    elif now > due_at:
        schedule_status = "overdue"
        deadline_met = False
        reasons.extend(("REQUIRED_TASKS_INCOMPLETE", "CHECKPOINT_OVERDUE"))
    elif due_at <= now + timedelta(days=3):
        schedule_status = "at_risk"
        reasons.extend(("REQUIRED_TASKS_INCOMPLETE", "CHECKPOINT_DUE_SOON"))
    else:
        schedule_status = "on_track"
        reasons.append("CHECKPOINT_WITHIN_TIME_WINDOW")

    if any(task.status == "submitted" for task, _required in required):
        reasons.append("TASK_SUBMISSION_AWAITING_LEAD_REVIEW")
    if any(task.status == "changes_requested" for task, _required in required):
        reasons.append("TASK_CHANGES_REQUESTED")

    quality = milestone.quality_review_status
    if quality == "accepted" and complete:
        completion_decision = "accepted"
    elif quality == "rejected":
        completion_decision = "rejected"
    elif complete:
        completion_decision = "pending_lead_quality_review"
        reasons.append("LEAD_QUALITY_REVIEW_PENDING")
    else:
        completion_decision = "pending_tasks"

    return DeliveryCheckpointAssessmentOut(
        checkpoint_id=milestone.id,
        plan_key=milestone.plan_key,
        conversation_id=milestone.conversation_id,
        title=milestone.title,
        due_at=due_at,
        schedule_status=schedule_status,
        completion_percent=percent,
        required_task_count=required_count,
        completed_required_task_count=completed_count,
        required_tasks_complete=complete,
        deadline_met=deadline_met,
        quality_review_status=quality,
        completion_decision=completion_decision,
        quality_review_note=milestone.quality_review_note,
        quality_reviewed_by_user_id=milestone.quality_reviewed_by_user_id,
        quality_reviewed_at=(
            _aware(milestone.quality_reviewed_at) if milestone.quality_reviewed_at else None
        ),
        reason_codes=list(dict.fromkeys(reasons)),
        tasks=[
            DeliveryCheckpointTaskOut(
                id=task.id,
                title=task.title,
                status=task.status,
                owner_id=task.owner_id,
                due_at=_aware(task.due_at) if task.due_at else None,
                completed_at=_aware(task.completed_at) if task.completed_at else None,
                required=is_required,
                requires_review=bool(task.requires_review),
                submission_note=task.submission_note,
                evidence_urls=list(task.evidence_urls or []),
                submitted_at=_aware(task.submitted_at) if task.submitted_at else None,
                review_note=task.review_note,
            )
            for task, is_required in task_rows
        ],
        row_version=milestone.row_version,
    )


async def read_delivery_checkpoint_progress(
    db: AsyncSession,
    *,
    scope: DeliveryReadScope,
    now: datetime | None = None,
) -> ToolResult:
    if not scope.effective_group_ids:
        return ToolResult(status=ToolResultStatus.SUCCESS, payload={"checkpoint_progress": []})
    statement = (
        select(DeliveryMilestone, Task, DeliveryCheckpointTask.required)
        .join(DeliveryCheckpointTask, DeliveryCheckpointTask.milestone_id == DeliveryMilestone.id)
        .join(Task, Task.id == DeliveryCheckpointTask.task_id)
        .where(
            DeliveryMilestone.workspace_id == scope.context.actor.organization_workspace_id,
            DeliveryMilestone.agent_workspace_id == scope.context.request.target_agent_workspace_id,
            DeliveryMilestone.conversation_id.in_(scope.effective_group_ids),
            Task.workspace_id == DeliveryMilestone.workspace_id,
            Task.agent_workspace_id == DeliveryMilestone.agent_workspace_id,
            Task.conversation_id == DeliveryMilestone.conversation_id,
        )
    )
    if scope.context.actor.business_role == BusinessRole.MEMBER:
        statement = statement.where(Task.owner_id == scope.context.actor.user_id)
    rows = list((await db.execute(statement.order_by(DeliveryMilestone.due_at.asc()))).all())
    grouped: dict[str, tuple[DeliveryMilestone, list[tuple[Task, bool]]]] = {}
    for milestone, task, required in rows:
        grouped.setdefault(milestone.id, (milestone, []))[1].append((task, bool(required)))
    current = now or datetime.now(UTC)
    assessments = [
        assess_delivery_checkpoint(milestone, task_rows, now=current)
        for milestone, task_rows in grouped.values()
    ]
    if scope.context.actor.business_role == BusinessRole.MEMBER:
        # This is explicitly the member's own checkpoint schedule, not a claim
        # about the whole team's checkpoint completion.
        assessments = [
            item.model_copy(update={"reason_codes": [*item.reason_codes, "MEMBER_SCOPED_TASKS_ONLY"]})
            for item in assessments
        ]
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={"checkpoint_progress": [item.model_dump(mode="json") for item in assessments]},
        sources=(),
        data_gaps=("NO_CHECKPOINT_PLAN_CONFIGURED",) if not assessments else (),
    )
