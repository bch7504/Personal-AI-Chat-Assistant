from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.db.models import User
from src.db.session import get_db
from src.models.assistant_schemas import AssistantMessageOut, AssistantThreadOut
from src.models.schemas import InterruptPayload
from src.services import assistant_thread_service

router = APIRouter(prefix="/assistant")


@router.get("/threads", response_model=list[AssistantThreadOut])
async def list_my_threads(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[AssistantThreadOut]:
    threads = await assistant_thread_service.list_threads(db, current_user.id)
    return [
        AssistantThreadOut(thread_id=t.thread_id, title=t.title, preview=t.preview, updated_at=t.updated_at)
        for t in threads
    ]


@router.get("/threads/{thread_id}/messages", response_model=list[AssistantMessageOut])
async def get_thread_messages(
    thread_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[AssistantMessageOut]:
    owned = await assistant_thread_service.get_owned_thread(db, current_user.id, thread_id)
    if owned is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    try:
        messages = await assistant_thread_service.get_thread_messages(current_user.id, thread_id)
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Personal Agent is temporarily unavailable",
        ) from None
    return [AssistantMessageOut(**m) for m in messages]


@router.get("/threads/{thread_id}/pending", response_model=InterruptPayload | None)
async def get_thread_pending_interrupt(
    thread_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> InterruptPayload | None:
    owned = await assistant_thread_service.get_owned_thread(db, current_user.id, thread_id)
    if owned is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    try:
        pending = await assistant_thread_service.get_pending_interrupt(current_user.id, thread_id)
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Personal Agent is temporarily unavailable",
        ) from None
    return InterruptPayload(**pending) if pending else None


@router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    try:
        deleted = await assistant_thread_service.delete_thread(db, current_user.id, thread_id)
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Personal Agent is temporarily unavailable",
        ) from None
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
