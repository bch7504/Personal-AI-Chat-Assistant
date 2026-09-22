from datetime import datetime

import pytest
from sqlalchemy import select

import src.db.session as db_session
from src.db.models import AgentWorkspace, AgentWorkspaceMembership, User


async def _other_user(client, other_auth_headers):
    resp = await client.get("/api/v1/auth/me", headers=other_auth_headers)
    return resp.json()


async def _team_workspace(client, auth_headers, other_auth_headers):
    other = await _other_user(client, other_auth_headers)
    workspace = (
        await client.post(
            "/api/v1/workspaces",
            json={"name": "Chat Team"},
            headers=auth_headers,
        )
    ).json()
    response = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/members",
        json={"email": other["email"], "role": "member"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    return workspace, other


@pytest.mark.asyncio
async def test_create_and_dedupe_direct_conversation(client, auth_headers, other_auth_headers):
    workspace, other = await _team_workspace(client, auth_headers, other_auth_headers)
    payload = {"type": "direct", "participant_ids": [other["id"]], "workspace_id": workspace["id"]}

    resp1 = await client.post("/api/v1/conversations", json=payload, headers=auth_headers)
    assert resp1.status_code == 200
    conv1 = resp1.json()
    assert conv1["type"] == "direct"
    assert conv1["name"] == "Bob"

    resp2 = await client.post("/api/v1/conversations", json=payload, headers=auth_headers)
    assert resp2.status_code == 200
    assert resp2.json()["id"] == conv1["id"]


@pytest.mark.asyncio
async def test_group_conversation_requires_name(client, auth_headers, other_auth_headers):
    workspace, other = await _team_workspace(client, auth_headers, other_auth_headers)
    resp = await client.post(
        "/api/v1/conversations",
        json={"type": "group", "participant_ids": [other["id"]], "workspace_id": workspace["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_group_conversation_with_name(client, auth_headers, other_auth_headers):
    workspace, other = await _team_workspace(client, auth_headers, other_auth_headers)
    resp = await client.post(
        "/api/v1/conversations",
        json={
            "type": "group",
            "participant_ids": [other["id"]],
            "name": "Team",
            "workspace_id": workspace["id"],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "group"
    assert body["scope"] == "personal"
    assert body["agent_workspace_id"] is None
    assert body["name"] == "Team"
    assert len(body["participants"]) == 2


async def _seed_delivery_workspace(workspace_id: str) -> tuple[str, str, str]:
    async with db_session.async_session_maker() as session:
        alice = (await session.execute(select(User).where(User.email == "alice@example.com"))).scalar_one()
        bob = (await session.execute(select(User).where(User.email == "bob@example.com"))).scalar_one()
        delivery = AgentWorkspace(
            organization_workspace_id=workspace_id,
            key="product-delivery",
            name="Product Delivery",
            agent_profile="product_delivery",
        )
        session.add(delivery)
        await session.flush()
        session.add_all(
            [
                AgentWorkspaceMembership(
                    agent_workspace_id=delivery.id,
                    user_id=alice.id,
                    business_role="lead",
                ),
                AgentWorkspaceMembership(
                    agent_workspace_id=delivery.id,
                    user_id=bob.id,
                    business_role="member",
                ),
            ]
        )
        await session.commit()
        return delivery.id, alice.id, bob.id


@pytest.mark.asyncio
async def test_workspace_member_cannot_create_channel(client, auth_headers, other_auth_headers):
    workspace, _ = await _team_workspace(client, auth_headers, other_auth_headers)
    delivery_id, alice_id, _ = await _seed_delivery_workspace(workspace["id"])

    response = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/agent-workspaces/{delivery_id}/channels",
        json={"name": "member-created", "participant_ids": [alice_id]},
        headers=other_auth_headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Only the workspace Lead can create channels"


@pytest.mark.asyncio
async def test_lead_creates_linked_workspace_channel(client, auth_headers, other_auth_headers):
    workspace, _ = await _team_workspace(client, auth_headers, other_auth_headers)
    delivery_id, _, bob_id = await _seed_delivery_workspace(workspace["id"])

    members = await client.get(
        f"/api/v1/workspaces/{workspace['id']}/agent-workspaces/{delivery_id}/channel-members",
        headers=auth_headers,
    )
    assert members.status_code == 200
    assert [member["id"] for member in members.json()] == [bob_id]

    created = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/agent-workspaces/{delivery_id}/channels",
        json={"name": "release-34", "participant_ids": [bob_id], "channel_kind": "release"},
        headers=auth_headers,
    )

    assert created.status_code == 201
    channel = created.json()
    assert channel["type"] == "group"
    assert channel["scope"] == "channel"
    assert channel["agent_workspace_id"] == delivery_id
    assert channel["channel_classification"] == "delivery"
    assert channel["channel_kind"] == "release"

    listed = await client.get(
        f"/api/v1/conversations?workspace_id={workspace['id']}",
        headers=other_auth_headers,
    )
    listed_channel = next(item for item in listed.json()["conversations"] if item["id"] == channel["id"])
    assert listed_channel["scope"] == "channel"


@pytest.mark.asyncio
async def test_send_and_list_messages(client, auth_headers, other_auth_headers):
    workspace, other = await _team_workspace(client, auth_headers, other_auth_headers)
    conv = (
        await client.post(
            "/api/v1/conversations",
            json={"type": "direct", "participant_ids": [other["id"]], "workspace_id": workspace["id"]},
            headers=auth_headers,
        )
    ).json()

    send_resp = await client.post(
        f"/api/v1/conversations/{conv['id']}/messages", json={"content": "hello"}, headers=auth_headers
    )
    assert send_resp.status_code == 200
    assert send_resp.json()["content"] == "hello"

    history = await client.get(f"/api/v1/conversations/{conv['id']}/messages", headers=auth_headers)
    assert history.status_code == 200
    body = history.json()
    assert len(body["messages"]) == 1
    assert body["messages"][0]["content"] == "hello"
    assert body["has_more"] is False


@pytest.mark.asyncio
async def test_unread_count_and_mark_read(client, auth_headers, other_auth_headers):
    workspace, other = await _team_workspace(client, auth_headers, other_auth_headers)
    conv = (
        await client.post(
            "/api/v1/conversations",
            json={"type": "direct", "participant_ids": [other["id"]], "workspace_id": workspace["id"]},
            headers=auth_headers,
        )
    ).json()
    sent = await client.post(
        f"/api/v1/conversations/{conv['id']}/messages",
        json={"content": "hi bob"},
        headers=auth_headers,
    )

    listed = await client.get(
        f"/api/v1/conversations?workspace_id={workspace['id']}",
        headers=other_auth_headers,
    )
    summary = next(c for c in listed.json()["conversations"] if c["id"] == conv["id"])
    assert summary["unread_count"] == 1

    await client.post(f"/api/v1/conversations/{conv['id']}/read", headers=other_auth_headers)
    listed_again = await client.get(
        f"/api/v1/conversations?workspace_id={workspace['id']}",
        headers=other_auth_headers,
    )
    summary_again = next(c for c in listed_again.json()["conversations"] if c["id"] == conv["id"])
    assert summary_again["unread_count"] == 0

    # Alice can now render Bob's avatar below the newest message his cursor has reached.
    history_for_sender = await client.get(
        f"/api/v1/conversations/{conv['id']}/messages",
        headers=auth_headers,
    )
    receipts = history_for_sender.json()["read_receipts"]
    assert len(receipts) == 1
    assert receipts[0]["user_id"] == other["id"]
    assert receipts[0]["display_name"] == other["display_name"]
    assert datetime.fromisoformat(receipts[0]["read_at"]) >= datetime.fromisoformat(sent.json()["created_at"])


@pytest.mark.asyncio
async def test_sending_a_last_message_advances_sender_read_cursor(
    client, auth_headers, other_auth_headers
):
    workspace, other = await _team_workspace(client, auth_headers, other_auth_headers)
    conv = (
        await client.post(
            "/api/v1/conversations",
            json={"type": "direct", "participant_ids": [other["id"]], "workspace_id": workspace["id"]},
            headers=auth_headers,
        )
    ).json()

    await client.post(
        f"/api/v1/conversations/{conv['id']}/messages",
        json={"content": "Tin từ người khác chưa đọc"},
        headers=other_auth_headers,
    )
    before_reply = await client.get(
        f"/api/v1/conversations?workspace_id={workspace['id']}", headers=auth_headers
    )
    summary = next(item for item in before_reply.json()["conversations"] if item["id"] == conv["id"])
    assert summary["unread_count"] == 1

    reply = await client.post(
        f"/api/v1/conversations/{conv['id']}/messages",
        json={"content": "Tôi đã xem và trả lời"},
        headers=auth_headers,
    )
    after_reply = await client.get(
        f"/api/v1/conversations?workspace_id={workspace['id']}", headers=auth_headers
    )
    summary = next(item for item in after_reply.json()["conversations"] if item["id"] == conv["id"])
    assert summary["unread_count"] == 0
    assert summary["last_message"]["id"] == reply.json()["id"]
    assert summary["last_message"]["sender_id"] != other["id"]


@pytest.mark.asyncio
async def test_first_unread_message_id_in_message_list(client, auth_headers, other_auth_headers):
    workspace, other = await _team_workspace(client, auth_headers, other_auth_headers)
    conv = (
        await client.post(
            "/api/v1/conversations",
            json={"type": "direct", "participant_ids": [other["id"]], "workspace_id": workspace["id"]},
            headers=auth_headers,
        )
    ).json()

    # Alice sends two messages; Bob hasn't read anything yet - the first one is his first unread.
    first = await client.post(
        f"/api/v1/conversations/{conv['id']}/messages", json={"content": "hi bob"}, headers=auth_headers
    )
    await client.post(
        f"/api/v1/conversations/{conv['id']}/messages", json={"content": "still there?"}, headers=auth_headers
    )

    history = await client.get(f"/api/v1/conversations/{conv['id']}/messages", headers=other_auth_headers)
    assert history.json()["first_unread_message_id"] == first.json()["id"]

    # Paginating into older history (`before` set) doesn't recompute it - not the "just opened" moment.
    paged = await client.get(
        f"/api/v1/conversations/{conv['id']}/messages",
        params={"before": first.json()["id"]},
        headers=other_auth_headers,
    )
    assert paged.json()["first_unread_message_id"] is None


@pytest.mark.asyncio
async def test_first_unread_message_id_none_after_marking_read(client, auth_headers, other_auth_headers):
    workspace, other = await _team_workspace(client, auth_headers, other_auth_headers)
    conv = (
        await client.post(
            "/api/v1/conversations",
            json={"type": "direct", "participant_ids": [other["id"]], "workspace_id": workspace["id"]},
            headers=auth_headers,
        )
    ).json()
    await client.post(f"/api/v1/conversations/{conv['id']}/messages", json={"content": "hi bob"}, headers=auth_headers)

    await client.post(f"/api/v1/conversations/{conv['id']}/read", headers=other_auth_headers)

    history = await client.get(f"/api/v1/conversations/{conv['id']}/messages", headers=other_auth_headers)
    assert history.json()["first_unread_message_id"] is None


@pytest.mark.asyncio
async def test_first_unread_message_id_none_for_own_messages(client, auth_headers, other_auth_headers):
    workspace, other = await _team_workspace(client, auth_headers, other_auth_headers)
    conv = (
        await client.post(
            "/api/v1/conversations",
            json={"type": "direct", "participant_ids": [other["id"]], "workspace_id": workspace["id"]},
            headers=auth_headers,
        )
    ).json()
    await client.post(f"/api/v1/conversations/{conv['id']}/messages", json={"content": "hi bob"}, headers=auth_headers)

    history = await client.get(f"/api/v1/conversations/{conv['id']}/messages", headers=auth_headers)
    assert history.json()["first_unread_message_id"] is None


@pytest.mark.asyncio
async def test_non_participant_forbidden(client, auth_headers, other_auth_headers):
    workspace, other = await _team_workspace(client, auth_headers, other_auth_headers)
    conv = (
        await client.post(
            "/api/v1/conversations",
            json={"type": "direct", "participant_ids": [other["id"]], "workspace_id": workspace["id"]},
            headers=auth_headers,
        )
    ).json()

    await client.post(
        "/api/v1/auth/register",
        json={"email": "carol@example.com", "password": "password123", "display_name": "Carol"},
    )
    third = await client.post(
        "/api/v1/auth/login",
        json={"email": "carol@example.com", "password": "password123"},
    )
    carol_headers = {"Authorization": f"Bearer {third.json()['access_token']}"}

    resp = await client.get(f"/api/v1/conversations/{conv['id']}/messages", headers=carol_headers)
    assert resp.status_code == 404

    resp2 = await client.post(
        f"/api/v1/conversations/{conv['id']}/messages", json={"content": "hey"}, headers=carol_headers
    )
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_list_users_excludes_self(client, auth_headers, other_auth_headers):
    workspace, _ = await _team_workspace(client, auth_headers, other_auth_headers)
    resp = await client.get(f"/api/v1/users?workspace_id={workspace['id']}", headers=auth_headers)
    assert resp.status_code == 200
    emails = [u["email"] for u in resp.json()]
    assert "bob@example.com" in emails
    assert "alice@example.com" not in emails


@pytest.mark.asyncio
async def test_open_test_chat_auto_joins_accounts_and_allows_direct_messages(client, monkeypatch):
    from src.config import get_settings

    alice_register = await client.post(
        "/api/v1/auth/register",
        json={"email": "open-alice@example.com", "password": "password123", "display_name": "Open Alice"},
    )
    bob_register = await client.post(
        "/api/v1/auth/register",
        json={"email": "open-bob@example.com", "password": "password123", "display_name": "Open Bob"},
    )
    assert alice_register.status_code == 201
    assert bob_register.status_code == 201

    alice_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "open-alice@example.com", "password": "password123"},
    )
    bob_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "open-bob@example.com", "password": "password123"},
    )
    alice_headers = {"Authorization": f"Bearer {alice_login.json()['access_token']}"}
    bob_headers = {"Authorization": f"Bearer {bob_login.json()['access_token']}"}

    # Simulate enabling public test chat after these users already have active sessions.
    test_settings = get_settings().model_copy(update={"open_test_chat_enabled": True})
    monkeypatch.setattr("src.services.company_service.get_settings", lambda: test_settings)

    alice_workspaces = (await client.get("/api/v1/workspaces", headers=alice_headers)).json()
    bob_workspaces = (await client.get("/api/v1/workspaces", headers=bob_headers)).json()
    alice_company = next(workspace for workspace in alice_workspaces if workspace["type"] == "organization")
    bob_company = next(workspace for workspace in bob_workspaces if workspace["type"] == "organization")
    assert alice_company["id"] == bob_company["id"]

    directory = await client.get(
        f"/api/v1/users?workspace_id={alice_company['id']}",
        headers=alice_headers,
    )
    assert directory.status_code == 200
    assert "open-bob@example.com" in {user["email"] for user in directory.json()}

    created = await client.post(
        "/api/v1/conversations",
        json={
            "type": "direct",
            "participant_ids": [bob_register.json()["id"]],
            "workspace_id": alice_company["id"],
        },
        headers=alice_headers,
    )
    assert created.status_code == 200

    bob_conversations = await client.get(
        f"/api/v1/conversations?workspace_id={bob_company['id']}",
        headers=bob_headers,
    )
    assert created.json()["id"] in {
        conversation["id"] for conversation in bob_conversations.json()["conversations"]
    }


@pytest.mark.asyncio
async def test_hide_conversation_is_per_user_and_new_message_restores_it(
    client, auth_headers, other_auth_headers
):
    workspace, other = await _team_workspace(client, auth_headers, other_auth_headers)
    conversation = (
        await client.post(
            "/api/v1/conversations",
            json={"type": "direct", "participant_ids": [other["id"]], "workspace_id": workspace["id"]},
            headers=auth_headers,
        )
    ).json()

    hidden = await client.delete(f"/api/v1/conversations/{conversation['id']}", headers=auth_headers)
    assert hidden.status_code == 204
    mine = await client.get(f"/api/v1/conversations?workspace_id={workspace['id']}", headers=auth_headers)
    theirs = await client.get(
        f"/api/v1/conversations?workspace_id={workspace['id']}", headers=other_auth_headers
    )
    assert conversation["id"] not in {item["id"] for item in mine.json()["conversations"]}
    assert conversation["id"] in {item["id"] for item in theirs.json()["conversations"]}

    sent = await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "This should restore the hidden conversation"},
        headers=other_auth_headers,
    )
    assert sent.status_code == 200
    restored = await client.get(
        f"/api/v1/conversations?workspace_id={workspace['id']}", headers=auth_headers
    )
    assert conversation["id"] in {item["id"] for item in restored.json()["conversations"]}


@pytest.mark.asyncio
async def test_leave_group_revokes_access_and_keeps_remaining_member(
    client, auth_headers, other_auth_headers
):
    workspace, other = await _team_workspace(client, auth_headers, other_auth_headers)
    conversation = (
        await client.post(
            "/api/v1/conversations",
            json={
                "type": "group",
                "participant_ids": [other["id"]],
                "name": "Lifecycle group",
                "workspace_id": workspace["id"],
            },
            headers=auth_headers,
        )
    ).json()

    left = await client.post(
        f"/api/v1/conversations/{conversation['id']}/leave", headers=other_auth_headers
    )
    assert left.status_code == 200
    assert left.json()["conversation_deleted"] is False
    denied = await client.get(
        f"/api/v1/conversations/{conversation['id']}/messages", headers=other_auth_headers
    )
    assert denied.status_code == 404
    remaining = await client.get(
        f"/api/v1/conversations/{conversation['id']}/messages", headers=auth_headers
    )
    assert remaining.status_code == 200
