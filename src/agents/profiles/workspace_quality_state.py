"""State owned exclusively by the Quality Assurance runtime."""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class WorkspaceQualityAgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    guardrail_blocked: bool
    metadata: dict[str, Any]
