from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from src.agents import graph as agent_graph


def _config():
    return {"configurable": {"thread_id": str(uuid4())}}


@pytest.mark.asyncio
async def test_agent_basic_flow_no_tool_call(monkeypatch, fake_llm_factory):
    reply = AIMessage(content="Just a plain reply, no tools needed.")
    llm = fake_llm_factory([reply])
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)

    result = await agent_graph.agent.ainvoke({"messages": [HumanMessage(content="Hello")]}, _config())

    assert "__interrupt__" not in result
    assert result["messages"][-1].content == "Just a plain reply, no tools needed."


@pytest.mark.asyncio
async def test_capability_help_is_answered_without_calling_llm(monkeypatch):
    def llm_must_not_run(*args, **kwargs):
        raise AssertionError("capability help must not call an LLM")

    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", llm_must_not_run)
    monkeypatch.setattr(
        "src.agents.nodes.guardrail_node.domain_classifier_service.classify_domain_request",
        llm_must_not_run,
    )

    result = await agent_graph.agent.ainvoke(
        {"messages": [HumanMessage(content="Bạn có thể giúp tôi những việc gì?")]},
        _config(),
    )

    assert result["guardrail_blocked"] is False
    assert result["personal_intent"] == "capability_help"
    assert result["routing_strategy"] == "deterministic"
    assert result["metadata"]["capability_response"]["source"] == "deterministic"
    assert "task/deadline" in result["messages"][-1].content
    assert "Google Calendar" in result["messages"][-1].content
    assert "xác nhận" in result["messages"][-1].content


@pytest.mark.asyncio
async def test_typed_confirmation_continues_calendar_intent_from_short_term_history(
    monkeypatch,
    fake_llm_factory,
):
    from unittest.mock import AsyncMock

    from src.services import calendar_service

    monkeypatch.setattr(calendar_service, "find_conflicts", AsyncMock(return_value=[]))
    llm = fake_llm_factory(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "create_calendar_event",
                        "args": {
                            "summary": "[E2E] Daily sync",
                            "start_iso": "2026-09-01T10:00:00+07:00",
                            "end_iso": "2026-09-01T10:30:00+07:00",
                        },
                        "id": "short-term-calendar",
                    }
                ],
            )
        ]
    )
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)

    result = await agent_graph.agent.ainvoke(
        {
            "messages": [
                HumanMessage(content="Đặt lịch Daily sync lúc 10 giờ sáng mai trong 30 phút"),
                AIMessage(content='Vui lòng trả lời “Xác nhận” để tạo lịch.'),
                HumanMessage(content="xác nhận"),
            ],
            "personal_intent": "calendar",
            "user_id": "user-1",
            "workspace_id": "workspace-1",
        },
        _config(),
    )

    assert result["__interrupt__"][0].value["type"] == "calendar_event"
    assert result["metadata"]["query_route"]["reason_code"] == "THREAD_FOLLOW_UP_INTENT"


@pytest.mark.asyncio
async def test_agent_interrupt_then_resume_round_trip(monkeypatch, fake_llm_factory):
    """Drive the full interrupt -> resume round trip through the compiled graph,
    using create_calendar_event as the tool that pauses for confirmation."""

    def _final_message(state):
        last = state["messages"][-1]
        assert isinstance(last, ToolMessage)
        return AIMessage(content=f"final:{last.content}")

    responses = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "create_calendar_event",
                    "args": {
                        "summary": "Sync",
                        "start_iso": "2026-08-01T10:00:00",
                        "end_iso": "2026-08-01T10:30:00",
                    },
                    "id": "call_1",
                }
            ],
        )
    ]
    llm = fake_llm_factory(responses)
    real_ainvoke = llm.ainvoke

    async def ainvoke(messages):
        if llm._responses:
            return await real_ainvoke(messages)
        return _final_message({"messages": messages})

    llm.ainvoke = ainvoke
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)

    fake_service = None
    from unittest.mock import AsyncMock, MagicMock

    from src.services import calendar_service, reminder_service

    fake_service = MagicMock()
    fake_service.events.return_value.insert.return_value.execute.return_value = {"id": "evt-1"}
    monkeypatch.setattr(calendar_service, "get_calendar_service", lambda: fake_service)
    monkeypatch.setattr(calendar_service, "authorize_calendar_access", AsyncMock())
    monkeypatch.setattr(calendar_service, "broadcast_change", AsyncMock())
    monkeypatch.setattr(reminder_service, "reconcile_calendar_event_reminder", AsyncMock())

    config = _config()
    result = await agent_graph.agent.ainvoke(
        {
            "messages": [HumanMessage(content="book a 30 minute sync tomorrow at 10:00")],
            "user_id": "user-1",
            "workspace_id": "workspace-1",
        },
        config,
    )
    assert result["__interrupt__"][0].value["type"] == "calendar_event"

    result2 = await agent_graph.agent.ainvoke(Command(resume={"approved": True}), config)
    assert "Event created" in result2["messages"][-1].content


@pytest.mark.asyncio
async def test_terminal_tool_ends_without_second_llm_call(monkeypatch, fake_llm_factory):
    """summarize_conversation's own output is the final answer - the graph must not loop back
    to planner for a second LLM call to 'relay' it (that call is what caused earlier bugs where
    the model either repeated the summary in 3 formats or hallucinated a bogus tool call)."""
    from unittest.mock import AsyncMock

    from src.agents.tools import summarize_tool

    fake_tool_llm = AsyncMock()
    fake_tool_llm.ainvoke.return_value = AsyncMock(content="A short summary.")
    monkeypatch.setattr(summarize_tool, "get_llm", lambda: fake_tool_llm)

    planner_llm = fake_llm_factory(
        [AIMessage(content="", tool_calls=[{"name": "summarize_conversation", "args": {}, "id": "call_1"}])]
    )
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: planner_llm)

    result = await agent_graph.agent.ainvoke(
        {"messages": [HumanMessage(content="Summarize this.")], "context": "Alice: hi\nBob: hello"}, _config()
    )

    assert result["messages"][-1].content == "A short summary."
    assert not planner_llm._responses  # planner was called exactly once, not looped back into
