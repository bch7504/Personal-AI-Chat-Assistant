import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agents.graph import route_after_planner
from src.agents.nodes.planner_node import planner_node


@pytest.mark.asyncio
async def test_planner_node_appends_ai_message(monkeypatch, fake_llm_factory):
    reply = AIMessage(content="Hi there!")
    llm = fake_llm_factory([reply])
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)

    result = await planner_node({"messages": [HumanMessage(content="hello")]})

    assert result == {"messages": [reply]}


@pytest.mark.asyncio
async def test_planner_recovers_plaintext_confirmation_into_calendar_tool_call(
    monkeypatch,
    fake_llm_factory,
):
    invalid_preview = AIMessage(
        content='Lịch đã sẵn sàng. Vui lòng trả lời “Xác nhận” để tạo lịch.'
    )
    tool_call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "create_calendar_event",
                "args": {
                    "summary": "Daily sync",
                    "start_iso": "2026-09-01T10:00:00+07:00",
                    "end_iso": "2026-09-01T10:30:00+07:00",
                },
                "id": "calendar-recovery",
            }
        ],
    )
    llm = fake_llm_factory([invalid_preview, tool_call])
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)

    result = await planner_node(
        {
            "messages": [HumanMessage(content="Đặt lịch Daily sync lúc 10 giờ sáng mai trong 30 phút")],
            "personal_intent": "calendar",
            "personal_plan": {"status": "ready", "steps": []},
        }
    )

    assert result["messages"] == [tool_call]
    assert result["metadata"]["planner_contract_recovery"]["recovered"] is True
    assert len(llm.invocations) == 2


@pytest.mark.asyncio
async def test_planner_node_captures_llm_error(monkeypatch):
    def broken_get_llm():
        raise RuntimeError("boom")

    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", broken_get_llm)

    result = await planner_node({"messages": [HumanMessage(content="hello")]})

    assert result == {"error": "Dịch vụ AI tạm thời không khả dụng. Vui lòng thử lại sau."}


def test_route_after_planner_ends_on_error():
    assert route_after_planner({"error": "boom", "messages": []}) == "__end__"


def test_route_after_planner_routes_to_tools_on_tool_call():
    state = {
        "messages": [
            HumanMessage(content="hi"),
            AIMessage(content="", tool_calls=[{"name": "summarize_conversation", "args": {}, "id": "1"}]),
        ]
    }
    assert route_after_planner(state) == "tools"


def test_route_after_planner_ends_on_plain_reply():
    state = {"messages": [HumanMessage(content="hi"), AIMessage(content="done")]}
    assert route_after_planner(state) == "__end__"
