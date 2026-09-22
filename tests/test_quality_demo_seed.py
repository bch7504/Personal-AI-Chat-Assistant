import pytest
from sqlalchemy import func, select

import scripts.seed_delivery_demo as delivery_seed
import scripts.seed_quality_demo as quality_seed
import src.db.session as db_session
from src.db.models import (
    AgentWorkspace,
    AgentWorkspaceConversation,
    AgentWorkspaceMembership,
    ReleaseCandidate,
    Task,
)


@pytest.mark.asyncio
async def test_quality_demo_seed_is_idempotent_and_keeps_one_agent_assignment(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(delivery_seed, "async_session_maker", db_session.async_session_maker)
    monkeypatch.setattr(quality_seed, "async_session_maker", db_session.async_session_maker)

    first = await quality_seed.seed_quality_demo()
    second = await quality_seed.seed_quality_demo()

    assert first["quality_agent_workspace_id"] == second["quality_agent_workspace_id"]
    async with db_session.async_session_maker() as session:
        quality = (
            await session.execute(
                select(AgentWorkspace).where(
                    AgentWorkspace.id == first["quality_agent_workspace_id"]
                )
            )
        ).scalar_one()
        active_members = (
            await session.execute(
                select(func.count(AgentWorkspaceMembership.id)).where(
                    AgentWorkspaceMembership.agent_workspace_id == quality.id,
                    AgentWorkspaceMembership.status == "active",
                )
            )
        ).scalar_one()
        group_count = (
            await session.execute(
                select(func.count(AgentWorkspaceConversation.id)).where(
                    AgentWorkspaceConversation.agent_workspace_id == quality.id
                )
            )
        ).scalar_one()
        task_count = (
            await session.execute(
                select(func.count(Task.id)).where(Task.agent_workspace_id == quality.id)
            )
        ).scalar_one()
        release_count = (
            await session.execute(
                select(func.count(ReleaseCandidate.id)).where(
                    ReleaseCandidate.quality_agent_workspace_id == quality.id,
                    ReleaseCandidate.release_key == quality_seed.QA_RELEASE_ID,
                )
            )
        ).scalar_one()
        duplicate_users = (
            await session.execute(
                select(AgentWorkspaceMembership.user_id)
                .join(
                    AgentWorkspace,
                    AgentWorkspace.id == AgentWorkspaceMembership.agent_workspace_id,
                )
                .where(
                    AgentWorkspace.organization_workspace_id == quality.organization_workspace_id,
                    AgentWorkspaceMembership.status == "active",
                )
                .group_by(AgentWorkspaceMembership.user_id)
                .having(func.count(AgentWorkspaceMembership.id) > 1)
            )
        ).scalars().all()

    assert active_members == 5
    assert group_count == 2
    assert task_count == 8
    assert release_count == 1
    assert duplicate_users == []
