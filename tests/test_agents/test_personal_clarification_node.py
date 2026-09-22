import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agents.nodes import personal_clarification_node as clarification_module


class _FakeLLM:
    def __init__(self, content: str):
        self.content = content

    async def ainvoke(self, messages):
        assert "đặt lịch họp với team" in messages[-1].content.lower()
        assert "ngày, giờ bắt đầu, thời lượng" in messages[-1].content
        return AIMessage(content=self.content)


@pytest.mark.asyncio
async def test_clarification_is_contextualized_by_llm(monkeypatch):
    monkeypatch.setattr(
        clarification_module,
        "get_llm",
        lambda: _FakeLLM("Cuộc họp với team dự kiến diễn ra ngày nào, lúc mấy giờ và trong bao lâu?"),
    )

    result = await clarification_module.personal_clarification_node(
        {
            "messages": [HumanMessage(content="Đặt lịch họp với team")],
            "personal_plan": {
                "intent": "calendar",
                "missing_fields": ["ngày", "giờ bắt đầu", "thời lượng"],
                "clarification_fallback": "Bạn muốn họp khi nào?",
            },
        }
    )

    assert "cuộc họp với team" in result["messages"][0].content.lower()
    assert result["metadata"]["clarification_generation"]["source"] == "llm"


@pytest.mark.asyncio
async def test_clarification_uses_fallback_only_when_llm_fails(monkeypatch):
    class _BrokenLLM:
        async def ainvoke(self, messages):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(clarification_module, "get_llm", lambda: _BrokenLLM())
    result = await clarification_module.personal_clarification_node(
        {
            "messages": [HumanMessage(content="Đặt lịch họp với team")],
            "personal_plan": {
                "intent": "calendar",
                "missing_fields": ["ngày"],
                "clarification_fallback": "Bạn muốn họp vào ngày nào?",
            },
        }
    )

    assert result["messages"][0].content == "Bạn muốn họp vào ngày nào?"
    assert result["metadata"]["clarification_generation"]["source"] == "fallback_llm_error"
