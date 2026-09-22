"""Durable, bounded memory shared by workspace-specialist API entry points."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.contracts import AgentProfile
from src.agents.runtime.contracts import RuntimeConversationMessage
from src.config import get_settings
from src.db import session as db_session
from src.db.models import WorkspaceAgentMessage, WorkspaceAgentThread


class WorkspaceAgentThreadDeniedError(PermissionError):
    """The supplied thread is absent, expired, or belongs to another security scope."""


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def resolve_thread(
    db: AsyncSession,
    *,
    thread_id: str | None,
    organization_workspace_id: str,
    agent_workspace_id: str,
    owner_id: str,
    profile: AgentProfile,
    authorization_scope_hash: str | None,
) -> WorkspaceAgentThread:
    """Create a thread or validate every part of an existing thread binding."""

    now = datetime.now(UTC)
    retention_days = get_settings().workspace_agent_memory_retention_days
    if thread_id is None:
        thread = WorkspaceAgentThread(
            organization_workspace_id=organization_workspace_id,
            agent_workspace_id=agent_workspace_id,
            owner_id=owner_id,
            agent_profile=profile.value,
            authorization_scope_hash=authorization_scope_hash,
            last_active_at=now,
            expires_at=now + timedelta(days=retention_days),
        )
        db.add(thread)
        await db.flush()
        return thread

    thread = (
        await db.execute(
            select(WorkspaceAgentThread)
            .where(
                WorkspaceAgentThread.id == thread_id,
                WorkspaceAgentThread.organization_workspace_id == organization_workspace_id,
                WorkspaceAgentThread.agent_workspace_id == agent_workspace_id,
                WorkspaceAgentThread.owner_id == owner_id,
                WorkspaceAgentThread.agent_profile == profile.value,
                WorkspaceAgentThread.authorization_scope_hash == authorization_scope_hash,
                WorkspaceAgentThread.status == "active",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if thread is None or _aware(thread.expires_at) <= now:
        raise WorkspaceAgentThreadDeniedError("Workspace agent thread is unavailable")
    return thread


async def load_history(db: AsyncSession, *, thread: WorkspaceAgentThread) -> tuple[RuntimeConversationMessage, ...]:
    """Return only the latest bounded user/assistant history, in chronological order."""

    rows = list(
        (
            await db.execute(
                select(WorkspaceAgentMessage)
                .where(WorkspaceAgentMessage.thread_id == thread.id)
                .order_by(WorkspaceAgentMessage.sequence_number.desc())
                .limit(get_settings().workspace_agent_memory_history_limit)
            )
        )
        .scalars()
        .all()
    )
    rows.reverse()
    return tuple(RuntimeConversationMessage(role=row.role, content=row.content) for row in rows)


def _preview(content: str, *, limit: int) -> str:
    normalized = " ".join(content.split())
    return normalized if len(normalized) <= limit else f"{normalized[: limit - 1].rstrip()}…"


async def list_thread_summaries(
    db: AsyncSession,
    *,
    organization_workspace_id: str,
    agent_workspace_id: str,
    owner_id: str,
    profile: AgentProfile,
    authorization_scope_hash: str | None,
    limit: int = 30,
) -> list[dict]:
    """List resumable short-term threads inside the caller's current security scope."""

    now = datetime.now(UTC)
    threads = list(
        (
            await db.execute(
                select(WorkspaceAgentThread)
                .where(
                    WorkspaceAgentThread.organization_workspace_id == organization_workspace_id,
                    WorkspaceAgentThread.agent_workspace_id == agent_workspace_id,
                    WorkspaceAgentThread.owner_id == owner_id,
                    WorkspaceAgentThread.agent_profile == profile.value,
                    WorkspaceAgentThread.authorization_scope_hash == authorization_scope_hash,
                    WorkspaceAgentThread.status == "active",
                    WorkspaceAgentThread.expires_at > now,
                    WorkspaceAgentThread.message_count > 0,
                )
                .order_by(WorkspaceAgentThread.last_active_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not threads:
        return []
    thread_ids = [thread.id for thread in threads]
    messages = list(
        (
            await db.execute(
                select(WorkspaceAgentMessage)
                .where(WorkspaceAgentMessage.thread_id.in_(thread_ids))
                .order_by(
                    WorkspaceAgentMessage.thread_id.asc(),
                    WorkspaceAgentMessage.sequence_number.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    by_thread: dict[str, list[WorkspaceAgentMessage]] = {thread_id: [] for thread_id in thread_ids}
    for message in messages:
        by_thread[message.thread_id].append(message)

    summaries = []
    for thread in threads:
        rows = by_thread[thread.id]
        first_user = next((row for row in rows if row.role == "user"), None)
        latest = rows[-1] if rows else None
        summaries.append(
            {
                "thread_id": thread.id,
                "title": _preview(first_user.content, limit=58) if first_user else "Cuộc trò chuyện mới",
                "preview": _preview(latest.content, limit=92) if latest else "",
                "message_count": thread.message_count,
                "updated_at": thread.last_active_at,
                "created_at": thread.created_at,
            }
        )
    return summaries


async def get_thread_messages(
    db: AsyncSession,
    *,
    thread_id: str,
    organization_workspace_id: str,
    agent_workspace_id: str,
    owner_id: str,
    profile: AgentProfile,
    authorization_scope_hash: str | None,
) -> list[WorkspaceAgentMessage]:
    """Return a complete display history after re-validating tenant, owner and scope."""

    thread = (
        await db.execute(
            select(WorkspaceAgentThread).where(
                WorkspaceAgentThread.id == thread_id,
                WorkspaceAgentThread.organization_workspace_id == organization_workspace_id,
                WorkspaceAgentThread.agent_workspace_id == agent_workspace_id,
                WorkspaceAgentThread.owner_id == owner_id,
                WorkspaceAgentThread.agent_profile == profile.value,
                WorkspaceAgentThread.authorization_scope_hash == authorization_scope_hash,
                WorkspaceAgentThread.status == "active",
                WorkspaceAgentThread.expires_at > datetime.now(UTC),
            )
        )
    ).scalar_one_or_none()
    if thread is None:
        raise WorkspaceAgentThreadDeniedError("Workspace agent thread is unavailable")
    return list(
        (
            await db.execute(
                select(WorkspaceAgentMessage)
                .where(WorkspaceAgentMessage.thread_id == thread.id)
                .order_by(WorkspaceAgentMessage.sequence_number.asc())
            )
        )
        .scalars()
        .all()
    )


async def delete_thread(
    db: AsyncSession,
    *,
    thread_id: str,
    organization_workspace_id: str,
    agent_workspace_id: str,
    owner_id: str,
    profile: AgentProfile,
    authorization_scope_hash: str | None,
) -> None:
    """Physically delete one thread after validating its complete security binding.

    Workspace-agent history is private to its creator even when the source facts belong to a
    shared workspace. Deleting this bounded chat memory must not delete workflows, tasks, source
    conversations, or any business evidence referenced by an answer.
    """

    thread = (
        await db.execute(
            select(WorkspaceAgentThread)
            .where(
                WorkspaceAgentThread.id == thread_id,
                WorkspaceAgentThread.organization_workspace_id == organization_workspace_id,
                WorkspaceAgentThread.agent_workspace_id == agent_workspace_id,
                WorkspaceAgentThread.owner_id == owner_id,
                WorkspaceAgentThread.agent_profile == profile.value,
                WorkspaceAgentThread.authorization_scope_hash == authorization_scope_hash,
                WorkspaceAgentThread.status == "active",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if thread is None:
        raise WorkspaceAgentThreadDeniedError("Workspace agent thread is unavailable")
    await discard_thread(db, thread=thread)


def _bounded(content: str) -> str:
    max_content = get_settings().workspace_agent_memory_max_content_chars
    if len(content) <= max_content:
        return content
    return f"{content[: max_content - 12]} [truncated]"


async def append_turn(
    db: AsyncSession,
    *,
    thread: WorkspaceAgentThread,
    user_message: str,
    assistant_message: str,
    assistant_workflow_id: str | None = None,
) -> None:
    """Append one atomic logical turn without persisting tool payloads or auth snapshots."""

    now = datetime.now(UTC)
    first_sequence = thread.message_count + 1
    db.add_all(
        [
            WorkspaceAgentMessage(
                thread_id=thread.id,
                sequence_number=first_sequence,
                role="user",
                content=_bounded(user_message),
                created_at=now,
            ),
            WorkspaceAgentMessage(
                thread_id=thread.id,
                workflow_id=assistant_workflow_id,
                sequence_number=first_sequence + 1,
                role="assistant",
                content=_bounded(assistant_message),
                created_at=now,
            ),
        ]
    )
    thread.message_count += 2
    thread.last_active_at = now
    thread.expires_at = now + timedelta(days=get_settings().workspace_agent_memory_retention_days)
    await db.flush()


async def discard_thread(db: AsyncSession, *, thread: WorkspaceAgentThread) -> None:
    """Remove an explicitly ephemeral thread after its response has been produced."""

    await db.execute(delete(WorkspaceAgentMessage).where(WorkspaceAgentMessage.thread_id == thread.id))
    await db.execute(delete(WorkspaceAgentThread).where(WorkspaceAgentThread.id == thread.id))
    await db.flush()


async def cleanup_expired_threads(*, batch_size: int = 100) -> int:
    """Physically remove expired specialist memory in a bounded transaction."""

    now = datetime.now(UTC)
    async with db_session.async_session_maker() as db:
        thread_ids = list(
            (
                await db.execute(
                    select(WorkspaceAgentThread.id)
                    .where(WorkspaceAgentThread.expires_at <= now)
                    .order_by(WorkspaceAgentThread.expires_at.asc())
                    .limit(batch_size)
                )
            )
            .scalars()
            .all()
        )
        if not thread_ids:
            return 0
        await db.execute(delete(WorkspaceAgentMessage).where(WorkspaceAgentMessage.thread_id.in_(thread_ids)))
        await db.execute(delete(WorkspaceAgentThread).where(WorkspaceAgentThread.id.in_(thread_ids)))
        await db.commit()
        return len(thread_ids)
