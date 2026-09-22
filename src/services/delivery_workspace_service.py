"""Scoped Delivery read boundary.

Production database reads intentionally do not exist here yet.  The shared
platform must first deliver task-to-Agent-Workspace binding and the member
participant intersection (A-DLV-01/06/09).  This module makes that dependency
explicit: callers can derive a query scope, but cannot obtain a broad fallback
scope when no authorized resource is present.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.contracts import AgentContext, BusinessRole, SourceReference
from src.agents.schemas.delivery import (
    DeliveryDecision,
    DeliveryDecisionStatus,
    DeliveryDependency,
    DeliveryDependencyStatus,
    DeliveryItem,
    DeliveryMessageEvidence,
    DeliveryPerson,
    DeliveryReadScope,
    DeliveryReleaseStatus,
    DeliveryViewScope,
    DeliveryWorkStatus,
)
from src.db.models import (
    ConversationParticipant,
    DeliveryDecisionRecord,
    DeliveryDependencyRecord,
    DeliveryMilestone,
    Message,
    ReleaseCandidate,
    Task,
    User,
)


class DeliveryScopeError(PermissionError):
    """Raised when a Delivery read would exceed the server-resolved scope."""


DeliveryWorkspaceRevalidator = Callable[[str], Awaitable[None]]
DeliveryResourceRevalidator = Callable[[str], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class DeliveryQueryScope:
    """Minimal values a future repository may bind directly into a DB query."""

    organization_workspace_id: str
    agent_workspace_id: str
    actor_user_id: str
    view_scope: DeliveryViewScope
    group_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    decision_ids: tuple[str, ...]
    person_ids: tuple[str, ...]

    def requires_resource_bound_query(self) -> bool:
        """True when a repository must bind group/task/decision predicates."""

        return bool(self.group_ids or self.task_ids or self.decision_ids or self.person_ids)


def _as_aware_timestamp(value: datetime) -> datetime:
    """Normalize legacy SQLite timestamps without changing their stored instant."""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class SqlAlchemyDeliveryTaskRepository:
    """Production task repository with no company-wide or legacy fallback path."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_tasks(self, scope: DeliveryQueryScope) -> Sequence[DeliveryItem]:
        if not scope.group_ids:
            return ()

        statement = select(Task).where(
            Task.workspace_id == scope.organization_workspace_id,
            Task.agent_workspace_id == scope.agent_workspace_id,
            Task.conversation_id.in_(scope.group_ids),
        )
        if scope.task_ids:
            statement = statement.where(Task.id.in_(scope.task_ids))
        if scope.view_scope == DeliveryViewScope.MEMBER:
            statement = statement.where(Task.owner_id == scope.actor_user_id)
        rows = (
            (
                await self._db.execute(
                    statement.order_by(Task.due_at.is_(None), Task.due_at.asc(), Task.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

        return tuple(
            DeliveryItem(
                id=task.id,
                title=task.title,
                status=DeliveryWorkStatus(task.status),
                assignee_id=task.owner_id,
                due_at=_as_aware_timestamp(task.due_at) if task.due_at is not None else None,
                created_at=_as_aware_timestamp(task.created_at),
                started_at=_as_aware_timestamp(task.started_at) if task.started_at is not None else None,
                completed_at=_as_aware_timestamp(task.completed_at) if task.completed_at is not None else None,
                blocked_reason=task.blocked_reason,
                row_version=task.row_version,
                requires_review=task.requires_review,
                submission_note=task.submission_note,
                evidence_urls=tuple(task.evidence_urls or []),
                submitted_at=(
                    _as_aware_timestamp(task.submitted_at) if task.submitted_at is not None else None
                ),
                reviewed_at=(
                    _as_aware_timestamp(task.reviewed_at) if task.reviewed_at is not None else None
                ),
                review_note=task.review_note,
                sources=(
                    SourceReference(
                        resource_id=task.conversation_id,
                        resource_type="conversation",
                        agent_workspace_id=scope.agent_workspace_id,
                        classification="delivery",
                        captured_at=_as_aware_timestamp(task.updated_at),
                    ),
                ),
            )
            for task in rows
        )


class SqlAlchemyDeliveryMilestoneRepository:
    """Typed milestone repository bound to the same Delivery query predicates."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_milestones(self, scope: DeliveryQueryScope) -> Sequence[DeliveryItem]:
        if not scope.group_ids:
            return ()
        statement = select(DeliveryMilestone).where(
            DeliveryMilestone.workspace_id == scope.organization_workspace_id,
            DeliveryMilestone.agent_workspace_id == scope.agent_workspace_id,
            DeliveryMilestone.conversation_id.in_(scope.group_ids),
        )
        if scope.view_scope == DeliveryViewScope.MEMBER:
            statement = statement.where(DeliveryMilestone.owner_id == scope.actor_user_id)
        rows = (
            (
                await self._db.execute(
                    statement.order_by(
                        DeliveryMilestone.due_at.is_(None),
                        DeliveryMilestone.due_at.asc(),
                        DeliveryMilestone.created_at.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        return tuple(
            DeliveryItem(
                id=milestone.id,
                title=milestone.title,
                status=DeliveryWorkStatus(milestone.status),
                assignee_id=milestone.owner_id,
                due_at=_as_aware_timestamp(milestone.due_at) if milestone.due_at is not None else None,
                blocked_reason=milestone.blocked_reason,
                sources=(
                    SourceReference(
                        resource_id=milestone.conversation_id,
                        resource_type="conversation",
                        agent_workspace_id=scope.agent_workspace_id,
                        classification="delivery",
                        captured_at=_as_aware_timestamp(milestone.updated_at),
                    ),
                ),
            )
            for milestone in rows
        )


_DELIVERY_SEARCH_STOPWORDS = frozenset(
    {
        "các",
        "cho",
        "của",
        "group",
        "hãy",
        "nhóm",
        "những",
        "tiến",
        "trong",
        "tóm",
        "workspace",
    }
)


def _search_terms(query: str) -> tuple[str, ...]:
    words = re.findall(r"[^\W_]+", query.casefold(), flags=re.UNICODE)
    return tuple(dict.fromkeys(word for word in words if len(word) >= 3 and word not in _DELIVERY_SEARCH_STOPWORDS))[:8]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class SqlAlchemyDeliveryMessageRepository:
    """Bounded chat evidence search over already-authorized Delivery groups."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def search_messages(
        self,
        scope: DeliveryQueryScope,
        *,
        query: str,
        from_at: datetime,
        to_at: datetime,
        limit: int,
    ) -> Sequence[DeliveryMessageEvidence]:
        if not scope.group_ids:
            return ()
        statement = (
            select(Message, User)
            .join(User, User.id == Message.sender_id)
            .where(
                Message.conversation_id.in_(scope.group_ids),
                Message.created_at >= from_at,
                Message.created_at <= to_at,
                User.is_active.is_(True),
            )
        )
        terms = _search_terms(query)
        if terms:
            statement = statement.where(
                or_(*(Message.content.ilike(f"%{_escape_like(term)}%", escape="\\") for term in terms))
            )
        rows = list(
            (
                await self._db.execute(statement.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit))
            ).all()
        )
        rows.reverse()
        return tuple(
            DeliveryMessageEvidence(
                message_id=message.id,
                conversation_id=message.conversation_id,
                excerpt=f"{sender.display_name}: {message.content}",
                sources=(
                    SourceReference(
                        resource_id=message.conversation_id,
                        resource_type="conversation",
                        agent_workspace_id=scope.agent_workspace_id,
                        classification="delivery",
                        captured_at=_as_aware_timestamp(message.created_at),
                    ),
                ),
            )
            for message, sender in rows
        )


class SqlAlchemyDeliveryPeopleRepository:
    """Return only active participants inside the scoped Delivery groups."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def resolve_people(
        self,
        scope: DeliveryQueryScope,
        *,
        user_ids: tuple[str, ...],
    ) -> Sequence[DeliveryPerson]:
        if not scope.group_ids or not user_ids:
            return ()
        rows = (
            await self._db.execute(
                select(User.id, User.display_name)
                .join(
                    ConversationParticipant,
                    ConversationParticipant.user_id == User.id,
                )
                .where(
                    ConversationParticipant.conversation_id.in_(scope.group_ids),
                    ConversationParticipant.revoked_at.is_(None),
                    ConversationParticipant.hidden_at.is_(None),
                    User.id.in_(user_ids),
                    User.is_active.is_(True),
                )
                .distinct()
                .order_by(User.display_name.asc(), User.id.asc())
            )
        ).all()
        return tuple(DeliveryPerson(user_id=user_id, display_name=display_name) for user_id, display_name in rows)


class SqlAlchemyDeliveryControlRepository:
    """Read source-bound dependencies and decisions without a broad fallback."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_dependencies(self, scope: DeliveryQueryScope) -> Sequence[DeliveryDependency]:
        if not scope.group_ids:
            return ()
        statement = select(DeliveryDependencyRecord).where(
            DeliveryDependencyRecord.workspace_id == scope.organization_workspace_id,
            DeliveryDependencyRecord.agent_workspace_id == scope.agent_workspace_id,
            DeliveryDependencyRecord.conversation_id.in_(scope.group_ids),
        )
        if scope.view_scope == DeliveryViewScope.MEMBER:
            statement = statement.where(DeliveryDependencyRecord.owner_id == scope.actor_user_id)
        rows = (
            (
                await self._db.execute(
                    statement.order_by(
                        DeliveryDependencyRecord.due_at.is_(None),
                        DeliveryDependencyRecord.due_at.asc(),
                        DeliveryDependencyRecord.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        return tuple(
            DeliveryDependency(
                id=row.id,
                title=row.title,
                status=DeliveryDependencyStatus(row.status),
                assignee_id=row.owner_id,
                predecessor_task_id=row.predecessor_task_id,
                successor_task_id=row.successor_task_id,
                due_at=_as_aware_timestamp(row.due_at) if row.due_at else None,
                sources=(
                    SourceReference(
                        resource_id=row.conversation_id,
                        resource_type="conversation",
                        agent_workspace_id=scope.agent_workspace_id,
                        classification="delivery",
                        captured_at=_as_aware_timestamp(row.updated_at),
                    ),
                ),
            )
            for row in rows
        )

    async def list_decisions(self, scope: DeliveryQueryScope) -> Sequence[DeliveryDecision]:
        if not scope.group_ids:
            return ()
        statement = select(DeliveryDecisionRecord).where(
            DeliveryDecisionRecord.workspace_id == scope.organization_workspace_id,
            DeliveryDecisionRecord.agent_workspace_id == scope.agent_workspace_id,
            DeliveryDecisionRecord.conversation_id.in_(scope.group_ids),
        )
        if scope.decision_ids:
            statement = statement.where(DeliveryDecisionRecord.id.in_(scope.decision_ids))
        if scope.view_scope == DeliveryViewScope.MEMBER:
            statement = statement.where(DeliveryDecisionRecord.owner_id == scope.actor_user_id)
        rows = (
            (
                await self._db.execute(
                    statement.order_by(
                        DeliveryDecisionRecord.due_at.is_(None),
                        DeliveryDecisionRecord.due_at.asc(),
                        DeliveryDecisionRecord.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        return tuple(
            DeliveryDecision(
                id=row.id,
                title=row.title,
                status=DeliveryDecisionStatus(row.status),
                owner_id=row.owner_id,
                due_at=_as_aware_timestamp(row.due_at) if row.due_at else None,
                options=tuple(row.options or ()),
                outcome=row.outcome,
                sources=(
                    SourceReference(
                        resource_id=row.conversation_id,
                        resource_type="conversation",
                        agent_workspace_id=scope.agent_workspace_id,
                        classification="delivery",
                        captured_at=_as_aware_timestamp(row.updated_at),
                    ),
                ),
            )
            for row in rows
        )


class SqlAlchemyDeliveryReleaseRepository:
    """Read Delivery-owned handoff state without depending on the QA runtime."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_releases(self, scope: DeliveryQueryScope) -> Sequence[DeliveryReleaseStatus]:
        if not scope.group_ids:
            return ()
        rows = (
            (
                await self._db.execute(
                    select(ReleaseCandidate)
                    .where(
                        ReleaseCandidate.organization_workspace_id == scope.organization_workspace_id,
                        ReleaseCandidate.delivery_agent_workspace_id == scope.agent_workspace_id,
                        ReleaseCandidate.source_conversation_id.in_(scope.group_ids),
                    )
                    .order_by(ReleaseCandidate.updated_at.desc(), ReleaseCandidate.id.asc())
                )
            )
            .scalars()
            .all()
        )
        return tuple(
            DeliveryReleaseStatus(
                id=row.id,
                release_key=row.release_key,
                status=row.status,
                version=row.version,
                build_number=row.build_number,
                environment=row.environment,
                quality_policy_version=row.quality_policy_version,
                sources=(
                    SourceReference(
                        resource_id=row.source_conversation_id,
                        resource_type="release_candidate",
                        agent_workspace_id=scope.agent_workspace_id,
                        classification="handoff",
                        captured_at=_as_aware_timestamp(row.updated_at),
                    ),
                ),
            )
            for row in rows
        )


def build_delivery_query_scope(scope: DeliveryReadScope) -> DeliveryQueryScope:
    """Convert a validated capability envelope into repository-bound parameters.

    A scope with no resolved resources is valid but cannot be sent to a
    repository. The caller must return an empty/partial `ToolResult` without a
    repository call; it must never replace these predicates with a Company Root
    query.
    """

    target_workspace_id = scope.context.request.target_agent_workspace_id
    if target_workspace_id is None:  # Defensive; DeliveryReadScope already validates it.
        raise DeliveryScopeError("Delivery target workspace is missing")

    query_scope = DeliveryQueryScope(
        organization_workspace_id=scope.context.actor.organization_workspace_id,
        agent_workspace_id=target_workspace_id,
        actor_user_id=scope.context.actor.user_id,
        view_scope=scope.view_scope,
        group_ids=scope.effective_group_ids,
        task_ids=scope.allowed_task_ids,
        decision_ids=scope.allowed_decision_ids,
        person_ids=scope.allowed_person_ids,
    )
    return query_scope


async def resolve_delivery_read_scope(
    *,
    context: AgentContext,
    requested_conversation_id: str | None,
    revalidate_workspace: DeliveryWorkspaceRevalidator,
    revalidate_resource: DeliveryResourceRevalidator,
    allowed_task_ids: tuple[str, ...] = (),
    allowed_decision_ids: tuple[str, ...] = (),
    allowed_person_ids: tuple[str, ...] = (),
) -> DeliveryReadScope:
    """Resolve the only Delivery view capability that tools may consume.

    ``requested_conversation_id`` is untrusted selector input, never a direct
    query predicate.  The resource revalidator proves that it remains inside
    the current Delivery allowlist before a single-group capability is issued.
    A member's unselected view remains limited to their own work. When a
    member explicitly selects one authorized channel, the channel itself is
    the read boundary and the agent may aggregate all work items visible in
    that channel. Mutation authorization remains separate and owner/Lead
    constrained.

    Production composition must pass callbacks backed by
    ``enforce_agent_workspace_access`` and ``enforce_agent_resource_access``.
    Keeping them injected avoids creating a second DB/session ownership path
    while ensuring all callers exercise the same policy boundary.
    """

    target_workspace_id = context.request.target_agent_workspace_id
    if target_workspace_id is None:
        raise DeliveryScopeError("Delivery target workspace is missing")
    await revalidate_workspace(target_workspace_id)

    if context.actor.business_role == BusinessRole.LEAD:
        if requested_conversation_id is None:
            return DeliveryReadScope(
                context=context,
                view_scope=DeliveryViewScope.WORKSPACE,
                effective_group_ids=context.authorization.allowed_resource_ids,
                allowed_task_ids=allowed_task_ids,
                allowed_decision_ids=allowed_decision_ids,
                allowed_person_ids=allowed_person_ids,
            )
        await revalidate_resource(requested_conversation_id)
        return DeliveryReadScope(
            context=context,
            view_scope=DeliveryViewScope.GROUP,
            effective_group_ids=(requested_conversation_id,),
            selected_conversation_id=requested_conversation_id,
            allowed_task_ids=allowed_task_ids,
            allowed_decision_ids=allowed_decision_ids,
            allowed_person_ids=allowed_person_ids,
        )

    if context.actor.business_role == BusinessRole.MEMBER:
        if requested_conversation_id is not None:
            await revalidate_resource(requested_conversation_id)
            return DeliveryReadScope(
                context=context,
                view_scope=DeliveryViewScope.GROUP,
                effective_group_ids=(requested_conversation_id,),
                selected_conversation_id=requested_conversation_id,
                allowed_task_ids=allowed_task_ids,
                allowed_decision_ids=allowed_decision_ids,
                allowed_person_ids=allowed_person_ids,
            )
        return DeliveryReadScope(
            context=context,
            view_scope=DeliveryViewScope.MEMBER,
            effective_group_ids=context.authorization.allowed_resource_ids,
            allowed_task_ids=allowed_task_ids,
            allowed_decision_ids=allowed_decision_ids,
            allowed_person_ids=allowed_person_ids,
        )

    raise DeliveryScopeError("The Delivery business role cannot resolve a read scope")
