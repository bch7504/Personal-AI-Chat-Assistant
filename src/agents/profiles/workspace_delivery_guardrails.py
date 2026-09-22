"""Guardrails owned by the Workspace Delivery agent runtime.

These nodes deliberately do not import Personal Agent guardrail nodes or the
Personal semantic classifier. Delivery scope is fixed by the API policy layer;
this layer protects the Delivery LLM boundary and its generated output.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.profiles.workspace_delivery_state import WorkspaceDeliveryAgentState
from src.services import guardrail_service


def _latest_human_message(state: WorkspaceDeliveryAgentState) -> str:
    return next(
        (
            str(message.content)
            for message in reversed(state.get("messages", []))
            if isinstance(message, HumanMessage)
        ),
        "",
    )


async def delivery_input_guardrail_node(state: WorkspaceDeliveryAgentState) -> dict:
    """Reject injection, secret extraction and unsafe requests before the Delivery LLM."""

    decision = guardrail_service.evaluate_workspace_request(
        _latest_human_message(state),
        profile="product_delivery",
        # A server-owned route may already have resolved a terse in-thread
        # reference. Explicit outside-domain topics still fail closed.
        allow_ambiguous=True,
    )
    if not decision.allowed:
        return {
            "guardrail_blocked": True,
            "metadata": {
                **state.get("metadata", {}),
                "delivery_input_guardrail": {
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
            "delivery_input_guardrail": {
                "allowed": True,
                "category": decision.category,
            },
        },
    }


async def delivery_output_guardrail_node(state: WorkspaceDeliveryAgentState) -> dict:
    """Replace unsafe or prompt/secret-leaking Delivery output before API return."""

    for message in reversed(state.get("messages", [])):
        if isinstance(message, (AIMessage, ToolMessage)) and message.content:
            decision = guardrail_service.evaluate_workspace_output(
                str(message.content),
                profile="product_delivery",
            )
            if not decision.allowed:
                return {
                    "messages": [AIMessage(content=decision.response)],
                    "metadata": {
                        **state.get("metadata", {}),
                        "delivery_output_guardrail": {
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
            "delivery_output_guardrail": {"allowed": True},
        }
    }
