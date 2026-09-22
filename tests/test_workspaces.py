import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from src.db import session as db_session
from src.db.models import Workspace, WorkspaceMembership
from src.services import workspace_service


async def _register_and_login(client, email: str, display_name: str) -> tuple[dict, dict]:
    password = "password123"
    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": display_name},
    )
    assert registered.status_code == 201
    logged_in = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert logged_in.status_code == 200
    return registered.json(), {"Authorization": f"Bearer {logged_in.json()['access_token']}"}


@pytest.mark.asyncio
async def test_register_creates_exactly_one_personal_workspace(client):
    payload, headers = await _register_and_login(
        client,
        "workspace-owner@example.com",
        "Workspace Owner",
    )

    response = await client.get("/api/v1/workspaces", headers=headers)

    assert response.status_code == 200
    workspaces = response.json()
    assert len(workspaces) == 1
    assert workspaces[0]["type"] == "personal"
    assert workspaces[0]["personal_owner_user_id"] == payload["id"]


@pytest.mark.asyncio
async def test_organization_workspace_is_listed_for_its_owner(client):
    payload, headers = await _register_and_login(
        client,
        "organization-owner@example.com",
        "Organization Owner",
    )

    async with db_session.async_session_maker() as db:
        organization = await workspace_service.create_organization_workspace(
            db,
            name="Orbit Engineering",
            owner_user_id=payload["id"],
        )
        await db.commit()
        organization_id = organization.id

    response = await client.get("/api/v1/workspaces", headers=headers)

    assert response.status_code == 200
    workspaces = response.json()
    assert len(workspaces) == 2
    assert workspaces[0]["type"] == "personal"
    assert workspaces[1]["id"] == organization_id
    assert workspaces[1]["type"] == "organization"
    assert workspaces[1]["name"] == "Orbit Engineering"


@pytest.mark.asyncio
async def test_last_owner_cannot_be_demoted(client):
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "last-owner@example.com",
            "password": "password123",
            "display_name": "Last Owner",
        },
    )
    owner_id = registered.json()["id"]

    async with db_session.async_session_maker() as db:
        organization = await workspace_service.create_organization_workspace(
            db,
            name="Owner Invariant",
            owner_user_id=owner_id,
        )
        await db.commit()
        membership = (
            await db.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == organization.id,
                    WorkspaceMembership.user_id == owner_id,
                )
            )
        ).scalar_one()

        with pytest.raises(HTTPException) as exc_info:
            await workspace_service.update_membership_role(db, membership.id, "admin")

        assert exc_info.value.status_code == 409
        await db.refresh(membership)
        assert membership.role == "owner"


@pytest.mark.asyncio
async def test_personal_workspace_rejects_membership(client):
    owner_payload, headers = await _register_and_login(
        client,
        "personal-owner@example.com",
        "Personal Owner",
    )
    other = await client.post(
        "/api/v1/auth/register",
        json={"email": "other-member@example.com", "password": "password123", "display_name": "Other Member"},
    )
    personal_workspace = (await client.get("/api/v1/workspaces", headers=headers)).json()[0]

    async with db_session.async_session_maker() as db:
        with pytest.raises(HTTPException) as exc_info:
            await workspace_service.add_workspace_member(
                db,
                workspace_id=personal_workspace["id"],
                user_id=other.json()["id"],
                role="member",
                invited_by_user_id=owner_payload["id"],
            )

        assert exc_info.value.status_code == 409
        memberships = (
            (
                await db.execute(
                    select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == personal_workspace["id"])
                )
            )
            .scalars()
            .all()
        )
        assert memberships == []


@pytest.mark.asyncio
async def test_organization_workspace_requires_active_owner(client):
    async with db_session.async_session_maker() as db:
        with pytest.raises(HTTPException) as exc_info:
            await workspace_service.create_organization_workspace(
                db,
                name="Invalid Organization",
                owner_user_id="missing-user-id",
            )

        assert exc_info.value.status_code == 404
        organization_count = (await db.execute(select(func.count()).select_from(Workspace))).scalar_one()
        assert organization_count == 0


@pytest.mark.asyncio
async def test_user_can_create_organization_workspace(client):
    payload, headers = await _register_and_login(
        client,
        "workspace-creator@example.com",
        "Creator",
    )

    response = await client.post(
        "/api/v1/workspaces",
        json={"name": "Product Team"},
        headers=headers,
    )

    assert response.status_code == 201
    organization = response.json()
    assert organization["type"] == "organization"
    assert organization["name"] == "Product Team"
    async with db_session.async_session_maker() as db:
        membership = (
            await db.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == organization["id"],
                    WorkspaceMembership.user_id == payload["id"],
                )
            )
        ).scalar_one()
        assert membership.role == "owner"
        assert membership.status == "active"


@pytest.mark.asyncio
async def test_enterprise_mode_blocks_user_workspace_creation(client, monkeypatch):
    _, headers = await _register_and_login(
        client,
        "self-service-blocked@example.com",
        "Blocked Creator",
    )
    monkeypatch.setattr(
        "src.api.workspace_routes.get_settings",
        lambda: type("Settings", (), {"allow_self_service_organization_creation": False})(),
    )

    response = await client.post(
        "/api/v1/workspaces",
        json={"name": "Unapproved Organization"},
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Organization workspaces are provisioned by platform administrators"


@pytest.mark.asyncio
async def test_only_owner_can_appoint_an_organization_admin(client):
    owner, owner_headers = await _register_and_login(
        client, "role-owner@example.com", "Role Owner"
    )
    _, admin_headers = await _register_and_login(
        client, "organization-admin@example.com", "Organization Admin"
    )
    await _register_and_login(client, "new-admin@example.com", "New Admin")

    async with db_session.async_session_maker() as db:
        organization = await workspace_service.create_organization_workspace(
            db, name="Role Boundaries", owner_user_id=owner["id"]
        )
        await db.commit()
        organization_id = organization.id

    appointed = await client.post(
        f"/api/v1/workspaces/{organization_id}/members",
        json={"email": "organization-admin@example.com", "role": "admin"},
        headers=owner_headers,
    )
    assert appointed.status_code == 201

    denied = await client.post(
        f"/api/v1/workspaces/{organization_id}/members",
        json={"email": "new-admin@example.com", "role": "admin"},
        headers=admin_headers,
    )
    assert denied.status_code == 403

    member_allowed = await client.post(
        f"/api/v1/workspaces/{organization_id}/members",
        json={"email": "new-admin@example.com", "role": "member"},
        headers=admin_headers,
    )
    assert member_allowed.status_code == 201
