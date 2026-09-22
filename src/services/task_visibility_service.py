"""Authorization-scoped task queries shared by user-facing personal workload tools."""

from __future__ import annotations

from sqlalchemy import and_, exists, or_, select

from src.db.models import (
    AgentWorkspace,
    AgentWorkspaceMembership,
    ConversationParticipant,
    Task,
    Workspace,
    WorkspaceMembership,
)


def visible_assigned_tasks_statement(user_id: str):
    """Select only tasks assigned to ``user_id`` that the user can still access.

    This intentionally does not expose a workspace backlog. Organization tasks are
    visible only while the assignee still has the required organization, agent
    workspace, and source-conversation memberships.
    """

    active_workspace_membership = exists(
        select(WorkspaceMembership.id).where(
            WorkspaceMembership.workspace_id == Task.workspace_id,
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.status == "active",
        )
    )
    active_agent_membership = exists(
        select(AgentWorkspaceMembership.id)
        .join(
            AgentWorkspace,
            AgentWorkspace.id == AgentWorkspaceMembership.agent_workspace_id,
        )
        .where(
            AgentWorkspaceMembership.agent_workspace_id == Task.agent_workspace_id,
            AgentWorkspaceMembership.user_id == user_id,
            AgentWorkspaceMembership.status == "active",
            AgentWorkspace.organization_workspace_id == Task.workspace_id,
            AgentWorkspace.status == "active",
        )
    )
    active_conversation_membership = exists(
        select(ConversationParticipant.id).where(
            ConversationParticipant.conversation_id == Task.conversation_id,
            ConversationParticipant.user_id == user_id,
            ConversationParticipant.principal_kind == "workspace_user",
            ConversationParticipant.revoked_at.is_(None),
        )
    )

    return (
        select(Task)
        .join(Workspace, Workspace.id == Task.workspace_id)
        .where(
            Task.owner_id == user_id,
            Workspace.status == "active",
            or_(
                and_(
                    Workspace.type == "personal",
                    Workspace.personal_owner_user_id == user_id,
                ),
                and_(
                    Workspace.type == "organization",
                    active_workspace_membership,
                    or_(Task.agent_workspace_id.is_(None), active_agent_membership),
                    or_(Task.conversation_id.is_(None), active_conversation_membership),
                ),
            ),
        )
    )
