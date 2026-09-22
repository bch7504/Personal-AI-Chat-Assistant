from datetime import UTC, datetime, timedelta

import pytest

import src.db.session as db_session
from src.agents.delivery_orchestration.contracts import (
    DeliveryExecutionMode,
    DeliveryIntent,
    DeliverySpecialist,
)
from src.agents.delivery_orchestration.request_router import route_delivery_request
from src.config import Settings
from src.db.models import (
    AgentWorkspaceConversation,
    Conversation,
    ConversationParticipant,
    DeliveryMilestone,
    Task,
    User,
)
from src.services.delivery_checkpoint_service import assess_delivery_checkpoint
from tests.test_agent_workspaces import _seed_agent_workspaces


def _task(*, status: str, completed_at: datetime | None = None) -> Task:
    now = datetime.now(UTC)
    return Task(
        id=f"task-{status}-{completed_at is not None}",
        workspace_id="workspace-1",
        owner_id="member-1",
        conversation_id="group-1",
        agent_workspace_id="delivery-1",
        title="Required work",
        status=status,
        completed_at=completed_at,
        created_at=now,
        updated_at=completed_at or now,
    )


def _checkpoint(*, due_at: datetime, quality: str = "pending") -> DeliveryMilestone:
    return DeliveryMilestone(
        id="checkpoint-1",
        workspace_id="workspace-1",
        agent_workspace_id="delivery-1",
        conversation_id="group-1",
        title="Sprint checkpoint",
        due_at=due_at,
        plan_key="sprint-12",
        quality_review_status=quality,
        row_version=1,
    )


def test_completed_on_time_still_waits_for_lead_quality_review():
    now = datetime.now(UTC)
    result = assess_delivery_checkpoint(
        _checkpoint(due_at=now + timedelta(hours=1)),
        [(_task(status="completed", completed_at=now), True)],
        now=now,
    )

    assert result.schedule_status == "completed_on_time"
    assert result.completion_percent == 100
    assert result.completion_decision == "pending_lead_quality_review"
    assert result.quality_review_status == "pending"


def test_lead_rejection_is_not_overwritten_by_schedule_rule():
    now = datetime.now(UTC)
    result = assess_delivery_checkpoint(
        _checkpoint(due_at=now + timedelta(hours=1), quality="rejected"),
        [(_task(status="completed", completed_at=now), True)],
        now=now,
    )

    assert result.schedule_status == "completed_on_time"
    assert result.completion_decision == "rejected"


def test_incomplete_checkpoint_is_at_risk_inside_three_day_window():
    now = datetime.now(UTC)
    result = assess_delivery_checkpoint(
        _checkpoint(due_at=now + timedelta(days=2)),
        [(_task(status="in_progress"), True)],
        now=now,
    )

    assert result.schedule_status == "at_risk"
    assert result.completion_percent == 0
    assert result.completion_decision == "pending_tasks"


@pytest.mark.parametrize(
    ("task_status", "reason_code"),
    [
        ("submitted", "TASK_SUBMISSION_AWAITING_LEAD_REVIEW"),
        ("changes_requested", "TASK_CHANGES_REQUESTED"),
    ],
)
def test_review_workflow_states_do_not_count_as_checkpoint_completion(task_status, reason_code):
    now = datetime.now(UTC)
    task = _task(status=task_status)
    task.requires_review = True
    task.submission_note = "Implementation evidence is attached."
    task.evidence_urls = ["https://evidence.example/task/1"]

    result = assess_delivery_checkpoint(
        _checkpoint(due_at=now + timedelta(days=2)),
        [(task, True)],
        now=now,
    )

    assert result.required_tasks_complete is False
    assert result.completion_percent == 0
    assert result.completion_decision == "pending_tasks"
    assert reason_code in result.reason_codes
    assert result.tasks[0].evidence_urls == ["https://evidence.example/task/1"]


def test_task_summary_uses_only_unified_task_then_planning_agents():
    route = route_delivery_request("Tổng hợp các task và đánh giá tiến độ theo checkpoint")

    assert route.execution_mode == DeliveryExecutionMode.MULTI_SPECIALIST
    assert route.intent == DeliveryIntent.TASK_PROGRESS_SUMMARY
    assert route.specialists == (
        DeliverySpecialist.TASK_INTELLIGENCE,
        DeliverySpecialist.PLANNING_FORECAST,
    )


@pytest.mark.parametrize(
    "message",
    [
        "Tiến độ task của các nhóm như thế nào rồi?",
        "Cho tôi tình hình task hiện tại",
        "Tiến độ của các nhóm đến đâu rồi?",
    ],
)
def test_natural_vietnamese_team_progress_uses_only_task_intelligence(message):
    route = route_delivery_request(message)

    assert route.execution_mode == DeliveryExecutionMode.SINGLE_SPECIALIST
    assert route.intent == DeliveryIntent.TASK_PROGRESS_SUMMARY
    assert route.specialists == (DeliverySpecialist.TASK_INTELLIGENCE,)


@pytest.mark.parametrize(
    "message",
    [
        "tổng hợp task của các group cho tôi đi",
        "không ý là toàn bộ group trong workspace tiến độ các task đang như thế nào",
    ],
)
def test_real_group_task_phrasing_does_not_fall_into_clarification(message):
    route = route_delivery_request(message)

    assert route.execution_mode == DeliveryExecutionMode.SINGLE_SPECIALIST
    assert route.intent == DeliveryIntent.TASK_PROGRESS_SUMMARY
    assert route.specialists == (DeliverySpecialist.TASK_INTELLIGENCE,)


def test_composite_task_dependency_meeting_request_uses_three_domain_agents():
    route = route_delivery_request(
        "tổng hợp các task, phân loại phụ thuộc và lên plan để tôi họp với những nhóm đánh giá yếu"
    )

    assert route.execution_mode == DeliveryExecutionMode.MULTI_SPECIALIST
    assert route.intent == DeliveryIntent.MEETING_PLAN
    assert route.specialists == (
        DeliverySpecialist.TASK_INTELLIGENCE,
        DeliverySpecialist.RISK_DEPENDENCY,
        DeliverySpecialist.PLANNING_FORECAST,
    )
    assert route.reason_code == "WEAKEST_TEAM_MEETING_PLAN"


def test_member_schedule_uses_only_task_intelligence():
    route = route_delivery_request("Lịch công việc của tôi tuần này")

    assert route.execution_mode == DeliveryExecutionMode.SINGLE_SPECIALIST
    assert route.intent == DeliveryIntent.MY_SCHEDULE
    assert route.specialists == (DeliverySpecialist.TASK_INTELLIGENCE,)


@pytest.mark.asyncio
async def test_lead_can_define_and_review_a_checkpoint_without_agent_quality_inference(
    client,
    auth_headers,
    monkeypatch,
):
    seed = await _seed_agent_workspaces(client, auth_headers)
    settings = Settings(_env_file=None, multi_agent_enabled=True, product_delivery_agent_enabled=True)
    monkeypatch.setattr("src.api.delivery_routes.get_settings", lambda: settings)
    async with db_session.async_session_maker() as db:
        lead = await db.get(User, seed["delivery_user_id"])
        group = Conversation(
            workspace_id=seed["organization_id"],
            type="group",
            name="Checkpoint group",
            created_by=lead.id,
            ai_enabled=True,
            ai_policy_version=1,
        )
        db.add(group)
        await db.flush()
        task = Task(
            workspace_id=seed["organization_id"],
            agent_workspace_id=seed["delivery_id"],
            conversation_id=group.id,
            owner_id=lead.id,
            title="Ship required scope",
            status="completed",
            completed_at=datetime.now(UTC),
            source="manual",
        )
        db.add_all(
            [
                AgentWorkspaceConversation(
                    agent_workspace_id=seed["delivery_id"],
                    conversation_id=group.id,
                    classification="delivery",
                    linked_by_user_id=lead.id,
                ),
                ConversationParticipant(
                    conversation_id=group.id,
                    principal_kind="workspace_user",
                    user_id=lead.id,
                    resource_role="manager",
                    invited_by_user_id=lead.id,
                ),
                task,
            ]
        )
        await db.commit()
        group_id, task_id = group.id, task.id

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "delivery@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    base = f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/{seed['delivery_id']}/delivery/checkpoints"
    created = await client.post(
        base,
        headers=headers,
        json={
            "source_conversation_id": group_id,
            "plan_key": "sprint-12",
            "title": "Sprint accepted scope",
            "due_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "required_task_ids": [task_id],
        },
    )
    assert created.status_code == 201, created.text
    progress = await client.get(base, headers=headers)
    assert progress.status_code == 200, progress.text
    assessment = progress.json()[0]
    assert assessment["schedule_status"] == "completed_on_time"
    assert assessment["completion_decision"] == "pending_lead_quality_review"

    reviewed = await client.patch(
        f"{base}/{created.json()['id']}/quality-review",
        headers=headers,
        json={
            "quality_review_status": "accepted",
            "quality_review_note": "Lead reviewed acceptance criteria.",
            "expected_row_version": 1,
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["quality_review_status"] == "accepted"
