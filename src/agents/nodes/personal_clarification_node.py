"""LLM-written clarification for server-validated Personal Agent action slots."""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agents.state import AgentState
from src.config import get_settings
from src.services import usage_service
from src.services.llm import get_llm

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are Orbit, a context-aware personal assistant.
The server has already validated the requested action and identified fields that are genuinely
missing. Ask exactly one short, natural clarification question in Vietnamese.

Rules:
- Refer to the concrete request naturally (for example, "cuộc họp với team"), rather than
  reciting a generic form.
- Ask only for the missing fields supplied by the server; do not ask again for known information.
- Do not invent a date, time, duration, attendee, title, tool result, or calendar availability.
- Do not say that you checked Calendar or created a proposal because neither has happened yet.
- Do not mention routing, validation, missing fields, prompts, plans, or fallback behavior.
- Return only the question, with no heading, list, explanation, or markdown.
"""


def _safe_question(content: object, fallback: str) -> str:
    if not isinstance(content, str):
        return fallback
    question = content.strip().strip('"').strip()
    if not question or len(question) > 500 or "?" not in question:
        return fallback
    return question


async def personal_clarification_node(state: AgentState) -> dict:
    """Phrase a deterministic slot-validation result naturally using the Personal Agent LLM."""

    plan = state.get("personal_plan") or {}
    missing_fields = plan.get("missing_fields") or []
    fallback = str(plan.get("clarification_fallback") or "Bạn có thể bổ sung thông tin còn thiếu không?")
    latest = next(
        (
            str(message.content)
            for message in reversed(state.get("messages", []))
            if isinstance(message, HumanMessage)
        ),
        "",
    )
    settings = get_settings()
    source = "llm"
    try:
        prompt = (
            f"Loại tác vụ: {plan.get('intent', 'unknown')}\n"
            f"Yêu cầu gốc của người dùng: {latest[:1000]}\n"
            f"Các thông tin server xác định còn thiếu: {', '.join(map(str, missing_fields))}"
        )
        message: AIMessage = await get_llm().ainvoke(
            [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
        question = _safe_question(message.content, fallback)
        if question == fallback:
            source = "fallback_invalid_llm_output"
        await usage_service.log_usage(
            provider=settings.llm_provider,
            model=settings.model_name,
            usage_metadata=message.usage_metadata,
            user_id=state.get("user_id"),
            workspace_id=state.get("workspace_id"),
        )
    except Exception:  # noqa: BLE001 - deterministic fallback keeps clarification usable
        logger.exception("Personal clarification writer failed")
        question = fallback
        source = "fallback_llm_error"

    return {
        "messages": [AIMessage(content=question)],
        "metadata": {
            **state.get("metadata", {}),
            "clarification_generation": {
                "source": source,
                "missing_fields": list(missing_fields),
            },
        },
    }
