
import pytest

from src.agents.contracts import ToolResult, ToolResultStatus
from src.agents.profiles.product_delivery import PRODUCT_DELIVERY_PROMPT_VERSION, PRODUCT_DELIVERY_SYSTEM_PROMPT
from src.agents.profiles.product_delivery_executor import (
    ProductDeliveryExecutionError,
    ProductDeliveryReadOnlyExecutor,
)
from src.agents.profiles.product_delivery_runner import PreparedProductDeliveryInvocation
from tests.test_agents.test_delivery_tools import _scope


def _prepared(*, allowed_tools: tuple[str, ...] = ("get_delivery_milestones",)) -> PreparedProductDeliveryInvocation:
    return PreparedProductDeliveryInvocation(
        context=_scope().context,
        prompt_version=PRODUCT_DELIVERY_PROMPT_VERSION,
        system_prompt=PRODUCT_DELIVERY_SYSTEM_PROMPT,
        allowed_tools=allowed_tools,
    )


@pytest.mark.asyncio
async def test_read_only_executor_uses_an_explicit_bound_tool_after_workspace_revalidation():
    calls: list[object] = []

    async def revalidate_workspace(workspace_id: str) -> None:
        calls.append(("workspace", workspace_id))

    async def milestone_tool(*, scope, marker: str) -> ToolResult:
        calls.append(("tool", scope.selected_conversation_id, marker))
        return ToolResult(status=ToolResultStatus.SUCCESS, payload={"milestones": []})

    executor = ProductDeliveryReadOnlyExecutor(
        tool_bindings={"get_delivery_milestones": milestone_tool},
        revalidate_workspace=revalidate_workspace,
    )
    result = await executor.invoke(
        prepared=_prepared(),
        scope=_scope(),
        tool_name="get_delivery_milestones",
        tool_input={"marker": "fixture"},
    )

    assert result.status == ToolResultStatus.SUCCESS
    assert calls == [
        ("workspace", "delivery-workspace"),
        ("tool", "group-apollo", "fixture"),
    ]


@pytest.mark.asyncio
async def test_read_only_executor_rejects_action_tool_even_when_profile_registry_lists_it():
    async def revalidate_workspace(_: str) -> None:
        raise AssertionError("Action tool must fail before workspace/tool execution")

    executor = ProductDeliveryReadOnlyExecutor(
        tool_bindings={}, revalidate_workspace=revalidate_workspace
    )
    with pytest.raises(ProductDeliveryExecutionError, match="action or unknown"):
        await executor.invoke(
            prepared=_prepared(allowed_tools=("propose_delivery_reminder",)),
            scope=_scope(),
            tool_name="propose_delivery_reminder",
        )


@pytest.mark.asyncio
async def test_read_only_executor_rejects_a_scope_from_another_prepared_context_before_checks():
    async def revalidate_workspace(_: str) -> None:
        raise AssertionError("Mismatched context must not reach workspace revalidation")

    async def milestone_tool(*, scope) -> ToolResult:
        raise AssertionError("Mismatched context must not reach a tool")

    executor = ProductDeliveryReadOnlyExecutor(
        tool_bindings={"get_delivery_milestones": milestone_tool},
        revalidate_workspace=revalidate_workspace,
    )
    mismatched_context = _scope().context.model_copy(update={"trace_id": "other-trace"})
    mismatched_scope = _scope().model_copy(update={"context": mismatched_context})

    with pytest.raises(ProductDeliveryExecutionError, match="does not match"):
        await executor.invoke(
            prepared=_prepared(),
            scope=mismatched_scope,
            tool_name="get_delivery_milestones",
        )


def test_read_only_executor_refuses_quality_or_action_bindings_at_composition_time():
    async def tool(**_: object) -> ToolResult:
        return ToolResult(status=ToolResultStatus.SUCCESS)

    with pytest.raises(ProductDeliveryExecutionError, match="Non-read-only"):
        ProductDeliveryReadOnlyExecutor(
            tool_bindings={"get_quality_work_items": tool},
            revalidate_workspace=tool,
        )
