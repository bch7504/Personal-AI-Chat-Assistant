from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from src.db import session as db_session
from src.db.models import User, WorkspaceMembership
from src.services.people_intelligence_service import build_relevant_people_context


async def _organization_with_member(client, auth_headers, other_auth_headers):
    other = (await client.get("/api/v1/auth/me", headers=other_auth_headers)).json()
    workspace_response = await client.post(
        "/api/v1/workspaces",
        json={"name": "People Intelligence Team"},
        headers=auth_headers,
    )
    assert workspace_response.status_code == 201
    workspace = workspace_response.json()
    member_response = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/members",
        json={"email": other["email"], "role": "member"},
        headers=auth_headers,
    )
    assert member_response.status_code == 201
    return workspace, other


@pytest.mark.asyncio
async def test_people_insights_derive_activity_and_keep_preferences_private(
    client,
    auth_headers,
    other_auth_headers,
):
    workspace, other = await _organization_with_member(client, auth_headers, other_auth_headers)
    conversation_response = await client.post(
        "/api/v1/conversations",
        json={
            "type": "direct",
            "participant_ids": [other["id"]],
            "workspace_id": workspace["id"],
        },
        headers=auth_headers,
    )
    assert conversation_response.status_code == 200
    conversation = conversation_response.json()
    for headers, content in ((auth_headers, "Hi Bob"), (other_auth_headers, "Hi Alice")):
        message_response = await client.post(
            f"/api/v1/conversations/{conversation['id']}/messages",
            json={"content": content},
            headers=headers,
        )
        assert message_response.status_code == 200

    insights_response = await client.get(
        f"/api/v1/workspaces/{workspace['id']}/people-insights",
        headers=auth_headers,
    )
    assert insights_response.status_code == 200
    insight = insights_response.json()[0]
    assert insight["user_id"] == other["id"]
    assert insight["message_count_30d"] == 2
    assert insight["direct_message_count_30d"] == 2
    assert insight["shared_conversation_count"] == 1
    assert insight["interaction_score"] > 0
    assert "recent" in insight["tags"]
    assert insight["metric_window_days"] == 30
    assert insight["score_version"] == "v1"

    follow_up_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    update_response = await client.patch(
        f"/api/v1/workspaces/{workspace['id']}/people-insights/{other['id']}",
        json={
            "is_pinned": True,
            "private_note": "Prefers concise technical updates",
            "follow_up_at": follow_up_at,
        },
        headers=auth_headers,
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["is_pinned"] is True
    assert updated["private_note"] == "Prefers concise technical updates"
    assert {"pinned", "follow_up"}.issubset(updated["tags"])

    other_view_response = await client.get(
        f"/api/v1/workspaces/{workspace['id']}/people-insights",
        headers=other_auth_headers,
    )
    assert other_view_response.status_code == 200
    alice_in_other_view = other_view_response.json()[0]
    assert alice_in_other_view["private_note"] is None
    assert alice_in_other_view["is_pinned"] is False

    async with db_session.async_session_maker() as db:
        owner = (await db.execute(select(User).where(User.email == "alice@example.com"))).scalar_one()
        unrelated_context = await build_relevant_people_context(
            db,
            owner,
            workspace["id"],
            "Tạo nhắc nhở vào ngày mai",
        )
        people_context = await build_relevant_people_context(
            db,
            owner,
            workspace["id"],
            "Tôi nên trao đổi với Bob như thế nào?",
        )
    assert unrelated_context == ""
    assert "name=Bob" in people_context
    assert "private_note=Prefers concise technical updates" in people_context


@pytest.mark.asyncio
async def test_personal_workspace_has_no_coworker_directory(client, auth_headers, personal_workspace):
    response = await client.get(
        f"/api/v1/workspaces/{personal_workspace['id']}/people-insights",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_guest_cannot_read_people_insights(client, auth_headers, other_auth_headers):
    workspace, other = await _organization_with_member(client, auth_headers, other_auth_headers)
    async with db_session.async_session_maker() as db:
        membership = (
            await db.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == workspace["id"],
                    WorkspaceMembership.user_id == other["id"],
                )
            )
        ).scalar_one()
        membership.role = "guest"
        await db.commit()

    response = await client.get(
        f"/api/v1/workspaces/{workspace['id']}/people-insights",
        headers=other_auth_headers,
    )
    assert response.status_code == 403
