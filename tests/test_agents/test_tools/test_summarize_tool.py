from unittest.mock import AsyncMock

import pytest

from src.agents.tools import summarize_tool


@pytest.mark.asyncio
async def test_summarize_conversation_reads_context_from_state(monkeypatch):
    fake_llm = AsyncMock()
    fake_llm.ainvoke.return_value = AsyncMock(content="A short summary.")
    monkeypatch.setattr(summarize_tool, "get_llm", lambda: fake_llm)

    state = {"context": "Alice: hi\nBob: let's meet tomorrow"}
    result = await summarize_tool.summarize_conversation.coroutine(style="brief", state=state)

    assert result == "A short summary."
    fake_llm.ainvoke.assert_awaited_once()
    prompt = fake_llm.ainvoke.await_args.args[0]
    assert "Alice: hi" in prompt
    assert "brief" in prompt


@pytest.mark.asyncio
async def test_summarize_conversation_no_context(monkeypatch):
    fake_llm = AsyncMock()
    monkeypatch.setattr(summarize_tool, "get_llm", lambda: fake_llm)

    result = await summarize_tool.summarize_conversation.coroutine(style="brief", state={})

    assert "No conversation text" in result
    fake_llm.ainvoke.assert_not_awaited()


def test_state_hidden_from_llm_tool_schema():
    assert list(summarize_tool.summarize_conversation.args.keys()) == ["style"]
