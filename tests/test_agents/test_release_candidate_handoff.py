from __future__ import annotations

import pytest

import src.db.session as db_session
from src.config import Settings
from src.db.models import AgentWorkspaceConversation, Conversation, ConversationParticipant, User
from tests.test_agent_workspaces import _seed_agent_workspaces


@pytest.mark.asyncio
async def test_delivery_to_quality_handoff_is_structured_and_gate_controlled(
    client, auth_headers, monkeypatch
):
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
        delivery_group = Conversation(
            workspace_id=seed["organization_id"],
            type="group",
            name="Delivery Release",
            created_by=delivery_lead.id,
            ai_enabled=True,
            ai_policy_version=1,
        )
        db.add(delivery_group)
        await db.flush()
        db.add_all(
            [
                AgentWorkspaceConversation(
                    agent_workspace_id=seed["delivery_id"],
                    conversation_id=delivery_group.id,
                    classification="delivery",
                    linked_by_user_id=delivery_lead.id,
                ),
                ConversationParticipant(
                    conversation_id=delivery_group.id,
                    principal_kind="workspace_user",
                    user_id=delivery_lead.id,
                    resource_role="manager",
                    invited_by_user_id=delivery_lead.id,
                ),
            ]
        )
        await db.commit()

    delivery_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "delivery@example.com", "password": "password123"},
    )
    delivery_headers = {"Authorization": f"Bearer {delivery_login.json()['access_token']}"}
    created = await client.post(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/{seed['delivery_id']}/delivery/release-candidates",
        headers=delivery_headers,
        json={
            "quality_agent_workspace_id": seed["quality_id"],
            "source_conversation_id": delivery_group.id,
            "release_key": "R-HANDOFF",
            "version": "1.0.0",
            "build_number": "42",
            "environment": "staging",
        },
    )
    assert created.status_code == 201, created.text
    candidate = created.json()
    assert candidate["status"] == "qa_requested"

    quality_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "quality@example.com", "password": "password123"},
    )
    quality_headers = {"Authorization": f"Bearer {quality_login.json()['access_token']}"}
    quality_base = (
        f"/api/v1/workspaces/{seed['organization_id']}"
        f"/agent-workspaces/{seed['quality_id']}/quality/release-candidates"
    )
    listed = await client.get(quality_base, headers=quality_headers)
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [candidate["id"]]

    started = await client.patch(
        f"{quality_base}/{candidate['id']}/status",
        headers=quality_headers,
        json={"status": "qa_in_progress", "expected_row_version": 1},
    )
    assert started.status_code == 200, started.text
    assert started.json()["row_version"] == 2

    delivery_view = await client.get(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/"
        f"{seed['delivery_id']}/delivery/release-candidates",
        headers=delivery_headers,
    )
    assert delivery_view.status_code == 200, delivery_view.text
    assert delivery_view.json()[0]["status"] == "qa_in_progress"

    blocked_approval = await client.patch(
        f"{quality_base}/{candidate['id']}/status",
        headers=quality_headers,
        json={"status": "approved", "expected_row_version": 2},
    )
    assert blocked_approval.status_code == 409
    assert "AT_RISK" in blocked_approval.json()["detail"]
