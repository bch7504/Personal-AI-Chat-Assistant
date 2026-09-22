from datetime import UTC, datetime

import pytest

from src.agents.contracts import (
    ActorContext,
    AgentContext,
    AgentIntent,
    AgentProfile,
    AgentRequestContext,
    AgentRuntimeContext,
    AuthorizationContext,
    BusinessRole,
    PolicyDecision,
    PolicyReason,
    RequestedScope,
    ToolResult,
    ToolResultStatus,
)
from src.agents.profiles.quality_assurance import (
    QUALITY_ASSURANCE_PROMPT_VERSION,
    QUALITY_ASSURANCE_SYSTEM_PROMPT,
)
from src.agents.profiles.quality_assurance_executor import (
    QualityExecutionError,
    QualityReadOnlyExecutor,
)
from src.agents.profiles.quality_assurance_runner import PreparedQualityInvocation
from src.agents.schemas.quality import (
    QualityReadScope,
    QualityStatus,
    QualityViewScope,
    QualityWorkItem,
    QualityWorkItemType,
)
from src.agents.tools.quality_work_items import get_release_test_status


def _scope() -> QualityReadScope:
    context = AgentContext(
        trace_id="quality-trace",
        actor=ActorContext(
            user_id="quality-lead",
            organization_workspace_id="company",
            business_role=BusinessRole.LEAD,
            agent_workspace_ids=("quality-workspace",),
        ),
        request=AgentRequestContext(
            text="Quality readiness",
            intent=AgentIntent.QUALITY_BRIEF,
            requested_scope=RequestedScope.WORKSPACE,
            target_agent_workspace_id="quality-workspace",
        ),
        authorization=AuthorizationContext(
            decision=PolicyDecision.ALLOW,
            reason=PolicyReason.ALLOWED,
            allowed_agent_workspace_ids=("quality-workspace",),
            allowed_resource_ids=("quality-group",),
        ),
        runtime=AgentRuntimeContext(
            agent_profile=AgentProfile.QUALITY_ASSURANCE,
            prompt_version=QUALITY_ASSURANCE_PROMPT_VERSION,
        ),
    )
    return QualityReadScope(
        context=context,
        release_id="R1",
        view_scope=QualityViewScope.WORKSPACE,
        effective_group_ids=("quality-group",),
    )


def _prepared(*, allowed_tools: tuple[str, ...]) -> PreparedQualityInvocation:
    return PreparedQualityInvocation(
        context=_scope().context,
        prompt_version=QUALITY_ASSURANCE_PROMPT_VERSION,
        system_prompt=QUALITY_ASSURANCE_SYSTEM_PROMPT,
        allowed_tools=allowed_tools,
    )


def _item(*, status: QualityStatus) -> QualityWorkItem:
    from src.agents.contracts import SourceReference

    return QualityWorkItem(
        id="regression",
        title="Regression suite",
        work_item_type=QualityWorkItemType.RELEASE_CHECK,
        quality_status=status,
        release_id="R1",
        required=True,
        sources=(
            SourceReference(
                resource_id="quality-group",
                resource_type="conversation",
                agent_workspace_id="quality-workspace",
                classification="quality",
                captured_at=datetime.now(UTC),
            ),
        ),
    )


@pytest.mark.asyncio
async def test_release_status_tool_uses_deterministic_gate():
    result = await get_release_test_status(
        scope=_scope(),
        items=(_item(status=QualityStatus.BLOCKED),),
    )

    assert result.payload["assessment"]["release_readiness"] == "NOT_READY"


@pytest.mark.asyncio
async def test_quality_executor_revalidates_workspace_before_bound_tool():
    calls: list[tuple[str, str]] = []

    async def revalidate(workspace_id: str) -> None:
        calls.append(("workspace", workspace_id))

    async def tool(*, scope) -> ToolResult:
        calls.append(("tool", scope.release_id))
        return ToolResult(status=ToolResultStatus.SUCCESS)

    executor = QualityReadOnlyExecutor(
        tool_bindings={"get_release_test_status": tool},
        revalidate_workspace=revalidate,
    )
    result = await executor.invoke(
        prepared=_prepared(allowed_tools=("get_release_test_status",)),
        scope=_scope(),
        tool_name="get_release_test_status",
    )

    assert result.status == ToolResultStatus.SUCCESS
    assert calls == [("workspace", "quality-workspace"), ("tool", "R1")]


def test_quality_executor_refuses_delivery_or_action_binding():
    async def tool(**_: object) -> ToolResult:
        return ToolResult(status=ToolResultStatus.SUCCESS)

    with pytest.raises(QualityExecutionError, match="Non-read-only"):
        QualityReadOnlyExecutor(
            tool_bindings={"get_delivery_tasks": tool},
            revalidate_workspace=tool,
        )
