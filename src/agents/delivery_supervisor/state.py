from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from src.agents.contracts import ToolResult
from src.agents.delivery_orchestration.contracts import (
    DeliveryOrchestrationContext,
    DeliverySpecialistResult,
)


class DeliverySupervisorState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    snapshot: ToolResult
    orchestration: DeliveryOrchestrationContext
    specialist_results: list[DeliverySpecialistResult]
    metadata: dict[str, Any]
