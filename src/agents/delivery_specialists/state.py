from __future__ import annotations

from typing import Any, TypedDict

from src.agents.contracts import ToolResult
from src.agents.delivery_orchestration.contracts import (
    DeliverySpecialistResult,
    RuntimeChildTask,
)


class DeliverySpecialistState(TypedDict, total=False):
    workflow_id: str
    user_message: str
    task: RuntimeChildTask
    context: ToolResult
    result: DeliverySpecialistResult
    analysis: dict[str, Any]
    tool_calls: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]
