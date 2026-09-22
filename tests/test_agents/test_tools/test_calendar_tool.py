from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from src.agents import graph as agent_graph
from src.services import calendar_service, reminder_service


def _config():
    return {"configurable": {"thread_id": str(uuid4())}}


def _agent_input(message):
    return {"messages": [HumanMessage(content=message)], "user_id": "user-1", "workspace_id": "workspace-1"}


def _allow_calendar(monkeypatch):
    monkeypatch.setattr(calendar_service, "authorize_calendar_access", AsyncMock())
    monkeypatch.setattr(calendar_service, "broadcast_change", AsyncMock())
    monkeypatch.setattr(
        reminder_service,
        "reconcile_calendar_event_reminder",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        reminder_service,
        "remove_calendar_event_reminder",
        AsyncMock(return_value=None),
    )


def _script_tool_call(fake_llm_factory, tool_name: str, args: dict):
    """First planner turn calls the tool; second turn (after the ToolMessage) replies."""

    def _final_message(state):
        last = state["messages"][-1]
        assert isinstance(last, ToolMessage)
        return AIMessage(content=f"final:{last.content}")

    responses = [
        AIMessage(content="", tool_calls=[{"name": tool_name, "args": args, "id": "call_1"}]),
    ]
    llm = fake_llm_factory(responses)
    real_ainvoke = llm.ainvoke

    async def ainvoke(messages):
        if llm._responses:
            return await real_ainvoke(messages)
        return _final_message({"messages": messages})

    llm.ainvoke = ainvoke
    return llm


@pytest.mark.asyncio
async def test_create_calendar_event_interrupts_then_creates(monkeypatch, fake_llm_factory):
    _allow_calendar(monkeypatch)
    fake_service = MagicMock()
    fake_service.events.return_value.insert.return_value.execute.return_value = {
        "id": "evt-abc",
        "htmlLink": "https://calendar.google.com/event?eid=abc",
    }
    fake_service.events.return_value.list.return_value.execute.return_value = {"items": []}
    monkeypatch.setattr(calendar_service, "get_calendar_service", lambda: fake_service)

    llm = _script_tool_call(
        fake_llm_factory,
        "create_calendar_event",
        {"summary": "Launch review", "start_iso": "2026-08-01T11:00:00", "end_iso": "2026-08-01T12:00:00"},
    )
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)

    config = _config()
    result = await agent_graph.agent.ainvoke(_agent_input("schedule the review"), config)

    interrupts = result.get("__interrupt__")
    assert interrupts is not None
    assert interrupts[0].value["type"] == "calendar_event"
    assert interrupts[0].value["draft"]["summary"] == "Launch review"
    fake_service.events.return_value.insert.assert_not_called()

    result2 = await agent_graph.agent.ainvoke(Command(resume={"approved": True}), config)
    final = result2["messages"][-1]
    assert "Event created" in final.content
    fake_service.events.return_value.insert.assert_called_once()


@pytest.mark.asyncio
async def test_create_calendar_event_declined(monkeypatch, fake_llm_factory):
    fake_service = MagicMock()
    fake_service.events.return_value.list.return_value.execute.return_value = {"items": []}
    monkeypatch.setattr(calendar_service, "get_calendar_service", lambda: fake_service)

    llm = _script_tool_call(
        fake_llm_factory,
        "create_calendar_event",
        {"summary": "Launch review", "start_iso": "2026-08-01T11:00:00", "end_iso": "2026-08-01T12:00:00"},
    )
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)

    config = _config()
    await agent_graph.agent.ainvoke(_agent_input("schedule the review"), config)

    result2 = await agent_graph.agent.ainvoke(Command(resume={"approved": False}), config)
    final = result2["messages"][-1]
    assert "not created" in final.content
    fake_service.events.return_value.insert.assert_not_called()


@pytest.mark.asyncio
async def test_create_calendar_event_conflict_offers_alternatives(monkeypatch, fake_llm_factory):
    _allow_calendar(monkeypatch)
    fake_service = MagicMock()
    fake_service.events.return_value.insert.return_value.execute.return_value = {
        "id": "evt-abc",
        "htmlLink": "https://calendar.google.com/event?eid=abc",
    }
    fake_service.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "evt-standup",
                "summary": "Standup",
                "start": {"dateTime": "2026-08-01T11:00:00"},
                "end": {"dateTime": "2026-08-01T11:30:00"},
            }
        ]
    }
    monkeypatch.setattr(calendar_service, "get_calendar_service", lambda: fake_service)

    llm = _script_tool_call(
        fake_llm_factory,
        "create_calendar_event",
        {"summary": "Launch review", "start_iso": "2026-08-01T11:00:00", "end_iso": "2026-08-01T12:00:00"},
    )
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)

    config = _config()
    result = await agent_graph.agent.ainvoke(_agent_input("schedule the review"), config)

    draft = result["__interrupt__"][0].value["draft"]
    assert [conflict["title"] for conflict in draft["conflicts"]] == ["Standup"]
    assert draft["alternatives"][0] == {
        "start": "2026-08-01T11:30:00",
        "end": "2026-08-01T12:30:00",
    }
    assert len(draft["alternatives"]) == 2

    alternative = draft["alternatives"][0]
    result2 = await agent_graph.agent.ainvoke(
        Command(resume={"approved": True, "edits": {"start": alternative["start"], "end": alternative["end"]}}),
        config,
    )
    assert "Event created" in result2["messages"][-1].content
    body = fake_service.events.return_value.insert.call_args.kwargs["body"]
    assert body["start"]["dateTime"] == alternative["start"]


@pytest.mark.asyncio
async def test_create_calendar_event_conflict_can_be_confirmed_anyway(monkeypatch, fake_llm_factory):
    _allow_calendar(monkeypatch)
    fake_service = MagicMock()
    fake_service.events.return_value.insert.return_value.execute.return_value = {
        "id": "evt-abc",
        "htmlLink": "https://calendar.google.com/event?eid=abc",
    }
    fake_service.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "evt-standup",
                "summary": "Standup",
                "start": {"dateTime": "2026-08-01T11:00:00"},
                "end": {"dateTime": "2026-08-01T11:30:00"},
            }
        ]
    }
    monkeypatch.setattr(calendar_service, "get_calendar_service", lambda: fake_service)

    llm = _script_tool_call(
        fake_llm_factory,
        "create_calendar_event",
        {"summary": "Launch review", "start_iso": "2026-08-01T11:00:00", "end_iso": "2026-08-01T12:00:00"},
    )
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)

    config = _config()
    await agent_graph.agent.ainvoke(_agent_input("schedule the review"), config)

    result = await agent_graph.agent.ainvoke(Command(resume={"approved": True}), config)
    assert "Event created" in result["messages"][-1].content
    body = fake_service.events.return_value.insert.call_args.kwargs["body"]
    assert body["start"]["dateTime"] == "2026-08-01T11:00:00"


@pytest.mark.asyncio
async def test_update_calendar_event_interrupts_then_updates(monkeypatch, fake_llm_factory):
    _allow_calendar(monkeypatch)
    fake_service = MagicMock()
    fake_service.events.return_value.patch.return_value.execute.return_value = {
        "id": "evt-1", "summary": "Launch review (moved)", "htmlLink": "https://calendar.google.com/event?eid=evt1",
    }
    monkeypatch.setattr(calendar_service, "get_calendar_service", lambda: fake_service)

    llm = _script_tool_call(
        fake_llm_factory, "update_calendar_event", {"event_id": "evt-1", "start_iso": "2026-08-01T15:00:00"}
    )
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)

    config = _config()
    result = await agent_graph.agent.ainvoke(_agent_input("move the review"), config)

    interrupts = result.get("__interrupt__")
    assert interrupts is not None
    assert interrupts[0].value["type"] == "calendar_event_update"
    fake_service.events.return_value.patch.assert_not_called()

    result2 = await agent_graph.agent.ainvoke(Command(resume={"approved": True}), config)
    final = result2["messages"][-1]
    assert "Event updated" in final.content
    fake_service.events.return_value.patch.assert_called_once()


@pytest.mark.asyncio
async def test_delete_calendar_event_interrupts_then_deletes(monkeypatch, fake_llm_factory):
    _allow_calendar(monkeypatch)
    fake_service = MagicMock()
    fake_service.events.return_value.delete.return_value.execute.return_value = {}
    monkeypatch.setattr(calendar_service, "get_calendar_service", lambda: fake_service)

    llm = _script_tool_call(fake_llm_factory, "delete_calendar_event", {"event_id": "evt-1"})
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)

    config = _config()
    result = await agent_graph.agent.ainvoke(_agent_input("cancel the review"), config)

    interrupts = result.get("__interrupt__")
    assert interrupts is not None
    assert interrupts[0].value["type"] == "calendar_event_delete"
    fake_service.events.return_value.delete.assert_not_called()

    result2 = await agent_graph.agent.ainvoke(Command(resume={"approved": True}), config)
    final = result2["messages"][-1]
    assert "deleted" in final.content.lower()
    fake_service.events.return_value.delete.assert_called_once()


@pytest.mark.asyncio
async def test_delete_calendar_event_declined(monkeypatch, fake_llm_factory):
    fake_service = MagicMock()
    monkeypatch.setattr(calendar_service, "get_calendar_service", lambda: fake_service)

    llm = _script_tool_call(fake_llm_factory, "delete_calendar_event", {"event_id": "evt-1"})
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)

    config = _config()
    await agent_graph.agent.ainvoke(_agent_input("cancel the review"), config)

    result2 = await agent_graph.agent.ainvoke(Command(resume={"approved": False}), config)
    final = result2["messages"][-1]
    assert "not deleted" in final.content
    fake_service.events.return_value.delete.assert_not_called()


@pytest.mark.asyncio
async def test_list_calendar_events_with_scope_resolves_deterministic_range(monkeypatch, fake_llm_factory):
    """The bug this fixes: the LLM used to freehand-compute time_min_iso/time_max_iso for "tuần
    này" and reliably got it wrong (anchoring at "now" instead of the start of the week, missing
    earlier-this-week events already past). scope removes that guesswork - calendar_service.
    resolve_scope() does the date math instead of the LLM."""
    fake_service = MagicMock()
    fake_service.events.return_value.list.return_value.execute.return_value = {
        "items": [{"id": "evt-1", "summary": "Standup", "start": {"dateTime": "2026-08-11T09:00:00"}}]
    }
    monkeypatch.setattr(calendar_service, "get_calendar_service", lambda: fake_service)
    monkeypatch.setattr(
        calendar_service, "resolve_scope",
        lambda scope: ("2026-08-10T00:00:00+07:00", "2026-08-17T00:00:00+07:00"),
    )

    llm = _script_tool_call(fake_llm_factory, "list_calendar_events", {"scope": "this_week"})
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)

    result = await agent_graph.agent.ainvoke(_agent_input("tuần này tôi có gì"), _config())

    kwargs = fake_service.events.return_value.list.call_args.kwargs
    assert kwargs["timeMin"] == "2026-08-10T00:00:00+07:00"
    assert kwargs["timeMax"] == "2026-08-17T00:00:00+07:00"
    assert "Standup" in result["messages"][-1].content


@pytest.mark.asyncio
async def test_list_calendar_events_with_explicit_range_still_works(monkeypatch, fake_llm_factory):
    fake_service = MagicMock()
    fake_service.events.return_value.list.return_value.execute.return_value = {"items": []}
    monkeypatch.setattr(calendar_service, "get_calendar_service", lambda: fake_service)

    llm = _script_tool_call(
        fake_llm_factory, "list_calendar_events",
        {"time_min_iso": "2026-08-01T00:00:00", "time_max_iso": "2026-08-02T00:00:00"},
    )
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)

    result = await agent_graph.agent.ainvoke(_agent_input("events tomorrow"), _config())

    kwargs = fake_service.events.return_value.list.call_args.kwargs
    assert kwargs["timeMin"] == "2026-08-01T00:00:00"
    assert kwargs["timeMax"] == "2026-08-02T00:00:00"
    assert "No events found" in result["messages"][-1].content


@pytest.mark.asyncio
async def test_list_calendar_events_without_scope_or_range_asks_for_one(monkeypatch, fake_llm_factory):
    fake_service = MagicMock()
    monkeypatch.setattr(calendar_service, "get_calendar_service", lambda: fake_service)

    llm = _script_tool_call(fake_llm_factory, "list_calendar_events", {})
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)

    result = await agent_graph.agent.ainvoke(_agent_input("list my events"), _config())

    fake_service.events.return_value.list.assert_not_called()
    assert "khoảng thời gian" in result["messages"][-1].content
