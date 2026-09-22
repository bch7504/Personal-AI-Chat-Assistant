"""State owned exclusively by the Workspace Delivery agent runtime.

This intentionally is not an alias or extension of ``src.agents.state.AgentState``.
The Personal Agent and Workspace Delivery Agent have different trust boundaries,
lifecycles and permitted capabilities, so their LangGraph state must remain
independent as well.
"""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class WorkspaceDeliveryAgentState(TypedDict, total=False):
    """Minimal state for a single, server-authorized Delivery turn."""

    messages: Annotated[list[AnyMessage], add_messages]
    guardrail_blocked: bool
    metadata: dict[str, Any]
