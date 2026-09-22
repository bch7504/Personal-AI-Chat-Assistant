import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select

import src.db.session as db_session
from src.agents import graph as agent_graph
from src.agents.tools.context_tool import _explicit_reminder_lead_minutes, get_personal_timeline
from src.db.models import Reminder
from src.services import calendar_service


def test_timeline_tool_infers_only_an_explicit_reminder_proposal_lead_time():
    assert (
        _explicit_reminder_lead_minutes(
            {
                "messages": [
                    HumanMessage(
                        content=(
                            "Nếu chưa có nhắc việc thì đề xuất reminder trước deadline task 60 phút"
                        )
                    )
                ]
            }
        )
        == 60
    )
    assert (
        _explicit_reminder_lead_minutes(
            {"messages": [HumanMessage(content="Tổng hợp reminder trong tuần này")]}
        )
        is None
    )


@pytest.mark.asyncio
async def test_personal_timeline_tool_returns_structured_deduplicated_business_report(
    client, auth_headers, personal_workspace, monkeypatch
):
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    owner_id = me.json()["id"]
    due_at = datetime.now(UTC) + timedelta(days=1)
    created = await client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={
            "workspace_id": personal_workspace["id"],
            "title": "Chuẩn bị báo cáo E2E",
            "due_at": due_at.isoformat(),
            "priority": "High",
        },
    )
    assert created.status_code == 201, created.text
    async with db_session.async_session_maker() as db:
        linked = await db.scalar(
            select(Reminder).where(Reminder.task_id == created.json()["id"])
        )
        if linked is None:
            db.add(
                Reminder(
                    workspace_id=personal_workspace["id"],
                    owner_id=owner_id,
                    task_id=created.json()["id"],
                    title="Chuẩn bị báo cáo E2E",
                    message="Nhắc trước deadline",
                    due_at=due_at,
                    fire_at=due_at - timedelta(minutes=60),
                    lead_minutes=60,
                    status="scheduled",
                    source="proactive",
                )
            )
            await db.commit()
    monkeypatch.setattr(calendar_service, "list_events", AsyncMock(return_value=[]))

    result = await get_personal_timeline.coroutine(
        from_iso=(due_at - timedelta(days=1)).isoformat(),
        to_iso=(due_at + timedelta(days=1)).isoformat(),
        include_overdue_tasks=True,
        state={
            "user_id": owner_id,
            "workspace_id": personal_workspace["id"],
            "messages": [
                HumanMessage(
                    content=(
                        "Đối chiếu task, reminder và Calendar; sắp xếp ưu tiên, chỉ ra xung đột"
                    )
                )
            ],
        },
    )

    report = json.loads(result)
    task = next(row for row in report["priority_order"] if row["title"] == "Chuẩn bị báo cáo E2E")
    assert report["schema_version"] == 1
    assert task["priority"] == "High"
    assert task["reminder"] is not None
    assert report["summary"]["linked_reminders"] >= 1
    assert report["summary"]["calendar_events"] == 0
    assert "## Xung đột và rủi ro" in report["report_markdown"]
    assert "Google Calendar không có sự kiện" in report["report_markdown"]
    assert "| task |" not in report["report_markdown"]


@pytest.mark.asyncio
async def test_personal_agent_graph_repairs_raw_multi_source_answer_before_returning_it(
    client,
    auth_headers,
    personal_workspace,
    monkeypatch,
    fake_llm_factory,
):
    owner_id = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()["id"]
    monkeypatch.setattr(calendar_service, "list_events", AsyncMock(return_value=[]))
    planner_llm = fake_llm_factory(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_personal_timeline",
                        "args": {
                            "from_iso": "2026-08-31T00:00:00+07:00",
                            "to_iso": "2026-09-07T23:59:59+07:00",
                            "include_overdue_tasks": True,
                        },
                        "id": "timeline-e2e",
                    }
                ],
            ),
            AIMessage(
                content=(
                    "- 2026-09-01T03:43:04+07:00 | task | "
                    "Chuẩn bị báo cáo | in_progress"
                )
            ),
        ]
    )
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: planner_llm)

    result = await agent_graph.agent.ainvoke(
        {
            "messages": [
                HumanMessage(
                    content=(
                        "Tổng hợp task, deadline, reminder và lịch 7 ngày tới; "
                        "sắp xếp ưu tiên và chỉ ra xung đột"
                    )
                )
            ],
            "user_id": owner_id,
            "workspace_id": personal_workspace["id"],
        },
        {"configurable": {"thread_id": str(uuid4())}},
    )

    answer = result["messages"][-1].content
    assert "## Tổng quan" in answer
    assert "## Việc cần ưu tiên" in answer
    assert "## Xung đột và rủi ro" in answer
    assert "2026-09-01T03:43:04" not in answer
    assert result["metadata"]["personal_response_quality"]["repaired"] is True
