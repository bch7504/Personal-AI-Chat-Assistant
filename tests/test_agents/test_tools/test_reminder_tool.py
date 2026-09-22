from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from src.agents import graph as agent_graph
from src.config import get_settings
from src.services import reminder_service


def _config():
    return {"configurable": {"thread_id": str(uuid4())}}


def _script_tool_call(fake_llm_factory, tool_name: str, args: dict):
    def _final_message(state):
        last = state["messages"][-1]
        assert isinstance(last, ToolMessage)
        return AIMessage(content=f"final:{last.content}")

    responses = [AIMessage(content="", tool_calls=[{"name": tool_name, "args": args, "id": "call_1"}])]
    llm = fake_llm_factory(responses)
    real_ainvoke = llm.ainvoke

    async def ainvoke(messages):
        if llm._responses:
            return await real_ainvoke(messages)
        return _final_message({"messages": messages})

    llm.ainvoke = ainvoke
    return llm


@pytest.mark.asyncio
async def test_create_reminder_interrupts_then_schedules(
    client, auth_headers, personal_workspace, monkeypatch, fake_llm_factory
):
    user = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    recorded_jobs = []
    monkeypatch.setattr(
        reminder_service.scheduler,
        "add_job",
        lambda func, trigger, run_date, args, id: recorded_jobs.append({"run_date": run_date, "reminder_id": args[0]}),
    )

    due_at = "2099-08-10T15:00:00"
    llm = _script_tool_call(
        fake_llm_factory,
        "create_reminder",
        {"title": "Product launch call", "due_at_iso": due_at, "lead_minutes": 30},
    )
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)

    config = _config()
    result = await agent_graph.agent.ainvoke(
        {
            "messages": [HumanMessage(content="remind me tomorrow at 14:30")],
            "user_id": user["id"],
            "workspace_id": personal_workspace["id"],
        },
        config,
    )

    interrupts = result.get("__interrupt__")
    assert interrupts is not None
    assert interrupts[0].value["type"] == "reminder"
    assert not recorded_jobs

    result2 = await agent_graph.agent.ainvoke(Command(resume={"approved": True}), config)
    final = result2["messages"][-1]
    assert "scheduled to fire" in final.content
    assert len(recorded_jobs) == 1
    expected_due_at = datetime.fromisoformat(due_at).replace(tzinfo=ZoneInfo(get_settings().scheduler_timezone))
    assert recorded_jobs[0]["run_date"] == expected_due_at - timedelta(minutes=30)

    reminders = await reminder_service.list_reminders(
        owner_id=user["id"], workspace_id=personal_workspace["id"]
    )
    assert len(reminders) == 1
    assert reminders[0].title == "Product launch call"
    assert reminders[0].source == "agent"


@pytest.mark.asyncio
async def test_fire_reminder_marks_status_and_pushes_to_owner(
    client, auth_headers, personal_workspace, monkeypatch
):
    user = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    pushed = []

    async def fake_broadcast(user_ids, payload):
        pushed.append((user_ids, payload))

    monkeypatch.setattr(reminder_service.manager, "broadcast_to_users", fake_broadcast)
    monkeypatch.setattr(reminder_service.scheduler, "add_job", lambda *a, **k: None)

    reminder = await reminder_service.schedule_reminder(
        workspace_id=personal_workspace["id"],
        owner_id=user["id"],
        title="Test",
        due_at_iso="2099-08-10T15:00:00",
        lead_minutes=30,
    )

    await reminder_service._fire_reminder_job(reminder.id)

    reminders = await reminder_service.list_reminders(
        owner_id=user["id"], workspace_id=personal_workspace["id"]
    )
    assert reminders[0].status == "fired"
    assert pushed == [
        (
            [user["id"]],
            {
                "type": "reminder_fired",
                "workspace_id": personal_workspace["id"],
                "reminder": {
                    "id": reminder.id,
                    "workspace_id": personal_workspace["id"],
                    "title": "Test",
                    "message": "",
                },
            },
        )
    ]


@pytest.mark.asyncio
async def test_schedule_reminder_without_owner_is_rejected(client, personal_workspace, monkeypatch):
    pushed = []

    async def fake_broadcast(user_ids, payload):
        pushed.append((user_ids, payload))

    monkeypatch.setattr(reminder_service.manager, "broadcast_to_users", fake_broadcast)
    monkeypatch.setattr(reminder_service.scheduler, "add_job", lambda *a, **k: None)

    with pytest.raises(ValueError, match="workspace and owner"):
        await reminder_service.schedule_reminder(
            workspace_id=personal_workspace["id"],
            owner_id=None,
            title="Agent reminder",
            due_at_iso="2099-08-10T15:00:00",
            lead_minutes=30,
        )

    assert pushed == []


@pytest.mark.asyncio
async def test_fire_reminder_missing_id_is_noop(client, monkeypatch):
    pushed = []

    async def fake_broadcast(user_ids, payload):
        pushed.append((user_ids, payload))

    monkeypatch.setattr(reminder_service.manager, "broadcast_to_users", fake_broadcast)

    await reminder_service._fire_reminder_job("does-not-exist")
    assert pushed == []
