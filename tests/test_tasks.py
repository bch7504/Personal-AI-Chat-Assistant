from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from src.config import get_settings
from src.db import session as db_session
from src.db.models import Reminder, Task
from src.services import calendar_service, reminder_service


def _api_datetime_as_utc(value: str) -> datetime:
    """SQLite drops timezone metadata even for timezone-aware test columns."""

    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=ZoneInfo("UTC"))


async def _create_proactive_task(client, auth_headers, *, title, due_at=None):
    created = (
        await client.post(
            "/api/v1/tasks",
            json={"title": title, "due_at": due_at, "source": "manual"},
            headers=auth_headers,
        )
    ).json()
    async with db_session.async_session_maker() as db:
        task = (await db.execute(select(Task).where(Task.id == created["id"]))).scalar_one()
        task.source = "proactive"
        task.status = "suggested"
        await db.commit()
    tasks = (await client.get("/api/v1/tasks", headers=auth_headers)).json()
    return next(task for task in tasks if task["id"] == created["id"])


@pytest.mark.asyncio
async def test_create_and_list_task(client, auth_headers):
    resp = await client.post(
        "/api/v1/tasks", json={"title": "Send report", "priority": "High"}, headers=auth_headers
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Send report"
    assert body["priority"] == "High"
    assert body["status"] == "pending"
    assert body["source"] == "manual"
    assert body["source"] == "manual"

    resp = await client.get("/api/v1/tasks", headers=auth_headers)
    assert resp.status_code == 200
    titles = [t["title"] for t in resp.json()]
    assert "Send report" in titles


@pytest.mark.asyncio
async def test_tasks_require_auth(client):
    resp = await client.get("/api/v1/tasks")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_update_task_status(client, auth_headers):
    created = (
        await client.post("/api/v1/tasks", json={"title": "Book flight"}, headers=auth_headers)
    ).json()

    resp = await client.patch(
        f"/api/v1/tasks/{created['id']}/status", json={"status": "pending"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_delete_task(client, auth_headers):
    created = (
        await client.post("/api/v1/tasks", json={"title": "Throwaway"}, headers=auth_headers)
    ).json()

    resp = await client.delete(f"/api/v1/tasks/{created['id']}", headers=auth_headers)
    assert resp.status_code == 204

    resp = await client.get("/api/v1/tasks", headers=auth_headers)
    assert created["id"] not in [t["id"] for t in resp.json()]


@pytest.mark.asyncio
async def test_task_not_visible_to_other_user(client, auth_headers, other_auth_headers):
    created = (
        await client.post("/api/v1/tasks", json={"title": "Private task"}, headers=auth_headers)
    ).json()

    resp = await client.get("/api/v1/tasks", headers=other_auth_headers)
    assert created["id"] not in [t["id"] for t in resp.json()]

    resp = await client.patch(
        f"/api/v1/tasks/{created['id']}/status", json={"status": "dismissed"}, headers=other_auth_headers
    )
    assert resp.status_code == 404

    resp = await client.delete(f"/api/v1/tasks/{created['id']}", headers=other_auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_task_with_naive_due_at_is_localized_to_calendar_timezone(client, auth_headers):
    """A due_at with no UTC offset (what the LLM emits, e.g. via AIPanel's "Extract tasks" posting
    it straight to this endpoint) must be interpreted as calendar_timezone - not left for
    Postgres/asyncpg to guess from the DB server's own session timezone, which only happens to
    match by coincidence on any given machine. Regression test for task_routes.py::create_task."""
    resp = await client.post(
        "/api/v1/tasks",
        json={"title": "Naive due date", "due_at": "2026-08-10T15:00:00", "priority": "Medium"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    due_at = datetime.fromisoformat(resp.json()["due_at"])
    assert due_at.tzinfo is not None
    assert due_at == datetime(2026, 8, 10, 15, 0, tzinfo=ZoneInfo(get_settings().calendar_timezone))


@pytest.mark.asyncio
async def test_create_task_with_offset_due_at_is_kept_as_is(client, auth_headers):
    """A due_at that already carries an explicit UTC offset must not be re-localized/shifted."""
    resp = await client.post(
        "/api/v1/tasks",
        json={"title": "Explicit offset due date", "due_at": "2026-08-10T15:00:00+00:00", "priority": "Medium"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    due_at = datetime.fromisoformat(resp.json()["due_at"])
    assert due_at == datetime(2026, 8, 10, 15, 0, tzinfo=ZoneInfo("UTC"))


@pytest.mark.asyncio
async def test_tasks_sorted_by_due_date_then_priority(client, auth_headers):
    await client.post(
        "/api/v1/tasks",
        json={"title": "No due date", "priority": "High"},
        headers=auth_headers,
    )
    await client.post(
        "/api/v1/tasks",
        json={"title": "Due soon", "due_at": "2026-01-01T00:00:00Z", "priority": "Low"},
        headers=auth_headers,
    )
    await client.post(
        "/api/v1/tasks",
        json={"title": "Due later", "due_at": "2026-06-01T00:00:00Z", "priority": "High"},
        headers=auth_headers,
    )

    resp = await client.get("/api/v1/tasks", headers=auth_headers)
    titles = [t["title"] for t in resp.json()]
    assert titles == ["Due soon", "Due later", "No due date"]


@pytest.mark.asyncio
async def test_accepting_proactive_task_only_accepts_task_without_hidden_side_effects(
    client, auth_headers, monkeypatch
):
    """A button labelled Accept task cannot silently confirm calendar/reminder writes too."""
    fake_service = MagicMock()
    fake_service.events.return_value.insert.return_value.execute.return_value = {
        "id": "evt-1", "htmlLink": "https://calendar.google.com/event?eid=evt1",
    }
    monkeypatch.setattr(calendar_service, "get_calendar_service", lambda: fake_service)

    created = await _create_proactive_task(
        client, auth_headers, title="Product launch call", due_at="2026-08-10T15:00:00"
    )
    assert created["status"] == "suggested"

    resp = await client.patch(
        f"/api/v1/tasks/{created['id']}/status", json={"status": "pending"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"

    fake_service.events.return_value.insert.assert_not_called()

    reminders = (await client.get("/api/v1/reminders", headers=auth_headers)).json()
    assert not any(r["title"] == "Product launch call" for r in reminders)


@pytest.mark.asyncio
async def test_accepting_manual_task_does_not_touch_calendar_or_reminder(client, auth_headers, monkeypatch):
    fake_service = MagicMock()
    monkeypatch.setattr(calendar_service, "get_calendar_service", lambda: fake_service)

    created = (
        await client.post(
            "/api/v1/tasks",
            json={"title": "Manual with due date", "due_at": "2026-08-10T15:00:00", "source": "manual"},
            headers=auth_headers,
        )
    ).json()

    resp = await client.patch(
        f"/api/v1/tasks/{created['id']}/status", json={"status": "pending"}, headers=auth_headers
    )
    assert resp.status_code == 200
    fake_service.events.return_value.insert.assert_not_called()


@pytest.mark.asyncio
async def test_accepting_proactive_task_without_due_date_does_not_touch_calendar_or_reminder(
    client, auth_headers, monkeypatch
):
    fake_service = MagicMock()
    monkeypatch.setattr(calendar_service, "get_calendar_service", lambda: fake_service)

    created = await _create_proactive_task(client, auth_headers, title="No due date")
    assert created["due_at"] is None

    resp = await client.patch(
        f"/api/v1/tasks/{created['id']}/status", json={"status": "pending"}, headers=auth_headers
    )
    assert resp.status_code == 200
    fake_service.events.return_value.insert.assert_not_called()


@pytest.mark.asyncio
async def test_accepting_proactive_task_never_calls_calendar(client, auth_headers, monkeypatch):

    def _broken_get_calendar_service():
        raise RuntimeError("Google API unreachable")

    monkeypatch.setattr(calendar_service, "get_calendar_service", _broken_get_calendar_service)

    created = await _create_proactive_task(
        client, auth_headers, title="Flaky calendar", due_at="2026-08-10T15:00:00"
    )

    resp = await client.patch(
        f"/api/v1/tasks/{created['id']}/status", json={"status": "pending"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"

    reminders = (await client.get("/api/v1/reminders", headers=auth_headers)).json()
    assert not any(r["title"] == "Flaky calendar" for r in reminders)


@pytest.mark.asyncio
async def test_opted_in_task_creates_one_private_linked_reminder(client, auth_headers):
    profile = await client.patch(
        "/api/v1/auth/me",
        json={
            "preferences": {
                "auto_task_reminders": True,
                "default_reminder_lead_minutes": 60,
            }
        },
        headers=auth_headers,
    )
    assert profile.status_code == 200, profile.text

    due_at = datetime(2099, 8, 10, 15, 0, tzinfo=ZoneInfo("UTC"))
    created = await client.post(
        "/api/v1/tasks",
        json={"title": "Linked deadline", "due_at": due_at.isoformat()},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    reminders = (await client.get("/api/v1/reminders", headers=auth_headers)).json()
    linked = [item for item in reminders if item["task_id"] == created.json()["id"]]
    assert len(linked) == 1
    assert linked[0]["source"] == "proactive"
    assert linked[0]["status"] == "scheduled"
    assert _api_datetime_as_utc(linked[0]["due_at"]) == due_at
    assert _api_datetime_as_utc(linked[0]["fire_at"]) == due_at - timedelta(hours=1)


@pytest.mark.asyncio
async def test_task_deadline_reschedules_same_reminder_and_completion_cancels_it(
    client, auth_headers
):
    await client.patch(
        "/api/v1/auth/me",
        json={
            "preferences": {
                "auto_task_reminders": True,
                "default_reminder_lead_minutes": 30,
            }
        },
        headers=auth_headers,
    )
    first_due = datetime(2099, 8, 10, 15, 0, tzinfo=ZoneInfo("UTC"))
    created = (
        await client.post(
            "/api/v1/tasks",
            json={"title": "Moving deadline", "due_at": first_due.isoformat()},
            headers=auth_headers,
        )
    ).json()
    first_reminder = next(
        item
        for item in (await client.get("/api/v1/reminders", headers=auth_headers)).json()
        if item["task_id"] == created["id"]
    )

    second_due = first_due + timedelta(days=2)
    updated = await client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={"due_at": second_due.isoformat(), "expected_row_version": created["row_version"]},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    second_reminder = next(
        item
        for item in (await client.get("/api/v1/reminders", headers=auth_headers)).json()
        if item["task_id"] == created["id"]
    )
    assert second_reminder["id"] == first_reminder["id"]
    assert _api_datetime_as_utc(second_reminder["due_at"]) == second_due
    assert _api_datetime_as_utc(second_reminder["fire_at"]) == second_due - timedelta(minutes=30)

    completed = await client.patch(
        f"/api/v1/tasks/{created['id']}/status",
        json={"status": "completed", "expected_row_version": updated.json()["row_version"]},
        headers=auth_headers,
    )
    assert completed.status_code == 200, completed.text
    cancelled = next(
        item
        for item in (await client.get("/api/v1/reminders", headers=auth_headers)).json()
        if item["task_id"] == created["id"]
    )
    assert cancelled["status"] == "cancelled"


@pytest.mark.asyncio
async def test_task_reminder_opt_out_and_global_lead_change_reconcile_existing_task(
    client, auth_headers
):
    await client.patch(
        "/api/v1/auth/me",
        json={
            "preferences": {
                "auto_task_reminders": True,
                "default_reminder_lead_minutes": 15,
            }
        },
        headers=auth_headers,
    )
    due_at = datetime(2099, 8, 10, 15, 0, tzinfo=ZoneInfo("UTC"))
    task = (
        await client.post(
            "/api/v1/tasks",
            json={"title": "Configurable reminder", "due_at": due_at.isoformat()},
            headers=auth_headers,
        )
    ).json()

    opted_out = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"auto_reminder_enabled": False, "expected_row_version": task["row_version"]},
        headers=auth_headers,
    )
    assert opted_out.status_code == 200, opted_out.text
    reminder = next(
        item
        for item in (await client.get("/api/v1/reminders", headers=auth_headers)).json()
        if item["task_id"] == task["id"]
    )
    assert reminder["status"] == "cancelled"

    opted_in = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={
            "auto_reminder_enabled": True,
            "expected_row_version": opted_out.json()["row_version"],
        },
        headers=auth_headers,
    )
    assert opted_in.status_code == 200, opted_in.text
    await client.patch(
        "/api/v1/auth/me",
        json={
            "preferences": {
                "auto_task_reminders": True,
                "default_reminder_lead_minutes": 60,
            }
        },
        headers=auth_headers,
    )
    rescheduled = next(
        item
        for item in (await client.get("/api/v1/reminders", headers=auth_headers)).json()
        if item["task_id"] == task["id"]
    )
    assert rescheduled["status"] == "scheduled"
    assert _api_datetime_as_utc(rescheduled["fire_at"]) == due_at - timedelta(hours=1)


@pytest.mark.asyncio
async def test_task_managed_reminder_cannot_be_cancelled_as_manual_reminder(client, auth_headers):
    await client.patch(
        "/api/v1/auth/me",
        json={"preferences": {"auto_task_reminders": True}},
        headers=auth_headers,
    )
    task = (
        await client.post(
            "/api/v1/tasks",
            json={"title": "Managed reminder", "due_at": "2099-08-10T15:00:00Z"},
            headers=auth_headers,
        )
    ).json()
    reminder = next(
        item
        for item in (await client.get("/api/v1/reminders", headers=auth_headers)).json()
        if item["task_id"] == task["id"]
    )
    response = await client.delete(f"/api/v1/reminders/{reminder['id']}", headers=auth_headers)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_deleting_task_removes_linked_reminder(client, auth_headers):
    await client.patch(
        "/api/v1/auth/me",
        json={"preferences": {"auto_task_reminders": True}},
        headers=auth_headers,
    )
    task = (
        await client.post(
            "/api/v1/tasks",
            json={"title": "Delete linked reminder", "due_at": "2099-08-10T15:00:00Z"},
            headers=auth_headers,
        )
    ).json()
    response = await client.delete(f"/api/v1/tasks/{task['id']}", headers=auth_headers)
    assert response.status_code == 204
    reminders = (await client.get("/api/v1/reminders", headers=auth_headers)).json()
    assert all(item["task_id"] != task["id"] for item in reminders)


@pytest.mark.asyncio
async def test_reassigning_task_moves_private_reminder_between_owners(client, auth_headers):
    await client.patch(
        "/api/v1/auth/me",
        json={"preferences": {"auto_task_reminders": True}},
        headers=auth_headers,
    )
    task = (
        await client.post(
            "/api/v1/tasks",
            json={"title": "Reassigned task", "due_at": "2099-08-10T15:00:00Z"},
            headers=auth_headers,
        )
    ).json()

    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "new-owner@example.com",
            "password": "password123",
            "display_name": "New Owner",
        },
    )
    assert registered.status_code == 201, registered.text
    logged_in = await client.post(
        "/api/v1/auth/login",
        json={"email": "new-owner@example.com", "password": "password123"},
    )
    second_headers = {"Authorization": f"Bearer {logged_in.json()['access_token']}"}
    await client.patch(
        "/api/v1/auth/me",
        json={"preferences": {"auto_task_reminders": True}},
        headers=second_headers,
    )

    async with db_session.async_session_maker() as db:
        stored = await db.get(Task, task["id"])
        stored.owner_id = registered.json()["id"]
        await db.commit()
    await reminder_service.reconcile_task_reminder(task["id"])

    former_owner_reminders = (await client.get("/api/v1/reminders", headers=auth_headers)).json()
    new_owner_reminders = (await client.get("/api/v1/reminders", headers=second_headers)).json()
    assert all(item["task_id"] != task["id"] for item in former_owner_reminders)
    assert len([item for item in new_owner_reminders if item["task_id"] == task["id"]]) == 1


@pytest.mark.asyncio
async def test_periodic_sweep_repairs_out_of_band_task_reminder_drift(client, auth_headers):
    await client.patch(
        "/api/v1/auth/me",
        json={
            "preferences": {
                "auto_task_reminders": True,
                "default_reminder_lead_minutes": 30,
            }
        },
        headers=auth_headers,
    )
    due_at = datetime(2099, 8, 20, 15, 0, tzinfo=ZoneInfo("UTC"))
    task = (
        await client.post(
            "/api/v1/tasks",
            json={"title": "Sweep protected", "due_at": due_at.isoformat()},
            headers=auth_headers,
        )
    ).json()

    async with db_session.async_session_maker() as db:
        reminder = await db.scalar(select(Reminder).where(Reminder.task_id == task["id"]))
        reminder.status = "cancelled"
        reminder.due_at = due_at + timedelta(days=1)
        reminder.fire_at = due_at + timedelta(days=1) - timedelta(minutes=30)
        await db.commit()

    processed = await reminder_service.reconcile_active_task_reminders(batch_size=1)

    assert processed >= 1
    repaired = next(
        item
        for item in (await client.get("/api/v1/reminders", headers=auth_headers)).json()
        if item["task_id"] == task["id"]
    )
    assert repaired["status"] == "scheduled"
    assert _api_datetime_as_utc(repaired["due_at"]) == due_at
    assert _api_datetime_as_utc(repaired["fire_at"]) == due_at - timedelta(minutes=30)
