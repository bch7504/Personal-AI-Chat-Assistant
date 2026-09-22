import json
from unittest.mock import AsyncMock

import pytest

from src.agents.tools import task_tool


@pytest.mark.asyncio
async def test_extract_tasks_reads_context_from_state(monkeypatch):
    fake_llm = AsyncMock()
    fake_llm.ainvoke.return_value = AsyncMock(content='[{"title": "Send report", "due_at": null, "priority": "High"}]')
    monkeypatch.setattr(task_tool, "get_llm", lambda: fake_llm)

    state = {"context": "Alice: don't forget to send the report Friday"}
    result = await task_tool.extract_tasks.coroutine(state=state)

    assert json.loads(result) == [{"title": "Send report", "due_at": None, "priority": "High"}]
    fake_llm.ainvoke.assert_awaited_once()
    prompt = fake_llm.ainvoke.await_args.args[0]
    assert "send the report" in prompt
    assert "JSON array" in prompt
    assert "untrusted user data" in prompt


@pytest.mark.asyncio
async def test_extract_tasks_rejects_malformed_model_output(monkeypatch):
    fake_llm = AsyncMock()
    fake_llm.ainvoke.return_value = AsyncMock(content='[{"title": "Bad", "priority": "Urgent"}]')
    monkeypatch.setattr(task_tool, "get_llm", lambda: fake_llm)

    result = await task_tool.extract_tasks.coroutine(state={"context": "Alice: do it"})

    assert result == "[]"


@pytest.mark.asyncio
async def test_extract_tasks_no_context(monkeypatch):
    fake_llm = AsyncMock()
    monkeypatch.setattr(task_tool, "get_llm", lambda: fake_llm)

    result = await task_tool.extract_tasks.coroutine(state={})

    assert result == "[]"
    fake_llm.ainvoke.assert_not_awaited()


def test_state_hidden_from_llm_tool_schema():
    assert list(task_tool.extract_tasks.args.keys()) == []
