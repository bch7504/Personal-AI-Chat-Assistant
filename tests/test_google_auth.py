import types

import jwt
import pytest
from sqlalchemy import select

import src.db.session as db_session
from src.api import auth_routes
from src.auth import google_oauth
from src.auth.security import decode_access_token
from src.db.models import GoogleIdentity, User


def _claims(sub="google-sub-1", email="newgoogle@example.com", email_verified=True, name="New Googler"):
    return {"sub": sub, "email": email, "email_verified": email_verified, "name": name}


@pytest.mark.asyncio
async def test_google_auth_new_user_creates_account(client, monkeypatch):
    monkeypatch.setattr(google_oauth, "verify_google_id_token", lambda token: _claims())

    resp = await client.post("/api/v1/auth/google", json={"id_token": "fake"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["email"] == "newgoogle@example.com"
    assert body["user"]["display_name"] == "New Googler"
    assert body["user"]["role"] == "user"

    async with db_session.async_session_maker() as db:
        identity = (
            await db.execute(select(GoogleIdentity).where(GoogleIdentity.google_sub == "google-sub-1"))
        ).scalar_one()
        assert identity.user_id == body["user"]["id"]


@pytest.mark.asyncio
async def test_google_auth_same_sub_logs_into_same_account(client, monkeypatch):
    monkeypatch.setattr(google_oauth, "verify_google_id_token", lambda token: _claims())

    first = await client.post("/api/v1/auth/google", json={"id_token": "fake"})
    second = await client.post("/api/v1/auth/google", json={"id_token": "fake"})
    assert first.json()["user"]["id"] == second.json()["user"]["id"]

    async with db_session.async_session_maker() as db:
        count = len((await db.execute(select(GoogleIdentity))).scalars().all())
        assert count == 1


@pytest.mark.asyncio
async def test_google_auth_links_existing_verified_email(client, monkeypatch):
    register_resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "linkme@example.com", "password": "password123", "display_name": "Link Me"},
    )
    original_user_id = register_resp.json()["id"]

    monkeypatch.setattr(
        google_oauth,
        "verify_google_id_token",
        lambda token: _claims(sub="google-sub-2", email="linkme@example.com", email_verified=True),
    )
    resp = await client.post("/api/v1/auth/google", json={"id_token": "fake"})
    assert resp.status_code == 200
    assert resp.json()["user"]["id"] == original_user_id

    async with db_session.async_session_maker() as db:
        user = await db.get(User, original_user_id)
        # Original password must survive linking - Google sign-in must not overwrite it.
        assert user.password_hash is not None
        identity = (
            await db.execute(select(GoogleIdentity).where(GoogleIdentity.google_sub == "google-sub-2"))
        ).scalar_one()
        assert identity.user_id == original_user_id


@pytest.mark.asyncio
async def test_google_auth_rejects_unverified_email_link(client, monkeypatch):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "unverified@example.com", "password": "password123", "display_name": "Unverified"},
    )

    monkeypatch.setattr(
        google_oauth,
        "verify_google_id_token",
        lambda token: _claims(sub="google-sub-3", email="unverified@example.com", email_verified=False),
    )
    resp = await client.post("/api/v1/auth/google", json={"id_token": "fake"})
    assert resp.status_code == 401

    async with db_session.async_session_maker() as db:
        identity = (
            await db.execute(select(GoogleIdentity).where(GoogleIdentity.google_sub == "google-sub-3"))
        ).scalar_one_or_none()
        assert identity is None


@pytest.mark.asyncio
async def test_google_auth_invalid_token_returns_401(client, monkeypatch):
    def _boom(token):
        raise google_oauth.GoogleTokenError("Wrong audience")

    monkeypatch.setattr(google_oauth, "verify_google_id_token", _boom)

    resp = await client.post("/api/v1/auth/google", json={"id_token": "garbage"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_google_auth_first_signup_matching_initial_admin_email_becomes_admin(client, monkeypatch):
    monkeypatch.setattr(
        auth_routes,
        "get_settings",
        lambda: types.SimpleNamespace(initial_admin_email="admin-via-google@example.com"),
    )
    monkeypatch.setattr(
        google_oauth,
        "verify_google_id_token",
        lambda token: _claims(sub="google-sub-admin", email="admin-via-google@example.com"),
    )

    resp = await client.post("/api/v1/auth/google", json={"id_token": "fake"})
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "admin"


@pytest.mark.asyncio
async def test_google_auth_jwt_shape_matches_password_flow(client, monkeypatch):
    """Regression guard: the Google flow must reuse create_access_token as-is, not grow extra
    claims - the project's hard constraint is not to change JWT structure."""
    monkeypatch.setattr(google_oauth, "verify_google_id_token", lambda token: _claims())

    resp = await client.post("/api/v1/auth/google", json={"id_token": "fake"})
    token = resp.json()["access_token"]

    user_id = decode_access_token(token)
    assert user_id == resp.json()["user"]["id"]

    payload = jwt.decode(token, options={"verify_signature": False})
    assert set(payload.keys()) == {"sub", "exp"}
