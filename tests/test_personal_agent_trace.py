import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.models.schemas import InterruptPayload
from src.services.personal_agent_trace_service import build_process_steps, build_process_summary


def test_process_summary_reports_observable_task_tool_activity_without_raw_output():
    messages = [
        HumanMessage(content="Deadline nào cần ưu tiên?"),
        AIMessage(
            content="",
            tool_calls=[{"name": "list_my_tasks", "args": {}, "id": "call-1"}],
        ),
        ToolMessage(content="Confidential task title", name="list_my_tasks", tool_call_id="call-1"),
        AIMessage(content="Có hai task cần ưu tiên."),
    ]

    summary = build_process_summary(
        messages,
        {"query_route": {"intent": "task_management"}},
    )

    assert "công việc và deadline" in summary
    assert "danh sách task được giao" in summary
    assert "Confidential task title" not in summary

    steps = build_process_steps(messages, {"query_route": {"intent": "task_management"}})
    assert steps == [
        "Nhận diện câu hỏi về công việc và deadline",
        "Kiểm tra danh sách task được giao",
        "Tổng hợp kết quả và soạn câu trả lời",
    ]
    assert all("Confidential task title" not in step for step in steps)


def test_process_summary_describes_direct_answer_without_claiming_a_tool_call():
    summary = build_process_summary(
        [HumanMessage(content="Xin chào"), AIMessage(content="Chào sếp!")],
        {"query_route": {"intent": "small_talk"}},
    )

    assert summary == "Đã nhận diện đây là trao đổi ngắn và trả lời trực tiếp."


def test_process_summary_describes_deterministic_capability_answer():
    summary = build_process_summary(
        [
            HumanMessage(content="Bạn có thể giúp tôi những việc gì?"),
            AIMessage(content="Mình là Orbit."),
        ],
        {"query_route": {"intent": "capability_help"}},
    )

    assert summary == "Đã nhận diện câu hỏi về khả năng của Orbit và trả lời trực tiếp."


def test_clarification_trace_reports_planning_instead_of_fallback_answer():
    metadata = {
        "query_route": {"intent": "calendar", "routing_strategy": "deterministic"},
        "personal_plan": {
            "status": "needs_clarification",
            "steps": ["Kiểm tra xung đột trên Google Calendar"],
        },
    }
    messages = [
        HumanMessage(content="Đặt lịch họp với team"),
        AIMessage(content="Sếp muốn họp vào ngày và giờ nào?"),
    ]

    summary = build_process_summary(messages, metadata)
    steps = build_process_steps(messages, metadata)

    assert "lập kế hoạch" in summary
    assert "bổ sung dữ kiện" in summary
    assert "trả lời trực tiếp" not in summary
    assert steps == [
        "Nhận diện câu hỏi về lịch",
        "Lập kế hoạch cho hành động được yêu cầu",
        "Kiểm tra các dữ kiện bắt buộc",
        "Phát hiện thông tin còn thiếu và hỏi người dùng bổ sung",
    ]


@pytest.mark.parametrize(
    "interrupt_type",
    ["reminder_update", "reminder_cancel", "reminder_snooze"],
)
def test_reminder_lifecycle_interrupts_are_valid_api_payloads(interrupt_type):
    payload = InterruptPayload(type=interrupt_type, draft={"reminder_id": "reminder-1"})
    assert payload.type == interrupt_type
