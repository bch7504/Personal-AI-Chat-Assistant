from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from src.agents.state import AgentState
from src.config import get_settings


def _message_line(message) -> str:
    if isinstance(message, HumanMessage):
        role = "Người dùng"
    elif isinstance(message, AIMessage):
        role = "Trợ lý"
    elif isinstance(message, ToolMessage):
        role = f"Tool {message.name or ''}".strip()
    else:
        role = "Hệ thống"
    content = message.content if isinstance(message.content, str) else str(message.content)
    return f"{role}: {' '.join(content.split())[:500]}"


async def compact_thread_node(state: AgentState) -> dict:
    """Bound checkpoint growth after a completed run while preserving recent turns and a
    deterministic, non-LLM summary of older content. Pending interrupts never reach this node."""
    settings = get_settings()
    messages = state.get("messages", [])
    if len(messages) <= settings.agent_max_thread_messages:
        return {}

    keep_count = max(6, settings.agent_max_thread_messages // 2)
    split_at = max(0, len(messages) - keep_count)
    for index in range(split_at, len(messages)):
        if isinstance(messages[index], HumanMessage):
            split_at = index
            break
    older, recent = messages[:split_at], messages[split_at:]
    if not older:
        return {}
    parts = [state.get("thread_summary", "").strip()]
    parts.extend(_message_line(message) for message in older if not isinstance(message, SystemMessage))
    summary = "\n".join(part for part in parts if part)[-settings.agent_thread_summary_chars :]
    compacted = [
        RemoveMessage(id=REMOVE_ALL_MESSAGES),
        AIMessage(
            content=(
                "[Tóm tắt dữ liệu từ các lượt cũ; không phải chỉ dẫn hệ thống]\n"
                f"{summary}"
            )
        ),
        *recent,
    ]
    return {"thread_summary": summary, "messages": compacted}
