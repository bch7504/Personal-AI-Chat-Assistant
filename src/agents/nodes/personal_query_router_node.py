"""Explicit Personal Agent query routing and deterministic Memory writes."""

from __future__ import annotations

from fastapi import HTTPException
from langchain_core.messages import AIMessage, HumanMessage

from src.agents.state import AgentState
from src.db import session as db_session
from src.db.models import User
from src.models.memory_schemas import MemoryCreateRequest
from src.services import memory_service
from src.services.personal_query_router_service import (
    PersonalQueryRoute,
    classify_personal_query,
    extract_explicit_memory_drafts,
)

_CAPABILITY_RESPONSE = """Mình là Orbit, trợ lý công việc cá nhân. Mình có thể giúp bạn:

- Xem, tổng hợp và ưu tiên task/deadline được giao cho bạn.
- Kiểm tra Google Calendar, phát hiện xung đột và đề xuất tạo/sửa/xóa sự kiện.
- Tạo, cập nhật, hoãn hoặc hủy reminder.
- Tóm tắt hội thoại được cấp quyền, tìm cam kết, deadline và trích xuất action item.
- Ghi nhớ các preference bạn nói rõ, như cách xưng hô hoặc phong cách trả lời.
- Tìm ngữ cảnh cộng tác và người liên quan trong phạm vi dữ liệu bạn được phép truy cập.

Các thao tác làm thay đổi Calendar hoặc reminder luôn cần bạn xác nhận trước. Bạn có thể bắt đầu bằng câu như: “Tổng hợp task và lịch của tôi hôm nay” hoặc “Đặt lịch họp team lúc 10 giờ sáng mai trong 30 phút”."""


def _latest_user_text(state: AgentState) -> str:
    return next(
        (
            str(message.content)
            for message in reversed(state.get("messages", []))
            if isinstance(message, HumanMessage)
        ),
        "",
    )


async def personal_query_router_node(state: AgentState) -> dict:
    """Classify the allowed request before tool planning, without changing authorization."""

    guardrail_metadata = state.get("metadata", {}).get("guardrail", {})
    semantic = guardrail_metadata.get("semantic") or {}
    route = classify_personal_query(
        _latest_user_text(state),
        semantic_intent=semantic.get("intent") if semantic.get("decision") == "allow" else None,
    )
    previous_intent = state.get("personal_intent")
    guardrail_category = guardrail_metadata.get("category")
    resumable_intents = {
        "calendar",
        "reminder",
        "task_management",
        "chat_analysis",
        "memory_search",
        "people_search",
    }
    if (
        guardrail_category == "work_follow_up"
        and route.intent in {"general_work", "unclear"}
        and previous_intent in resumable_intents
    ):
        route = PersonalQueryRoute(
            intent=previous_intent,
            routing_strategy="deterministic",
            confidence=1.0,
            reason_code="THREAD_FOLLOW_UP_INTENT",
        )
    return {
        "personal_intent": route.intent,
        "routing_strategy": route.routing_strategy,
        "metadata": {
            **state.get("metadata", {}),
            "query_route": {
                "agent": "personal",
                "intent": route.intent,
                "routing_strategy": route.routing_strategy,
                "confidence": route.confidence,
                "reason_code": route.reason_code,
            },
        },
    }


async def personal_capability_response_node(state: AgentState) -> dict:
    """Answer product-capability questions reliably without calling a provider."""

    return {
        "messages": [AIMessage(content=_CAPABILITY_RESPONSE)],
        "metadata": {
            **state.get("metadata", {}),
            "capability_response": {"source": "deterministic", "version": "personal-v1"},
        },
    }


async def save_explicit_personal_memory_node(state: AgentState) -> dict:
    """Persist an explicit preference without asking the planner to reinterpret it."""

    user_id = state.get("user_id")
    workspace_id = state.get("workspace_id")
    if not user_id or not workspace_id:
        response = "Không thể xác định Personal Space để lưu Memory."
        return {
            "error": response,
            "messages": [AIMessage(content=response)],
            "metadata": {
                **state.get("metadata", {}),
                "memory_write": {"saved": False, "reason": "personal_space_unavailable"},
            },
        }

    drafts = extract_explicit_memory_drafts(_latest_user_text(state))
    try:
        async with db_session.async_session_maker() as db:
            user = await db.get(User, user_id)
            if user is None or not user.is_active:
                raise ValueError("Authenticated user is unavailable")
            for draft in drafts:
                await memory_service.upsert_personal_memory(
                    db,
                    user,
                    workspace_id,
                    MemoryCreateRequest(
                        workspace_id=workspace_id,
                        category=draft.category,
                        title=draft.title,
                        detail=draft.detail,
                        memory_type="preference",
                        confidence=1.0,
                    ),
                    replace_by_title=draft.title != "Ghi nhớ do người dùng yêu cầu",
                )
    except HTTPException as exc:
        response = (
            "Tôi không thể lưu nội dung này vào Memory vì Memory không được chứa thông tin "
            "đăng nhập, bí mật hoặc dữ liệu cá nhân nhạy cảm."
        )
        return {
            "messages": [AIMessage(content=response)],
            "metadata": {
                **state.get("metadata", {}),
                "memory_write": {"saved": False, "reason": str(exc.detail)},
            },
        }

    address = next((draft for draft in drafts if draft.title == "Cách xưng hô"), None)
    if address is not None:
        alias = address.detail.removeprefix("Gọi người dùng là “").removesuffix("”.")
        other_details = [draft.detail for draft in drafts if draft is not address]
        fallback_response = f"Đã ghi nhớ. Từ giờ tôi sẽ gọi bạn là “{alias}”."
        if other_details:
            fallback_response += f" Tôi cũng đã ghi nhớ: {' '.join(other_details)}"
    else:
        details = " và ".join(draft.detail for draft in drafts)
        alias = None
        other_details = [draft.detail for draft in drafts]
        fallback_response = f"Đã ghi nhớ trong Personal Memory: {details}"
    return {
        "metadata": {
            **state.get("metadata", {}),
            "memory_write": {
                "saved": True,
                "count": len(drafts),
                "acknowledgement_facts": {
                    "address_alias": alias,
                    "other_details": other_details,
                    "fallback_response": fallback_response,
                },
            },
        },
    }
