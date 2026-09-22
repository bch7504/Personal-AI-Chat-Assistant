import pytest
from sqlalchemy import select

import src.db.session as db_session
from src.db.models import User, WorkspaceMembership
from src.services.scheduler import scheduler


async def _personal_workspace(client, headers):
    response = await client.get("/api/v1/workspaces", headers=headers)
    assert response.status_code == 200
    return next(workspace for workspace in response.json() if workspace["type"] == "personal")


async def _approve_support_scope(client, admin_headers, owner_headers, workspace_id, scope):
    requested = await client.post(
        "/api/v1/platform/support-grants",
        json={
            "workspace_id": workspace_id,
            "requested_scope": scope,
            "reason": "Investigate an owner-approved support request",
            "duration_minutes": 30,
        },
        headers=admin_headers,
    )
    assert requested.status_code == 201
    approved = await client.post(
        f"/api/v1/workspaces/{workspace_id}/support-grants/{requested.json()['id']}/approve",
        headers=owner_headers,
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


@pytest.mark.asyncio
async def test_me_includes_role(client, auth_headers):
    resp = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["role"] == "user"


@pytest.mark.asyncio
async def test_non_admin_cannot_access_admin_routes(client, auth_headers):
    resp = await client.get("/api/v1/admin/stats", headers=auth_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_view_stats(client, admin_auth_headers, auth_headers):
    resp = await client.get("/api/v1/admin/stats", headers=admin_auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_users"] >= 2
    assert "total_conversations" in body
    assert "total_messages" in body
    assert "new_users_last_7_days" in body


@pytest.mark.asyncio
async def test_admin_can_list_users(client, admin_auth_headers, auth_headers):
    resp = await client.get("/api/v1/admin/users", headers=admin_auth_headers)
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert "admin@example.com" in emails
    assert "alice@example.com" in emails


@pytest.mark.asyncio
async def test_single_company_is_fixed_and_platform_admin_does_not_join_it(
    client, admin_auth_headers, auth_headers
):
    response = await client.get("/api/v1/admin/company", headers=admin_auth_headers)
    assert response.status_code == 200
    company = response.json()
    assert company["slug"] == "company-root"

    same_company = await client.get("/api/v1/admin/company", headers=admin_auth_headers)
    assert same_company.json()["id"] == company["id"]

    cannot_create_another_company = await client.post(
        "/api/v1/admin/workspaces",
        json={"name": "Provisioned Company", "owner_email": "alice@example.com"},
        headers=admin_auth_headers,
    )
    assert cannot_create_another_company.status_code == 409

    async with db_session.async_session_maker() as db:
        admin = (await db.execute(select(User).where(User.email == "admin@example.com"))).scalar_one()
        admin_membership = (
            await db.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == company["id"],
                    WorkspaceMembership.user_id == admin.id,
                )
            )
        ).scalar_one_or_none()
    assert admin_membership is None


@pytest.mark.asyncio
async def test_admin_can_promote_and_demote_other_user(client, admin_auth_headers, auth_headers):
    users_resp = await client.get("/api/v1/admin/users", headers=admin_auth_headers)
    alice = next(u for u in users_resp.json() if u["email"] == "alice@example.com")

    resp = await client.patch(
        f"/api/v1/admin/users/{alice['id']}/role", json={"role": "admin"}, headers=admin_auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"

    resp = await client.patch(
        f"/api/v1/admin/users/{alice['id']}/role", json={"role": "user"}, headers=admin_auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "user"


@pytest.mark.asyncio
async def test_admin_cannot_change_own_role(client, admin_auth_headers):
    me = await client.get("/api/v1/auth/me", headers=admin_auth_headers)
    resp = await client.patch(
        f"/api/v1/admin/users/{me.json()['id']}/role", json={"role": "user"}, headers=admin_auth_headers
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_admin_cannot_deactivate_own_account(client, admin_auth_headers):
    me = await client.get("/api/v1/auth/me", headers=admin_auth_headers)
    resp = await client.patch(
        f"/api/v1/admin/users/{me.json()['id']}/status", json={"is_active": False}, headers=admin_auth_headers
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_deactivated_user_loses_access(client, admin_auth_headers, auth_headers):
    users_resp = await client.get("/api/v1/admin/users", headers=admin_auth_headers)
    alice = next(u for u in users_resp.json() if u["email"] == "alice@example.com")

    resp = await client.patch(
        f"/api/v1/admin/users/{alice['id']}/status", json={"is_active": False}, headers=admin_auth_headers
    )
    assert resp.status_code == 200

    resp = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_platform_admin_cannot_list_view_or_delete_private_conversations(
    client,
    admin_auth_headers,
    auth_headers,
    other_auth_headers,
):
    bob = (await client.get("/api/v1/auth/me", headers=other_auth_headers)).json()
    workspace = (
        await client.post(
            "/api/v1/workspaces",
            json={"name": "Private Team"},
            headers=auth_headers,
        )
    ).json()
    await client.post(
        f"/api/v1/workspaces/{workspace['id']}/members",
        json={"email": bob["email"], "role": "member"},
        headers=auth_headers,
    )
    conv = (
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

    resp = await client.get("/api/v1/admin/conversations", headers=admin_auth_headers)
    assert resp.status_code == 404

    resp = await client.get(f"/api/v1/admin/conversations/{conv['id']}/messages", headers=admin_auth_headers)
    assert resp.status_code == 404

    resp = await client.delete(f"/api/v1/admin/conversations/{conv['id']}", headers=admin_auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_non_admin_cannot_access_new_admin_routes(client, auth_headers):
    for path in ("/api/v1/admin/tasks", "/api/v1/admin/reminders", "/api/v1/admin/memories"):
        resp = await client.get(path, headers=auth_headers)
        assert resp.status_code == 403, path


@pytest.mark.asyncio
async def test_admin_can_list_and_delete_tasks(client, admin_auth_headers, auth_headers):
    alice = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    workspace = await _personal_workspace(client, auth_headers)
    created = (await client.post("/api/v1/tasks", json={"title": "Admin-visible task"}, headers=auth_headers)).json()

    await _approve_support_scope(client, admin_auth_headers, auth_headers, workspace["id"], "personal_data:read")
    resp = await client.get(f"/api/v1/admin/tasks?workspace_id={workspace['id']}", headers=admin_auth_headers)
    assert resp.status_code == 200
    listed = next(t for t in resp.json() if t["id"] == created["id"])
    assert listed["owner_id"] == alice["id"]
    assert listed["owner_email"] == "alice@example.com"
    assert listed["owner_display_name"] == alice["display_name"]
    assert listed["conversation_label"] is None

    await _approve_support_scope(client, admin_auth_headers, auth_headers, workspace["id"], "personal_data:manage")
    resp = await client.delete(
        f"/api/v1/admin/tasks/{created['id']}?workspace_id={workspace['id']}",
        headers=admin_auth_headers,
    )
    assert resp.status_code == 204

    resp = await client.get("/api/v1/tasks", headers=auth_headers)
    assert created["id"] not in [t["id"] for t in resp.json()]


@pytest.mark.asyncio
async def test_admin_tasks_owner_filter(client, admin_auth_headers, auth_headers, other_auth_headers):
    alice = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    bob = (await client.get("/api/v1/auth/me", headers=other_auth_headers)).json()
    workspace = (await client.post("/api/v1/workspaces", json={"name": "Shared tasks"}, headers=auth_headers)).json()
    await client.post(
        f"/api/v1/workspaces/{workspace['id']}/members",
        json={"email": bob["email"], "role": "member"},
        headers=auth_headers,
    )
    await client.post(
        "/api/v1/tasks",
        json={"title": "Alice task", "workspace_id": workspace["id"]},
        headers=auth_headers,
    )
    await client.post(
        "/api/v1/tasks",
        json={"title": "Bob task", "workspace_id": workspace["id"]},
        headers=other_auth_headers,
    )
    await _approve_support_scope(client, admin_auth_headers, auth_headers, workspace["id"], "personal_data:read")

    resp = await client.get(
        f"/api/v1/admin/tasks?workspace_id={workspace['id']}&owner_id={alice['id']}",
        headers=admin_auth_headers,
    )
    assert resp.status_code == 200
    owners = {t["owner_id"] for t in resp.json()}
    assert owners == {alice["id"]}


@pytest.mark.asyncio
async def test_admin_can_list_and_delete_memories(client, admin_auth_headers, auth_headers):
    alice = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    workspace = await _personal_workspace(client, auth_headers)
    created = (
        await client.post(
            "/api/v1/memories", json={"category": "Work", "title": "Admin-visible memory"}, headers=auth_headers
        )
    ).json()

    await _approve_support_scope(client, admin_auth_headers, auth_headers, workspace["id"], "personal_data:read")
    resp = await client.get(f"/api/v1/admin/memories?workspace_id={workspace['id']}", headers=admin_auth_headers)
    assert resp.status_code == 200
    listed = next(m for m in resp.json() if m["id"] == created["id"])
    assert listed["owner_id"] == alice["id"]
    assert listed["owner_email"] == "alice@example.com"

    await _approve_support_scope(client, admin_auth_headers, auth_headers, workspace["id"], "personal_data:manage")
    resp = await client.delete(
        f"/api/v1/admin/memories/{created['id']}?workspace_id={workspace['id']}",
        headers=admin_auth_headers,
    )
    assert resp.status_code == 204

    resp = await client.get("/api/v1/memories", headers=auth_headers)
    assert created["id"] not in [m["id"] for m in resp.json()]


@pytest.mark.asyncio
async def test_admin_can_list_and_delete_reminders_and_cancels_scheduler_job(client, admin_auth_headers, auth_headers):
    alice = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    workspace = await _personal_workspace(client, auth_headers)
    created = (
        await client.post(
            "/api/v1/reminders",
            json={"title": "Admin-visible reminder", "due_at_iso": "2099-08-10T15:00:00"},
            headers=auth_headers,
        )
    ).json()
    assert scheduler.get_job(created["id"]) is not None

    await _approve_support_scope(client, admin_auth_headers, auth_headers, workspace["id"], "personal_data:read")
    resp = await client.get(f"/api/v1/admin/reminders?workspace_id={workspace['id']}", headers=admin_auth_headers)
    assert resp.status_code == 200
    listed = next(r for r in resp.json() if r["id"] == created["id"])
    assert listed["owner_id"] == alice["id"]
    assert listed["owner_email"] == "alice@example.com"
    assert listed["status"] == "scheduled"

    await _approve_support_scope(client, admin_auth_headers, auth_headers, workspace["id"], "personal_data:manage")
    resp = await client.delete(
        f"/api/v1/admin/reminders/{created['id']}?workspace_id={workspace['id']}",
        headers=admin_auth_headers,
    )
    assert resp.status_code == 204

    # Hard-deleted (unlike the user-facing DELETE, which only soft-cancels) and the underlying
    # APScheduler job must actually be gone, not just the DB row.
    assert scheduler.get_job(created["id"]) is None
    resp = await client.get("/api/v1/reminders", headers=auth_headers)
    assert created["id"] not in [r["id"] for r in resp.json()]


@pytest.mark.asyncio
async def test_admin_delete_reminder_404_when_missing(client, admin_auth_headers, auth_headers):
    workspace = await _personal_workspace(client, auth_headers)
    await _approve_support_scope(client, admin_auth_headers, auth_headers, workspace["id"], "personal_data:manage")
    resp = await client.delete(
        f"/api/v1/admin/reminders/does-not-exist?workspace_id={workspace['id']}",
        headers=admin_auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_admin_private_data_requires_owner_approved_grant(client, admin_auth_headers, auth_headers):
    workspace = await _personal_workspace(client, auth_headers)
    resp = await client.get(f"/api/v1/admin/reminders?workspace_id={workspace['id']}", headers=admin_auth_headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Active support access grant required"


@pytest.mark.asyncio
async def test_admin_can_view_ai_management_health_usage_and_audit(client, admin_auth_headers):
    management = await client.get("/api/v1/admin/ai-management", headers=admin_auth_headers)
    assert management.status_code == 200
    assert management.json()["human_confirmation_required"] is True
    assert management.json()["conversation_consent_required"] is True

    health = await client.get("/api/v1/admin/system-health", headers=admin_auth_headers)
    assert health.status_code == 200
    assert {component["key"] for component in health.json()["components"]} >= {
        "database",
        "scheduler",
        "websocket",
        "llm",
        "calendar",
    }

    usage = await client.get("/api/v1/admin/ai-usage?days=7", headers=admin_auth_headers)
    assert usage.status_code == 200
    assert len(usage.json()["daily"]) == 7

    audit = await client.get("/api/v1/admin/audit-log", headers=admin_auth_headers)
    assert audit.status_code == 200
    assert audit.json()["total"] >= 0


@pytest.mark.asyncio
async def test_admin_budget_update_is_persisted_and_audited(client, admin_auth_headers):
    response = await client.patch(
        "/api/v1/admin/settings/budget",
        json={"daily_token_budget": 123456},
        headers=admin_auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["daily_token_budget"] == 123456

    audit = await client.get(
        "/api/v1/admin/audit-log?q=platform.budget_changed",
        headers=admin_auth_headers,
    )
    assert audit.status_code == 200
    assert audit.json()["items"][0]["metadata"] == {"daily_token_budget": 123456}
