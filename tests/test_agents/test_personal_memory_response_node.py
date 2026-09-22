import pytest
from langchain_core.messages import AIMessage

from src.agents.nodes import personal_memory_response_node as response_module


class _FakeLLM:
    async def ainvoke(self, messages):
        assert "sếp" in messages[-1].content
        return AIMessage(content="Được, từ giờ tôi sẽ gọi bạn là “sếp”.")


@pytest.mark.asyncio
async def test_saved_memory_acknowledgement_is_worded_by_llm(monkeypatch):
    monkeypatch.setattr(response_module, "get_llm", lambda: _FakeLLM())
    result = await response_module.personal_memory_response_node(
        {
            "metadata": {
                "memory_write": {
                    "saved": True,
                    "acknowledgement_facts": {
                        "address_alias": "sếp",
                        "other_details": [],
                        "fallback_response": "Đã ghi nhớ. Từ giờ tôi sẽ gọi bạn là “sếp”.",
                    },
                }
            }
        }
    )

    assert result["messages"][0].content == "Được, từ giờ tôi sẽ gọi bạn là “sếp”."
    assert result["metadata"]["memory_response_generation"]["source"] == "llm"


@pytest.mark.asyncio
async def test_saved_memory_acknowledgement_falls_back_only_on_llm_error(monkeypatch):
    class _BrokenLLM:
        async def ainvoke(self, messages):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(response_module, "get_llm", lambda: _BrokenLLM())
    fallback = "Đã ghi nhớ. Từ giờ tôi sẽ gọi bạn là “sếp”."
    result = await response_module.personal_memory_response_node(
        {
            "metadata": {
                "memory_write": {
                    "saved": True,
                    "acknowledgement_facts": {
                        "address_alias": "sếp",
                        "other_details": [],
                        "fallback_response": fallback,
                    },
                }
            }
        }
    )

    assert result["messages"][0].content == fallback
    assert result["metadata"]["memory_response_generation"]["source"] == "fallback_llm_error"
