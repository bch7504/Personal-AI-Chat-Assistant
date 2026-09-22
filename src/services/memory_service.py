import re
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Conversation, Memory, User
from src.models.memory_schemas import MemoryCreateRequest
from src.services import chat_service, consent_service
from src.services.authorization_service import require_conversation_access
from src.services.personal_query_router_service import (
    extract_explicit_memory_drafts,
    normalize_for_routing,
)

# Persistent assistant memory must never become a secondary secret store. This check is kept
# deterministic and runs for both direct API writes and edits; conversation provenance/consent is
# validated separately below.
_FORBIDDEN_MEMORY_RE = re.compile(
    r"\b(password|mat\s*khau|passcode|otp|api[_ -]?key|secret|access[_ -]?token|"
    r"refresh[_ -]?token|private[_ -]?key|cvv|so\s*the|cccd|cmnd|ho\s*chieu|"
    r"social\s*security|bank\s*account|tai\s*khoan\s*ngan\s*hang|sinh\s*trac|biometric|"
    r"ton\s*giao|religion|xu\s*huong\s*tinh\s*duc|sexual\s*orientation|"
    r"dang\s*phai|political\s*affiliation|chan\s*doan|diagnos(?:is|ed))\b",
    flags=re.IGNORECASE,
)


def contains_forbidden_sensitive_memory(text: str) -> bool:
    return bool(_FORBIDDEN_MEMORY_RE.search(text or ""))


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def is_expired(memory: Memory, now: datetime | None = None) -> bool:
    if memory.expires_at is None:
        return False
    return _utc(memory.expires_at) <= (now or datetime.now(UTC))


_PREFERENCE_CATEGORIES = {"preference", "language", "routine"}


def inferred_memory_type(category: str) -> str:
    """Map the user-facing category to the governed backend memory type."""

    normalized = (category or "").strip().casefold()
    if normalized in _PREFERENCE_CATEGORIES:
        return "preference"
    if normalized == "people":
        return "relationship"
    return "semantic"


def compile_personal_preference_directives(memories: list[Memory]) -> tuple[str, ...]:
    """Compile allow-listed preferences into trusted, non-user-authored directives.

    Raw memory remains untrusted. Only recognized values are converted into fixed server-owned
    sentences, preventing a manually entered prompt injection from becoming a system instruction.
    """

    directives: list[str] = []
    for memory in memories:
        if (
            memory.memory_type != "preference"
            and (memory.category or "").strip().casefold() not in _PREFERENCE_CATEGORIES
        ):
            continue
        combined = " ".join(part.strip() for part in (memory.title, memory.detail) if part.strip())
        normalized = normalize_for_routing(combined)

        for draft in extract_explicit_memory_drafts(combined):
            if draft.title != "Cách xưng hô":
                continue
            alias = draft.detail.removeprefix("Gọi người dùng là “").removesuffix("”.").strip()
            if re.fullmatch(r"[\wÀ-ỹ .'-]{1,40}", alias, flags=re.UNICODE):
                directives.append(f'Address the user as "{alias}" naturally in responses.')

        if "can than" in normalized and "cach lam viec" in normalized:
            directives.append("The user values careful, accuracy-focused work.")
        if any(phrase in normalized for phrase in ("tra loi ngan gon", "phan hoi ngan gon", "concise responses")):
            directives.append("Keep responses concise unless more detail is requested.")
        if any(phrase in normalized for phrase in ("tra loi chi tiet", "phan hoi chi tiet", "detailed responses")):
            directives.append("Prefer detailed responses unless the user asks for brevity.")
        if any(phrase in normalized for phrase in ("tieng viet", "vietnamese")):
            directives.append("Use Vietnamese for responses.")
        elif any(phrase in normalized for phrase in ("tieng anh", "english")):
            directives.append("Use English for responses.")

    return tuple(dict.fromkeys(directives))


async def validate_memory_source(
    db: AsyncSession,
    user: User,
    conversation_id: str,
    workspace_id: str,
    source_message_ids: list[str],
    consent_scope_hash: str,
) -> None:
    await require_conversation_access(db, user, conversation_id, "viewer")
    await chat_service.assert_ai_permission(db, conversation_id, user.id)
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Memory source does not belong to the selected workspace",
        )
    current_hash = await consent_service.get_consent_scope_hash(db, conversation_id)
    if current_hash != consent_scope_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conversation AI consent changed; create the memory from fresh context",
        )
    if not await consent_service.validate_authorized_source_ids(db, conversation_id, source_message_ids):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Memory provenance includes a message that AI is not allowed to process",
        )


async def create_memory_from_request(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    request: MemoryCreateRequest,
) -> Memory:
    if contains_forbidden_sensitive_memory(f"{request.title}\n{request.detail}"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Memory must not contain credentials or sensitive personal data",
        )
    if request.expires_at is not None and _utc(request.expires_at) <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="expires_at must be in the future",
        )
    if request.source_conversation_id:
        await validate_memory_source(
            db,
            user,
            request.source_conversation_id,
            workspace_id,
            request.source_message_ids,
            request.consent_scope_hash or "",
        )
    memory = Memory(
        workspace_id=workspace_id,
        owner_id=user.id,
        category=request.category,
        title=request.title,
        detail=request.detail,
        memory_type=request.memory_type,
        source_conversation_id=request.source_conversation_id,
        source_message_ids=request.source_message_ids,
        consent_scope_hash=request.consent_scope_hash,
        sensitivity=request.sensitivity,
        confidence=request.confidence,
        expires_at=request.expires_at,
    )
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    return memory


async def upsert_personal_memory(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    request: MemoryCreateRequest,
    *,
    replace_by_title: bool = True,
) -> Memory:
    """Idempotently persist an explicit Personal Agent memory.

    Stable preference titles such as "Cách xưng hô" are replaced when the user changes them.
    Generic memories are de-duplicated by exact detail so unrelated facts are not overwritten.
    """

    if contains_forbidden_sensitive_memory(f"{request.title}\n{request.detail}"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Memory must not contain credentials or sensitive personal data",
        )
    stmt = select(Memory).where(
        Memory.owner_id == user.id,
        Memory.workspace_id == workspace_id,
        Memory.memory_type == request.memory_type,
        Memory.category == request.category,
        Memory.title == request.title,
    )
    if not replace_by_title:
        stmt = stmt.where(Memory.detail == request.detail)
    existing = (await db.execute(stmt.order_by(Memory.updated_at.desc()).limit(1))).scalar_one_or_none()
    if existing is None:
        return await create_memory_from_request(db, user, workspace_id, request)

    existing.detail = request.detail
    existing.sensitivity = request.sensitivity
    existing.confidence = request.confidence
    existing.expires_at = request.expires_at
    await db.commit()
    await db.refresh(existing)
    return existing


async def search_active_memories(
    db: AsyncSession,
    *,
    owner_id: str,
    workspace_id: str,
    query: str = "",
    memory_types: set[str] | None = None,
    limit: int = 10,
) -> list[Memory]:
    now = datetime.now(UTC)
    owner = await db.get(User, owner_id)
    if owner is None or not owner.is_active:
        return []
    stmt = select(Memory).where(
        Memory.owner_id == owner_id,
        Memory.workspace_id == workspace_id,
        or_(Memory.expires_at.is_(None), Memory.expires_at > now),
    )
    if memory_types:
        if memory_types == {"preference"}:
            # Include records created by the legacy UI, which displayed category=Preference but
            # omitted memory_type and therefore persisted them as semantic.
            stmt = stmt.where(
                or_(
                    Memory.memory_type == "preference",
                    func.lower(Memory.category).in_(_PREFERENCE_CATEGORIES),
                )
            )
        else:
            stmt = stmt.where(Memory.memory_type.in_(memory_types))
    if query.strip():
        # Durable preferences influence every Personal Agent response, so they must not disappear
        # merely because the current query does not repeat the wording used when saved. Other
        # memory types use bounded token matching instead of requiring the entire query verbatim.
        terms = list(
            dict.fromkeys(
                term.casefold()
                for term in re.findall(r"[\wÀ-ỹ-]{3,}", query, flags=re.UNICODE)
                if term.casefold()
                not in {
                    "của", "cho", "với", "tôi", "bạn", "những", "các", "một", "the", "and",
                    "for", "with", "this", "that", "what", "please", "hãy", "giúp",
                }
            )
        )[:8]
        lexical_filters = []
        for term in terms:
            pattern = f"%{term}%"
            lexical_filters.extend(
                (Memory.title.ilike(pattern), Memory.detail.ilike(pattern), Memory.category.ilike(pattern))
            )
        stmt = stmt.where(
            or_(
                Memory.memory_type == "preference",
                func.lower(Memory.category).in_(_PREFERENCE_CATEGORIES),
                *lexical_filters,
            )
        )
    candidates = list(
        (await db.execute(stmt.order_by(Memory.updated_at.desc()).limit(max(1, min(limit * 3, 50))))).scalars()
    )
    active: list[Memory] = []
    for memory in candidates:
        if memory.source_conversation_id:
            try:
                await require_conversation_access(db, owner, memory.source_conversation_id, "viewer")
            except HTTPException:
                continue
            current_hash = await consent_service.get_consent_scope_hash(db, memory.source_conversation_id)
            if current_hash != memory.consent_scope_hash:
                continue
            if not await consent_service.validate_authorized_source_ids(
                db, memory.source_conversation_id, memory.source_message_ids
            ):
                continue
        memory.last_accessed_at = now
        active.append(memory)
        if len(active) >= limit:
            break
    if active:
        await db.commit()
    return active
