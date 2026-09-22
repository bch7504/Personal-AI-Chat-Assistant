from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from src.agents.contracts import (
    ActionProposal,
    ActorContext,
    AgentContext,
    AgentIntent,
    AgentInvocationRequest,
    AgentProfile,
    AgentRequestContext,
    AgentRuntimeContext,
    AuthorizationContext,
    BriefType,
    BusinessRole,
    ExecutiveBrief,
    PolicyDecision,
    PolicyReason,
    ReleaseReadiness,
    RequestedScope,
    SourceReference,
    ToolResult,
    ToolResultStatus,
    WorkspaceBrief,
    action_payload_hash,
)


def _context(**authorization_overrides) -> AgentContext:
    authorization = {
        "decision": PolicyDecision.ALLOW,
        "reason": PolicyReason.ALLOWED,
        "allowed_agent_workspace_ids": ("delivery-1",),
        "allowed_resource_ids": ("task-1", "conversation-1"),
        "consent_scope_hash": "consent-hash",
    }
    authorization.update(authorization_overrides)
    return AgentContext(
        trace_id="trace-1",
        actor=ActorContext(
            user_id="user-1",
            organization_workspace_id="organization-1",
            business_role=BusinessRole.LEAD,
            agent_workspace_ids=("delivery-1",),
        ),
        request=AgentRequestContext(
            text="Tình hình delivery tuần này?",
            intent=AgentIntent.DELIVERY_BRIEF,
            requested_scope=RequestedScope.WORKSPACE,
            target_agent_workspace_id="delivery-1",
        ),
        authorization=AuthorizationContext(**authorization),
        runtime=AgentRuntimeContext(
            agent_profile=AgentProfile.PRODUCT_DELIVERY,
            prompt_version="product-delivery-v1",
        ),
    )


def test_agent_context_is_strict_immutable_and_json_serializable():
    context = _context()

    payload = context.model_dump(mode="json")

    assert payload["runtime"]["agent_profile"] == "product_delivery"
    assert payload["authorization"]["decision"] == "ALLOW"
    assert payload["authorization"]["allowed_resource_ids"] == ["task-1", "conversation-1"]
    with pytest.raises(ValidationError):
        context.trace_id = "tampered"


def test_denied_context_cannot_carry_allowed_capabilities():
    with pytest.raises(ValidationError, match="cannot include allowed capabilities"):
        AuthorizationContext(
            decision=PolicyDecision.DENY,
            reason=PolicyReason.NOT_MEMBER,
            allowed_resource_ids=("private-message-1",),
        )


def test_target_workspace_must_be_inside_resolved_scope():
    with pytest.raises(ValidationError, match="outside the resolved authorization scope"):
        AgentContext(
            trace_id="trace-2",
            actor=ActorContext(
                user_id="user-1",
                organization_workspace_id="organization-1",
                business_role=BusinessRole.LEAD,
                agent_workspace_ids=("delivery-1",),
            ),
            request=AgentRequestContext(
                text="Đọc workspace khách hàng",
                intent=AgentIntent.QUALITY_BRIEF,
                requested_scope=RequestedScope.WORKSPACE,
                target_agent_workspace_id="quality-1",
            ),
            authorization=AuthorizationContext(
                decision=PolicyDecision.ALLOW,
                reason=PolicyReason.ALLOWED,
                allowed_agent_workspace_ids=("delivery-1",),
            ),
            runtime=AgentRuntimeContext(
                agent_profile=AgentProfile.QUALITY_ASSURANCE,
                prompt_version="quality-assurance-v1",
            ),
        )


@pytest.mark.parametrize("spoofed_field", ["business_role", "agent_profile", "allowed_resource_ids"])
def test_untrusted_request_rejects_server_authorization_fields(spoofed_field):
    payload = {"message": "hello", spoofed_field: "spoofed"}

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AgentInvocationRequest.model_validate(payload)


def _source(*, workspace_id: str = "quality-1") -> SourceReference:
    return SourceReference(
        resource_id="quality-task-1",
        resource_type="task",
        agent_workspace_id=workspace_id,
        classification="internal",
        captured_at=datetime(2026, 8, 18, 8, tzinfo=UTC),
    )


def test_tool_result_requires_consistent_status_metadata():
    result = ToolResult(
        status=ToolResultStatus.PARTIAL,
        payload={"items": []},
        sources=(_source(),),
        data_gaps=("Release check is missing",),
    )
    assert result.schema_version == "1.0"

    with pytest.raises(ValidationError, match="partial tool result requires"):
        ToolResult(status=ToolResultStatus.PARTIAL)

    with pytest.raises(ValidationError, match="requires error_code"):
        ToolResult(status=ToolResultStatus.ERROR, error_message="timeout")


def test_action_proposal_binds_payload_hash_and_expiry():
    created_at = datetime(2026, 8, 18, 8, tzinfo=UTC)
    payload = {"target": "quality-lead", "title": "Review release blocker"}
    proposal = ActionProposal(
        proposal_id="proposal-1",
        trace_id="trace-1",
        actor_user_id="executive-1",
        action="propose_meeting",
        payload=payload,
        payload_hash=action_payload_hash(payload),
        idempotency_key="trace-1:proposal-1",
        created_at=created_at,
        expires_at=created_at + timedelta(minutes=15),
    )
    assert proposal.is_expired(at=created_at + timedelta(minutes=16)) is True

    with pytest.raises(ValidationError, match="does not match"):
        ActionProposal.model_validate(
            {
                **proposal.model_dump(),
                "payload_hash": "0" * 64,
            }
        )


def test_workspace_brief_enforces_profile_sources_and_freshness():
    generated_at = datetime(2026, 8, 18, 8, tzinfo=UTC)
    brief = WorkspaceBrief(
        brief_id="quality-brief-1",
        trace_id="trace-1",
        organization_workspace_id="organization-1",
        agent_workspace_id="quality-1",
        brief_type=BriefType.QUALITY,
        producer_profile=AgentProfile.QUALITY_ASSURANCE,
        period_start=generated_at - timedelta(days=7),
        period_end=generated_at,
        generated_at=generated_at,
        expires_at=generated_at + timedelta(hours=4),
        headline="Release is at risk",
        facts=({"summary": "Two failed tests", "source_ids": ["quality-task-1"]},),
        sources=(_source(),),
        release_readiness=ReleaseReadiness.AT_RISK,
    )
    assert brief.is_stale(at=generated_at + timedelta(hours=5)) is True

    with pytest.raises(ValidationError, match="do not match"):
        WorkspaceBrief.model_validate(
            {
                **brief.model_dump(),
                "producer_profile": AgentProfile.PRODUCT_DELIVERY,
            }
        )
    with pytest.raises(ValidationError, match="producing agent workspace"):
        WorkspaceBrief.model_validate(
            {
                **brief.model_dump(),
                "sources": [_source(workspace_id="delivery-1").model_dump()],
            }
        )
    with pytest.raises(ValidationError, match="requires release_readiness"):
        WorkspaceBrief.model_validate({**brief.model_dump(), "release_readiness": None})
    with pytest.raises(ValidationError, match="cannot contain data gaps"):
        WorkspaceBrief.model_validate(
            {
                **brief.model_dump(),
                "release_readiness": ReleaseReadiness.READY,
                "data_gaps": ["Release evidence is incomplete"],
            }
        )
    with pytest.raises(ValidationError, match="requires at least one source"):
        WorkspaceBrief.model_validate({**brief.model_dump(), "sources": []})


def test_executive_brief_requires_briefs_or_an_explicit_data_gap():
    payload = {
        "brief_id": "executive-brief-1",
        "trace_id": "trace-1",
        "organization_workspace_id": "organization-1",
        "generated_at": datetime(2026, 8, 18, 8, tzinfo=UTC),
        "workspace_brief_ids": (),
        "headline": "No current specialist data",
    }
    with pytest.raises(ValidationError, match="must report a data gap"):
        ExecutiveBrief(**payload)

    brief = ExecutiveBrief(**payload, data_gaps=("Quality brief is stale",))
    assert brief.workspace_brief_ids == ()
