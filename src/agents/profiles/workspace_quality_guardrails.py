"""Hard input/output guardrails owned by the QA runtime."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.profiles.workspace_quality_state import WorkspaceQualityAgentState
from src.services import guardrail_service


def _latest_human_message(state: WorkspaceQualityAgentState) -> str:
    return next(
        (
            str(message.content)
            for message in reversed(state.get("messages", []))
            if isinstance(message, HumanMessage)
        ),
        "",
    )


async def quality_input_guardrail_node(state: WorkspaceQualityAgentState) -> dict:
    decision = guardrail_service.evaluate_workspace_request(
        _latest_human_message(state),
        profile="quality_assurance",
        allow_ambiguous=True,
    )
    if not decision.allowed:
        return {
            "guardrail_blocked": True,
            "metadata": {
                **state.get("metadata", {}),
                "quality_input_guardrail": {
                    "allowed": False,
                    "category": decision.category,
                    "reason": decision.reason,
                },
            },
            "messages": [AIMessage(content=decision.response)],
        }
    return {
        "guardrail_blocked": False,
        "metadata": {
            **state.get("metadata", {}),
            "quality_input_guardrail": {
                "allowed": True,
                "category": decision.category,
            },
        },
    }


async def quality_output_guardrail_node(state: WorkspaceQualityAgentState) -> dict:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, (AIMessage, ToolMessage)) and message.content:
            decision = guardrail_service.evaluate_workspace_output(
                str(message.content),
                profile="quality_assurance",
            )
            if not decision.allowed:
                return {
                    "messages": [AIMessage(content=decision.response)],
                    "metadata": {
                        **state.get("metadata", {}),
                        "quality_output_guardrail": {
                            "allowed": False,
                            "category": decision.category,
                            "reason": decision.reason,
                        },
                    },
                }
            break
    return {
        "metadata": {
            **state.get("metadata", {}),
            "quality_output_guardrail": {"allowed": True},
        }
    }
