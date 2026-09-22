from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.db import session as db_session
from src.db.models import AgentThread, User


def checkpoint_thread_id(user_id: str, public_thread_id: str) -> str:
    return f"{user_id}:{public_thread_id}"


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def prepare_thread(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    public_thread_id: str,
) -> tuple[str, bool]:
    now = datetime.now(UTC)
    internal_id = checkpoint_thread_id(user.id, public_thread_id)
    thread = await db.get(AgentThread, internal_id)
    expired = thread is not None and _aware(thread.expires_at) <= now
    if thread is not None and thread.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your agent thread")
    if expired and thread is not None:
        await db.delete(thread)
        await db.flush()
        thread = None
    if thread is None:
        thread = AgentThread(
            id=internal_id,
            owner_id=user.id,
            workspace_id=workspace_id,
            last_active_at=now,
            expires_at=now + timedelta(days=get_settings().agent_thread_retention_days),
        )
        db.add(thread)
    else:
        if thread.workspace_id != workspace_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Agent thread belongs to another workspace",
            )
        thread.last_active_at = now
        thread.expires_at = now + timedelta(days=get_settings().agent_thread_retention_days)
    await db.commit()
    return internal_id, expired


async def require_resumable_thread(
    db: AsyncSession, user: User, public_thread_id: str
) -> AgentThread:
    internal_id = checkpoint_thread_id(user.id, public_thread_id)
    thread = await db.get(AgentThread, internal_id)
    if thread is None or _aware(thread.expires_at) <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent thread expired or no longer exists; start a new request",
        )
    if thread.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your agent thread")
    now = datetime.now(UTC)
    thread.last_active_at = now
    thread.expires_at = now + timedelta(days=get_settings().agent_thread_retention_days)
    await db.commit()
    return thread


async def cleanup_expired_threads() -> None:
    """Delete expired metadata and its LangGraph checkpoint in bounded batches."""
    from src.agents import graph as agent_graph

    now = datetime.now(UTC)
    async with db_session.async_session_maker() as db:
        expired = list(
            (
                await db.execute(
                    select(AgentThread).where(AgentThread.expires_at <= now).limit(100)
                )
            ).scalars()
        )
        for thread in expired:
            await agent_graph.checkpointer.adelete_thread(thread.id)
            await db.delete(thread)
        if expired:
            await db.commit()
