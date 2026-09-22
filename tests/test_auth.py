import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import func, select

import src.db.session as db_session
from src.auth.security import hash_password
from src.db.models import User, Workspace


@pytest.mark.asyncio
async def test_register_success(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "new@example.com", "password": "password123", "display_name": "New User"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "access_token" not in body
    assert body["email"] == "new@example.com"
    assert body["display_name"] == "New User"


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    payload = {"email": "dup@example.com", "password": "password123", "display_name": "Dup"}
    await client.post("/api/v1/auth/register", json=payload)
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_login_success(client):
    payload = {"email": "login@example.com", "password": "password123", "display_name": "Login"}
    await client.post("/api/v1/auth/register", json=payload)
    resp = await client.post("/api/v1/auth/login", json={"email": payload["email"], "password": payload["password"]})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    payload = {"email": "wrong@example.com", "password": "password123", "display_name": "Wrong"}
    await client.post("/api/v1/auth/register", json=payload)
    resp = await client.post("/api/v1/auth/login", json={"email": payload["email"], "password": "nope"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_repairs_legacy_account_and_personal_apis_need_no_workspace_id(
    client, monkeypatch, fake_llm_factory
):
    """Directly provisioned accounts must behave exactly like registered accounts."""
    async with db_session.async_session_maker() as session:
        session.add(
            User(
                email="legacy-import@example.com",
                password_hash=hash_password("password123"),
                display_name="Legacy Import",
            )
        )
        await session.commit()

    reply = AIMessage(content="Your personal work summary is ready.")
    monkeypatch.setattr(
        "src.agents.nodes.planner_node.get_llm",
        lambda: fake_llm_factory([reply]),
    )

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "legacy-import@example.com", "password": "password123"},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    for path in ("/api/v1/tasks", "/api/v1/memories", "/api/v1/reminders"):
        response = await client.get(path, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json() == []

    chat = await client.post(
        "/api/v1/chat",
        json={"message": "Summarize my work tasks"},
        headers=headers,
    )
    assert chat.status_code == 200, chat.text

    # Repeated logins are idempotent and cannot create a second Personal Space.
    second_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "legacy-import@example.com", "password": "password123"},
    )
    assert second_login.status_code == 200
    async with db_session.async_session_maker() as session:
        user_id = (
            await session.execute(select(User.id).where(User.email == "legacy-import@example.com"))
        ).scalar_one()
        count = (
            await session.execute(
                select(func.count(Workspace.id)).where(
                    Workspace.type == "personal",
                    Workspace.personal_owner_user_id == user_id,
                )
            )
        ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_me_requires_token(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_me_with_token(client, auth_headers):
    resp = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "alice@example.com"
