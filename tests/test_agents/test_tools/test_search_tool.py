from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy import select

from src.agents import graph as agent_graph
from src.agents.tools import search_tool
from src.db import session as db_session
from src.db.models import (
    AIPermission,
    Conversation,
    ConversationParticipant,
    Message,
    User,
    Workspace,
    WorkspaceMembership,
)


async def _get_user_id(email: str) -> str:
    async with db_session.async_session_maker() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        return user.id


async def _seed_conversation(alice_id: str, bob_id: str, messages: list[tuple[str, str, datetime]]) -> str:
    async with db_session.async_session_maker() as db:
        workspace = Workspace(type="organization", name="Search tool test workspace")
        db.add(workspace)
        await db.flush()
        db.add_all(
            [
                WorkspaceMembership(workspace_id=workspace.id, user_id=alice_id, role="owner"),
                WorkspaceMembership(workspace_id=workspace.id, user_id=bob_id, role="member"),
            ]
        )
        conversation = Conversation(
            workspace_id=workspace.id,
            type="direct",
            name=None,
            created_by=alice_id,
        )
        db.add(conversation)
        await db.flush()
        for uid in (alice_id, bob_id):
            db.add(
                ConversationParticipant(
                    conversation_id=conversation.id,
                    user_id=uid,
                    principal_kind="workspace_user",
                    resource_role="participant",
                )
            )
            db.add(
                AIPermission(
                    conversation_id=conversation.id,
                    user_id=uid,
                    granted=True,
                    contribution_allowed=True,
                )
            )
        for sender_id, content, created_at in messages:
            db.add(Message(conversation_id=conversation.id, sender_id=sender_id, content=content, created_at=created_at))
        await db.commit()
        return conversation.id


def test_state_hidden_from_llm_tool_schema():
    assert list(search_tool.search_messages.args.keys()) == ["query", "max_results"]


@pytest.mark.asyncio
async def test_search_messages_no_conversation_id_in_state():
    result = await search_tool.search_messages.coroutine(query="deadline", max_results=20, state={})
    assert "No authenticated conversation history" in result


@pytest.mark.asyncio
async def test_personal_agent_searches_all_authorized_conversations(
    client, auth_headers, other_auth_headers
):
    alice_id = await _get_user_id("alice@example.com")
    bob_id = await _get_user_id("bob@example.com")
    now = datetime.now(UTC)
    first = await _seed_conversation(
        alice_id, bob_id, [(bob_id, "OAuth deadline is Friday", now - timedelta(minutes=2))]
    )
    second = await _seed_conversation(
        alice_id, bob_id, [(bob_id, "OAuth deadline moved to Monday", now - timedelta(minutes=1))]
    )

    result = await search_tool.search_messages.coroutine(
        query="OAuth deadline", max_results=20, state={"user_id": alice_id}
    )

    assert "OAuth deadline is Friday" in result
    assert "OAuth deadline moved to Monday" in result
    assert first in result and second in result


@pytest.mark.asyncio
async def test_global_search_excludes_direct_conversation_without_caller_ai_grant(
    client, auth_headers, other_auth_headers
):
    alice_id = await _get_user_id("alice@example.com")
    bob_id = await _get_user_id("bob@example.com")
    conv_id = await _seed_conversation(
        alice_id, bob_id, [(bob_id, "hidden global deadline", datetime.now(UTC))]
    )
    async with db_session.async_session_maker() as db:
        permission = await db.get(AIPermission, (conv_id, alice_id))
        permission.granted = False
        await db.commit()

    result = await search_tool.search_messages.coroutine(
        query="hidden global deadline", max_results=20, state={"user_id": alice_id}
    )

    assert result == "No authorized messages matched 'hidden global deadline'."


@pytest.mark.asyncio
async def test_search_messages_no_results_found(client, auth_headers, other_auth_headers):
    alice_id = await _get_user_id("alice@example.com")
    bob_id = await _get_user_id("bob@example.com")
    now = datetime.now(UTC)
    conv_id = await _seed_conversation(alice_id, bob_id, [(alice_id, "hello there", now)])

    result = await search_tool.search_messages.coroutine(
        query="deadline", max_results=20, state={"conversation_id": conv_id}
    )
    assert "No authorized messages matched 'deadline'" in result


@pytest.mark.asyncio
async def test_search_messages_found_returns_formatted_results(client, auth_headers, other_auth_headers):
    alice_id = await _get_user_id("alice@example.com")
    bob_id = await _get_user_id("bob@example.com")
    now = datetime.now(UTC)
    conv_id = await _seed_conversation(
        alice_id,
        bob_id,
        [
            (alice_id, "we should ship by Friday", now - timedelta(minutes=10)),
            (bob_id, "the deadline is Friday too", now - timedelta(minutes=5)),
        ],
    )

    result = await search_tool.search_messages.coroutine(
        query="deadline", max_results=20, state={"conversation_id": conv_id}
    )
    assert "the deadline is Friday too" in result
    assert "we should ship by Friday" not in result
    assert "[" in result and "]" in result  # local-timezone timestamp annotation present


@pytest.mark.asyncio
async def test_search_messages_scoped_via_state_not_spoofable(client, auth_headers, other_auth_headers):
    """conversation_id only ever comes from injected state (see args schema test above), never a
    tool argument - proven here by seeding the matching content in a DIFFERENT conversation than
    the one passed in state, confirming the DB query genuinely filters by it."""
    alice_id = await _get_user_id("alice@example.com")
    bob_id = await _get_user_id("bob@example.com")
    now = datetime.now(UTC)
    await _seed_conversation(alice_id, bob_id, [(alice_id, "secret project codename", now)])
    other_conv_id = await _seed_conversation(alice_id, bob_id, [(alice_id, "unrelated chit chat", now)])

    result = await search_tool.search_messages.coroutine(
        query="secret", max_results=20, state={"conversation_id": other_conv_id}
    )
    assert "No authorized messages matched 'secret'" in result


@pytest.mark.asyncio
async def test_search_messages_not_terminal_loops_back_to_planner(
    client, auth_headers, other_auth_headers, fake_llm_factory, monkeypatch
):
    """search_messages' output is raw data, not a final answer - unlike summarize_conversation/
    extract_tasks, it must NOT be in graph.TERMINAL_TOOLS: the graph should loop back to planner
    for a second LLM turn to phrase a reply from the results."""
    alice_id = await _get_user_id("alice@example.com")
    bob_id = await _get_user_id("bob@example.com")
    now = datetime.now(UTC)
    conv_id = await _seed_conversation(alice_id, bob_id, [(bob_id, "the deadline is Friday", now)])

    def _final_message(state):
        last = state["messages"][-1]
        assert isinstance(last, ToolMessage)
        return AIMessage(content=f"final:{last.content}")

    responses = [
        AIMessage(content="", tool_calls=[{"name": "search_messages", "args": {"query": "deadline"}, "id": "call_1"}]),
    ]
    llm = fake_llm_factory(responses)
    real_ainvoke = llm.ainvoke

    async def ainvoke(messages):
        if llm._responses:
            return await real_ainvoke(messages)
        return _final_message({"messages": messages})

    llm.ainvoke = ainvoke
    monkeypatch.setattr("src.agents.nodes.planner_node.get_llm", lambda: llm)

    config = {"configurable": {"thread_id": str(uuid4())}}
    result = await agent_graph.agent.ainvoke(
        {"messages": [HumanMessage(content="what's the deadline?")], "conversation_id": conv_id, "user_id": alice_id},
        config,
    )
    assert result["messages"][-1].content.startswith("final:")
    assert "the deadline is Friday" in result["messages"][-1].content
