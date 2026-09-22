from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from src.services import calendar_service


@pytest.mark.asyncio
async def test_personal_timeline_merges_task_reminder_and_calendar(
    client, auth_headers, personal_workspace, monkeypatch
):
    start = datetime.now(UTC) + timedelta(days=1)
    end = start + timedelta(hours=1)
    task = await client.post(
        "/api/v1/tasks",
        json={
            "workspace_id": personal_workspace["id"],
            "title": "Chốt báo cáo",
            "due_at": start.isoformat(),
            "priority": "High",
        },
        headers=auth_headers,
    )
    assert task.status_code == 201
    reminder = await client.post(
        "/api/v1/reminders",
        json={
            "workspace_id": personal_workspace["id"],
            "title": "Nhắc báo cáo",
            "due_at_iso": start.isoformat(),
            "lead_minutes": 30,
        },
        headers=auth_headers,
    )
    assert reminder.status_code == 201
    monkeypatch.setattr(
        calendar_service,
        "list_events",
        AsyncMock(
            return_value=[
                {
                    "id": "event-1",
                    "summary": "Họp dự án",
                    "start": {"dateTime": start.isoformat()},
                    "end": {"dateTime": end.isoformat()},
                    "htmlLink": "https://calendar.test/event-1",
                    "status": "confirmed",
                }
            ]
        ),
    )

    response = await client.get(
        "/api/v1/timeline",
        params={
            "workspace_id": personal_workspace["id"],
            "from_at": (start - timedelta(hours=2)).isoformat(),
            "to_at": (end + timedelta(hours=2)).isoformat(),
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["kind"] for item in body["items"]] == ["reminder", "calendar", "task"]
    assert {source["source"]: source["status"] for source in body["sources"]} == {
        "task": "ok",
        "reminder": "ok",
        "calendar": "ok",
    }
    assert body["timezone"] == "Asia/Ho_Chi_Minh"


@pytest.mark.asyncio
async def test_timeline_calendar_failure_returns_partial_result(
    client, auth_headers, personal_workspace, monkeypatch
):
    monkeypatch.setattr(
        calendar_service,
        "list_events",
        AsyncMock(side_effect=RuntimeError("provider unavailable")),
    )
    response = await client.get(
        "/api/v1/timeline",
        params={"workspace_id": personal_workspace["id"]},
        headers=auth_headers,
    )
    assert response.status_code == 200
    calendar = next(source for source in response.json()["sources"] if source["source"] == "calendar")
    assert calendar["status"] == "unavailable"


@pytest.mark.asyncio
async def test_timeline_rejects_range_over_ninety_days(client, auth_headers):
    start = datetime.now(UTC)
    response = await client.get(
        "/api/v1/timeline",
        params={"from_at": start.isoformat(), "to_at": (start + timedelta(days=91)).isoformat()},
        headers=auth_headers,
    )
    assert response.status_code == 422
