import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from src.agents.nodes.compact_node import compact_thread_node


@pytest.mark.asyncio
async def test_compact_thread_bounds_history_and_keeps_recent_turn(monkeypatch):
    monkeypatch.setenv("AGENT_MAX_THREAD_MESSAGES", "6")
    from src.config import get_settings

    get_settings.cache_clear()
    messages = []
    for index in range(8):
        messages.extend([HumanMessage(content=f"question {index}"), AIMessage(content=f"answer {index}")])
    result = await compact_thread_node({"messages": messages})
    assert isinstance(result["messages"][0], RemoveMessage)
    assert isinstance(result["messages"][1], AIMessage)
    assert "question 0" in result["thread_summary"]
    assert result["messages"][-2].content == "question 7"
    assert result["messages"][-1].content == "answer 7"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_compact_thread_is_noop_under_limit(monkeypatch):
    monkeypatch.setenv("AGENT_MAX_THREAD_MESSAGES", "20")
    from src.config import get_settings

    get_settings.cache_clear()
    result = await compact_thread_node({"messages": [HumanMessage(content="hello")]})
    assert result == {}
    get_settings.cache_clear()
