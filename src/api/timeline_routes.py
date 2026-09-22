from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.db.models import User
from src.db.session import get_db
from src.models.timeline_schemas import PersonalTimelineOut
from src.services import timeline_service
from src.services.authorization_service import require_conversation_access
from src.services.workspace_service import resolve_workspace_for_user

router = APIRouter()


@router.get("/timeline", response_model=PersonalTimelineOut)
async def get_timeline(
    workspace_id: str | None = Query(default=None),
    from_at: datetime | None = Query(default=None),
    to_at: datetime | None = Query(default=None),
    include_messages: bool = Query(default=False),
    conversation_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PersonalTimelineOut:
    workspace = await resolve_workspace_for_user(db, current_user.id, workspace_id)
    if conversation_id:
        await require_conversation_access(db, current_user, conversation_id, "viewer")
        include_messages = True
    try:
        return await timeline_service.get_personal_timeline(
            db,
            user=current_user,
            workspace_id=workspace.id,
            from_at=from_at,
            to_at=to_at,
            include_messages=include_messages,
            conversation_id=conversation_id,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
