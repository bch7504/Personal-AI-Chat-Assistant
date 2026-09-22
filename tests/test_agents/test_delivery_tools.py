from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

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
    SourceReference,
    ToolResultStatus,
)
from src.agents.profiles.product_delivery import PRODUCT_DELIVERY_PROMPT_VERSION
from src.agents.schemas.delivery import DeliveryItem, DeliveryReadScope, DeliveryViewScope, DeliveryWorkStatus
from src.agents.tools.delivery_tasks import get_delivery_tasks
from src.services.delivery_workspace_service import DeliveryQueryScope, DeliveryScopeError

NOW = datetime(2026, 8, 22, 9, tzinfo=UTC)


def _scope() -> DeliveryReadScope:
    context = AgentContext(
        trace_id="trace-delivery-tool",
        actor=ActorContext(
            user_id="lead-user",
            organization_workspace_id="company-root",
            business_role=BusinessRole.LEAD,
            agent_workspace_ids=("delivery-workspace",),
        ),
        request=AgentRequestContext(
            text="Show Apollo status",
            intent=AgentIntent.DELIVERY_BRIEF,
            requested_scope=RequestedScope.WORKSPACE,
            target_agent_workspace_id="delivery-workspace",
        ),
        authorization=AuthorizationContext(
            decision=PolicyDecision.ALLOW,
            reason=PolicyReason.ALLOWED,
            allowed_agent_workspace_ids=("delivery-workspace",),
            allowed_resource_ids=("group-apollo",),
            consent_scope_hash="scope-hash",
        ),
        runtime=AgentRuntimeContext(
            agent_profile=AgentProfile.PRODUCT_DELIVERY,
            prompt_version=PRODUCT_DELIVERY_PROMPT_VERSION,
        ),
    )
    return DeliveryReadScope(
        context=context,
        view_scope=DeliveryViewScope.GROUP,
        effective_group_ids=("group-apollo",),
        selected_conversation_id="group-apollo",
    )


def _item(source_id: str = "group-apollo") -> DeliveryItem:
    return DeliveryItem(
        id="task-apollo-1",
        title="Confirm API contract",
        status=DeliveryWorkStatus.IN_PROGRESS,
        assignee_id="lead-user",
        due_at=NOW + timedelta(days=1),
        sources=(
            SourceReference(
                resource_id=source_id,
                resource_type="conversation",
                agent_workspace_id="delivery-workspace",
                classification="delivery",
                captured_at=NOW,
            ),
        ),
    )


class _Repository:
    def __init__(self, items: Sequence[DeliveryItem] = ()) -> None:
        self.items = items
        self.scopes: list[DeliveryQueryScope] = []

    async def list_tasks(self, scope: DeliveryQueryScope) -> Sequence[DeliveryItem]:
        self.scopes.append(scope)
        return self.items


@pytest.mark.asyncio
async def test_task_tool_revalidates_scope_and_returns_evidence_backed_items():
    repository = _Repository((_item(),))
    revalidated: list[str] = []

    async def revalidate(resource_id: str) -> None:
        revalidated.append(resource_id)

    result = await get_delivery_tasks(
        scope=_scope(), repository=repository, revalidate_resource=revalidate
    )

    assert revalidated == ["group-apollo"]
    assert repository.scopes[0].group_ids == ("group-apollo",)
    assert result.status == ToolResultStatus.SUCCESS
    assert result.sources[0].resource_id == "group-apollo"
    assert result.payload["items"][0]["id"] == "task-apollo-1"


@pytest.mark.asyncio
async def test_task_tool_rejects_returned_sources_outside_effective_scope():
    repository = _Repository((_item(source_id="group-qa"),))

    async def revalidate(_: str) -> None:
        return None

    with pytest.raises(DeliveryScopeError, match="outside Delivery scope"):
        await get_delivery_tasks(scope=_scope(), repository=repository, revalidate_resource=revalidate)


@pytest.mark.asyncio
async def test_task_tool_normalizes_repository_outage_without_leaking_exception_details():
    class FailingRepository:
        async def list_tasks(self, scope: DeliveryQueryScope) -> Sequence[DeliveryItem]:
            raise TimeoutError("database endpoint details must not reach the model")

    async def revalidate(_: str) -> None:
        return None

    result = await get_delivery_tasks(
        scope=_scope(), repository=FailingRepository(), revalidate_resource=revalidate
    )

    assert result.status == ToolResultStatus.ERROR
    assert result.error_code == "DELIVERY_TASK_READ_FAILED"
    assert "endpoint" not in (result.error_message or "")


@pytest.mark.asyncio
async def test_task_tool_returns_empty_without_calling_repository_when_scope_has_no_resources():
    context = _scope().context.model_copy(
        update={
            "authorization": _scope().context.authorization.model_copy(
                update={"allowed_resource_ids": ()}
            )
        }
    )
    empty_scope = DeliveryReadScope(context=context, view_scope=DeliveryViewScope.WORKSPACE)
    repository = _Repository((_item(),))

    async def revalidate(_: str) -> None:
        raise AssertionError("No resource may be revalidated for an empty scope")

    result = await get_delivery_tasks(
        scope=empty_scope, repository=repository, revalidate_resource=revalidate
    )

    assert result.status == ToolResultStatus.SUCCESS
    assert result.payload == {"items": []}
    assert repository.scopes == []
