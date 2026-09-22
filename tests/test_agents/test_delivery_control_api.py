from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage

import src.db.session as db_session
from src.config import Settings
from src.db.models import AgentWorkspaceConversation, Conversation, ConversationParticipant, User
from tests.test_agent_workspaces import _seed_agent_workspaces
from tests.test_agents.test_delivery_api import _delivery_lead_headers


@pytest.mark.asyncio
async def test_delivery_lead_manages_source_bound_dependency_and_decision(
    client, auth_headers, monkeypatch, fake_llm_factory
):
    seed = await _seed_agent_workspaces(client, auth_headers)
    settings = Settings(
        _env_file=None,
        multi_agent_enabled=True,
        product_delivery_agent_enabled=True,
    )
    monkeypatch.setattr("src.api.delivery_routes.get_settings", lambda: settings)
    monkeypatch.setattr(
        "src.agents.profiles.workspace_delivery_graph.get_workspace_llm",
        lambda _profile: fake_llm_factory(
            [
                AIMessage(content="Portfolio health: BLOCKED. Nguồn: Delivery controls."),
            ]
        ),
    )
    async with db_session.async_session_maker() as db:
        lead = await db.get(User, seed["delivery_user_id"])
        group = Conversation(
            workspace_id=seed["organization_id"],
            type="group",
            name="Delivery controls",
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

    headers = await _delivery_lead_headers(client)
    base = (
        f"/api/v1/workspaces/{seed['organization_id']}"
        f"/agent-workspaces/{seed['delivery_id']}/delivery"
    )
    dependency = await client.post(
        f"{base}/dependencies",
        headers=headers,
        json={
            "source_conversation_id": group.id,
            "title": "Platform API contract",
            "owner_id": seed["delivery_user_id"],
            "due_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        },
    )
    assert dependency.status_code == 201, dependency.text
    blocked = await client.patch(
        f"{base}/dependencies/{dependency.json()['id']}",
        headers=headers,
        json={"status": "blocked", "expected_row_version": 1},
    )
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["row_version"] == 2

    stale_update = await client.patch(
        f"{base}/dependencies/{dependency.json()['id']}",
        headers=headers,
        json={"status": "resolved", "expected_row_version": 1},
    )
    assert stale_update.status_code == 409

    decision = await client.post(
        f"{base}/decisions",
        headers=headers,
        json={
            "source_conversation_id": group.id,
            "title": "Select API compatibility strategy",
            "owner_id": seed["delivery_user_id"],
            "options": ["adapter", "version bump"],
        },
    )
    assert decision.status_code == 201, decision.text
    invalid_decision = await client.patch(
        f"{base}/decisions/{decision.json()['id']}",
        headers=headers,
        json={"status": "decided", "expected_row_version": 1},
    )
    assert invalid_decision.status_code == 422
    decided = await client.patch(
        f"{base}/decisions/{decision.json()['id']}",
        headers=headers,
        json={
            "status": "decided",
            "expected_row_version": 1,
            "outcome": "Use an adapter for backward compatibility",
        },
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "decided"

    brief = await client.post(
        f"{base}/brief",
        headers=headers,
        json={"message": "Show the current dependency and decision state"},
    )
    assert brief.status_code == 200, brief.text
    snapshot = brief.json()["payload"]
    assert snapshot["portfolio_health"]["health"] == "BLOCKED"
    assert snapshot["dependencies"][0]["title"] == "Platform API contract"
    assert snapshot["decisions"][0]["outcome"].startswith("Use an adapter")

    quality_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "quality@example.com", "password": "password123"},
    )
    denied = await client.post(
        f"{base}/dependencies",
        headers={"Authorization": f"Bearer {quality_login.json()['access_token']}"},
        json={
            "source_conversation_id": group.id,
            "title": "Must not cross workspace boundary",
        },
    )
    assert denied.status_code == 403
