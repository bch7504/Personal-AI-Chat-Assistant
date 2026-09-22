import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.nodes.personal_response_quality_node import personal_response_quality_node


def _report() -> dict:
    return {
        "report_markdown": (
            "## Tổng quan\n- Có 2 task.\n\n"
            "## Việc cần ưu tiên\n1. Task A.\n\n"
            "## Lịch và reminder\n- Google Calendar không có sự kiện.\n\n"
            "## Xung đột và rủi ro\n- Không phát hiện xung đột lịch trực tiếp."
        )
    }


@pytest.mark.asyncio
async def test_quality_node_replaces_raw_timeline_echo_with_business_report():
    result = await personal_response_quality_node(
        {
            "messages": [
                HumanMessage(
                    content=(
                        "Tổng hợp task, reminder và lịch 7 ngày tới; sắp xếp ưu tiên và chỉ ra xung đột"
                    )
                ),
                ToolMessage(
                    content=json.dumps(_report(), ensure_ascii=False),
                    name="get_personal_timeline",
                    tool_call_id="timeline-1",
                ),
                AIMessage(
                    content="- 2026-09-01T03:43:04+07:00 | task | Task A | in_progress"
                ),
            ]
        }
    )

    answer = result["messages"][0].content
    assert "## Việc cần ưu tiên" in answer
    assert "## Xung đột và rủi ro" in answer
    assert "2026-09-01T03:43:04" not in answer
    assert result["metadata"]["personal_response_quality"]["repaired"] is True


@pytest.mark.asyncio
async def test_quality_node_preserves_search_evidence_when_repairing_orbit_plan_query():
    result = await personal_response_quality_node(
        {
            "messages": [
                HumanMessage(
                    content=(
                        "Tìm cam kết ORBIT-PLAN-01, đối chiếu task, reminder, Calendar, "
                        "lập thứ tự ưu tiên và chỉ ra xung đột"
                    )
                ),
                ToolMessage(
                    content="ORBIT-PLAN-01: Cam kết hoàn tất trước 10:00 ngày 02/09/2026.",
                    name="search_messages",
                    tool_call_id="search-1",
                ),
                ToolMessage(
                    content=json.dumps(_report(), ensure_ascii=False),
                    name="get_personal_timeline",
                    tool_call_id="timeline-1",
                ),
                AIMessage(
                    content="- 2026-09-02T10:00:00+07:00 | task | ORBIT-PLAN-01 | pending"
                ),
            ]
        }
    )

    answer = result["messages"][0].content
    assert "## Dữ kiện từ tin nhắn cũ" in answer
    assert "ORBIT-PLAN-01" in answer
    assert "## Việc cần ưu tiên" in answer


@pytest.mark.asyncio
async def test_quality_node_replaces_incomplete_natural_answer_without_duplicate_sections():
    result = await personal_response_quality_node(
        {
            "messages": [
                HumanMessage(content="Sắp xếp task, reminder, lịch và chỉ ra xung đột"),
                ToolMessage(
                    content=json.dumps(_report(), ensure_ascii=False),
                    name="get_personal_timeline",
                    tool_call_id="timeline-1",
                ),
                AIMessage(content="## Tổng quan\nCó 2 task.\n\n## Việc cần ưu tiên\n1. Task A"),
            ]
        }
    )

    answer = result["messages"][0].content
    assert answer.count("## Tổng quan") == 1
    assert answer.count("## Việc cần ưu tiên") == 1
    assert "## Xung đột và rủi ro" in answer


@pytest.mark.asyncio
async def test_quality_node_leaves_complete_natural_answer_unchanged():
    answer = (
        "## Tổng quan\nĐã đối chiếu.\n"
        "## Việc cần ưu tiên\nTask A.\n"
        "## Lịch và reminder\nCalendar trống.\n"
        "## Xung đột và rủi ro\nKhông phát hiện xung đột."
    )
    result = await personal_response_quality_node(
        {
            "messages": [
                HumanMessage(content="Sắp xếp task, reminder, lịch và chỉ ra xung đột"),
                ToolMessage(
                    content=json.dumps(_report(), ensure_ascii=False),
                    name="get_personal_timeline",
                    tool_call_id="timeline-1",
                ),
                AIMessage(content=answer),
            ]
        }
    )

    assert "messages" not in result
    assert result["metadata"]["personal_response_quality"]["passed"] is True


@pytest.mark.asyncio
async def test_quality_node_builds_report_when_model_returns_no_text_after_timeline_tool():
    result = await personal_response_quality_node(
        {
            "messages": [
                HumanMessage(content="Sắp xếp task, reminder, lịch và chỉ ra xung đột"),
                ToolMessage(
                    content=json.dumps(_report(), ensure_ascii=False),
                    name="get_personal_timeline",
                    tool_call_id="timeline-1",
                ),
                AIMessage(content=""),
            ]
        }
    )

    assert "## Tổng quan" in result["messages"][0].content
    assert result["metadata"]["personal_response_quality"]["missing_answer"] is True


@pytest.mark.asyncio
async def test_quality_node_stops_without_guessing_when_required_message_evidence_is_missing():
    result = await personal_response_quality_node(
        {
            "messages": [
                HumanMessage(
                    content=(
                        "Tìm cam kết ORBIT-PLAN-01 và dùng deadline để đối chiếu task, reminder, "
                        "Calendar. Không được tự đoán."
                    )
                ),
                ToolMessage(
                    content="No authorized messages matched 'ORBIT-PLAN-01'.",
                    name="search_messages",
                    tool_call_id="search-1",
                ),
                AIMessage(content="Tôi không tìm thấy marker nhưng đây là một số task khác..."),
            ]
        }
    )

    answer = result["messages"][0].content
    assert "## Kết quả xác minh" in answer
    assert "ORBIT-PLAN-01" in answer
    assert "không tự đoán dữ kiện thiếu" in answer
    assert "Không đề xuất hoặc tạo reminder" in answer
    assert "task khác..." not in answer
    assert result["metadata"]["personal_response_quality"]["evidence_missing"] is True
