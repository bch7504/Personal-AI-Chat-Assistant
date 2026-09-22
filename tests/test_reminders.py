import pytest

from src.services import reminder_service


@pytest.mark.asyncio
async def test_create_and_list_reminder(client, auth_headers):
    resp = await client.post(
        "/api/v1/reminders",
        json={"title": "Send report", "due_at_iso": "2099-08-10T15:00:00", "lead_minutes": 30},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Send report"
    assert body["status"] == "scheduled"
    assert body["source"] == "manual"

    resp = await client.get("/api/v1/reminders", headers=auth_headers)
    assert resp.status_code == 200
    titles = [r["title"] for r in resp.json()]
    assert "Send report" in titles


@pytest.mark.asyncio
async def test_reminders_require_auth(client):
    resp = await client.get("/api/v1/reminders")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_cancel_reminder(client, auth_headers):
    created = (
        await client.post(
            "/api/v1/reminders",
            json={"title": "Throwaway", "due_at_iso": "2099-08-10T15:00:00"},
            headers=auth_headers,
        )
    ).json()

    resp = await client.delete(f"/api/v1/reminders/{created['id']}", headers=auth_headers)
    assert resp.status_code == 204

    resp = await client.get("/api/v1/reminders", headers=auth_headers)
    cancelled = next(r for r in resp.json() if r["id"] == created["id"])
    assert cancelled["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_missing_reminder_404(client, auth_headers):
    resp = await client.delete("/api/v1/reminders/does-not-exist", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reminder_not_visible_to_other_user(client, auth_headers, other_auth_headers):
    created = (
        await client.post(
            "/api/v1/reminders",
            json={"title": "Private reminder", "due_at_iso": "2099-08-10T15:00:00"},
            headers=auth_headers,
        )
    ).json()

    resp = await client.get("/api/v1/reminders", headers=other_auth_headers)
    assert created["id"] not in [r["id"] for r in resp.json()]

    resp = await client.delete(f"/api/v1/reminders/{created['id']}", headers=other_auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_and_snooze_independent_reminder(client, auth_headers):
    created = (
        await client.post(
            "/api/v1/reminders",
            json={"title": "Original", "due_at_iso": "2099-08-10T15:00:00", "lead_minutes": 30},
            headers=auth_headers,
        )
    ).json()

    updated_response = await client.patch(
        f"/api/v1/reminders/{created['id']}",
        json={"title": "Updated", "due_at_iso": "2099-08-11T16:00:00", "lead_minutes": 60},
        headers=auth_headers,
    )
    assert updated_response.status_code == 200
    updated = updated_response.json()
    assert updated["title"] == "Updated"
    assert updated["status"] == "scheduled"
    assert updated["fire_at"].startswith("2099-08-11T15:00:00")

    snoozed_response = await client.post(
        f"/api/v1/reminders/{created['id']}/snooze",
        json={"minutes": 10},
        headers=auth_headers,
    )
    assert snoozed_response.status_code == 200
    assert snoozed_response.json()["status"] == "scheduled"


@pytest.mark.asyncio
async def test_update_reminder_requires_a_change(client, auth_headers):
    created = (
        await client.post(
            "/api/v1/reminders",
            json={"title": "Original", "due_at_iso": "2099-08-10T15:00:00"},
            headers=auth_headers,
        )
    ).json()
    response = await client.patch(
        f"/api/v1/reminders/{created['id']}", json={}, headers=auth_headers
    )
    assert response.status_code == 409
    assert "At least one" in response.json()["detail"]


@pytest.mark.asyncio
async def test_calendar_event_reminder_stays_linked_through_update_and_delete(
    client, auth_headers, personal_workspace, monkeypatch
):
    user = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    monkeypatch.setattr(reminder_service.scheduler, "add_job", lambda *args, **kwargs: None)
    monkeypatch.setattr(reminder_service.scheduler, "remove_job", lambda *args, **kwargs: None)

    created = await reminder_service.reconcile_calendar_event_reminder(
        owner_id=user["id"],
        calendar_event_id="google-event-1",
        title="Design review",
        start_at="2099-08-10T15:00:00+07:00",
        create_if_missing=True,
        lead_minutes=30,
        source="agent",
    )

    assert created is not None
    assert created.workspace_id == personal_workspace["id"]
    assert created.calendar_event_id == "google-event-1"
    assert created.lead_minutes == 30
    assert created.fire_at.isoformat().startswith("2099-08-10T14:30:00")

    updated = await reminder_service.reconcile_calendar_event_reminder(
        owner_id=user["id"],
        calendar_event_id="google-event-1",
        title="Design review moved",
        start_at="2099-08-11T16:00:00+07:00",
    )

    assert updated is not None
    assert updated.id == created.id
    assert updated.title == "Design review moved"
    assert updated.lead_minutes == 30
    assert updated.fire_at.isoformat().startswith("2099-08-11T15:30:00")

    await reminder_service.remove_calendar_event_reminder(user["id"], "google-event-1")
    reminders = await reminder_service.list_reminders(
        owner_id=user["id"], workspace_id=personal_workspace["id"]
    )
    assert reminders == []
