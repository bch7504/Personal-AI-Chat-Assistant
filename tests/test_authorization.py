from importlib import import_module

import pytest
from sqlalchemy import select

from src.db import session as db_session
from src.db.models import User
from src.services import authorization_service, workspace_service


async def _create_private_conversation(client, auth_headers, other_auth_headers):
    bob = (await client.get("/api/v1/auth/me", headers=other_auth_headers)).json()
    workspace = (
        await client.post(
            "/api/v1/workspaces",
            json={"name": "Private Conversation Team"},
            headers=auth_headers,
        )
    ).json()
    member_response = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/members",
        json={"email": bob["email"], "role": "member"},
        headers=auth_headers,
    )
    assert member_response.status_code == 201
    return (
        await client.post(
            "/api/v1/conversations",
            json={
                "type": "direct",
                "participant_ids": [bob["id"]],
                "workspace_id": workspace["id"],
            },
            headers=auth_headers,
        )
    ).json()


@pytest.mark.asyncio
async def test_current_user_exposes_platform_role(client, auth_headers):
    response = await client.get("/api/v1/auth/me", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["platform_role"] == "user"


@pytest.mark.asyncio
async def test_legacy_admin_role_does_not_grant_platform_access(client, legacy_admin_headers):
    response = await client.get("/api/v1/platform/stats", headers=legacy_admin_headers)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_platform_admin_can_read_aggregate_platform_stats(client, platform_admin_headers):
    response = await client.get("/api/v1/platform/stats", headers=platform_admin_headers)

    assert response.status_code == 200
    assert set(response.json()) == {
        "total_users",
        "total_workspaces",
        "total_conversations",
        "total_messages",
        "new_users_last_7_days",
    }


@pytest.mark.asyncio
async def test_active_owner_satisfies_workspace_role(client, auth_headers):
    current_user = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()

    async with db_session.async_session_maker() as db:
        workspace = await workspace_service.create_organization_workspace(
            db,
            name="Authorization Matrix",
            owner_user_id=current_user["id"],
        )
        await db.commit()
        user = await db.get(User, current_user["id"])

        membership = await authorization_service.require_workspace_role(
            db,
            user,
            workspace.id,
            {"owner", "admin"},
        )

        assert membership.role == "owner"


@pytest.mark.asyncio
async def test_platform_admin_can_request_scoped_support_access(
    client,
    auth_headers,
    platform_admin_headers,
):
    workspace = (
        await client.post(
            "/api/v1/workspaces",
            json={"name": "Customer Support"},
            headers=auth_headers,
        )
    ).json()

    response = await client.post(
        "/api/v1/platform/support-grants",
        json={
            "workspace_id": workspace["id"],
            "requested_scope": "conversation:read",
            "reason": "Investigate customer-reported delivery failure",
            "duration_minutes": 30,
        },
        headers=platform_admin_headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["workspace_id"] == workspace["id"]
    assert body["requested_scope"] == "conversation:read"
    assert body["status"] == "requested"
    assert body["approved_at"] is None
    assert body["revoked_at"] is None


@pytest.mark.asyncio
async def test_active_workspace_owner_can_approve_support_access(
    client,
    auth_headers,
    platform_admin_headers,
):
    owner = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    workspace = (
        await client.post(
            "/api/v1/workspaces",
            json={"name": "Owner Approval"},
            headers=auth_headers,
        )
    ).json()
    requested = (
        await client.post(
            "/api/v1/platform/support-grants",
            json={
                "workspace_id": workspace["id"],
                "requested_scope": "conversation:read",
                "reason": "Investigate customer-reported delivery failure",
                "duration_minutes": 30,
            },
            headers=platform_admin_headers,
        )
    ).json()

    response = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/support-grants/{requested['id']}/approve",
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["approved_by_owner_id"] == owner["id"]
    assert body["approved_at"] is not None


@pytest.mark.asyncio
async def test_workspace_owner_can_reject_and_revoke_support_access(
    client,
    auth_headers,
    platform_admin_headers,
):
    workspace = (
        await client.post(
            "/api/v1/workspaces",
            json={"name": "Grant lifecycle"},
            headers=auth_headers,
        )
    ).json()

    async def request_grant(scope):
        response = await client.post(
            "/api/v1/platform/support-grants",
            json={
                "workspace_id": workspace["id"],
                "requested_scope": scope,
                "reason": "Resolve a customer-approved support incident",
                "duration_minutes": 30,
            },
            headers=platform_admin_headers,
        )
        assert response.status_code == 201
        return response.json()

    rejected = await request_grant("personal_data:read")
    response = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/support-grants/{rejected['id']}/reject",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"

    approved = await request_grant("personal_data:manage")
    response = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/support-grants/{approved['id']}/approve",
        headers=auth_headers,
    )
    assert response.status_code == 200

    async with db_session.async_session_maker() as db:
        platform_admin = (await db.execute(select(User).where(User.email == "platform@example.com"))).scalar_one()
        inherited = await authorization_service.require_support_scope(
            db, platform_admin, workspace["id"], "personal_data:read"
        )
        assert inherited.id == approved["id"]

    response = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/support-grants/{approved['id']}/revoke",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"


@pytest.mark.asyncio
async def test_platform_admin_cannot_approve_own_support_request(client, platform_admin_headers):
    workspace = (
        await client.post(
            "/api/v1/workspaces",
            json={"name": "No Self Approval"},
            headers=platform_admin_headers,
        )
    ).json()
    requested = (
        await client.post(
            "/api/v1/platform/support-grants",
            json={
                "workspace_id": workspace["id"],
                "requested_scope": "conversation:read",
                "reason": "Investigate customer-reported delivery failure",
                "duration_minutes": 30,
            },
            headers=platform_admin_headers,
        )
    ).json()

    response = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/support-grants/{requested['id']}/approve",
        headers=platform_admin_headers,
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_approved_support_scope_is_checked_from_current_database_state(
    client,
    auth_headers,
    platform_admin_headers,
):
    workspace = (
        await client.post(
            "/api/v1/workspaces",
            json={"name": "Request-time Grant Check"},
            headers=auth_headers,
        )
    ).json()
    requested = (
        await client.post(
            "/api/v1/platform/support-grants",
            json={
                "workspace_id": workspace["id"],
                "requested_scope": "conversation:read",
                "reason": "Investigate customer-reported delivery failure",
                "duration_minutes": 30,
            },
            headers=platform_admin_headers,
        )
    ).json()
    await client.post(
        f"/api/v1/workspaces/{workspace['id']}/support-grants/{requested['id']}/approve",
        headers=auth_headers,
    )

    async with db_session.async_session_maker() as db:
        platform_admin = (await db.execute(select(User).where(User.email == "platform@example.com"))).scalar_one()

        grant = await authorization_service.require_support_scope(
            db,
            platform_admin,
            workspace["id"],
            "conversation:read",
        )

        assert grant.id == requested["id"]


@pytest.mark.asyncio
async def test_audit_service_records_identifier_metadata_without_content(client, auth_headers):
    current_user = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    audit_service = import_module("src.services.audit_service")

    async with db_session.async_session_maker() as db:
        actor = await db.get(User, current_user["id"])
        record = await audit_service.record_audit_event(
            db,
            actor=actor,
            action="workspace.created",
            target_type="workspace",
            target_id="workspace-123",
            workspace_id=None,
            metadata={"source": "api"},
        )
        await db.commit()

        assert record.actor_user_id == actor.id
        assert record.actor_type == "user"
        assert record.metadata_json == {"source": "api"}


@pytest.mark.asyncio
@pytest.mark.parametrize("forbidden_key", ["content", "message", "memory", "token", "secret"])
async def test_audit_service_rejects_sensitive_metadata(client, auth_headers, forbidden_key):
    current_user = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    audit_service = import_module("src.services.audit_service")

    async with db_session.async_session_maker() as db:
        actor = await db.get(User, current_user["id"])

        with pytest.raises(ValueError, match="sensitive"):
            await audit_service.record_audit_event(
                db,
                actor=actor,
                action="conversation.inspected",
                target_type="conversation",
                target_id="conversation-123",
                workspace_id=None,
                metadata={forbidden_key: "must not be stored"},
            )


@pytest.mark.asyncio
async def test_platform_admin_cannot_use_admin_route_to_read_private_messages(
    client,
    admin_auth_headers,
    auth_headers,
    other_auth_headers,
):
    conversation = await _create_private_conversation(client, auth_headers, other_auth_headers)
    await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "private message"},
        headers=auth_headers,
    )

    response = await client.get(
        f"/api/v1/admin/conversations/{conversation['id']}/messages",
        headers=admin_auth_headers,
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_platform_admin_cannot_list_private_conversations(
    client,
    admin_auth_headers,
    auth_headers,
    other_auth_headers,
):
    await _create_private_conversation(client, auth_headers, other_auth_headers)

    response = await client.get("/api/v1/admin/conversations", headers=admin_auth_headers)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_platform_admin_cannot_delete_private_conversation(
    client,
    admin_auth_headers,
    auth_headers,
    other_auth_headers,
):
    conversation = await _create_private_conversation(client, auth_headers, other_auth_headers)

    response = await client.delete(
        f"/api/v1/admin/conversations/{conversation['id']}",
        headers=admin_auth_headers,
    )

    assert response.status_code == 404
