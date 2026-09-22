import types
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from src.db import session as db_session
from src.db.models import UsageLog
from src.services import usage_service


def _settings(budget: int):
    return types.SimpleNamespace(daily_token_budget=budget, calendar_timezone="Asia/Ho_Chi_Minh")


@pytest.mark.asyncio
async def test_is_over_budget_false_when_under(monkeypatch):
    monkeypatch.setattr(usage_service, "get_settings", lambda: _settings(1000))

    async def _usage(*, user_id=None):
        assert user_id == "user-1"
        return {"total_tokens": 500, "request_count": 1, "since": None}

    monkeypatch.setattr(usage_service, "get_usage_today", _usage)
    assert await usage_service.is_over_budget("user-1") is False


@pytest.mark.asyncio
async def test_is_over_budget_true_when_at_or_over(monkeypatch):
    monkeypatch.setattr(usage_service, "get_settings", lambda: _settings(1000))

    async def _usage(*, user_id=None):
        assert user_id == "user-1"
        return {"total_tokens": 1000, "request_count": 1, "since": None}

    monkeypatch.setattr(usage_service, "get_usage_today", _usage)
    assert await usage_service.is_over_budget("user-1") is True


@pytest.mark.asyncio
async def test_is_over_budget_false_when_budget_is_zero(monkeypatch):
    # 0 means "unlimited" (matches AdminStats' existing `if budget else 0.0` treatment) - never block.
    monkeypatch.setattr(usage_service, "get_settings", lambda: _settings(0))
    assert await usage_service.is_over_budget("user-1") is False


@pytest.mark.asyncio
async def test_log_usage_still_writes_a_row(client):
    await usage_service.log_usage(
        provider="openai", model="gpt-4o-mini", usage_metadata={"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}
    )
    async with db_session.async_session_maker() as db:
        rows = (await db.execute(select(UsageLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].total_tokens == 7


@pytest.mark.asyncio
async def test_log_usage_alerts_account_owner_on_warning_crossing(client, auth_headers, monkeypatch):
    monkeypatch.setattr(usage_service, "get_settings", lambda: _settings(100))
    broadcast = AsyncMock()
    monkeypatch.setattr(usage_service.manager, "broadcast_to_users", broadcast)

    # before=0 -> after=85 crosses the 80% warning threshold.
    owner_id = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()["id"]
    await usage_service.log_usage(
        provider="openai",
        model="gpt-4o-mini",
        usage_metadata={"total_tokens": 85},
        user_id=owner_id,
    )

    broadcast.assert_awaited_once()
    recipient_ids, payload = broadcast.call_args.args
    assert recipient_ids == [owner_id]
    assert payload["type"] == "usage_budget_alert"
    assert payload["level"] == "warning"
    assert payload["used_pct"] == 85.0


@pytest.mark.asyncio
async def test_log_usage_alerts_exceeded_not_warning_when_crossing_both_at_once(client, auth_headers, monkeypatch):
    monkeypatch.setattr(usage_service, "get_settings", lambda: _settings(100))
    broadcast = AsyncMock()
    monkeypatch.setattr(usage_service.manager, "broadcast_to_users", broadcast)

    # before=0 -> after=100 jumps past both thresholds in one call - only the more severe one fires.
    owner_id = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()["id"]
    await usage_service.log_usage(
        provider="openai",
        model="gpt-4o-mini",
        usage_metadata={"total_tokens": 100},
        user_id=owner_id,
    )

    broadcast.assert_awaited_once()
    _, payload = broadcast.call_args.args
    assert payload["level"] == "exceeded"


@pytest.mark.asyncio
async def test_log_usage_no_alert_when_no_new_threshold_crossed(client, auth_headers, monkeypatch):
    monkeypatch.setattr(usage_service, "get_settings", lambda: _settings(100))
    broadcast = AsyncMock()
    monkeypatch.setattr(usage_service.manager, "broadcast_to_users", broadcast)

    owner_id = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()["id"]
    await usage_service.log_usage(
        provider="openai",
        model="gpt-4o-mini",
        usage_metadata={"total_tokens": 150},
        user_id=owner_id,
    )
    broadcast.assert_awaited_once()
    broadcast.reset_mock()

    # Already over 100% from the call above - no *new* crossing, so no repeat alert.
    await usage_service.log_usage(
        provider="openai",
        model="gpt-4o-mini",
        usage_metadata={"total_tokens": 10},
        user_id=owner_id,
    )
    broadcast.assert_not_awaited()


@pytest.mark.asyncio
async def test_usage_is_isolated_between_accounts(
    client, auth_headers, other_auth_headers, monkeypatch
):
    monkeypatch.setattr(usage_service, "get_settings", lambda: _settings(100))
    owner_id = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()["id"]
    other_id = (await client.get("/api/v1/auth/me", headers=other_auth_headers)).json()["id"]
    monkeypatch.setattr(usage_service.manager, "broadcast_to_users", AsyncMock())

    await usage_service.log_usage(
        provider="openai",
        model="gpt-4o-mini",
        usage_metadata={"total_tokens": 85},
        user_id=owner_id,
    )
    await usage_service.log_usage(
        provider="openai",
        model="gpt-4o-mini",
        usage_metadata={"total_tokens": 20},
        user_id=other_id,
    )

    owner = await usage_service.get_usage_summary(owner_id)
    other = await usage_service.get_usage_summary(other_id)
    aggregate = await usage_service.get_usage_today()
    assert owner["tokens_used_today"] == 85
    assert owner["used_pct"] == 85.0
    assert other["tokens_used_today"] == 20
    assert other["used_pct"] == 20.0
    assert aggregate["total_tokens"] == 105
    assert await usage_service.get_peak_account_usage_today() == 85
