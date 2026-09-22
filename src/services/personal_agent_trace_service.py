"""Safe, user-facing summaries of observable Personal Agent activity."""

from __future__ import annotations

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

_INTENT_LABELS = {
    "capability_help": "câu hỏi về khả năng của Orbit",
    "memory_write": "yêu cầu ghi nhớ",
    "memory_search": "câu hỏi về Personal Memory",
    "task_management": "câu hỏi về công việc và deadline",
    "calendar": "câu hỏi về lịch",
    "reminder": "yêu cầu nhắc nhở",
    "chat_analysis": "yêu cầu phân tích hội thoại",
    "people_search": "câu hỏi về người cộng tác",
    "small_talk": "trao đổi ngắn",
    "general_work": "yêu cầu công việc",
    "unclear": "yêu cầu cần làm rõ",
}

_TOOL_LABELS = {
    "list_my_tasks": "danh sách task được giao",
    "get_personal_timeline": "timeline từ Tasks, Reminders và Calendar",
    "list_calendar_events": "Google Calendar",
    "create_calendar_event": "đề xuất tạo sự kiện Calendar",
    "update_calendar_event": "đề xuất cập nhật sự kiện Calendar",
    "delete_calendar_event": "đề xuất xóa sự kiện Calendar",
    "list_reminders": "các reminder đang hoạt động",
    "create_reminder": "đề xuất tạo reminder",
    "update_reminder": "đề xuất cập nhật reminder",
    "cancel_reminder": "đề xuất hủy reminder",
    "snooze_reminder": "đề xuất hoãn reminder",
    "search_my_memories": "Personal Memory",
    "save_personal_memory": "Personal Memory",
    "search_people_context": "ngữ cảnh cộng tác",
    "search_messages": "tin nhắn được cấp quyền",
    "summarize_conversation": "hội thoại được cấp quyền",
    "extract_tasks": "hội thoại để trích xuất task",
    "check_request_policy": "phạm vi hỗ trợ của Orbit",
}


def _latest_turn(messages: list[AnyMessage]) -> list[AnyMessage]:
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return messages[index:]
    return messages


def _tool_names(messages: list[AnyMessage]) -> list[str]:
    names: list[str] = []
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                name = str(call.get("name") or "").strip()
                if name and name not in names:
                    names.append(name)
        elif isinstance(message, ToolMessage):
            name = str(message.name or "").strip()
            if name and name not in names:
                names.append(name)
    return names


def build_process_summary(messages: list[AnyMessage], metadata: dict | None = None) -> str:
    """Describe routing and tool use without exposing model chain-of-thought or raw data."""

    values = metadata or {}
    route = values.get("query_route") if isinstance(values.get("query_route"), dict) else {}
    intent = str(route.get("intent") or "general_work")
    intent_label = _INTENT_LABELS.get(intent, _INTENT_LABELS["general_work"])
    plan = values.get("personal_plan")
    if isinstance(plan, dict) and plan.get("status") == "needs_clarification":
        return (
            f"Đã nhận diện {intent_label}, lập kế hoạch và phát hiện cần bổ sung dữ kiện "
            "bắt buộc trước khi gọi công cụ."
        )
    labels: list[str] = []
    for name in _tool_names(_latest_turn(messages)):
        label = _TOOL_LABELS.get(name, "một công cụ được cấp quyền")
        if label not in labels:
            labels.append(label)

    memory_write = values.get("memory_write")
    if intent == "memory_write" and isinstance(memory_write, dict):
        return (
            "Đã nhận diện yêu cầu ghi nhớ và cập nhật Personal Memory."
            if memory_write.get("saved")
            else "Đã kiểm tra yêu cầu ghi nhớ nhưng không lưu vì không đáp ứng chính sách Memory."
        )

    guardrail = values.get("guardrail")
    if isinstance(guardrail, dict) and guardrail.get("allowed") is False:
        return "Đã kiểm tra phạm vi an toàn và dừng trước khi sử dụng dữ liệu hoặc công cụ."

    if labels:
        visible = labels[:3]
        sources = ", ".join(visible[:-1]) + (" và " if len(visible) > 1 else "") + visible[-1]
        suffix = "" if len(labels) <= 3 else " cùng các nguồn liên quan"
        return f"Đã nhận diện {intent_label}, kiểm tra {sources}{suffix} rồi tổng hợp câu trả lời."

    if intent == "capability_help":
        return "Đã nhận diện câu hỏi về khả năng của Orbit và trả lời trực tiếp."
    if intent == "small_talk":
        return "Đã nhận diện đây là trao đổi ngắn và trả lời trực tiếp."
    return f"Đã nhận diện {intent_label} và trả lời trực tiếp, không cần gọi thêm công cụ."


def build_process_steps(messages: list[AnyMessage], metadata: dict | None = None) -> list[str]:
    """Return a compact activity timeline grounded in routing and tool-call metadata."""

    values = metadata or {}
    route = values.get("query_route") if isinstance(values.get("query_route"), dict) else {}
    intent = str(route.get("intent") or "general_work")
    intent_label = _INTENT_LABELS.get(intent, _INTENT_LABELS["general_work"])
    plan = values.get("personal_plan")

    if isinstance(plan, dict) and plan.get("status") == "needs_clarification":
        return [
            f"Nhận diện {intent_label}",
            "Lập kế hoạch cho hành động được yêu cầu",
            "Kiểm tra các dữ kiện bắt buộc",
            "Phát hiện thông tin còn thiếu và hỏi người dùng bổ sung",
        ]

    guardrail = values.get("guardrail")
    if isinstance(guardrail, dict) and guardrail.get("allowed") is False:
        return [
            f"Nhận diện {intent_label}",
            "Kiểm tra phạm vi an toàn và dừng xử lý",
        ]

    memory_write = values.get("memory_write")
    if intent == "memory_write" and isinstance(memory_write, dict):
        outcome = (
            "Cập nhật Personal Memory"
            if memory_write.get("saved")
            else "Kiểm tra chính sách và không lưu Memory"
        )
        return [f"Nhận diện {intent_label}", outcome, "Tổng hợp kết quả trả lời"]

    steps = [f"Nhận diện {intent_label}"]
    if isinstance(plan, dict) and isinstance(plan.get("steps"), list):
        for planned_step in plan["steps"][:5]:
            planned_step = str(planned_step).strip()
            if planned_step and planned_step not in steps:
                steps.append(planned_step)
    for name in _tool_names(_latest_turn(messages)):
        label = _TOOL_LABELS.get(name, "một công cụ được cấp quyền")
        step = f"Kiểm tra {label}"
        if step not in steps:
            steps.append(step)
    steps.append("Tổng hợp kết quả và soạn câu trả lời")
    return steps


def message_process_summary(message: AIMessage) -> str:
    value = message.additional_kwargs.get("orbit_process_summary", "")
    return str(value).strip()


def message_process_steps(message: AIMessage) -> list[str]:
    value = message.additional_kwargs.get("orbit_process_steps", [])
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
