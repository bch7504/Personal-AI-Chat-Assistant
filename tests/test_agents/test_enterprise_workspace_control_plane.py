from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

import src.db.session as db_session
from src.config import Settings
from src.db.models import (
    AgentWorkspaceConversation,
    Conversation,
    ConversationParticipant,
    DeliveryDependencyRecord,
    DeliveryGroupSchedule,
    Message,
    Task,
    User,
    WorkspaceOutboxEvent,
)
from src.services.agent_workspace_service import add_agent_workspace_member
from src.services.workspace_outbox_service import process_workspace_outbox_events
from tests.test_agent_workspaces import _seed_agent_workspaces


async def _login(client, email: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_normalized_quality_gate_controls_release_approval(client, auth_headers, monkeypatch):
    seed = await _seed_agent_workspaces(client, auth_headers)
    settings = Settings(
        _env_file=None,
        multi_agent_enabled=True,
        product_delivery_agent_enabled=True,
        quality_assurance_agent_enabled=True,
    )
    monkeypatch.setattr("src.api.delivery_routes.get_settings", lambda: settings)
    monkeypatch.setattr("src.api.quality_routes.get_settings", lambda: settings)
    async with db_session.async_session_maker() as db:
        delivery_lead = await db.get(User, seed["delivery_user_id"])
        quality_lead = await db.get(User, seed["quality_user_id"])
        delivery_group = Conversation(
            workspace_id=seed["organization_id"],
            type="group",
            name="Release source",
            created_by=delivery_lead.id,
            ai_enabled=True,
            ai_policy_version=1,
        )
        quality_group = Conversation(
            workspace_id=seed["organization_id"],
            type="group",
            name="Quality controls",
            created_by=quality_lead.id,
            ai_enabled=True,
            ai_policy_version=1,
        )
        db.add_all([delivery_group, quality_group])
        await db.flush()
        db.add_all(
            [
                AgentWorkspaceConversation(
                    agent_workspace_id=seed["delivery_id"],
                    conversation_id=delivery_group.id,
                    classification="delivery",
                    linked_by_user_id=delivery_lead.id,
                ),
                AgentWorkspaceConversation(
                    agent_workspace_id=seed["quality_id"],
                    conversation_id=quality_group.id,
                    classification="quality",
                    linked_by_user_id=quality_lead.id,
                ),
                ConversationParticipant(
                    conversation_id=delivery_group.id,
                    principal_kind="workspace_user",
                    user_id=delivery_lead.id,
                    resource_role="manager",
                    invited_by_user_id=delivery_lead.id,
                ),
                ConversationParticipant(
                    conversation_id=quality_group.id,
                    principal_kind="workspace_user",
                    user_id=quality_lead.id,
                    resource_role="manager",
                    invited_by_user_id=quality_lead.id,
                ),
            ]
        )
        await db.commit()

    delivery_headers = await _login(client, "delivery@example.com")
    candidate_response = await client.post(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/"
        f"{seed['delivery_id']}/delivery/release-candidates",
        headers=delivery_headers,
        json={
            "quality_agent_workspace_id": seed["quality_id"],
            "source_conversation_id": delivery_group.id,
            "release_key": "R-NORMALIZED",
            "version": "2.0.0",
            "build_number": "84",
            "environment": "staging",
        },
    )
    assert candidate_response.status_code == 201, candidate_response.text
    candidate = candidate_response.json()
    assert candidate["quality_policy_version"] == "quality-gate-v2"

    quality_headers = await _login(client, "quality@example.com")
    base = f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/{seed['quality_id']}/quality"
    requirement = await client.post(
        f"{base}/requirements",
        headers=quality_headers,
        json={
            "conversation_id": quality_group.id,
            "release_id": "R-NORMALIZED",
            "requirement_key": "REQ-1",
            "title": "Authenticated checkout",
            "required": True,
        },
    )
    assert requirement.status_code == 201, requirement.text
    requirement_id = requirement.json()["record"]["id"]
    case_ids = []
    for key, kind in (("TC-F", "functional"), ("TC-S", "security")):
        response = await client.post(
            f"{base}/test-cases",
            headers=quality_headers,
            json={
                "conversation_id": quality_group.id,
                "release_id": "R-NORMALIZED",
                "requirement_id": requirement_id,
                "test_case_key": key,
                "title": f"{kind} gate",
                "test_kind": kind,
                "required": True,
            },
        )
        assert response.status_code == 201, response.text
        case_ids.append(response.json()["record"]["id"])
    evidence = await client.post(
        f"{base}/evidence",
        headers=quality_headers,
        json={
            "conversation_id": quality_group.id,
            "release_id": "R-NORMALIZED",
            "artifact_type": "report",
            "uri": "https://ci.example.test/reports/84",
        },
    )
    evidence_record = evidence.json()["record"]
    verified = await client.patch(
        f"{base}/records/evidence/{evidence_record['id']}",
        headers=quality_headers,
        json={"status": "verified", "expected_row_version": 1},
    )
    assert verified.status_code == 200, verified.text
    for case_id in case_ids:
        run = await client.post(
            f"{base}/test-runs",
            headers=quality_headers,
            json={
                "conversation_id": quality_group.id,
                "release_id": "R-NORMALIZED",
                "test_case_id": case_id,
                "release_candidate_id": candidate["id"],
                "evidence_id": evidence_record["id"],
                "build_number": "84",
                "environment": "staging",
                "status": "passed",
            },
        )
        assert run.status_code == 201, run.text
    control = await client.get(f"{base}/control-plane?release_id=R-NORMALIZED", headers=quality_headers)
    assert control.status_code == 200, control.text
    assert control.json()["assessment"]["release_readiness"] == "READY"

    quality_candidates = f"{base}/release-candidates/{candidate['id']}/status"
    started = await client.patch(
        quality_candidates,
        headers=quality_headers,
        json={"status": "qa_in_progress", "expected_row_version": 1},
    )
    assert started.status_code == 200, started.text
    approved = await client.patch(
        quality_candidates,
        headers=quality_headers,
        json={"status": "approved", "expected_row_version": 2},
    )
    assert approved.status_code == 200, approved.text

    async with db_session.async_session_maker() as db:
        events = list((await db.execute(select(WorkspaceOutboxEvent))).scalars().all())
        assert len(events) == 3
    assert await process_workspace_outbox_events() == 3


@pytest.mark.asyncio
async def test_workspace_action_requires_durable_lead_approval(client, auth_headers, monkeypatch):
    seed = await _seed_agent_workspaces(client, auth_headers)
    settings = Settings(
        _env_file=None,
        multi_agent_enabled=True,
        product_delivery_agent_enabled=True,
    )
    monkeypatch.setattr("src.api.delivery_routes.get_settings", lambda: settings)
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "delivery-proposer@example.com",
            "password": "password123",
            "display_name": "Delivery Proposer",
        },
    )
    assert registered.status_code == 201
    organization_member = await client.post(
        f"/api/v1/workspaces/{seed['organization_id']}/members",
        headers=auth_headers,
        json={"email": "delivery-proposer@example.com", "role": "member"},
    )
    assert organization_member.status_code == 201
    async with db_session.async_session_maker() as db:
        lead = await db.get(User, seed["delivery_user_id"])
        member = (await db.execute(select(User).where(User.email == "delivery-proposer@example.com"))).scalar_one()
        await add_agent_workspace_member(db, seed["delivery_id"], member.id, "member")
        group = Conversation(
            workspace_id=seed["organization_id"],
            type="group",
            name="HITL delivery",
            created_by=lead.id,
            ai_enabled=True,
            ai_policy_version=1,
        )
        hidden_group = Conversation(
            workspace_id=seed["organization_id"],
            type="group",
            name="Lead-only HITL delivery",
            created_by=lead.id,
            ai_enabled=True,
            ai_policy_version=1,
        )
        db.add_all([group, hidden_group])
        await db.flush()
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
                ConversationParticipant(
                    conversation_id=group.id,
                    principal_kind="workspace_user",
                    user_id=member.id,
                    resource_role="participant",
                    invited_by_user_id=lead.id,
                ),
                AgentWorkspaceConversation(
                    agent_workspace_id=seed["delivery_id"],
                    conversation_id=hidden_group.id,
                    classification="delivery",
                    linked_by_user_id=lead.id,
                ),
                ConversationParticipant(
                    conversation_id=hidden_group.id,
                    principal_kind="workspace_user",
                    user_id=lead.id,
                    resource_role="manager",
                    invited_by_user_id=lead.id,
                ),
            ]
        )
        dependency = DeliveryDependencyRecord(
            workspace_id=seed["organization_id"],
            agent_workspace_id=seed["delivery_id"],
            conversation_id=group.id,
            title="Approve external dependency change",
            created_by_user_id=lead.id,
        )
        hidden_dependency = DeliveryDependencyRecord(
            workspace_id=seed["organization_id"],
            agent_workspace_id=seed["delivery_id"],
            conversation_id=hidden_group.id,
            title="Member must not reach this dependency",
            created_by_user_id=lead.id,
        )
        member_task = Task(
            workspace_id=seed["organization_id"],
            agent_workspace_id=seed["delivery_id"],
            conversation_id=group.id,
            owner_id=member.id,
            title="Member-owned delivery task",
            status="in_progress",
            source="manual",
        )
        db.add_all([dependency, hidden_dependency, member_task])
        await db.commit()
        dependency_id = dependency.id
        hidden_dependency_id = hidden_dependency.id
        member_task_id = member_task.id

    lead_headers = await _login(client, "delivery@example.com")
    member_headers = await _login(client, "delivery-proposer@example.com")
    base = f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/{seed['delivery_id']}/action-proposals"
    outside_scope = await client.post(
        base,
        headers=member_headers,
        json={
            "action": "delivery_dependency_status",
            "payload": {
                "record_id": hidden_dependency_id,
                "status": "blocked",
                "expected_row_version": 1,
            },
            "idempotency_key": "hidden-dependency-1",
        },
    )
    assert outside_scope.status_code == 404
    proposed = await client.post(
        base,
        headers=member_headers,
        json={
            "action": "delivery_dependency_status",
            "payload": {
                "record_id": dependency_id,
                "status": "blocked",
                "expected_row_version": 1,
            },
            "idempotency_key": "block-dependency-1",
        },
    )
    assert proposed.status_code == 201, proposed.text
    duplicate = await client.post(
        base,
        headers=member_headers,
        json={
            "action": "delivery_dependency_status",
            "payload": {
                "record_id": dependency_id,
                "status": "blocked",
                "expected_row_version": 1,
            },
            "idempotency_key": "block-dependency-1",
        },
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == proposed.json()["id"]
    conflicting_replay = await client.post(
        base,
        headers=member_headers,
        json={
            "action": "delivery_dependency_status",
            "payload": {
                "record_id": dependency_id,
                "status": "resolved",
                "expected_row_version": 1,
            },
            "idempotency_key": "block-dependency-1",
        },
    )
    assert conflicting_replay.status_code == 409
    async with db_session.async_session_maker() as db:
        assert (await db.get(DeliveryDependencyRecord, dependency_id)).status == "open"
    approved = await client.patch(
        f"{base}/{proposed.json()['id']}",
        headers=lead_headers,
        json={"decision": "approved", "expected_row_version": 1},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "executed"
    replayed_approval = await client.patch(
        f"{base}/{proposed.json()['id']}",
        headers=lead_headers,
        json={"decision": "approved", "expected_row_version": 1},
    )
    assert replayed_approval.status_code == 409
    listed = await client.get(base, headers=lead_headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [proposed.json()["id"]]
    metrics = await client.get(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/{seed['delivery_id']}/operational-metrics",
        headers=lead_headers,
    )
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["domain"]["dependencies"]["blocked"] == 1
    assert metrics.json()["action_proposals"]["executed"] == 1
    async with db_session.async_session_maker() as db:
        dependency = await db.get(DeliveryDependencyRecord, dependency_id)
        assert dependency.status == "blocked"
        assert dependency.row_version == 2

    task_proposal = await client.post(
        base,
        headers=member_headers,
        json={
            "action": "delivery_task_status",
            "payload": {
                "record_id": member_task_id,
                "status": "blocked",
                "blocked_reason": "Waiting for approved dependency",
                "expected_row_version": 1,
            },
            "idempotency_key": "block-member-task-1",
        },
    )
    assert task_proposal.status_code == 201, task_proposal.text
    task_approved = await client.patch(
        f"{base}/{task_proposal.json()['id']}",
        headers=lead_headers,
        json={"decision": "approved", "expected_row_version": 1},
    )
    assert task_approved.status_code == 200, task_approved.text
    async with db_session.async_session_maker() as db:
        task = await db.get(Task, member_task_id)
        assert task.status == "blocked"
        assert task.blocked_reason == "Waiting for approved dependency"
        assert task.row_version == 2


@pytest.mark.asyncio
async def test_delivery_group_update_and_schedule_are_lead_approved(client, auth_headers, monkeypatch):
    seed = await _seed_agent_workspaces(client, auth_headers)
    settings = Settings(_env_file=None, multi_agent_enabled=True, product_delivery_agent_enabled=True)
    monkeypatch.setattr("src.api.delivery_routes.get_settings", lambda: settings)
    async with db_session.async_session_maker() as db:
        lead = await db.get(User, seed["delivery_user_id"])
        group = Conversation(
            workspace_id=seed["organization_id"],
            type="group",
            name="Approved agent operations",
            created_by=lead.id,
            ai_enabled=True,
            ai_policy_version=1,
        )
        db.add(group)
        await db.flush()
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
            ]
        )
        await db.commit()
        group_id = group.id

    lead_headers = await _login(client, "delivery@example.com")
    base = f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/{seed['delivery_id']}/action-proposals"
    update_proposal = await client.post(
        base,
        headers=lead_headers,
        json={
            "action": "delivery_group_update",
            "payload": {"conversation_id": group_id, "content": "3 task hoàn thành, 1 task đang bị chặn."},
            "idempotency_key": "group-update-demo-1",
        },
    )
    assert update_proposal.status_code == 201, update_proposal.text
    approved_update = await client.patch(
        f"{base}/{update_proposal.json()['id']}",
        headers=lead_headers,
        json={"decision": "approved", "expected_row_version": 1},
    )
    assert approved_update.status_code == 200, approved_update.text

    scheduled_for = datetime.now(UTC) + timedelta(hours=1)
    schedule_proposal = await client.post(
        base,
        headers=lead_headers,
        json={
            "action": "delivery_group_reminder_schedule",
            "payload": {
                "conversation_id": group_id,
                "title": "Daily checkpoint",
                "content": "Cập nhật task trước checkpoint.",
                "scheduled_for": scheduled_for.isoformat(),
            },
            "idempotency_key": "group-schedule-demo-1",
        },
    )
    assert schedule_proposal.status_code == 201, schedule_proposal.text
    approved_schedule = await client.patch(
        f"{base}/{schedule_proposal.json()['id']}",
        headers=lead_headers,
        json={"decision": "approved", "expected_row_version": 1},
    )
    assert approved_schedule.status_code == 200, approved_schedule.text

    async with db_session.async_session_maker() as db:
        messages = list(
            (
                await db.execute(
                    select(Message).where(
                        Message.conversation_id == group_id,
                        Message.content.contains("Lead approved"),
                    )
                )
            )
            .scalars()
            .all()
        )
        schedules = list((await db.execute(select(DeliveryGroupSchedule))).scalars().all())
        assert len(messages) == 1
        assert len(schedules) == 1
        assert schedules[0].status == "scheduled"
