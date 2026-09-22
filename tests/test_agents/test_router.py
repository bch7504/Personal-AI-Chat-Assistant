from types import SimpleNamespace

import pytest

from src.agents.contracts import (
    AgentIntent,
    AgentInvocationRequest,
    AgentProfile,
    PolicyReason,
    RequestedScope,
)
from src.agents.router import AgentRouteDeniedError, route_agent_request
from src.agents.tools.registry import (
    assert_tool_allowed,
    get_profile_registration,
    list_profile_registrations,
)


class FakeSession:
    def __init__(self, workspace=None):
        self.workspace = workspace

    async def get(self, _model, _identifier):
        return self.workspace


def _invocation(scope: RequestedScope, target: str | None = None) -> AgentInvocationRequest:
    return AgentInvocationRequest(
        message="Tạo brief",
        requested_scope=scope,
        target_agent_workspace_id=target,
    )


@pytest.mark.asyncio
async def test_router_selects_specialist_from_trusted_workspace_profile():
    db = FakeSession(
        SimpleNamespace(
            id="quality-1",
            organization_workspace_id="organization-1",
            agent_profile="quality_assurance",
            status="active",
        )
    )
    route = await route_agent_request(
        db,
        organization_workspace_id="organization-1",
        invocation=_invocation(RequestedScope.WORKSPACE, "quality-1"),
        intent=AgentIntent.QUALITY_BRIEF,
    )
    assert route.profile == AgentProfile.QUALITY_ASSURANCE
    assert route.prompt_version == "quality-assurance-v3"
    assert "build_quality_brief" in route.allowed_tools
    assert "build_delivery_brief" not in route.allowed_tools


@pytest.mark.asyncio
async def test_router_rejects_intent_profile_mismatch():
    db = FakeSession(
        SimpleNamespace(
            id="delivery-1",
            organization_workspace_id="organization-1",
            agent_profile="product_delivery",
            status="active",
        )
    )
    with pytest.raises(AgentRouteDeniedError) as error:
        await route_agent_request(
            db,
            organization_workspace_id="organization-1",
            invocation=_invocation(RequestedScope.WORKSPACE, "delivery-1"),
            intent=AgentIntent.QUALITY_BRIEF,
        )
    assert error.value.reason == PolicyReason.PROFILE_MISMATCH


@pytest.mark.asyncio
async def test_router_rejects_workspace_from_another_organization():
    db = FakeSession(
        SimpleNamespace(
            id="delivery-1",
            organization_workspace_id="organization-2",
            agent_profile="product_delivery",
            status="active",
        )
    )
    with pytest.raises(AgentRouteDeniedError) as error:
        await route_agent_request(
            db,
            organization_workspace_id="organization-1",
            invocation=_invocation(RequestedScope.WORKSPACE, "delivery-1"),
            intent=AgentIntent.DELIVERY_BRIEF,
        )
    assert error.value.reason == PolicyReason.WRONG_WORKSPACE


@pytest.mark.asyncio
async def test_router_selects_personal_and_executive_without_client_profile():
    personal = await route_agent_request(
        FakeSession(),
        organization_workspace_id="organization-1",
        invocation=_invocation(RequestedScope.PERSONAL),
        intent=AgentIntent.PERSONAL_ASSISTANCE,
    )
    executive = await route_agent_request(
        FakeSession(),
        organization_workspace_id="organization-1",
        invocation=_invocation(RequestedScope.AGGREGATE),
        intent=AgentIntent.EXECUTIVE_BRIEF,
    )
    assert personal.profile == AgentProfile.PERSONAL
    assert executive.profile == AgentProfile.EXECUTIVE


def test_registry_has_one_strict_allowlist_per_profile():
    registrations = list_profile_registrations()
    assert {registration.profile for registration in registrations} == set(AgentProfile)
    assert_tool_allowed(AgentProfile.PRODUCT_DELIVERY, "build_delivery_brief")
    with pytest.raises(PermissionError, match="not allowed"):
        assert_tool_allowed(AgentProfile.PRODUCT_DELIVERY, "build_quality_brief")
    assert get_profile_registration(AgentProfile.EXECUTIVE).allowed_scopes == (
        RequestedScope.AGGREGATE,
    )
