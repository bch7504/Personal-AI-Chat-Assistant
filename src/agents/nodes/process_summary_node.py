from langchain_core.messages import AIMessage, ToolMessage

from src.agents.state import AgentState
from src.services.personal_agent_trace_service import build_process_steps, build_process_summary


async def attach_process_summary_node(state: AgentState) -> dict:
    """Attach a safe process summary to the final display message for history replay."""

    messages = state.get("messages", [])
    summary = build_process_summary(messages, state.get("metadata", {}))
    steps = build_process_steps(messages, state.get("metadata", {}))
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.content:
            additional = {
                **message.additional_kwargs,
                "orbit_process_summary": summary,
                "orbit_process_steps": steps,
            }
            return {"messages": [message.model_copy(update={"additional_kwargs": additional})]}
        if isinstance(message, ToolMessage) and message.content:
            return {
                "messages": [
                    AIMessage(
                        content=str(message.content),
                        additional_kwargs={
                            "orbit_process_summary": summary,
                            "orbit_process_steps": steps,
                        },
                    )
                ]
            }
    return {}
