"""Deterministic Personal Agent planning and action-slot validation."""

from __future__ import annotations

import re

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.state import AgentState
from src.services.personal_query_router_service import normalize_for_routing

_CALENDAR_CREATE_RE = re.compile(r"\b(dat lich|tao su kien|schedule|book|create).{0,50}\b(hop|meeting|event|call|lich)\b")
_REMINDER_CREATE_RE = re.compile(r"\b(nhac toi|nhac nho|remind me|set a reminder|create a reminder|tao reminder)\b")
_DATE_RE = re.compile(
    r"\b(hom nay|ngay mai|mai|tuan sau|today|tomorrow|next week|"
    r"thu [2-7]|chu nhat|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|"
    r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b"
)
_TIME_RE = re.compile(
    r"\b\d{1,2}h\d{0,2}\b|\b(?:luc|vao|at)\s+\d{1,2}(?:\s+\d{1,2})?\b|"
    r"\b(sang|chieu|buoi toi|morning|afternoon|evening|noon)\b"
)
_DURATION_RE = re.compile(
    r"\b\d+\s*(phut|minute|minutes|gio|hour|hours)\b|\b(den|until)\s+\d{1,2}"
)


def _latest_turn(state: AgentState) -> tuple[str, str]:
    messages = state.get("messages", [])
    latest_index = next(
        (index for index in range(len(messages) - 1, -1, -1) if isinstance(messages[index], HumanMessage)),
        None,
    )
    if latest_index is None:
        return "", ""
    previous_assistant = next(
        (
            str(message.content)
            for message in reversed(messages[:latest_index])
            if isinstance(message, AIMessage) and message.content
        ),
        "",
    )
    return str(messages[latest_index].content), previous_assistant


def _plan_steps(intent: str, normalized: str) -> list[str]:
    if intent == "task_management":
        steps = ["Đọc các task đang được giao và deadline hiện tại"]
        if re.search(r"\b(tin nhan|message|chat|cam ket|ma)\b", normalized):
            steps.extend(
                [
                    "Tìm dữ kiện trong tin nhắn cũ được cấp quyền",
                    "Xác minh deadline từ bằng chứng, không tự đoán dữ kiện thiếu",
                ]
            )
        if re.search(r"\b(lich|calendar|ke hoach|plan|conflict|xung dot)\b", normalized):
            steps.append("Đối chiếu với Google Calendar")
        if re.search(r"\b(reminder|nhac viec|nhac nho|nhac truoc)\b", normalized):
            steps.append("Đối chiếu reminder và gộp reminder liên kết vào task tương ứng")
        steps.append("Đánh giá ưu tiên, trạng thái chặn và rủi ro quá hạn")
        if re.search(r"\b(conflict|xung dot|trung lich|chong lich)\b", normalized):
            steps.append("Phân biệt xung đột lịch trực tiếp với rủi ro deadline dồn sát")
        if re.search(r"\b(de xuat|goi y)\b.{0,80}\b(reminder|nhac)\b", normalized):
            steps.append("Đề xuất reminder còn thiếu nhưng không tự tạo khi chưa xác nhận")
    elif intent == "calendar":
        if _CALENDAR_CREATE_RE.search(normalized):
            steps = [
                "Xác nhận đủ thời gian và nội dung sự kiện",
                "Kiểm tra xung đột trên Google Calendar",
                "Chuẩn bị đề xuất để người dùng xác nhận",
            ]
        else:
            steps = ["Xác định khoảng lịch cần tra cứu", "Đọc dữ liệu Google Calendar"]
    elif intent == "reminder":
        steps = [
            "Xác nhận nội dung và thời điểm cần nhắc",
            "Kiểm tra reminder liên quan",
            "Chuẩn bị thay đổi để người dùng xác nhận",
        ]
    elif intent == "chat_analysis":
        steps = ["Xác định phạm vi hội thoại được cấp quyền", "Tìm dữ kiện trong tin nhắn phù hợp"]
    elif intent == "memory_search":
        steps = ["Tìm Personal Memory còn hiệu lực", "Áp dụng preference phù hợp"]
    elif intent == "people_search":
        steps = ["Tìm ngữ cảnh cộng tác được cấp quyền", "Đối chiếu người liên quan"]
    else:
        steps = ["Phân tích yêu cầu và xác định nguồn dữ liệu cần thiết"]
    steps.append("Kiểm tra kết quả và tổng hợp câu trả lời")
    return steps


def _clarification_requirements(
    intent: str,
    normalized: str,
    previous_assistant: str,
) -> tuple[list[str], str]:
    # A short answer following an earlier question is slot-filling context, not a fresh command.
    # A repeated/new action command must still be validated; otherwise revisiting an existing
    # thread can incorrectly bypass clarification merely because the prior assistant used "?".
    is_fresh_action = bool(
        _CALENDAR_CREATE_RE.search(normalized) or _REMINDER_CREATE_RE.search(normalized)
    )
    if previous_assistant.rstrip().endswith("?") and not is_fresh_action:
        return [], ""
    has_date = bool(_DATE_RE.search(normalized))
    has_time = bool(_TIME_RE.search(normalized))
    if intent == "calendar" and _CALENDAR_CREATE_RE.search(normalized):
        missing = []
        if not has_date:
            missing.append("ngày")
        if not has_time:
            missing.append("giờ bắt đầu")
        if not _DURATION_RE.search(normalized):
            missing.append("thời lượng")
        if missing:
            readable = ", ".join(missing[:-1]) + (f" và {missing[-1]}" if len(missing) > 1 else missing[0])
            return missing, f"Bạn cho mình biết {readable} của cuộc họp nhé?"
    if intent == "reminder" and _REMINDER_CREATE_RE.search(normalized):
        missing = []
        if not has_date:
            missing.append("ngày cần nhắc")
        if not has_time:
            missing.append("giờ cần nhắc")
        if missing:
            readable = ", ".join(missing[:-1]) + (f" và {missing[-1]}" if len(missing) > 1 else missing[0])
            return missing, f"Bạn muốn Orbit nhắc vào {readable} nào?"
    return [], ""


async def personal_plan_node(state: AgentState) -> dict:
    """Create a bounded server-owned execution plan and clarify missing write-action slots."""

    latest, previous_assistant = _latest_turn(state)
    normalized = normalize_for_routing(latest)
    intent = state.get("personal_intent", "general_work")
    steps = _plan_steps(intent, normalized)
    missing_fields, fallback_question = _clarification_requirements(
        intent,
        normalized,
        previous_assistant,
    )
    plan = {
        "goal": latest[:500],
        "intent": intent,
        "steps": steps,
        "status": "needs_clarification" if missing_fields else "ready",
        "missing_fields": missing_fields,
        "clarification_fallback": fallback_question,
        "max_tool_calls": 8,
    }
    result: dict = {
        "personal_plan": plan,
        "action_requires_clarification": bool(missing_fields),
        "metadata": {**state.get("metadata", {}), "personal_plan": plan},
    }
    return result


async def tool_budget_exhausted_node(state: AgentState) -> dict:
    """Stop a runaway tool loop with a useful partial-result response."""

    return {
        "messages": [
            AIMessage(
                content=(
                    "Em đã dừng sau khi đạt giới hạn công cụ an toàn của một lượt xử lý. "
                    "Sếp có thể thu hẹp phạm vi hoặc chia yêu cầu thành hai phần để em tiếp tục."
                )
            )
        ],
        "metadata": {
            **state.get("metadata", {}),
            "tool_budget": {"exhausted": True},
        },
    }
