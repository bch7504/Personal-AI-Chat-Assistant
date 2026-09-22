from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

import src.db.session as db_session
from src.agents.tools.context_tool import list_my_tasks
from src.config import Settings
from src.db.models import (
    AgentWorkspaceConversation,
    AgentWorkspaceMembership,
    Conversation,
    ConversationParticipant,
    Message,
    Task,
    User,
)
from src.services import consent_service, proactive_service
from src.services.agent_workspace_service import add_agent_workspace_member
from src.services.workspace_service import add_workspace_member
from tests.test_agent_workspaces import _seed_agent_workspaces


@pytest.fixture(autouse=True)
def _enable_product_delivery_agent(monkeypatch):
    """Keep this feature-specific module independent from the CI rollout matrix."""

    settings = Settings(
        _env_file=None,
        multi_agent_enabled=True,
        product_delivery_agent_enabled=True,
    )
    monkeypatch.setattr("src.api.delivery_routes.get_settings", lambda: settings)


async def _setup_review_flow(client, auth_headers):
    seed = await _seed_agent_workspaces(client, auth_headers)
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "delivery-review-member@example.com",
            "password": "password123",
            "display_name": "Review Member",
        },
    )
    assert registered.status_code == 201
    async with db_session.async_session_maker() as db:
        lead = await db.get(User, seed["delivery_user_id"])
        member = await db.scalar(select(User).where(User.email == "delivery-review-member@example.com"))
        await add_workspace_member(db, seed["organization_id"], member.id, "member", lead.id)
        await add_agent_workspace_member(db, seed["delivery_id"], member.id, "member")
        group = Conversation(
            workspace_id=seed["organization_id"],
            type="group",
            name="Review Flow",
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
                ConversationParticipant(
                    conversation_id=group.id,
                    principal_kind="workspace_user",
                    user_id=member.id,
                    resource_role="participant",
                    invited_by_user_id=lead.id,
                ),
            ]
        )
        await db.commit()
    lead_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "delivery@example.com", "password": "password123"},
    )
    member_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "delivery-review-member@example.com", "password": "password123"},
    )
    return {
        **seed,
        "group_id": group.id,
        "member_id": member.id,
        "lead_headers": {"Authorization": f"Bearer {lead_login.json()['access_token']}"},
        "member_headers": {"Authorization": f"Bearer {member_login.json()['access_token']}"},
    }


@pytest.mark.asyncio
async def test_my_tasks_all_combines_personal_and_current_delivery_assignments(client, auth_headers):
    seed = await _setup_review_flow(client, auth_headers)
    root = (
        f"/api/v1/workspaces/{seed['organization_id']}"
        f"/agent-workspaces/{seed['delivery_id']}/delivery"
    )
    personal = await client.post(
        "/api/v1/tasks",
        headers=seed["member_headers"],
        json={"title": "Renew personal certificate", "priority": "Low"},
    )
    assert personal.status_code == 201, personal.text
    delivery = await client.post(
        f"{root}/tasks",
        headers=seed["lead_headers"],
        json={
            "source_conversation_id": seed["group_id"],
            "owner_id": seed["member_id"],
            "title": "Implement delivery callback",
            "priority": "High",
            "requires_review": False,
        },
    )
    assert delivery.status_code == 201, delivery.text

    personal_only = await client.get("/api/v1/tasks", headers=seed["member_headers"])
    assert personal_only.status_code == 200
    assert [item["title"] for item in personal_only.json()] == ["Renew personal certificate"]

    all_tasks = await client.get("/api/v1/tasks?scope=all", headers=seed["member_headers"])
    assert all_tasks.status_code == 200, all_tasks.text
    tasks_by_title = {item["title"]: item for item in all_tasks.json()}
    assert set(tasks_by_title) == {"Renew personal certificate", "Implement delivery callback"}
    assert tasks_by_title["Renew personal certificate"]["workspace_type"] == "personal"
    delivery_task = tasks_by_title["Implement delivery callback"]
    assert delivery_task["workspace_type"] == "organization"
    assert delivery_task["agent_profile"] == "product_delivery"
    assert delivery_task["agent_workspace_name"] == "Product Delivery"
    assert delivery_task["conversation_name"] == "Review Flow"

    async with db_session.async_session_maker() as db:
        membership = await db.scalar(
            select(AgentWorkspaceMembership).where(
                AgentWorkspaceMembership.agent_workspace_id == seed["delivery_id"],
                AgentWorkspaceMembership.user_id == seed["member_id"],
            )
        )
        membership.status = "revoked"
        await db.commit()

    after_revoke = await client.get("/api/v1/tasks?scope=all", headers=seed["member_headers"])
    assert after_revoke.status_code == 200
    assert [item["title"] for item in after_revoke.json()] == ["Renew personal certificate"]
    assigned_after_revoke = await list_my_tasks.coroutine(
        include_completed=False,
        scope="all_assigned",
        state={"user_id": seed["member_id"], "workspace_id": seed["organization_id"]},
    )
    assert "Renew personal certificate" in assigned_after_revoke
    assert "Implement delivery callback" not in assigned_after_revoke
    stale_update = await client.patch(
        f"/api/v1/tasks/{delivery.json()['id']}/status",
        headers=seed["member_headers"],
        json={"status": "in_progress", "expected_row_version": delivery.json()["row_version"]},
    )
    assert stale_update.status_code == 404


@pytest.mark.asyncio
async def test_personal_extraction_from_delivery_channel_stays_private_and_unbound(
    client, auth_headers
):
    seed = await _setup_review_flow(client, auth_headers)
    async with db_session.async_session_maker() as db:
        source = Message(
            conversation_id=seed["group_id"],
            sender_id=seed["member_id"],
            content="Tôi sẽ chuẩn bị tài liệu trước thứ Sáu.",
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)
        scope_hash = await consent_service.get_consent_scope_hash(db, seed["group_id"])

    extracted = await client.post(
        "/api/v1/tasks",
        headers=seed["member_headers"],
        json={
            "workspace_id": seed["organization_id"],
            "conversation_id": seed["group_id"],
            "title": "Chuẩn bị tài liệu cá nhân",
            "priority": "Medium",
            "source": "ai_extracted",
            "source_message_ids": [source.id],
            "consent_scope_hash": scope_hash,
        },
    )
    assert extracted.status_code == 201, extracted.text
    assert extracted.json()["agent_workspace_id"] is None

    delivery = await client.post(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/"
        f"{seed['delivery_id']}/delivery/tasks",
        headers=seed["lead_headers"],
        json={
            "source_conversation_id": seed["group_id"],
            "owner_id": seed["member_id"],
            "title": "Workspace delivery task",
            "priority": "High",
            "requires_review": False,
        },
    )
    assert delivery.status_code == 201, delivery.text

    personal_result = await list_my_tasks.coroutine(
        include_completed=False,
        state={
            "user_id": seed["member_id"],
            "workspace_id": seed["organization_id"],
            "conversation_id": seed["group_id"],
        },
    )
    assert "Chuẩn bị tài liệu cá nhân" in personal_result
    assert "Workspace delivery task" not in personal_result

    assigned_result = await list_my_tasks.coroutine(
        include_completed=False,
        scope="all_assigned",
        state={
            "user_id": seed["member_id"],
            "workspace_id": seed["organization_id"],
            "conversation_id": seed["group_id"],
        },
    )
    assert "Chuẩn bị tài liệu cá nhân" in assigned_result
    assert "Workspace delivery task" in assigned_result

    async with db_session.async_session_maker() as db:
        rows = list(
            (
                await db.execute(
                    select(Task).where(Task.owner_id == seed["member_id"]).order_by(Task.title)
                )
            )
            .scalars()
            .all()
        )
    assert {row.title: row.agent_workspace_id for row in rows} == {
        "Chuẩn bị tài liệu cá nhân": None,
        "Workspace delivery task": seed["delivery_id"],
    }


@pytest.mark.asyncio
async def test_channel_commitment_is_bound_to_delivery_workspace(
    client, auth_headers, monkeypatch
):
    seed = await _setup_review_flow(client, auth_headers)
    async with db_session.async_session_maker() as db:
        source = Message(
            conversation_id=seed["group_id"],
            sender_id=seed["member_id"],
            content="Tôi sẽ hoàn thành API vào thứ Sáu.",
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)
    member = (await client.get("/api/v1/auth/me", headers=seed["member_headers"])).json()
    llm = AsyncMock()
    llm.ainvoke.side_effect = [
        SimpleNamespace(content='{"relevant":true}', usage_metadata={}),
        SimpleNamespace(
            content=(
                '{"commitments":[{"title":"Hoàn thành API","due_at":null,'
                '"proposal_message_index":1,"cancelled":false,"owners":['
                f'{{"name":"{member["display_name"]}","evidence":"self","message_index":1}}]}}]}}'
            ),
            usage_metadata={},
        ),
    ]
    monkeypatch.setattr(proactive_service, "get_llm", lambda: llm)

    await proactive_service.maybe_suggest_task(
        conversation_id=seed["group_id"],
        sender_id=seed["member_id"],
        content=source.content,
        message_id=source.id,
    )

    async with db_session.async_session_maker() as db:
        task = await db.scalar(
            select(Task).where(
                Task.owner_id == seed["member_id"],
                Task.source == "proactive",
            )
        )
    assert task is not None
    assert task.agent_workspace_id == seed["delivery_id"]
    assert task.conversation_id == seed["group_id"]
    assert task.source_message_ids == [source.id]


@pytest.mark.asyncio
async def test_delivery_review_required_task_runs_auditable_closed_loop(client, auth_headers):
    seed = await _setup_review_flow(client, auth_headers)
    root = (
        f"/api/v1/workspaces/{seed['organization_id']}"
        f"/agent-workspaces/{seed['delivery_id']}/delivery"
    )
    created = await client.post(
        f"{root}/tasks",
        headers=seed["lead_headers"],
        json={
            "source_conversation_id": seed["group_id"],
            "owner_id": seed["member_id"],
            "title": "Submit OAuth pull request evidence",
            "due_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
            "priority": "High",
            "requires_review": True,
        },
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["status"] == "pending"
    assert task["requires_review"] is True

    direct_complete = await client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        headers=seed["member_headers"],
        json={"status": "completed", "expected_row_version": task["row_version"]},
    )
    assert direct_complete.status_code == 409

    submitted = await client.post(
        f"/api/v1/tasks/{task['id']}/submission",
        headers=seed["member_headers"],
        json={
            "submission_note": "OAuth callback and rollback tests are green.",
            "evidence_urls": ["https://github.example/pull/42"],
            "expected_row_version": task["row_version"],
        },
    )
    assert submitted.status_code == 200, submitted.text
    first_submission = submitted.json()
    assert first_submission["status"] == "submitted"

    governed_delete = await client.delete(
        f"/api/v1/tasks/{task['id']}",
        headers=seed["member_headers"],
    )
    assert governed_delete.status_code == 409

    queue = await client.get(f"{root}/task-reviews", headers=seed["lead_headers"])
    assert queue.status_code == 200, queue.text
    assert [item["id"] for item in queue.json()] == [task["id"]]

    rejected = await client.patch(
        f"{root}/tasks/{task['id']}/review",
        headers=seed["lead_headers"],
        json={
            "decision": "changes_requested",
            "review_note": "Add security scan evidence.",
            "expected_row_version": first_submission["row_version"],
        },
    )
    assert rejected.status_code == 200, rejected.text
    changes = rejected.json()
    assert changes["status"] == "changes_requested"
    assert changes["review_note"] == "Add security scan evidence."

    restarted = await client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        headers=seed["member_headers"],
        json={"status": "in_progress", "expected_row_version": changes["row_version"]},
    )
    assert restarted.status_code == 200, restarted.text
    resubmitted = await client.post(
        f"/api/v1/tasks/{task['id']}/submission",
        headers=seed["member_headers"],
        json={
            "submission_note": "Added security scan and rollback proof.",
            "evidence_urls": [
                "https://github.example/pull/42",
                "https://security.example/scans/42",
            ],
            "expected_row_version": restarted.json()["row_version"],
        },
    )
    assert resubmitted.status_code == 200, resubmitted.text
    accepted = await client.patch(
        f"{root}/tasks/{task['id']}/review",
        headers=seed["lead_headers"],
        json={
            "decision": "accepted",
            "review_note": "Evidence verified.",
            "expected_row_version": resubmitted.json()["row_version"],
        },
    )
    assert accepted.status_code == 200, accepted.text
    completed = accepted.json()
    assert completed["status"] == "completed"
    assert completed["completed_at"] is not None
    assert completed["reviewed_by_user_id"] == seed["delivery_user_id"]


@pytest.mark.asyncio
async def test_member_cannot_create_team_task_or_review_submission(client, auth_headers):
    seed = await _setup_review_flow(client, auth_headers)
    root = (
        f"/api/v1/workspaces/{seed['organization_id']}"
        f"/agent-workspaces/{seed['delivery_id']}/delivery"
    )
    denied_create = await client.post(
        f"{root}/tasks",
        headers=seed["member_headers"],
        json={
            "source_conversation_id": seed["group_id"],
            "owner_id": seed["member_id"],
            "title": "Unauthorized assignment",
        },
    )
    assert denied_create.status_code == 403
    denied_queue = await client.get(f"{root}/task-reviews", headers=seed["member_headers"])
    assert denied_queue.status_code == 403
