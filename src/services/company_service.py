from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.db.models import User, Workspace, WorkspaceMembership

COMPANY_WORKSPACE_SLUG = "company-root"


async def get_or_create_company_workspace(db: AsyncSession) -> Workspace:
    """Return the one hidden company boundary used by this single-company app."""
    company = (
        await db.execute(
            select(Workspace).where(
                Workspace.type == "organization",
                Workspace.slug == COMPANY_WORKSPACE_SLUG,
            )
        )
    ).scalar_one_or_none()
    if company is not None:
        return company

    company = Workspace(
        type="organization",
        name=get_settings().company_name.strip() or "Company",
        slug=COMPANY_WORKSPACE_SLUG,
        status="active",
    )
    try:
        async with db.begin_nested():
            db.add(company)
            await db.flush()
        return company
    except IntegrityError:
        # A concurrent first request may have created the singleton after our
        # initial SELECT. The unique slug is the final source of truth.
        return (
            await db.execute(
                select(Workspace).where(
                    Workspace.type == "organization",
                    Workspace.slug == COMPANY_WORKSPACE_SLUG,
                )
            )
        ).scalar_one()


async def ensure_open_test_chat_membership(
    db: AsyncSession,
    user: User,
) -> WorkspaceMembership | None:
    """Idempotently enroll an active tester in the shared company workspace.

    This is deliberately feature-gated. Normal deployments retain explicit
    organization membership, while the public demo can let registered users find
    one another without exposing agent-workspace channels or private groups.
    """
    if not get_settings().open_test_chat_enabled or not user.is_active:
        return None

    company = await get_or_create_company_workspace(db)
    membership = (
        await db.execute(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == company.id,
                WorkspaceMembership.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if membership is not None:
        if membership.status != "active":
            membership.status = "active"
            membership.role = "member"
            await db.flush()
        return membership

    membership = WorkspaceMembership(
        workspace_id=company.id,
        user_id=user.id,
        role="member",
        status="active",
        invited_by_user_id=None,
    )
    try:
        async with db.begin_nested():
            db.add(membership)
            await db.flush()
        return membership
    except IntegrityError:
        # Concurrent login/list requests can race on first enrollment. The unique
        # workspace/user constraint decides the winner; both requests use that row.
        return (
            await db.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == company.id,
                    WorkspaceMembership.user_id == user.id,
                )
            )
        ).scalar_one()
