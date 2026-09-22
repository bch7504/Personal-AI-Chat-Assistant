from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.db.models import Memory, User
from src.db.session import get_db
from src.models.memory_schemas import MemoryCreateRequest, MemoryOut, MemoryUpdateRequest
from src.services import memory_service
from src.services.workspace_service import resolve_workspace_for_user

router = APIRouter()


def _to_out(memory: Memory) -> MemoryOut:
    return MemoryOut(
        id=memory.id, category=memory.category, title=memory.title, detail=memory.detail,
        workspace_id=memory.workspace_id, memory_type=memory.memory_type,
        source_conversation_id=memory.source_conversation_id,
        source_message_ids=memory.source_message_ids or [], consent_scope_hash=memory.consent_scope_hash,
        sensitivity=memory.sensitivity, confidence=memory.confidence, expires_at=memory.expires_at,
        last_accessed_at=memory.last_accessed_at, created_at=memory.created_at, updated_at=memory.updated_at,
    )


async def _get_own_memory_or_404(memory_id: str, current_user: User, db: AsyncSession) -> Memory:
    memory = (
        await db.execute(select(Memory).where(Memory.id == memory_id, Memory.owner_id == current_user.id))
    ).scalar_one_or_none()
    if memory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    await resolve_workspace_for_user(db, current_user.id, memory.workspace_id)
    return memory


@router.get("/memories", response_model=list[MemoryOut])
async def list_memories(
    workspace_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    include_expired: bool = Query(default=False),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[MemoryOut]:
    workspace = await resolve_workspace_for_user(db, current_user.id, workspace_id)
    stmt = select(Memory).where(Memory.owner_id == current_user.id, Memory.workspace_id == workspace.id)
    if not include_expired:
        now = datetime.now(UTC)
        stmt = stmt.where(or_(Memory.expires_at.is_(None), Memory.expires_at > now))
    memories = (
        await db.execute(
            stmt
            .order_by(Memory.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return [_to_out(m) for m in memories]


@router.post("/memories", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def create_memory(
    request: MemoryCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryOut:
    workspace = await resolve_workspace_for_user(db, current_user.id, request.workspace_id)
    if "memory_type" not in request.model_fields_set:
        request = request.model_copy(
            update={"memory_type": memory_service.inferred_memory_type(request.category)}
        )
    memory = await memory_service.create_memory_from_request(
        db, current_user, workspace.id, request
    )
    return _to_out(memory)


@router.patch("/memories/{memory_id}", response_model=MemoryOut)
async def update_memory(
    memory_id: str,
    request: MemoryUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryOut:
    memory = await _get_own_memory_or_404(memory_id, current_user, db)
    updates = request.model_dump(exclude_unset=True)
    if "category" in updates and "memory_type" not in updates:
        updates["memory_type"] = memory_service.inferred_memory_type(updates["category"])
    prospective_title = updates.get("title", memory.title)
    prospective_detail = updates.get("detail", memory.detail)
    if memory_service.contains_forbidden_sensitive_memory(f"{prospective_title}\n{prospective_detail}"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Memory must not contain credentials or sensitive personal data",
        )
    expires_at = updates.get("expires_at")
    if expires_at is not None:
        expires_at = expires_at if expires_at.tzinfo is not None else expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            # An explicit past timestamp is a supported way for the user to expire a memory now.
            updates["expires_at"] = expires_at
    for field, value in updates.items():
        setattr(memory, field, value)
    await db.commit()
    await db.refresh(memory)
    return _to_out(memory)


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    memory = await _get_own_memory_or_404(memory_id, current_user, db)
    await db.delete(memory)
    await db.commit()
