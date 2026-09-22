from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.api.routes import _build_chat_response


@pytest.fixture(autouse=True)
def _no_live_llm(monkeypatch, fake_llm_factory):
    """Every route test gets a fake LLM by default so nothing hits a live OpenAI key."""
    reply = AIMessage(content="Mocked agent reply.")
    llm = fake_llm_factory([reply])
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)
    return llm


async def _team_workspace(client, owner_headers, member: dict) -> dict:
    workspace_response = await client.post(
        "/api/v1/workspaces",
        json={"name": "Agent route test team"},
        headers=owner_headers,
    )
    assert workspace_response.status_code == 201
    workspace = workspace_response.json()
    member_response = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/members",
        json={"email": member["email"], "role": "member"},
        headers=owner_headers,
    )
    assert member_response.status_code == 201
    return workspace


@pytest.mark.asyncio
async def test_chat_answers_capability_question_without_llm_fallback(
    client,
    auth_headers,
    _no_live_llm,
):
    response = await client.post(
        "/api/v1/chat",
        json={"message": "Bạn có thể giúp tôi những việc gì?"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert "task/deadline" in data["response"]
    assert "Google Calendar" in data["response"]
    assert "xác nhận" in data["response"]
    assert "không thể hỗ trợ" not in data["response"].casefold()
    assert len(_no_live_llm._responses) == 1


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_chat_requires_auth(client):
    response = await client.post("/api/v1/chat", json={"message": "hello"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_empty_message(client, auth_headers):
    response = await client.post("/api/v1/chat", json={"message": ""}, headers=auth_headers)
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_chat_rejects_conversation_id_caller_is_not_a_participant_of(
    client, auth_headers, other_auth_headers
):
    # A third user's conversation with other_auth_headers' user - auth_headers' user is in neither.
    await client.post(
        "/api/v1/auth/register",
        json={"email": "carol@example.com", "password": "password123", "display_name": "Carol"},
    )
    third = await client.post(
        "/api/v1/auth/login",
        json={"email": "carol@example.com", "password": "password123"},
    )
    third_headers = {"Authorization": f"Bearer {third.json()['access_token']}"}
    other_me = await client.get("/api/v1/auth/me", headers=other_auth_headers)
    other = other_me.json()
    workspace = await _team_workspace(client, third_headers, other)
    conv = await client.post(
        "/api/v1/conversations",
        json={"type": "direct", "participant_ids": [other["id"]], "workspace_id": workspace["id"]},
        headers=third_headers,
    )
    conversation_id = conv.json()["id"]

    # auth_headers' user was never added to this conversation - it belongs to third_headers and
    # other_auth_headers' user only.
    response = await client.post(
        "/api/v1/chat",
        json={"message": "Summarize this.", "conversation_id": conversation_id},
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_chat_rejects_conversation_id_when_ai_permission_not_granted(client, auth_headers, other_auth_headers):
    other_me = await client.get("/api/v1/auth/me", headers=other_auth_headers)
    other = other_me.json()
    workspace = await _team_workspace(client, auth_headers, other)
    conv = await client.post(
        "/api/v1/conversations",
        json={"type": "direct", "participant_ids": [other["id"]], "workspace_id": workspace["id"]},
        headers=auth_headers,
    )
    conversation_id = conv.json()["id"]

    # A participant, but the AI permission for this conversation was never granted - default deny.
    response = await client.post(
        "/api/v1/chat",
        json={"message": "Summarize this.", "conversation_id": conversation_id},
        headers=auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_chat_allows_conversation_id_caller_is_a_participant_of(client, auth_headers, other_auth_headers):
    other_me = await client.get("/api/v1/auth/me", headers=other_auth_headers)
    other = other_me.json()
    workspace = await _team_workspace(client, auth_headers, other)
    conv = await client.post(
        "/api/v1/conversations",
        json={"type": "direct", "participant_ids": [other["id"]], "workspace_id": workspace["id"]},
        headers=auth_headers,
    )
    conversation_id = conv.json()["id"]
    await client.put(
        f"/api/v1/conversations/{conversation_id}/ai-permission", json={"granted": True}, headers=auth_headers
    )

    response = await client.post(
        "/api/v1/chat",
        json={"message": "Summarize this.", "conversation_id": conversation_id},
        headers=auth_headers,
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_conversation_context_excludes_messages_from_nonconsenting_authors(
    client, auth_headers, other_auth_headers, monkeypatch, fake_llm_factory
):
    owner = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    other = (await client.get("/api/v1/auth/me", headers=other_auth_headers)).json()
    workspace = await _team_workspace(client, auth_headers, other)
    conv = await client.post(
        "/api/v1/conversations",
        json={
            "type": "direct",
            "participant_ids": [other["id"]],
            "workspace_id": workspace["id"],
        },
        headers=auth_headers,
    )
    conversation_id = conv.json()["id"]
    await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "OWNER-CONTENT-ALLOWED"},
        headers=auth_headers,
    )
    await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "OTHER-SECRET-MUST-NOT-REACH-MODEL"},
        headers=other_auth_headers,
    )
    await client.put(
        f"/api/v1/conversations/{conversation_id}/ai-permission",
        json={"granted": True, "contribution_allowed": True},
        headers=auth_headers,
    )

    captured = {}
    reply = AIMessage(content="Consent-filtered answer")
    llm = fake_llm_factory([reply])

    async def ainvoke(messages):
        captured["text"] = "\n".join(str(message.content) for message in messages)
        return reply

    llm.ainvoke = ainvoke
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)

    response = await client.post(
        "/api/v1/chat",
        json={"message": "Summarize this", "conversation_id": conversation_id},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert "OWNER-CONTENT-ALLOWED" in captured["text"]
    assert "OTHER-SECRET-MUST-NOT-REACH-MODEL" not in captured["text"]
    scope = response.json()["context_scope"]
    assert scope["included_message_count"] == 1
    assert scope["window_message_count"] == 2
    assert scope["coverage"] == 0.5
    assert owner["display_name"] in scope["included_participants"]
    assert other["display_name"] in scope["excluded_participants"]


@pytest.mark.asyncio
async def test_chat_completed_response(client, auth_headers):
    response = await client.post("/api/v1/chat", json={"message": "hello"}, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["response"] == "Mocked agent reply."
    assert data["thread_id"]


def test_build_chat_response_replaces_empty_agent_output():
    response = _build_chat_response(
        {"messages": [AIMessage(content="")]},
        "empty-output-thread",
    )

    assert response.status == "completed"
    assert response.response
    assert "thử diễn đạt lại" in response.response


@pytest.mark.asyncio
async def test_chat_surfaces_llm_error_instead_of_empty_response(client, auth_headers, monkeypatch):
    def broken_get_llm():
        raise RuntimeError("Rate limit reached")

    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", broken_get_llm)

    response = await client.post("/api/v1/chat", json={"message": "hello"}, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert data["response"] == "Dịch vụ AI tạm thời không khả dụng. Vui lòng thử lại sau."


@pytest.mark.asyncio
async def test_chat_uses_provided_messages_as_context(client, auth_headers, monkeypatch, fake_llm_factory):
    captured = {}
    reply = AIMessage(content="Summary done.")
    llm = fake_llm_factory([reply])

    async def ainvoke(messages):
        captured["messages"] = messages
        return reply

    llm.ainvoke = ainvoke
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)

    response = await client.post(
        "/api/v1/chat",
        json={
            "message": "Summarize this",
            "messages": [
                {"role": "user", "sender": "Alice", "content": "hi"},
                {"role": "user", "sender": "Bob", "content": "let's meet tomorrow"},
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_chat_interrupts_and_resume_completes(client, auth_headers, monkeypatch, fake_llm_factory):
    from src.services import calendar_service

    fake_service = MagicMock()
    fake_service.events.return_value.insert.return_value.execute.return_value = {"id": "evt-1"}
    monkeypatch.setattr(calendar_service, "get_calendar_service", lambda: fake_service)
    monkeypatch.setattr(calendar_service, "authorize_calendar_access", AsyncMock())
    monkeypatch.setattr(calendar_service, "broadcast_change", AsyncMock())

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

    response = await client.post("/api/v1/chat", json={"message": "book a sync"}, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "interrupted"
    assert data["interrupt"]["type"] == "calendar_event"
    thread_id = data["thread_id"]

    resume_response = await client.post(
        "/api/v1/chat/resume", json={"thread_id": thread_id, "approved": True}, headers=auth_headers
    )
    assert resume_response.status_code == 200
    resume_data = resume_response.json()
    assert resume_data["status"] == "completed"
    assert "Event created" in resume_data["response"]


@pytest.mark.asyncio
async def test_chat_blocked_when_over_daily_token_budget(client, auth_headers, monkeypatch):
    from src.agents import graph as agent_graph
    from src.services import usage_service

    async def _over_budget(user_id):
        assert user_id
        return True

    monkeypatch.setattr(usage_service, "is_over_budget", _over_budget)

    async def _must_not_run(*args, **kwargs):
        raise AssertionError("agent graph must not run when over the daily token budget")

    monkeypatch.setattr(agent_graph.agent, "ainvoke", _must_not_run)

    response = await client.post("/api/v1/chat", json={"message": "hello"}, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert "hạn mức" in data["response"]


@pytest.mark.asyncio
async def test_capability_help_remains_available_when_over_budget(
    client,
    auth_headers,
    monkeypatch,
    _no_live_llm,
):
    from src.services import usage_service

    async def _over_budget(user_id):
        assert user_id
        return True

    monkeypatch.setattr(usage_service, "is_over_budget", _over_budget)

    response = await client.post(
        "/api/v1/chat",
        json={"message": "Bạn có thể giúp tôi những việc gì?"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert "task/deadline" in data["response"]
    assert "hạn mức" not in data["response"]
    assert len(_no_live_llm._responses) == 1


@pytest.mark.asyncio
async def test_chat_resume_not_blocked_by_budget(client, auth_headers, monkeypatch, fake_llm_factory):
    """resume_chat() completes an action a human already approved (interrupt() confirm) - it must
    stay exempt from the budget block, or an approved reminder/calendar action could get stranded
    with no way to finish once the daily budget is hit mid-flow."""
    from src.services import calendar_service

    fake_service = MagicMock()
    fake_service.events.return_value.insert.return_value.execute.return_value = {"id": "evt-1"}
    monkeypatch.setattr(calendar_service, "get_calendar_service", lambda: fake_service)
    monkeypatch.setattr(calendar_service, "authorize_calendar_access", AsyncMock())
    monkeypatch.setattr(calendar_service, "broadcast_change", AsyncMock())

    def _final_message(state):
        last = state["messages"][-1]
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

    response = await client.post("/api/v1/chat", json={"message": "book a sync"}, headers=auth_headers)
    assert response.json()["status"] == "interrupted"
    thread_id = response.json()["thread_id"]

    from src.services import usage_service

    async def _over_budget(user_id):
        assert user_id
        return True

    monkeypatch.setattr(usage_service, "is_over_budget", _over_budget)

    resume_response = await client.post(
        "/api/v1/chat/resume", json={"thread_id": thread_id, "approved": True}, headers=auth_headers
    )
    assert resume_response.status_code == 200
    assert resume_response.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_chat_resume_rejects_stale_consent_snapshot(
    client, auth_headers, other_auth_headers, monkeypatch
):
    from src.agents import graph as agent_graph
    from src.db import session as db_session
    from src.db.models import AgentThread
    from src.services.thread_memory_service import checkpoint_thread_id

    owner = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    other = (await client.get("/api/v1/auth/me", headers=other_auth_headers)).json()
    workspace = await _team_workspace(client, auth_headers, other)
    conversation = (
        await client.post(
            "/api/v1/conversations",
            json={
                "type": "direct",
                "participant_ids": [other["id"]],
                "workspace_id": workspace["id"],
            },
            headers=auth_headers,
        )
    ).json()
    await client.put(
        f"/api/v1/conversations/{conversation['id']}/ai-permission",
        json={"granted": True, "contribution_allowed": True},
        headers=auth_headers,
    )

    thread_id = "stale-consent-thread"
    async with db_session.async_session_maker() as db:
        from datetime import UTC, datetime, timedelta

        db.add(
            AgentThread(
                id=checkpoint_thread_id(owner["id"], thread_id),
                owner_id=owner["id"],
                workspace_id=workspace["id"],
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        await db.commit()
    monkeypatch.setattr(
        agent_graph.agent,
        "aget_state",
        AsyncMock(
            return_value=SimpleNamespace(
                values={
                    "conversation_id": conversation["id"],
                    "consent_scope_hash": "outdated-snapshot",
                }
            )
        ),
    )
    must_not_resume = AsyncMock(side_effect=AssertionError("stale action must not execute"))
    monkeypatch.setattr(agent_graph.agent, "ainvoke", must_not_resume)

    response = await client.post(
        "/api/v1/chat/resume",
        json={"thread_id": thread_id, "approved": True},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert "thay đổi" in response.json()["response"]
    must_not_resume.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_status(client):
    response = await client.get("/api/v1/status")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_usage_status_requires_auth(client):
    response = await client.get("/api/v1/usage/status")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_usage_status_accessible_to_regular_user_without_cost_or_model_fields(client, auth_headers):
    """Sidebar.jsx's widget, not the admin-only /admin/stats - a regular (non-admin) user must be
    able to call this, and the response must never leak estimated_cost_usd or per-model data."""
    response = await client.get("/api/v1/usage/status", headers=auth_headers)
    assert response.status_code == 200
    assert set(response.json().keys()) == {"tokens_used_today", "daily_token_budget", "used_pct"}


@pytest.mark.asyncio
async def test_usage_status_is_scoped_to_authenticated_account(
    client, auth_headers, other_auth_headers, monkeypatch
):
    from src.services import usage_service

    monkeypatch.setattr(usage_service.manager, "broadcast_to_users", AsyncMock())
    owner_id = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()["id"]
    other_id = (await client.get("/api/v1/auth/me", headers=other_auth_headers)).json()["id"]
    await usage_service.log_usage(
        provider="openai",
        model="gpt-4o-mini",
        usage_metadata={"total_tokens": 11},
        user_id=owner_id,
    )
    await usage_service.log_usage(
        provider="openai",
        model="gpt-4o-mini",
        usage_metadata={"total_tokens": 29},
        user_id=other_id,
    )

    owner_status = await client.get("/api/v1/usage/status", headers=auth_headers)
    other_status = await client.get("/api/v1/usage/status", headers=other_auth_headers)

    assert owner_status.json()["tokens_used_today"] == 11
    assert other_status.json()["tokens_used_today"] == 29


@pytest.mark.asyncio
async def test_usage_status_zero_budget_reports_zero_pct(client, auth_headers, monkeypatch):
    from src.services import usage_service

    async def _zero_budget():
        return 0

    monkeypatch.setattr(usage_service, "get_daily_token_budget", _zero_budget)

    response = await client.get("/api/v1/usage/status", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["used_pct"] == 0.0
    assert response.json()["daily_token_budget"] == 0
