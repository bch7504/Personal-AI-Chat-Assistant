import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from src.config import get_settings
from src.db import session as db_session
from src.db.models import SystemConfig, UsageLog
from src.websocket.manager import manager

logger = logging.getLogger(__name__)

_SYSTEM_CONFIG_ID = "default"

# Edge-triggered alert thresholds (percent of daily_token_budget). "Edge-triggered" so admins get
# one push per crossing per day, not one on every single request once already over the line.
_WARNING_PCT = 80
_EXCEEDED_PCT = 100

_PRICING_PER_MILLION: dict[tuple[str, str], tuple[float, float]] = {
    ("google", "gemini-2.5-flash"): (0.30, 2.50),
    ("google", "gemini-2.5-flash-lite"): (0.10, 0.40),
    ("openai", "gpt-4o-mini"): (0.15, 0.60),
    ("openai", "gpt-4.1-mini"): (0.40, 1.60),
    ("groq", "openai/gpt-oss-20b"): (0.075, 0.30),
}


def _estimate_cost(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
) -> tuple[float, int]:
    normalized_model = model.lower().removeprefix("models/")
    prices = _PRICING_PER_MILLION.get((provider.lower(), normalized_model))
    if prices is None:
        return 0.0, total_tokens
    input_price, output_price = prices
    cost = prompt_tokens / 1_000_000 * input_price + completion_tokens / 1_000_000 * output_price
    return cost, 0


def _midnight_local_as_utc() -> datetime:
    tz = ZoneInfo(get_settings().calendar_timezone)
    return datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


async def log_usage(
    *,
    provider: str,
    model: str,
    usage_metadata: dict | None,
    user_id: str | None = None,
    workspace_id: str | None = None,
) -> None:
    """Best-effort token logging with a separate daily allowance for each account.

    Rows without ``user_id`` remain visible in aggregate admin cost reports, but cannot consume
    or alert against any individual account's allowance.
    """
    if not isinstance(usage_metadata, dict) or not usage_metadata:
        return
    try:
        tokens = usage_metadata.get("total_tokens", 0)
        async with db_session.async_session_maker() as db:
            before_tokens = 0
            if user_id:
                before_result = await db.execute(
                    select(func.coalesce(func.sum(UsageLog.total_tokens), 0)).where(
                        UsageLog.created_at >= _midnight_local_as_utc(),
                        UsageLog.user_id == user_id,
                    )
                )
                before_tokens = before_result.scalar_one()
            db.add(
                UsageLog(
                    user_id=user_id,
                    workspace_id=workspace_id,
                    provider=provider,
                    model=model,
                    prompt_tokens=usage_metadata.get("input_tokens", 0),
                    completion_tokens=usage_metadata.get("output_tokens", 0),
                    total_tokens=tokens,
                )
            )
            await db.commit()
        if user_id:
            await _maybe_alert_budget(
                user_id=user_id,
                before_tokens=before_tokens,
                after_tokens=before_tokens + tokens,
            )
    except Exception:  # noqa: BLE001 - usage tracking must never break the agent turn
        logger.exception("Failed to log LLM usage")


async def _maybe_alert_budget(*, user_id: str, before_tokens: int, after_tokens: int) -> None:
    """Notify the affected account when its own allowance crosses 80% or 100%."""
    budget = await get_daily_token_budget()
    if not budget:
        return
    before_pct = before_tokens / budget * 100
    after_pct = after_tokens / budget * 100
    if before_pct < _EXCEEDED_PCT <= after_pct:
        level = "exceeded"
    elif before_pct < _WARNING_PCT <= after_pct:
        level = "warning"
    else:
        return

    await manager.broadcast_to_users(
        [user_id],
        {
            "type": "usage_budget_alert",
            "level": level,
            "tokens_used_today": after_tokens,
            "daily_token_budget": budget,
            "used_pct": round(after_pct, 1),
            "message": f"Bạn đã dùng {round(after_pct, 1)}% hạn mức AI của tài khoản hôm nay.",
        },
    )


async def get_usage_today(
    workspace_id: str | None = None,
    *,
    user_id: str | None = None,
) -> dict:
    since = _midnight_local_as_utc()
    async with db_session.async_session_maker() as db:
        stmt = select(
            UsageLog.provider,
            UsageLog.model,
            func.coalesce(func.sum(UsageLog.prompt_tokens), 0),
            func.coalesce(func.sum(UsageLog.completion_tokens), 0),
            func.coalesce(func.sum(UsageLog.total_tokens), 0),
            func.count(UsageLog.id),
        ).where(
            UsageLog.created_at >= since,
        )
        if workspace_id:
            stmt = stmt.where(UsageLog.workspace_id == workspace_id)
        if user_id:
            stmt = stmt.where(UsageLog.user_id == user_id)
        rows = (await db.execute(stmt.group_by(UsageLog.provider, UsageLog.model))).all()

    estimated_cost_usd = 0.0
    unpriced_tokens = 0
    for provider, model, prompt, completion, total, _requests in rows:
        cost, unpriced = _estimate_cost(provider, model, prompt, completion, total)
        estimated_cost_usd += cost
        unpriced_tokens += unpriced
    return {
        "prompt_tokens": sum(row[2] for row in rows),
        "completion_tokens": sum(row[3] for row in rows),
        "total_tokens": sum(row[4] for row in rows),
        "request_count": sum(row[5] for row in rows),
        "estimated_cost_usd": round(estimated_cost_usd, 6),
        "unpriced_tokens": unpriced_tokens,
        "since": since,
    }


async def get_daily_token_budget() -> int:
    try:
        async with db_session.async_session_maker() as db:
            config = await db.get(SystemConfig, _SYSTEM_CONFIG_ID)
    except SQLAlchemyError:
        # Supports rolling deployment and isolated unit tests before the migration is applied.
        return get_settings().daily_token_budget
    if config is not None and config.daily_token_budget is not None:
        return config.daily_token_budget
    return get_settings().daily_token_budget


async def get_peak_account_usage_today() -> int:
    """Return today's highest token total for any one account."""

    per_user = (
        select(func.sum(UsageLog.total_tokens).label("total_tokens"))
        .where(
            UsageLog.created_at >= _midnight_local_as_utc(),
            UsageLog.user_id.is_not(None),
        )
        .group_by(UsageLog.user_id)
        .subquery()
    )
    async with db_session.async_session_maker() as db:
        result = await db.execute(
            select(func.coalesce(func.max(per_user.c.total_tokens), 0))
        )
        return int(result.scalar_one())


async def get_usage_summary(user_id: str) -> dict:
    """Return one account's non-admin-safe daily AI allowance status."""
    budget = await get_daily_token_budget()
    usage = await get_usage_today(user_id=user_id)
    used_pct = round(usage["total_tokens"] / budget * 100, 1) if budget else 0.0
    return {
        "tokens_used_today": usage["total_tokens"],
        "daily_token_budget": budget,
        "used_pct": used_pct,
    }


async def set_daily_token_budget(value: int, *, updated_by: str | None) -> int:
    async with db_session.async_session_maker() as db:
        config = await db.get(SystemConfig, _SYSTEM_CONFIG_ID)
        if config is None:
            config = SystemConfig(id=_SYSTEM_CONFIG_ID)
            db.add(config)
        config.daily_token_budget = value
        config.updated_by = updated_by
        await db.commit()
    return value


async def get_usage_report(days: int = 7) -> dict:
    tz = ZoneInfo(get_settings().calendar_timezone)
    now = datetime.now(tz)
    today = now.date()
    since_local = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    since = since_local.astimezone(UTC)
    async with db_session.async_session_maker() as db:
        rows = (
            await db.execute(
                select(
                    UsageLog.provider,
                    UsageLog.model,
                    UsageLog.prompt_tokens,
                    UsageLog.completion_tokens,
                    UsageLog.total_tokens,
                    UsageLog.created_at,
                ).where(UsageLog.created_at >= since)
            )
        ).all()

    daily = {
        (today - timedelta(days=offset)).isoformat(): {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "request_count": 0,
            "estimated_cost_usd": 0.0,
            "unpriced_tokens": 0,
        }
        for offset in range(days - 1, -1, -1)
    }
    models: dict[tuple[str, str], dict] = {}
    for provider, model, prompt, completion, total, created_at in rows:
        timestamp = created_at.replace(tzinfo=UTC) if created_at.tzinfo is None else created_at
        day_key = timestamp.astimezone(tz).date().isoformat()
        if day_key not in daily:
            continue
        cost, unpriced = _estimate_cost(provider, model, prompt, completion, total)
        day = daily[day_key]
        day["prompt_tokens"] += prompt
        day["completion_tokens"] += completion
        day["total_tokens"] += total
        day["request_count"] += 1
        day["estimated_cost_usd"] += cost
        day["unpriced_tokens"] += unpriced
        model_usage = models.setdefault(
            (provider, model),
            {
                "provider": provider,
                "model": model,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "request_count": 0,
                "estimated_cost_usd": 0.0,
                "unpriced_tokens": 0,
            },
        )
        for key, value in (
            ("prompt_tokens", prompt),
            ("completion_tokens", completion),
            ("total_tokens", total),
            ("request_count", 1),
            ("estimated_cost_usd", cost),
            ("unpriced_tokens", unpriced),
        ):
            model_usage[key] += value

    daily_rows = []
    for day_key, values in daily.items():
        values["estimated_cost_usd"] = round(values["estimated_cost_usd"], 6)
        daily_rows.append({"date": day_key, **values})
    model_rows = sorted(models.values(), key=lambda item: item["total_tokens"], reverse=True)
    for values in model_rows:
        values["estimated_cost_usd"] = round(values["estimated_cost_usd"], 6)
    total_keys = (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "request_count",
        "estimated_cost_usd",
        "unpriced_tokens",
    )
    totals = {key: sum(row[key] for row in daily_rows) for key in total_keys}
    totals["estimated_cost_usd"] = round(totals["estimated_cost_usd"], 6)
    return {"days": days, "since": since, "totals": totals, "daily": daily_rows, "models": model_rows}


async def is_over_budget(user_id: str) -> bool:
    """True once one account has reached (not just approached) daily_token_budget. Used to
    block *new* LLM calls - never to interrupt one already in flight or a human-approved action
    that's just completing (see routes.py::resume_chat for why resume is exempt)."""
    budget = await get_daily_token_budget()
    if not budget:
        return False
    usage = await get_usage_today(user_id=user_id)
    return usage["total_tokens"] >= budget
