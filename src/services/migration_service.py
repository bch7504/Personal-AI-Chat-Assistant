from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Conversation, ConversationParticipant, MigrationState, User, Workspace, WorkspaceMembership
from src.services.workspace_service import create_personal_workspace


@dataclass(frozen=True)
class MigrationPreflightReport:
    can_run: bool
    owner_user_id: str | None
    user_count: int
    conversation_count: int
    orphan_count: int
    error_code: str | None = None


MIGRATION_KEY = "workspace_foundation_v1"


async def set_workspace_migration_state(
    db: AsyncSession,
    *,
    status: str,
    error_code: str | None = None,
) -> MigrationState:
    state = (
        await db.execute(select(MigrationState).where(MigrationState.migration_key == MIGRATION_KEY))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if state is None:
        state = MigrationState(
            migration_key=MIGRATION_KEY,
            migration_version=MIGRATION_KEY,
            status=status,
            error_code=error_code,
            error_message=error_code,
            started_at=now,
        )
        db.add(state)
    else:
        state.status = status
        state.error_code = error_code
        state.error_message = error_code
    state.completed_at = now if status == "completed" else None
    await db.flush()
    return state


async def preflight_workspace_migration(
    db: AsyncSession,
    bootstrap_owner_user_id: str | None,
) -> MigrationPreflightReport:
    user_count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    conversation_count = (await db.execute(select(func.count()).select_from(Conversation))).scalar_one()
    orphan_count = (
        await db.execute(
            select(func.count())
            .select_from(ConversationParticipant)
            .outerjoin(User, User.id == ConversationParticipant.user_id)
            .where(User.id.is_(None))
        )
    ).scalar_one()

    if orphan_count:
        return MigrationPreflightReport(
            can_run=False,
            owner_user_id=None,
            user_count=user_count,
            conversation_count=conversation_count,
            orphan_count=orphan_count,
            error_code="orphan_participants",
        )

    active_admin_ids = list(
        (
            await db.execute(
                select(User.id).where(
                    User.role == "admin",
                    User.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )

    if bootstrap_owner_user_id:
        if bootstrap_owner_user_id not in active_admin_ids:
            return MigrationPreflightReport(
                can_run=False,
                owner_user_id=None,
                user_count=user_count,
                conversation_count=conversation_count,
                orphan_count=orphan_count,
                error_code="invalid_bootstrap_owner",
            )
        owner_user_id = bootstrap_owner_user_id
    elif len(active_admin_ids) == 1:
        owner_user_id = active_admin_ids[0]
    else:
        return MigrationPreflightReport(
            can_run=False,
            owner_user_id=None,
            user_count=user_count,
            conversation_count=conversation_count,
            orphan_count=orphan_count,
            error_code="ambiguous_bootstrap_owner",
        )

    return MigrationPreflightReport(
        can_run=True,
        owner_user_id=owner_user_id,
        user_count=user_count,
        conversation_count=conversation_count,
        orphan_count=orphan_count,
    )


async def run_workspace_foundation_backfill(
    db: AsyncSession,
    bootstrap_owner_user_id: str | None,
    *,
    dry_run: bool,
) -> MigrationPreflightReport:
    report = await preflight_workspace_migration(db, bootstrap_owner_user_id)
    if not report.can_run or dry_run:
        return report

    users = list((await db.execute(select(User).order_by(User.created_at.asc()))).scalars().all())
    for user in users:
        await create_personal_workspace(db, user)

    organization = (
        await db.execute(select(Workspace).where(Workspace.slug == "legacy-organization"))
    ).scalar_one_or_none()
    if organization is None:
        organization = Workspace(
            type="organization",
            name="Legacy Organization",
            slug="legacy-organization",
        )
        db.add(organization)
        await db.flush()

    existing_members = set(
        (
            await db.execute(
                select(WorkspaceMembership.user_id).where(WorkspaceMembership.workspace_id == organization.id)
            )
        )
        .scalars()
        .all()
    )
    for user in users:
        if user.id in existing_members:
            continue
        db.add(
            WorkspaceMembership(
                workspace_id=organization.id,
                user_id=user.id,
                role="owner" if user.id == report.owner_user_id else "member",
                status="active",
                invited_by_user_id=report.owner_user_id,
            )
        )
    await db.flush()
    return report
