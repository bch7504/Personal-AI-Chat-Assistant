from __future__ import annotations

import pytest
from sqlalchemy import select

import src.db.session as db_session
from src.agents.contracts import AgentProfile
from src.db.models import (
    AgentWorkspace,
    User,
    Workspace,
    WorkspaceAgentMessage,
    WorkspaceAgentThread,
)
from src.services.workspace_agent_memory_service import (
    WorkspaceAgentThreadDeniedError,
    append_turn,
    cleanup_expired_threads,
    delete_thread,
    get_thread_messages,
    list_thread_summaries,
    load_history,
    resolve_thread,
)


@pytest.mark.asyncio
async def test_workspace_memory_is_durable_bounded_and_profile_isolated(client, auth_headers):
    async with db_session.async_session_maker() as db:
        user = (await db.execute(select(User).where(User.email == "alice@example.com"))).scalar_one()
        organization = Workspace(type="organization", name="Memory Company", slug="memory-company")
        db.add(organization)
        await db.flush()
        delivery = AgentWorkspace(
            organization_workspace_id=organization.id,
            key="memory-delivery",
            name="Memory Delivery",
            agent_profile=AgentProfile.PRODUCT_DELIVERY.value,
        )
        db.add(delivery)
        await db.flush()
        thread = await resolve_thread(
            db,
            thread_id=None,
            organization_workspace_id=organization.id,
            agent_workspace_id=delivery.id,
            owner_id=user.id,
            profile=AgentProfile.PRODUCT_DELIVERY,
            authorization_scope_hash="scope-v1",
        )
        await append_turn(
            db,
            thread=thread,
            user_message="Release nào đang trễ?",
            assistant_message="R1 đang có blocker.",
        )
        thread_id = thread.id
        await db.commit()

    async with db_session.async_session_maker() as db:
        resumed = await resolve_thread(
            db,
            thread_id=thread_id,
            organization_workspace_id=organization.id,
            agent_workspace_id=delivery.id,
            owner_id=user.id,
            profile=AgentProfile.PRODUCT_DELIVERY,
            authorization_scope_hash="scope-v1",
        )
        history = await load_history(db, thread=resumed)
        assert [(item.role, item.content) for item in history] == [
            ("user", "Release nào đang trễ?"),
            ("assistant", "R1 đang có blocker."),
        ]
        summaries = await list_thread_summaries(
            db,
            organization_workspace_id=organization.id,
            agent_workspace_id=delivery.id,
            owner_id=user.id,
            profile=AgentProfile.PRODUCT_DELIVERY,
            authorization_scope_hash="scope-v1",
        )
        assert summaries[0]["thread_id"] == thread_id
        assert summaries[0]["title"] == "Release nào đang trễ?"
        assert summaries[0]["preview"] == "R1 đang có blocker."
        assert summaries[0]["message_count"] == 2
        display_history = await get_thread_messages(
            db,
            thread_id=thread_id,
            organization_workspace_id=organization.id,
            agent_workspace_id=delivery.id,
            owner_id=user.id,
            profile=AgentProfile.PRODUCT_DELIVERY,
            authorization_scope_hash="scope-v1",
        )
        assert [item.role for item in display_history] == ["user", "assistant"]
        assert await list_thread_summaries(
            db,
            organization_workspace_id=organization.id,
            agent_workspace_id=delivery.id,
            owner_id=user.id,
            profile=AgentProfile.PRODUCT_DELIVERY,
            authorization_scope_hash="scope-revoked",
        ) == []
        with pytest.raises(WorkspaceAgentThreadDeniedError):
            await resolve_thread(
                db,
                thread_id=thread_id,
                organization_workspace_id=organization.id,
                agent_workspace_id=delivery.id,
                owner_id=user.id,
                profile=AgentProfile.QUALITY_ASSURANCE,
                authorization_scope_hash="scope-v1",
            )
        with pytest.raises(WorkspaceAgentThreadDeniedError):
            await resolve_thread(
                db,
                thread_id=thread_id,
                organization_workspace_id=organization.id,
                agent_workspace_id=delivery.id,
                owner_id=user.id,
                profile=AgentProfile.PRODUCT_DELIVERY,
                authorization_scope_hash="scope-revoked",
            )
        with pytest.raises(WorkspaceAgentThreadDeniedError):
            await delete_thread(
                db,
                thread_id=thread_id,
                organization_workspace_id=organization.id,
                agent_workspace_id=delivery.id,
                owner_id="another-owner",
                profile=AgentProfile.PRODUCT_DELIVERY,
                authorization_scope_hash="scope-v1",
            )
        with pytest.raises(WorkspaceAgentThreadDeniedError):
            await delete_thread(
                db,
                thread_id=thread_id,
                organization_workspace_id=organization.id,
                agent_workspace_id=delivery.id,
                owner_id=user.id,
                profile=AgentProfile.PRODUCT_DELIVERY,
                authorization_scope_hash="scope-revoked",
            )

        await delete_thread(
            db,
            thread_id=thread_id,
            organization_workspace_id=organization.id,
            agent_workspace_id=delivery.id,
            owner_id=user.id,
            profile=AgentProfile.PRODUCT_DELIVERY,
            authorization_scope_hash="scope-v1",
        )
        await db.commit()
        assert await db.get(WorkspaceAgentThread, thread_id) is None
        remaining_messages = list(
            (
                await db.execute(
                    select(WorkspaceAgentMessage).where(
                        WorkspaceAgentMessage.thread_id == thread_id
                    )
                )
            ).scalars()
        )
        assert remaining_messages == []


@pytest.mark.asyncio
async def test_workspace_memory_cleanup_physically_deletes_expired_thread_and_messages(
    client, auth_headers
):
    from datetime import UTC, datetime, timedelta

    async with db_session.async_session_maker() as db:
        user = (await db.execute(select(User).where(User.email == "alice@example.com"))).scalar_one()
        organization = Workspace(type="organization", name="Expired Memory", slug="expired-memory")
        db.add(organization)
        await db.flush()
        delivery = AgentWorkspace(
            organization_workspace_id=organization.id,
            key="expired-delivery",
            name="Expired Delivery",
            agent_profile=AgentProfile.PRODUCT_DELIVERY.value,
        )
        db.add(delivery)
        await db.flush()
        thread = await resolve_thread(
            db,
            thread_id=None,
            organization_workspace_id=organization.id,
            agent_workspace_id=delivery.id,
            owner_id=user.id,
            profile=AgentProfile.PRODUCT_DELIVERY,
            authorization_scope_hash="expired-scope",
        )
        await append_turn(
            db,
            thread=thread,
            user_message="Old question",
            assistant_message="Old answer",
        )
        thread.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        thread_id = thread.id
        await db.commit()

    assert await cleanup_expired_threads() == 1

    async with db_session.async_session_maker() as db:
        assert await db.get(WorkspaceAgentThread, thread_id) is None
        messages = (
            await db.execute(
                select(WorkspaceAgentMessage).where(
                    WorkspaceAgentMessage.thread_id == thread_id
                )
            )
        ).scalars().all()
        assert messages == []
