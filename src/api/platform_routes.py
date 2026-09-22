from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import require_platform_admin
from src.db.models import Conversation, Message, SupportAccessGrant, User, Workspace
from src.db.session import get_db
from src.models.platform_schemas import PlatformStats, SupportAccessGrantOut, SupportAccessGrantRequest
from src.services.authorization_service import request_support_access

router = APIRouter(dependencies=[Depends(require_platform_admin)])


@router.get("/support-grants", response_model=list[SupportAccessGrantOut])
async def list_support_grants(
    workspace_id: str | None = Query(default=None),
    current_user: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> list[SupportAccessGrantOut]:
    stmt = select(SupportAccessGrant).where(SupportAccessGrant.platform_admin_id == current_user.id)
    if workspace_id:
        stmt = stmt.where(SupportAccessGrant.workspace_id == workspace_id)
    grants = (await db.execute(stmt.order_by(SupportAccessGrant.created_at.desc()))).scalars().all()
    return [SupportAccessGrantOut.model_validate(grant) for grant in grants]


@router.get("/stats", response_model=PlatformStats)
async def get_platform_stats(db: AsyncSession = Depends(get_db)) -> PlatformStats:
    total_users = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    total_workspaces = (await db.execute(select(func.count()).select_from(Workspace))).scalar_one()
    total_conversations = (await db.execute(select(func.count()).select_from(Conversation))).scalar_one()
    total_messages = (await db.execute(select(func.count()).select_from(Message))).scalar_one()
    since = datetime.now(UTC) - timedelta(days=7)
    new_users = (await db.execute(select(func.count()).select_from(User).where(User.created_at >= since))).scalar_one()
    return PlatformStats(
        total_users=total_users,
        total_workspaces=total_workspaces,
        total_conversations=total_conversations,
        total_messages=total_messages,
        new_users_last_7_days=new_users,
    )


@router.post(
    "/support-grants",
    response_model=SupportAccessGrantOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_support_grant_request(
    request: SupportAccessGrantRequest,
    current_user: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> SupportAccessGrantOut:
    grant = await request_support_access(
        db,
        current_user,
        request.workspace_id,
        request.requested_scope,
        request.reason,
        request.duration_minutes,
    )
    await db.commit()
    await db.refresh(grant)
    return SupportAccessGrantOut.model_validate(grant)
