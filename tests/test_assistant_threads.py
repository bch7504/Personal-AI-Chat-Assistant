from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from src.db import session as db_session
from src.services import assistant_thread_service


def _mock_reply(monkeypatch, fake_llm_factory, text: str):
    llm = fake_llm_factory([AIMessage(content=text)])
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)
    return llm


@pytest.mark.asyncio
async def test_fresh_chat_creates_assistant_thread(client, auth_headers, monkeypatch, fake_llm_factory):
    _mock_reply(monkeypatch, fake_llm_factory, "Đây là câu trả lời của Orbit.")

    resp = await client.post(
        "/api/v1/chat",
        json={"message": "  Tổng hợp lịch, task và deadline của tôi hôm nay  "},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["analysis"]
    assert len(resp.json()["analysis_steps"]) >= 2
    thread_id = resp.json()["thread_id"]

    listing = await client.get("/api/v1/assistant/threads", headers=auth_headers)
    assert listing.status_code == 200
    threads = listing.json()
    assert len(threads) == 1
    assert threads[0]["thread_id"] == thread_id
    assert threads[0]["title"] == "Tổng hợp lịch, task và deadline của tôi hôm nay"
    assert threads[0]["preview"] == "Đây là câu trả lời của Orbit."


@pytest.mark.asyncio
async def test_second_turn_updates_preview_not_title(client, auth_headers, monkeypatch, fake_llm_factory):
    _mock_reply(monkeypatch, fake_llm_factory, "Phản hồi lượt 1.")
    first = await client.post("/api/v1/chat", json={"message": "Tin nhắn đầu tiên"}, headers=auth_headers)
    thread_id = first.json()["thread_id"]

    _mock_reply(monkeypatch, fake_llm_factory, "Phản hồi lượt 2.")
    second = await client.post(
        "/api/v1/chat", json={"message": "Tin nhắn thứ hai", "thread_id": thread_id}, headers=auth_headers
    )
    assert second.status_code == 200

    listing = await client.get("/api/v1/assistant/threads", headers=auth_headers)
    threads = listing.json()
    assert len(threads) == 1
    assert threads[0]["title"] == "Tin nhắn đầu tiên"  # unchanged
    assert threads[0]["preview"] == "Phản hồi lượt 2."  # refreshed


@pytest.mark.asyncio
async def test_conversation_scoped_chat_does_not_create_assistant_thread(
    client, auth_headers, other_auth_headers, monkeypatch, fake_llm_factory
):
    """AIPanel's embedded quick actions/Ask Orbit always send conversation_id - those turns must
    not show up in the Personal Assistant's own "Gần đây" list."""
    _mock_reply(monkeypatch, fake_llm_factory, "Tóm tắt hội thoại.")
    other_me = await client.get("/api/v1/auth/me", headers=other_auth_headers)
    other = other_me.json()
    workspace = (
        await client.post(
            "/api/v1/workspaces", json={"name": "Assistant thread test"}, headers=auth_headers
        )
    ).json()
    await client.post(
        f"/api/v1/workspaces/{workspace['id']}/members",
        json={"email": other["email"], "role": "member"},
        headers=auth_headers,
    )
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
    await client.put(
        f"/api/v1/conversations/{conversation_id}/ai-permission", json={"granted": True}, headers=auth_headers
    )

    resp = await client.post(
        "/api/v1/chat",
        json={"message": "Summarize this.", "conversation_id": conversation_id},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    listing = await client.get("/api/v1/assistant/threads", headers=auth_headers)
    assert listing.json() == []


@pytest.mark.asyncio
async def test_list_threads_only_returns_own(client, auth_headers, other_auth_headers, monkeypatch, fake_llm_factory):
    _mock_reply(monkeypatch, fake_llm_factory, "Reply for alice.")
    await client.post("/api/v1/chat", json={"message": "Alice's question"}, headers=auth_headers)

    _mock_reply(monkeypatch, fake_llm_factory, "Reply for bob.")
    await client.post("/api/v1/chat", json={"message": "Bob's question"}, headers=other_auth_headers)

    mine = (await client.get("/api/v1/assistant/threads", headers=auth_headers)).json()
    assert len(mine) == 1
    assert mine[0]["title"] == "Alice's question"


@pytest.mark.asyncio
async def test_thread_messages_returns_history_and_checks_ownership(
    client, auth_headers, other_auth_headers, monkeypatch, fake_llm_factory
):
    _mock_reply(monkeypatch, fake_llm_factory, "Câu trả lời thật.")
    user_message = "Hãy giúp tôi lập kế hoạch công việc hôm nay."
    resp = await client.post("/api/v1/chat", json={"message": user_message}, headers=auth_headers)
    thread_id = resp.json()["thread_id"]

    history = await client.get(f"/api/v1/assistant/threads/{thread_id}/messages", headers=auth_headers)
    assert history.status_code == 200
    messages = history.json()
    assert any(message["role"] == "user" and message["content"] == user_message for message in messages)
    assistant = next(message for message in messages if message["role"] == "assistant")
    assert assistant["content"] == "Câu trả lời thật."
    assert assistant["analysis"]
    assert len(assistant["analysis_steps"]) >= 2

    forbidden = await client.get(f"/api/v1/assistant/threads/{thread_id}/messages", headers=other_auth_headers)
    assert forbidden.status_code == 404

    missing = await client.get("/api/v1/assistant/threads/does-not-exist/messages", headers=auth_headers)
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_touch_if_exists_never_creates_a_row(client):
    """A resume for a conversation-embedded interrupt (thread never touched by a personal-assistant
    chat() call) must not retroactively create an AssistantThread row."""
    async with db_session.async_session_maker() as db:
        await assistant_thread_service.touch_if_exists(
            db, owner_id="whoever", thread_id="never-existed", ai_preview="irrelevant"
        )
        threads = await assistant_thread_service.list_threads(db, owner_id="whoever")
    assert threads == []


@pytest.mark.asyncio
async def test_delete_thread_removes_metadata_and_checkpoint_history(
    client, auth_headers, monkeypatch, fake_llm_factory
):
    _mock_reply(monkeypatch, fake_llm_factory, "Phản hồi cũ.")
    created = await client.post(
        "/api/v1/chat", json={"message": "Nội dung cũ cần xóa"}, headers=auth_headers
    )
    thread_id = created.json()["thread_id"]

    deleted = await client.delete(f"/api/v1/assistant/threads/{thread_id}", headers=auth_headers)
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/assistant/threads", headers=auth_headers)).json() == []
    assert (
        await client.get(f"/api/v1/assistant/threads/{thread_id}/messages", headers=auth_headers)
    ).status_code == 404

    # Reusing the opaque client thread id must start clean; deleting only the sidebar metadata
    # would incorrectly replay the old LangGraph checkpoint here.
    _mock_reply(monkeypatch, fake_llm_factory, "Phản hồi mới.")
    recreated = await client.post(
        "/api/v1/chat",
        json={"message": "Nội dung mới", "thread_id": thread_id},
        headers=auth_headers,
    )
    assert recreated.status_code == 200
    history = (
        await client.get(f"/api/v1/assistant/threads/{thread_id}/messages", headers=auth_headers)
    ).json()
    contents = [message["content"] for message in history]
    assert "Nội dung mới" in contents
    assert "Nội dung cũ cần xóa" not in contents
    assert "Phản hồi cũ." not in contents


@pytest.mark.asyncio
async def test_delete_thread_hides_ownership_and_preserves_other_users_data(
    client, auth_headers, other_auth_headers, monkeypatch, fake_llm_factory
):
    _mock_reply(monkeypatch, fake_llm_factory, "Chỉ chủ sở hữu được xóa.")
    created = await client.post(
        "/api/v1/chat", json={"message": "Cuộc trò chuyện riêng"}, headers=auth_headers
    )
    thread_id = created.json()["thread_id"]

    forbidden = await client.delete(
        f"/api/v1/assistant/threads/{thread_id}", headers=other_auth_headers
    )
    assert forbidden.status_code == 404
    mine = (await client.get("/api/v1/assistant/threads", headers=auth_headers)).json()
    assert [thread["thread_id"] for thread in mine] == [thread_id]

    missing = await client.delete(
        "/api/v1/assistant/threads/does-not-exist", headers=auth_headers
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_pending_interrupt_is_restored_and_checks_ownership(
    client, auth_headers, other_auth_headers, monkeypatch
):
    owner = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    thread_id = "personal-pending-calendar-test"
    async with db_session.async_session_maker() as db:
        await assistant_thread_service.touch_new_or_existing(
            db,
            thread_id=thread_id,
            owner_id=owner["id"],
            user_message="Đặt lịch họp ngày mai",
            ai_preview="Đang chờ xác nhận",
        )

    payload = {
        "type": "calendar_event",
        "draft": {
            "summary": "[E2E] Daily sync",
            "start": "2026-09-01T10:00:00+07:00",
            "end": "2026-09-01T10:30:00+07:00",
        },
    }

    class FakeAgent:
        async def aget_state(self, config):
            assert config["configurable"]["thread_id"] == f'{owner["id"]}:{thread_id}'
            interrupt = SimpleNamespace(value=payload)
            task = SimpleNamespace(interrupts=(interrupt,))
            return SimpleNamespace(tasks=(task,))

    monkeypatch.setattr(assistant_thread_service.agent_graph, "agent", FakeAgent())

    restored = await client.get(
        f"/api/v1/assistant/threads/{thread_id}/pending", headers=auth_headers
    )
    assert restored.status_code == 200
    assert restored.json() == payload

    forbidden = await client.get(
        f"/api/v1/assistant/threads/{thread_id}/pending", headers=other_auth_headers
    )
    assert forbidden.status_code == 404
