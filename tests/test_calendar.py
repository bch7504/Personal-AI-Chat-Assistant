from unittest.mock import AsyncMock, MagicMock, call
from urllib.parse import parse_qs, urlparse

import pytest
from google.oauth2.credentials import Credentials
from sqlalchemy import select

import src.db.session as db_session
from src.auth.crypto import decrypt_secret
from src.auth.security import create_access_token
from src.db.models import GoogleCalendarCredential
from src.services import calendar_service, google_credentials, reminder_service
from src.websocket.manager import manager


async def _user_id(client, headers):
    return (await client.get("/api/v1/auth/me", headers=headers)).json()["id"]


async def _credential(user_id: str) -> GoogleCalendarCredential | None:
    async with db_session.async_session_maker() as db:
        return (
            await db.execute(
                select(GoogleCalendarCredential).where(GoogleCalendarCredential.user_id == user_id)
            )
        ).scalar_one_or_none()


def test_calendar_oauth_uses_event_only_scope():
    assert google_credentials.SCOPES == ["https://www.googleapis.com/auth/calendar.events"]


def test_calendar_oauth_does_not_merge_legacy_grants(monkeypatch):
    settings = google_credentials.get_settings().model_copy(
        update={
            "google_calendar_client_id": "test-calendar-client",
            "google_calendar_client_secret": "test-calendar-secret",
            "google_calendar_redirect_uri": "http://localhost:8000/api/v1/calendar/oauth/callback",
        }
    )
    monkeypatch.setattr(google_credentials, "get_settings", lambda: settings)

    query = parse_qs(urlparse(google_credentials.build_authorization_url("user-1")).query)
    assert query["scope"] == google_credentials.SCOPES
    assert "include_granted_scopes" not in query


@pytest.mark.asyncio
async def test_list_events_requires_auth(client):
    response = await client.get("/api/v1/calendar/events")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_events_returns_not_connected(client, auth_headers):
    response = await client.get("/api/v1/calendar/events", headers=auth_headers)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "calendar_not_connected"


@pytest.mark.asyncio
async def test_list_events_uses_callers_calendar(client, auth_headers, monkeypatch):
    caller = await _user_id(client, auth_headers)
    service = MagicMock()
    service.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "evt-1",
                "summary": "Team sync",
                "start": {"dateTime": "2026-08-10T10:00:00+07:00"},
                "end": {"dateTime": "2026-08-10T10:30:00+07:00"},
            }
        ]
    }

    async def fake_service(user_id):
        assert user_id == caller
        return service

    monkeypatch.setattr(calendar_service, "_service", fake_service)
    response = await client.get("/api/v1/calendar/events", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()[0]["title"] == "Team sync"
    assert service.events.return_value.list.call_args.kwargs["calendarId"] == "primary"


@pytest.mark.asyncio
async def test_create_event_uses_callers_calendar(client, auth_headers, monkeypatch):
    caller = await _user_id(client, auth_headers)
    service = MagicMock()

    def insert(calendarId=None, body=None):  # noqa: N803 - Google client kwarg
        assert calendarId == "primary"
        return MagicMock(
            execute=MagicMock(
                return_value={
                    "id": "evt-2",
                    "summary": body["summary"],
                    "start": body["start"],
                    "end": body["end"],
                }
            )
        )

    service.events.return_value.insert.side_effect = insert

    async def fake_service(user_id):
        assert user_id == caller
        return service

    monkeypatch.setattr(calendar_service, "_service", fake_service)
    response = await client.post(
        "/api/v1/calendar/events",
        json={
            "summary": "Design sync",
            "start_iso": "2026-08-11T09:00:00+07:00",
            "end_iso": "2026-08-11T09:30:00+07:00",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["id"] == "evt-2"


@pytest.mark.asyncio
async def test_update_and_delete_event_write_to_callers_google_calendar(client, auth_headers, monkeypatch):
    caller = await _user_id(client, auth_headers)
    service = MagicMock()
    service.events.return_value.patch.return_value.execute.return_value = {
        "id": "evt-2",
        "summary": "Updated design sync",
        "start": {"dateTime": "2026-08-11T10:00:00+07:00"},
        "end": {"dateTime": "2026-08-11T10:30:00+07:00"},
    }
    service.events.return_value.delete.return_value.execute.return_value = None

    async def fake_service(user_id):
        assert user_id == caller
        return service

    monkeypatch.setattr(calendar_service, "_service", fake_service)
    updated = await client.patch(
        "/api/v1/calendar/events/evt-2",
        json={"summary": "Updated design sync"},
        headers=auth_headers,
    )
    deleted = await client.delete("/api/v1/calendar/events/evt-2", headers=auth_headers)

    assert updated.status_code == 200
    assert updated.json()["title"] == "Updated design sync"
    assert deleted.status_code == 204
    assert service.events.return_value.patch.call_args.kwargs["calendarId"] == "primary"
    assert service.events.return_value.patch.call_args.kwargs["eventId"] == "evt-2"
    assert service.events.return_value.delete.call_args.kwargs == {
        "calendarId": "primary",
        "eventId": "evt-2",
    }


@pytest.mark.asyncio
async def test_connection_status_and_oauth_state_are_user_bound(client, auth_headers):
    status_response = await client.get("/api/v1/calendar/connection", headers=auth_headers)
    assert status_response.json()["connected"] is False
    user_id = await _user_id(client, auth_headers)
    state = google_credentials.make_oauth_state(user_id)
    assert google_credentials.read_oauth_state(state) == user_id
    assert (
        await client.get(
            "/api/v1/calendar/oauth/callback", params={"code": "x", "state": create_access_token(user_id)}
        )
    ).status_code == 400


@pytest.mark.asyncio
async def test_refresh_token_is_encrypted_at_rest(client, auth_headers):
    user_id = await _user_id(client, auth_headers)
    plaintext = "1//secret-refresh-token"
    credentials = Credentials(token="access", refresh_token=plaintext, scopes=google_credentials.SCOPES)
    await google_credentials.save_credentials(user_id, credentials, google_email="alice@example.com")
    row = await _credential(user_id)
    assert row is not None
    assert plaintext not in row.refresh_token_enc
    assert decrypt_secret(row.refresh_token_enc) == plaintext


@pytest.mark.asyncio
async def test_disconnect_removes_credential(client, auth_headers, monkeypatch):
    user_id = await _user_id(client, auth_headers)
    credentials = Credentials(token="access", refresh_token="refresh", scopes=google_credentials.SCOPES)
    await google_credentials.save_credentials(user_id, credentials)
    monkeypatch.setattr("httpx.AsyncClient.post", AsyncMock())
    response = await client.delete("/api/v1/calendar/connection", headers=auth_headers)
    assert response.status_code == 204
    assert await _credential(user_id) is None


@pytest.mark.asyncio
async def test_broadcast_reaches_only_calendar_owner(monkeypatch):
    broadcast = AsyncMock()
    monkeypatch.setattr(manager, "broadcast_to_users", broadcast)
    await calendar_service.broadcast_change("owner", "calendar_event_created", {"event": {"id": "e1"}})
    broadcast.assert_awaited_once_with(
        ["owner"], {"type": "calendar_event_created", "event": {"id": "e1"}}
    )


@pytest.mark.asyncio
async def test_poll_only_checks_online_connected_users(monkeypatch):
    monkeypatch.setattr(google_credentials, "list_connected_user_ids", AsyncMock(return_value=["online", "offline"]))
    poll = AsyncMock()
    monkeypatch.setattr(calendar_service, "_poll_one_user", poll)
    manager.active["online"] = {object()}
    try:
        await calendar_service.poll_calendar_changes()
    finally:
        manager.active.pop("online", None)
    poll.assert_awaited_once_with("online")


@pytest.mark.asyncio
async def test_google_changes_are_pushed_back_to_orbit(monkeypatch):
    changed = {
        "id": "changed-event",
        "summary": "Changed in Google",
        "start": {"dateTime": "2026-08-11T10:00:00+07:00"},
        "end": {"dateTime": "2026-08-11T10:30:00+07:00"},
    }
    cancelled = {"id": "cancelled-event", "status": "cancelled"}
    monkeypatch.setattr(google_credentials, "get_sync_token", AsyncMock(return_value="old-cursor"))
    monkeypatch.setattr(
        calendar_service,
        "_fetch_changes",
        AsyncMock(return_value=([changed, cancelled], "next-cursor")),
    )
    broadcast = AsyncMock()
    reconcile = AsyncMock()
    remove = AsyncMock()
    set_cursor = AsyncMock()
    monkeypatch.setattr(calendar_service, "broadcast_change", broadcast)
    monkeypatch.setattr(reminder_service, "reconcile_calendar_event_reminder", reconcile)
    monkeypatch.setattr(reminder_service, "remove_calendar_event_reminder", remove)
    monkeypatch.setattr(google_credentials, "set_sync_token", set_cursor)

    await calendar_service._poll_one_user("owner")

    broadcast.assert_has_awaits(
        [
            call(
                "owner",
                "calendar_event_updated",
                {"event": calendar_service.to_out_dict(changed)},
            ),
            call("owner", "calendar_event_deleted", {"event_id": "cancelled-event"}),
        ]
    )
    reconcile.assert_awaited_once()
    remove.assert_awaited_once_with("owner", "cancelled-event")
    set_cursor.assert_awaited_once_with("owner", "next-cursor")
