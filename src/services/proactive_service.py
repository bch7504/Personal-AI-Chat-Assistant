import json
import logging
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.db import session as db_session
from src.db.models import (
    AgentWorkspace,
    AgentWorkspaceConversation,
    AgentWorkspaceMembership,
    AIPermission,
    Conversation,
    Message,
    Task,
    User,
)
from src.models.chat_content import text_only_chat_content
from src.services import chat_service, consent_service, usage_service
from src.services.llm import get_llm
from src.websocket.manager import manager

logger = logging.getLogger(__name__)

_WINDOW_MAX_MESSAGES = 30
_WINDOW_MAX_AGE = timedelta(hours=6)
_WINDOW_MAX_CHARS = 4000


def _strip_fence(text: str) -> str:
    return text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def _build_relevance_prompt(content: str) -> str:
    return (
        "Tin nhắn dưới đây có thể liên quan đến một cam kết, cuộc hẹn hoặc deadline cá nhân không, "
        "kể cả đề xuất, xác nhận, từ chối, hủy hoặc đổi giờ cho một đề xuất trước đó? Chào hỏi, "
        "câu hỏi thông thường, kể chuyện quá khứ và đùa giỡn không tính. Nếu chưa chắc, chọn true. "
        'Chỉ trả JSON: {"relevant": true} hoặc {"relevant": false}.\n\n'
        f"Tin nhắn: {content}"
    )


def _parse_relevant(raw: object) -> bool:
    """Fail open so malformed output cannot silently discard a real commitment."""
    if not isinstance(raw, str):
        return True
    try:
        data = json.loads(_strip_fence(raw))
    except ValueError:
        return True
    return not (isinstance(data, dict) and data.get("relevant") is False)


async def _permission_scope(
    db: AsyncSession,
    *,
    conversation: Conversation,
    participant_ids: list[str],
) -> tuple[set[str], set[str]]:
    """Return message-readable ids and proactive-task-eligible ids."""
    participants = set(participant_ids)
    if conversation.type == "group":
        return (participants, participants) if conversation.ai_enabled else (set(), set())

    permissions = (
        (
            await db.execute(
                select(AIPermission).where(AIPermission.conversation_id == conversation.id)
            )
        )
        .scalars()
        .all()
    )
    readable = {
        permission.user_id
        for permission in permissions
        if permission.user_id in participants and permission.contribution_allowed
    }
    eligible = {
        permission.user_id
        for permission in permissions
        if permission.user_id in readable and permission.granted
    }
    return readable, eligible


async def _load_window(
    db: AsyncSession,
    *,
    conversation: Conversation,
) -> tuple[list[tuple[Message, User]], dict[str, str], set[str], bool]:
    participant_ids = await chat_service.get_participant_ids(db, conversation.id)
    readable_ids, eligible_ids = await _permission_scope(
        db,
        conversation=conversation,
        participant_ids=participant_ids,
    )
    is_direct = conversation.type == "direct" and len(participant_ids) == 2

    roster: dict[str, str] = {}
    if participant_ids:
        rows = (
            await db.execute(
                select(User.id, User.display_name).where(
                    User.id.in_(participant_ids),
                    User.is_active.is_(True),
                )
            )
        ).all()
        counts: dict[str, int] = {}
        names: dict[str, str] = {}
        for user_id, display_name in rows:
            names[user_id] = display_name
            counts[display_name] = counts.get(display_name, 0) + 1
        roster = {name: user_id for user_id, name in names.items() if counts[name] == 1}

    if not readable_ids:
        return [], roster, eligible_ids, is_direct

    rows = (
        await db.execute(
            select(Message, User)
            .join(User, User.id == Message.sender_id)
            .where(
                Message.conversation_id == conversation.id,
                Message.sender_id.in_(readable_ids),
                Message.created_at >= datetime.now(UTC) - _WINDOW_MAX_AGE,
            )
            .order_by(Message.created_at.desc())
            .limit(_WINDOW_MAX_MESSAGES)
        )
    ).all()
    window = list(reversed(rows))
    total_chars = sum(len(text_only_chat_content(message.content)) for message, _ in window)
    while total_chars > _WINDOW_MAX_CHARS and len(window) > 1:
        dropped, _ = window.pop(0)
        total_chars -= len(text_only_chat_content(dropped.content))
    return window, roster, eligible_ids, is_direct


def _format_window(window: list[tuple[Message, User]], tz_name: str) -> str:
    timezone = ZoneInfo(tz_name)
    lines: list[str] = []
    for index, (message, sender) in enumerate(window, start=1):
        created_at = message.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        lines.append(
            f"[{index}] {sender.display_name} ({created_at.astimezone(timezone).strftime('%H:%M')}): "
            f"{text_only_chat_content(message.content)}"
        )
    return "\n".join(lines)


def _build_window_prompt(
    window: list[tuple[Message, User]],
    *,
    now: datetime,
    tz_name: str,
    visible_participants: list[str],
    is_direct: bool,
) -> str:
    direct_rule = (
        "Trong hội thoại 1-1, đề xuất làm việc chung của một người mặc nhiên là lời mời dành cho "
        'người còn lại, kể cả không nêu tên; dùng evidence "invited". '
        if is_direct
        else "Trong hội thoại nhóm, chỉ dùng invited khi tin nhắn nêu rõ tên người được mời. "
    )
    return (
        "Phân tích đoạn chat và tìm cam kết, cuộc hẹn hoặc deadline cá nhân. Chỉ trả JSON đúng dạng "
        '{"commitments":[{"title":string,"due_at":string|null,"proposal_message_index":int,'
        '"cancelled":boolean,"owners":[{"name":string,"evidence":"self"|"confirmed"|'
        '"invited","message_index":int}]}]}. Không có thì trả {"commitments":[]}.\n\n'
        f"Người được phép dùng AI: {', '.join(visible_participants) or '(không có)'}. {direct_rule}\n"
        "Quy tắc:\n"
        "- self: chính người đó tự cam kết; confirmed: chính người đó xác nhận sau đề xuất.\n"
        "- invited chỉ áp dụng cho hoạt động chung, không áp dụng cho việc giao người kia tự làm.\n"
        "- Người giao việc không tự thành owner; im lặng không phải confirmed.\n"
        "- Nếu bị hủy hoặc đổi giờ, trả cancelled=true cho đề xuất cũ.\n"
        f"- Giải quyết thời gian tương đối theo {now.strftime('%A, %Y-%m-%d %H:%M')} ({tz_name}).\n\n"
        f"Đoạn chat:\n{_format_window(window, tz_name)}"
    )


def _strip_name_suffix(name: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()


def _is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _verify_owner(
    claim: object,
    *,
    window: list[tuple[Message, User]],
    roster: dict[str, str],
    eligible_ids: set[str],
    proposal_idx: int,
    is_direct: bool,
) -> str | None:
    if not isinstance(claim, dict):
        return None
    claim_name = str(claim.get("name") or "").strip()
    user_id = roster.get(claim_name)
    if user_id is None:
        core_name = _strip_name_suffix(claim_name).casefold()
        matches = {
            candidate_id
            for name, candidate_id in roster.items()
            if _strip_name_suffix(name).casefold() == core_name
        }
        user_id = matches.pop() if len(matches) == 1 else None
    if user_id is None or user_id not in eligible_ids:
        return None

    message_index = claim.get("message_index")
    if not _is_plain_int(message_index) or not (1 <= message_index <= len(window)):
        return None
    message, _ = window[message_index - 1]
    evidence = claim.get("evidence")
    if evidence not in {"self", "confirmed", "invited"}:
        return None
    if evidence in {"self", "confirmed"} and message.sender_id != user_id:
        return None
    if evidence == "confirmed" and message_index <= proposal_idx:
        return None
    if evidence == "invited":
        if message.sender_id == user_id:
            return None
        if not is_direct and _strip_name_suffix(claim_name).casefold() not in text_only_chat_content(message.content).casefold():
            return None
    return user_id


def _personalize_title(title: str, owner_name: str) -> str:
    return re.sub(rf"\b{re.escape(owner_name)}\b", "tôi", title) if owner_name else title


def _invited_title(title: str, inviter_name: str) -> str:
    suffix = f"(lời mời từ {inviter_name}, chưa xác nhận)" if inviter_name else "(lời mời, chưa xác nhận)"
    return f"{title} {suffix}"


def _parse_due_at(raw: object, tz_name: str) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        due_at = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return due_at if due_at.tzinfo is not None else due_at.replace(tzinfo=ZoneInfo(tz_name))


async def _task_exists(
    db: AsyncSession,
    *,
    owner_id: str,
    conversation_id: str,
    proposal_message_id: str,
) -> bool:
    tasks = (
        (
            await db.execute(
                select(Task).where(
                    Task.owner_id == owner_id,
                    Task.conversation_id == conversation_id,
                    Task.source == "proactive",
                )
            )
        )
        .scalars()
        .all()
    )
    return any(task.source_message_ids and task.source_message_ids[0] == proposal_message_id for task in tasks)


async def _resolve_delivery_workspace_binding(
    db: AsyncSession,
    *,
    conversation_id: str,
    owner_id: str,
) -> str | None:
    """Resolve an explicit Delivery binding for a channel-owned work item.

    A conversation reference alone is not enough: the channel must be mapped
    to one active Product Delivery Agent Workspace and the assignee must still
    be an active member there. Direct/personal conversations therefore remain
    private and unbound.
    """

    return await db.scalar(
        select(AgentWorkspaceConversation.agent_workspace_id)
        .join(
            AgentWorkspace,
            AgentWorkspace.id == AgentWorkspaceConversation.agent_workspace_id,
        )
        .join(
            AgentWorkspaceMembership,
            AgentWorkspaceMembership.agent_workspace_id == AgentWorkspace.id,
        )
        .where(
            AgentWorkspaceConversation.conversation_id == conversation_id,
            AgentWorkspaceConversation.classification == "delivery",
            AgentWorkspace.agent_profile == "product_delivery",
            AgentWorkspace.status == "active",
            AgentWorkspaceMembership.user_id == owner_id,
            AgentWorkspaceMembership.status == "active",
            AgentWorkspaceMembership.business_role.in_(("lead", "member")),
        )
    )


def _task_payload(task: Task) -> dict:
    return {
        "id": task.id,
        "workspace_id": task.workspace_id,
        "conversation_id": task.conversation_id,
        "agent_workspace_id": task.agent_workspace_id,
        "title": task.title,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "auto_reminder_enabled": task.auto_reminder_enabled,
        "priority": task.priority,
        "status": task.status,
        "source": task.source,
        "source_message_ids": task.source_message_ids,
        "consent_scope_hash": task.consent_scope_hash,
        "invalidated_reason": task.invalidated_reason,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }


async def _retract_tasks_for_source(
    db: AsyncSession,
    *,
    conversation_id: str,
    proposal_message_id: str,
) -> None:
    candidates = (
        (
            await db.execute(
                select(Task).where(
                    Task.conversation_id == conversation_id,
                    Task.source == "proactive",
                    Task.status == "suggested",
                )
            )
        )
        .scalars()
        .all()
    )
    tasks = [
        task
        for task in candidates
        if task.source_message_ids and task.source_message_ids[0] == proposal_message_id
    ]
    if not tasks:
        return
    for task in tasks:
        task.status = "dismissed"
    await db.commit()
    for task in tasks:
        await db.refresh(task)
        await manager.broadcast_to_users(
            [task.owner_id],
            {"type": "task_updated", "task": _task_payload(task)},
        )


async def maybe_suggest_task(
    *,
    conversation_id: str,
    sender_id: str,
    content: str,
    message_id: str | None = None,
) -> None:
    """Create consent-scoped task suggestions from a bounded recent conversation window."""
    try:
        content = text_only_chat_content(content)
        if not content:
            return
        async with db_session.async_session_maker() as db:
            conversation = await db.get(Conversation, conversation_id)
            if conversation is None:
                return
            participant_ids = await chat_service.get_participant_ids(db, conversation_id)
            _, eligible_ids = await _permission_scope(
                db,
                conversation=conversation,
                participant_ids=participant_ids,
            )
            if sender_id not in eligible_ids:
                return
            workspace_id = conversation.workspace_id

        if await usage_service.is_over_budget(sender_id):
            return

        settings = get_settings()
        llm = get_llm()
        relevance = await llm.ainvoke(_build_relevance_prompt(content))
        await usage_service.log_usage(
            provider=settings.llm_provider,
            model=settings.model_name,
            usage_metadata=getattr(relevance, "usage_metadata", None),
            user_id=sender_id,
            workspace_id=workspace_id,
        )
        if not _parse_relevant(relevance.content):
            return

        async with db_session.async_session_maker() as db:
            conversation = await db.get(Conversation, conversation_id)
            if conversation is None:
                return
            window, roster, eligible_ids, is_direct = await _load_window(
                db,
                conversation=conversation,
            )
            consent_scope_hash = await consent_service.get_consent_scope_hash(db, conversation_id)
        if not window or (message_id and all(message.id != message_id for message, _ in window)):
            return

        now = datetime.now(ZoneInfo(settings.calendar_timezone))
        visible_participants = [name for name, user_id in roster.items() if user_id in eligible_ids]
        extraction = await llm.ainvoke(
            _build_window_prompt(
                window,
                now=now,
                tz_name=settings.calendar_timezone,
                visible_participants=visible_participants,
                is_direct=is_direct,
            )
        )
        await usage_service.log_usage(
            provider=settings.llm_provider,
            model=settings.model_name,
            usage_metadata=getattr(extraction, "usage_metadata", None),
            user_id=sender_id,
            workspace_id=workspace_id,
        )
        data = json.loads(_strip_fence(extraction.content))
        commitments = data.get("commitments") if isinstance(data, dict) else None
        if not isinstance(commitments, list):
            return

        async with db_session.async_session_maker() as db:
            for commitment in commitments:
                if not isinstance(commitment, dict):
                    continue
                proposal_idx = commitment.get("proposal_message_index")
                if not _is_plain_int(proposal_idx) or not (1 <= proposal_idx <= len(window)):
                    continue
                proposal_message = window[proposal_idx - 1][0]
                if commitment.get("cancelled"):
                    await _retract_tasks_for_source(
                        db,
                        conversation_id=conversation_id,
                        proposal_message_id=proposal_message.id,
                    )
                    continue

                owners = commitment.get("owners")
                if not isinstance(owners, list):
                    continue
                title = str(commitment.get("title") or "").strip()[:200] or "Cam kết mới"
                due_at = _parse_due_at(commitment.get("due_at"), settings.calendar_timezone)
                id_to_name = {user_id: name for name, user_id in roster.items()}
                for claim in owners:
                    owner_id = _verify_owner(
                        claim,
                        window=window,
                        roster=roster,
                        eligible_ids=eligible_ids,
                        proposal_idx=proposal_idx,
                        is_direct=is_direct,
                    )
                    if owner_id is None or await _task_exists(
                        db,
                        owner_id=owner_id,
                        conversation_id=conversation_id,
                        proposal_message_id=proposal_message.id,
                    ):
                        continue

                    evidence_message = window[claim["message_index"] - 1][0]
                    source_message_ids = [proposal_message.id]
                    if evidence_message.id != proposal_message.id:
                        source_message_ids.append(evidence_message.id)
                    if claim.get("evidence") == "invited":
                        inviter = window[claim["message_index"] - 1][1]
                        owner_title = _invited_title(title, inviter.display_name)
                    else:
                        owner_title = _personalize_title(title, id_to_name.get(owner_id, ""))

                    task = Task(
                        workspace_id=workspace_id,
                        owner_id=owner_id,
                        conversation_id=conversation_id,
                        agent_workspace_id=await _resolve_delivery_workspace_binding(
                            db,
                            conversation_id=conversation_id,
                            owner_id=owner_id,
                        ),
                        title=owner_title,
                        due_at=due_at,
                        priority="Medium",
                        source="proactive",
                        source_message_ids=source_message_ids,
                        source_sender_id=evidence_message.sender_id,
                        consent_scope_hash=consent_scope_hash,
                    )
                    db.add(task)
                    await db.commit()
                    await db.refresh(task)
                    await manager.broadcast_to_users(
                        [owner_id],
                        {"type": "task_suggested", "task": _task_payload(task)},
                    )
    except Exception:  # noqa: BLE001 - background detection must never break message delivery
        logger.exception("Proactive commitment detection failed")
