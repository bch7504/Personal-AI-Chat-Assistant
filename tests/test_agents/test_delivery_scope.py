import pytest
from pydantic import ValidationError

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
)
from src.agents.schemas.delivery import DeliveryReadScope, DeliveryViewScope
from src.api.delivery_routes import _delivery_thread_scope_hash
from src.services.delivery_workspace_service import (
    DeliveryScopeError,
    build_delivery_query_scope,
    resolve_delivery_read_scope,
)


def _context(
    *,
    role: BusinessRole = BusinessRole.LEAD,
    resources: tuple[str, ...] = ("group-apollo", "group-release"),
) -> AgentContext:
    return AgentContext(
        trace_id="trace-delivery-scope",
        actor=ActorContext(
            user_id="user-lead",
            organization_workspace_id="company-root",
            business_role=role,
            agent_workspace_ids=("delivery-workspace",),
        ),
        request=AgentRequestContext(
            text="Show Delivery status",
            intent=AgentIntent.DELIVERY_BRIEF,
            requested_scope=RequestedScope.WORKSPACE,
            target_agent_workspace_id="delivery-workspace",
        ),
        authorization=AuthorizationContext(
            decision=PolicyDecision.ALLOW,
            reason=PolicyReason.ALLOWED,
            allowed_agent_workspace_ids=("delivery-workspace",),
            allowed_resource_ids=resources,
            consent_scope_hash="scope-hash",
        ),
        runtime=AgentRuntimeContext(
            agent_profile=AgentProfile.PRODUCT_DELIVERY,
            prompt_version="product-delivery-v1",
        ),
    )


def test_lead_workspace_overview_uses_exactly_the_resolved_group_allowlist():
    scope = DeliveryReadScope(
        context=_context(),
        view_scope=DeliveryViewScope.WORKSPACE,
        effective_group_ids=("group-apollo", "group-release"),
        allowed_task_ids=("task-1",),
    )

    query_scope = build_delivery_query_scope(scope)

    assert query_scope.organization_workspace_id == "company-root"
    assert query_scope.group_ids == ("group-apollo", "group-release")
    assert query_scope.requires_resource_bound_query()


def test_group_snapshot_can_only_narrow_to_one_authorized_group():
    scope = DeliveryReadScope(
        context=_context(),
        view_scope=DeliveryViewScope.GROUP,
        effective_group_ids=("group-apollo",),
        selected_conversation_id="group-apollo",
    )

    assert build_delivery_query_scope(scope).group_ids == ("group-apollo",)

    with pytest.raises(ValidationError, match="subset"):
        DeliveryReadScope(
            context=_context(),
            view_scope=DeliveryViewScope.GROUP,
            effective_group_ids=("group-qa",),
            selected_conversation_id="group-qa",
        )


def test_workspace_agent_memory_hash_changes_when_lead_switches_group_scope():
    apollo = DeliveryReadScope(
        context=_context(),
        view_scope=DeliveryViewScope.GROUP,
        effective_group_ids=("group-apollo",),
        selected_conversation_id="group-apollo",
    )
    release = DeliveryReadScope(
        context=_context(),
        view_scope=DeliveryViewScope.GROUP,
        effective_group_ids=("group-release",),
        selected_conversation_id="group-release",
    )

    assert _delivery_thread_scope_hash(consent_scope_hash="scope-hash", scope=apollo) != (
        _delivery_thread_scope_hash(consent_scope_hash="scope-hash", scope=release)
    )


def test_member_cannot_request_workspace_overview_but_can_use_member_view():
    member_context = _context(role=BusinessRole.MEMBER, resources=("group-apollo",))

    with pytest.raises(ValidationError, match="Delivery lead"):
        DeliveryReadScope(
            context=member_context,
            view_scope=DeliveryViewScope.WORKSPACE,
            effective_group_ids=("group-apollo",),
        )

    member_scope = DeliveryReadScope(
        context=member_context,
        view_scope=DeliveryViewScope.MEMBER,
        effective_group_ids=("group-apollo",),
        allowed_task_ids=("task-member-1",),
    )
    assert build_delivery_query_scope(member_scope).task_ids == ("task-member-1",)


def test_empty_scope_has_no_resource_predicate_for_a_tool_to_query():
    empty_scope = DeliveryReadScope(
        context=_context(resources=()),
        view_scope=DeliveryViewScope.WORKSPACE,
    )

    assert not build_delivery_query_scope(empty_scope).requires_resource_bound_query()


@pytest.mark.asyncio
async def test_server_resolver_issues_a_lead_group_capability_only_after_revalidation():
    workspace_checks: list[str] = []
    resource_checks: list[str] = []

    async def revalidate_workspace(workspace_id: str) -> None:
        workspace_checks.append(workspace_id)

    async def revalidate_resource(resource_id: str) -> None:
        resource_checks.append(resource_id)

    scope = await resolve_delivery_read_scope(
        context=_context(),
        requested_conversation_id="group-apollo",
        revalidate_workspace=revalidate_workspace,
        revalidate_resource=revalidate_resource,
    )

    assert workspace_checks == ["delivery-workspace"]
    assert resource_checks == ["group-apollo"]
    assert scope.view_scope == DeliveryViewScope.GROUP
    assert scope.effective_group_ids == ("group-apollo",)


@pytest.mark.asyncio
async def test_server_resolver_allows_member_to_read_an_authorized_group_snapshot():
    resource_checks: list[str] = []

    async def revalidate_workspace(_: str) -> None:
        return None

    async def revalidate_resource(resource_id: str) -> None:
        resource_checks.append(resource_id)

    scope = await resolve_delivery_read_scope(
        context=_context(role=BusinessRole.MEMBER, resources=("group-apollo",)),
        requested_conversation_id="group-apollo",
        revalidate_workspace=revalidate_workspace,
        revalidate_resource=revalidate_resource,
    )

    assert resource_checks == ["group-apollo"]
    assert scope.view_scope == DeliveryViewScope.GROUP
    assert scope.effective_group_ids == ("group-apollo",)
    assert scope.selected_conversation_id == "group-apollo"


@pytest.mark.asyncio
async def test_server_resolver_rejects_member_group_outside_authorized_channels():
    async def revalidate_workspace(_: str) -> None:
        return None

    async def revalidate_resource(_: str) -> None:
        raise DeliveryScopeError("Delivery resource is outside the authorized scope")

    with pytest.raises(DeliveryScopeError, match="outside"):
        await resolve_delivery_read_scope(
            context=_context(role=BusinessRole.MEMBER, resources=("group-apollo",)),
            requested_conversation_id="group-release",
            revalidate_workspace=revalidate_workspace,
            revalidate_resource=revalidate_resource,
        )
