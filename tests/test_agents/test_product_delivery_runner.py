from types import SimpleNamespace

import pytest

from src.agents.contracts import AgentIntent, AgentInvocationRequest, AgentProfile, RequestedScope
from src.agents.profiles.product_delivery import PRODUCT_DELIVERY_PROMPT_VERSION
from src.agents.profiles.product_delivery_runner import (
    PreparedProductDeliveryInvocation,
    ProductDeliveryPreparationError,
    prepare_product_delivery_invocation,
    resolve_prepared_delivery_read_scope,
)
from src.agents.router import AgentRoute
from src.agents.tools.registry import get_profile_registration
from tests.test_agents.test_delivery_tools import _scope


def _invocation() -> AgentInvocationRequest:
    return AgentInvocationRequest(
        message="Tổng hợp tiến độ Apollo",
        requested_scope=RequestedScope.WORKSPACE,
        target_agent_workspace_id="delivery-workspace",
    )


@pytest.mark.asyncio
async def test_delivery_runner_routes_then_builds_trusted_context_before_returning_allowlist(monkeypatch):
    calls: list[str] = []
    registration = get_profile_registration(AgentProfile.PRODUCT_DELIVERY)

    async def fake_route(*_args, **_kwargs) -> AgentRoute:
        calls.append("route")
        return AgentRoute(
            profile=AgentProfile.PRODUCT_DELIVERY,
            intent=AgentIntent.DELIVERY_BRIEF,
            requested_scope=RequestedScope.WORKSPACE,
            target_agent_workspace_id="delivery-workspace",
            prompt_version=PRODUCT_DELIVERY_PROMPT_VERSION,
            allowed_tools=registration.allowed_tools,
        )

    async def fake_context(*_args, **_kwargs):
        calls.append("context")
        return _scope().context

    monkeypatch.setattr("src.agents.profiles.product_delivery_runner.route_agent_request", fake_route)
    monkeypatch.setattr("src.agents.profiles.product_delivery_runner.build_agent_context", fake_context)

    prepared = await prepare_product_delivery_invocation(
        SimpleNamespace(),
        user_id="lead-user",
        organization_workspace_id="company-root",
        invocation=_invocation(),
    )

    assert calls == ["route", "context"]
    assert prepared.context.runtime.agent_profile == AgentProfile.PRODUCT_DELIVERY
    assert prepared.prompt_version == PRODUCT_DELIVERY_PROMPT_VERSION
    assert prepared.allowed_tools == registration.allowed_tools
    assert "build_delivery_brief" in prepared.allowed_tools
    assert "get_delivery_dependencies" in prepared.allowed_tools
    assert "get_delivery_portfolio_health" in prepared.allowed_tools
    assert "propose_delivery_reminder" not in prepared.allowed_tools
    assert "build_quality_brief" not in prepared.allowed_tools


@pytest.mark.asyncio
async def test_delivery_runner_fails_before_context_when_router_does_not_select_delivery(monkeypatch):
    async def fake_route(*_args, **_kwargs) -> AgentRoute:
        return AgentRoute(
            profile=AgentProfile.QUALITY_ASSURANCE,
            intent=AgentIntent.QUALITY_BRIEF,
            requested_scope=RequestedScope.WORKSPACE,
            target_agent_workspace_id="delivery-workspace",
            prompt_version="quality-assurance-v1",
            allowed_tools=("build_quality_brief",),
        )

    async def must_not_build_context(*_args, **_kwargs):
        raise AssertionError("Invalid route must not reach context/model preparation")

    monkeypatch.setattr("src.agents.profiles.product_delivery_runner.route_agent_request", fake_route)
    monkeypatch.setattr("src.agents.profiles.product_delivery_runner.build_agent_context", must_not_build_context)

    with pytest.raises(ProductDeliveryPreparationError, match="not Product Delivery"):
        await prepare_product_delivery_invocation(
            SimpleNamespace(),
            user_id="lead-user",
            organization_workspace_id="company-root",
            invocation=_invocation(),
        )


@pytest.mark.asyncio
async def test_prepared_delivery_scope_revalidates_workspace_then_selected_resource(monkeypatch):
    calls: list[tuple[str, str]] = []

    class PersonResult:
        def scalars(self):
            return self

        def all(self):
            return ["lead-user"]

    class ScopeDatabase:
        async def execute(self, _statement):
            return PersonResult()

    async def revalidate_workspace(_db, *, context, agent_workspace_id: str) -> None:
        assert context == _scope().context
        calls.append(("workspace", agent_workspace_id))

    async def revalidate_resource(_db, *, context, resource_id: str) -> None:
        assert context == _scope().context
        calls.append(("resource", resource_id))

    monkeypatch.setattr(
        "src.agents.profiles.product_delivery_runner.enforce_agent_workspace_access",
        revalidate_workspace,
    )
    monkeypatch.setattr(
        "src.agents.profiles.product_delivery_runner.enforce_agent_resource_access",
        revalidate_resource,
    )

    prepared = PreparedProductDeliveryInvocation(
        context=_scope().context,
        prompt_version=PRODUCT_DELIVERY_PROMPT_VERSION,
        system_prompt="fixture prompt",
        allowed_tools=get_profile_registration(AgentProfile.PRODUCT_DELIVERY).allowed_tools,
    )
    scope = await resolve_prepared_delivery_read_scope(
        ScopeDatabase(),
        prepared=prepared,
        requested_conversation_id="group-apollo",
    )

    assert calls == [("workspace", "delivery-workspace"), ("resource", "group-apollo")]
    assert scope.selected_conversation_id == "group-apollo"
    assert scope.allowed_person_ids == ("lead-user",)
