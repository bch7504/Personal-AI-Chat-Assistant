"""Read-only executor for a prepared Product Delivery invocation.

This is intentionally a narrow composition boundary: a caller explicitly
binds Delivery read tools, then invokes one of them with a server-resolved
``DeliveryReadScope``.  It never imports the shared global tool list, calls a
model, publishes a brief, or accepts proposal/action tools.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.agents.contracts import ToolResult
from src.agents.profiles.product_delivery_runner import PreparedProductDeliveryInvocation
from src.agents.schemas.delivery import DeliveryReadScope

DeliveryReadTool = Callable[..., Awaitable[ToolResult]]
DeliveryWorkspaceRevalidator = Callable[[str], Awaitable[None]]

READ_ONLY_DELIVERY_TOOL_NAMES = frozenset(
    {
        "get_delivery_tasks",
        "search_delivery_messages",
        "get_delivery_milestones",
        "get_delivery_people",
        "get_delivery_dependencies",
        "get_delivery_risks",
        "get_delivery_decisions",
        "get_delivery_release_status",
        "get_delivery_capacity_summary",
        "get_delivery_flow_metrics",
        "get_delivery_portfolio_health",
        "get_delivery_checkpoint_progress",
        "build_delivery_brief",
    }
)


class ProductDeliveryExecutionError(PermissionError):
    """Raised when a prepared invocation would escape its trusted capability."""


class ProductDeliveryReadOnlyExecutor:
    """Execute only explicit, profile-approved Delivery read tool bindings."""

    def __init__(
        self,
        *,
        tool_bindings: Mapping[str, DeliveryReadTool],
        revalidate_workspace: DeliveryWorkspaceRevalidator,
    ) -> None:
        unexpected_names = set(tool_bindings) - READ_ONLY_DELIVERY_TOOL_NAMES
        if unexpected_names:
            values = ", ".join(sorted(unexpected_names))
            raise ProductDeliveryExecutionError(
                f"Non-read-only Delivery tools cannot be bound: {values}"
            )
        self._tool_bindings = dict(tool_bindings)
        self._revalidate_workspace = revalidate_workspace

    async def invoke(
        self,
        *,
        prepared: PreparedProductDeliveryInvocation,
        scope: DeliveryReadScope,
        tool_name: str,
        tool_input: Mapping[str, Any] | None = None,
    ) -> ToolResult:
        """Invoke one bound tool after validating context, scope and workspace.

        A read tool still revalidates each source immediately before its own
        repository query.  The executor owns the complementary workspace-level
        check so a stale/mismatched target cannot reach any tool binding.
        """

        if scope.context != prepared.context:
            raise ProductDeliveryExecutionError("Delivery scope does not match the prepared context")
        if tool_name not in READ_ONLY_DELIVERY_TOOL_NAMES:
            raise ProductDeliveryExecutionError("Delivery action or unknown tool is not executable")
        if tool_name not in prepared.allowed_tools:
            raise ProductDeliveryExecutionError("Tool is outside the prepared Delivery allowlist")
        tool = self._tool_bindings.get(tool_name)
        if tool is None:
            raise ProductDeliveryExecutionError("Approved Delivery tool is not bound by this runtime")

        target_workspace_id = prepared.context.request.target_agent_workspace_id
        if target_workspace_id is None:
            raise ProductDeliveryExecutionError("Prepared Delivery target workspace is missing")
        await self._revalidate_workspace(target_workspace_id)

        return await tool(scope=scope, **dict(tool_input or {}))
