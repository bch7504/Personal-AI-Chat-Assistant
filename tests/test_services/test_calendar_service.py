from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from src.services import calendar_service

_USER_ID = "test-user-calendar-service"


def _mock_service(monkeypatch, fake_service):
    async def _fake(user_id):
        return fake_service

    monkeypatch.setattr(calendar_service, "_service", _fake)


def _mock_now(monkeypatch, dt: datetime) -> None:
    monkeypatch.setattr(calendar_service, "_local_now", lambda: dt)


# ---------------------------------------------------------------- resolve_scope


def test_resolve_scope_today_covers_the_whole_local_day(monkeypatch):
    _mock_now(monkeypatch, datetime(2026, 8, 15, 13, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")))
    start, end = calendar_service.resolve_scope("today")
    assert start == "2026-08-15T00:00:00+07:00"
    assert end == "2026-08-16T00:00:00+07:00"


def test_resolve_scope_this_week_includes_days_already_past(monkeypatch):
    """The exact bug this fixes: asked on a Saturday, "tuần này" must still cover Monday-Friday
    already gone, not just "from now onward" - see calendar_tool.py's list_calendar_events."""
    _mock_now(monkeypatch, datetime(2026, 8, 15, 13, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")))  # a Saturday
    start, end = calendar_service.resolve_scope("this_week")
    assert start == "2026-08-10T00:00:00+07:00"  # Monday
    assert end == "2026-08-17T00:00:00+07:00"  # following Monday


def test_resolve_scope_next_7_days_is_forward_looking_from_now(monkeypatch):
    now = datetime(2026, 8, 15, 13, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    _mock_now(monkeypatch, now)
    start, end = calendar_service.resolve_scope("next_7_days")
    assert start == now.isoformat()
    assert end == (now + timedelta(days=7)).isoformat()


def test_resolve_scope_next_30_days_is_forward_looking_from_now(monkeypatch):
    now = datetime(2026, 8, 15, 13, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    _mock_now(monkeypatch, now)
    start, end = calendar_service.resolve_scope("next_30_days")
    assert start == now.isoformat()
    assert end == (now + timedelta(days=30)).isoformat()


def test_resolve_scope_rejects_unknown_scope():
    with pytest.raises(ValueError):
        calendar_service.resolve_scope("next_month")


def _with_items(items: list[dict]) -> MagicMock:
    fake_service = MagicMock()
    fake_service.events.return_value.list.return_value.execute.return_value = {"items": items}
    return fake_service


@pytest.mark.asyncio
async def test_find_conflicts_empty_when_no_events(monkeypatch):
    _mock_service(monkeypatch, _with_items([]))

    conflicts = await calendar_service.find_conflicts(_USER_ID, "2026-08-01T11:00:00", "2026-08-01T12:00:00")

    assert conflicts == []


@pytest.mark.asyncio
async def test_find_conflicts_returns_overlapping_events(monkeypatch):
    items = [
        {"id": "evt-1", "summary": "Standup", "start": {"dateTime": "2026-08-01T11:00:00"}, "end": {"dateTime": "2026-08-01T11:30:00"}},
        {"id": "evt-2", "summary": "1:1", "start": {"dateTime": "2026-08-01T11:45:00"}, "end": {"dateTime": "2026-08-01T12:15:00"}},
    ]
    _mock_service(monkeypatch, _with_items(items))

    conflicts = await calendar_service.find_conflicts(_USER_ID, "2026-08-01T11:00:00", "2026-08-01T12:00:00")

    assert conflicts == items


@pytest.mark.asyncio
async def test_suggest_alternative_slots_starts_right_after_busy_event(monkeypatch):
    """One 30-minute conflict right at the requested start: the first alternative should pick up
    exactly where it ends, and a second alternative should still be found (next working day, since
    the rest of the requested day is free)."""
    items = [
        {"id": "evt-1", "summary": "Standup", "start": {"dateTime": "2026-08-01T11:00:00"}, "end": {"dateTime": "2026-08-01T11:30:00"}},
    ]
    _mock_service(monkeypatch, _with_items(items))

    slots = await calendar_service.suggest_alternative_slots(_USER_ID, "2026-08-01T11:00:00", "2026-08-01T12:00:00")

    assert slots[0] == {"start": "2026-08-01T11:30:00", "end": "2026-08-01T12:30:00"}
    assert len(slots) == 2


@pytest.mark.asyncio
async def test_suggest_alternative_slots_respects_count(monkeypatch):
    _mock_service(monkeypatch, _with_items([]))

    slots = await calendar_service.suggest_alternative_slots(
        _USER_ID, "2026-08-01T11:00:00", "2026-08-01T12:00:00", count=1
    )

    assert len(slots) == 1
    assert slots[0] == {"start": "2026-08-01T11:00:00", "end": "2026-08-01T12:00:00"}


@pytest.mark.asyncio
async def test_suggest_alternative_slots_returns_fewer_when_window_is_full(monkeypatch):
    """A single busy block spanning the entire search window leaves no free gap anywhere in it -
    best-effort means returning what was found (nothing here), never raising."""
    items = [
        {"id": "evt-1", "summary": "Offsite", "start": {"dateTime": "2026-08-01T00:00:00"}, "end": {"dateTime": "2026-08-04T00:00:00"}},
    ]
    _mock_service(monkeypatch, _with_items(items))

    slots = await calendar_service.suggest_alternative_slots(_USER_ID, "2026-08-01T11:00:00", "2026-08-01T12:00:00")

    assert slots == []
