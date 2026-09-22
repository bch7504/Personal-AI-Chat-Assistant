from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from scripts.generate_multi_agent_dataset import build_cases
from src.agents.contracts import AgentIntent, AgentProfile, RequestedScope, SourceReference
from src.agents.profiles.product_delivery import (
    PRODUCT_DELIVERY_PROMPT_VERSION,
    PRODUCT_DELIVERY_SYSTEM_PROMPT,
    accepts_product_delivery_context,
)
from src.agents.schemas.delivery import (
    DeliveryBriefPayload,
    DeliveryHealth,
    DeliveryItem,
    DeliveryViewScope,
    DeliveryWorkStatus,
    classify_delivery_item,
)

NOW = datetime(2026, 8, 22, 9, tzinfo=UTC)


def _source(resource_id: str = "conversation-1") -> SourceReference:
    return SourceReference(
        resource_id=resource_id,
        resource_type="conversation",
        agent_workspace_id="delivery-workspace",
        classification="delivery",
        captured_at=NOW,
    )


def _item(**overrides) -> DeliveryItem:
    values = {
        "id": "task-1",
        "title": "Publish API contract",
        "status": DeliveryWorkStatus.IN_PROGRESS,
        "assignee_id": "user-1",
        "due_at": NOW + timedelta(days=2),
        "sources": (_source(),),
    }
    values.update(overrides)
    return DeliveryItem(**values)


def test_profile_accepts_only_its_trusted_capability_tuple():
    assert accepts_product_delivery_context(
        profile=AgentProfile.PRODUCT_DELIVERY,
        scope=RequestedScope.WORKSPACE,
        intent=AgentIntent.DELIVERY_BRIEF,
    )
    assert not accepts_product_delivery_context(
        profile=AgentProfile.QUALITY_ASSURANCE,
        scope=RequestedScope.WORKSPACE,
        intent=AgentIntent.DELIVERY_BRIEF,
    )
    assert not accepts_product_delivery_context(
        profile=AgentProfile.PRODUCT_DELIVERY,
        scope=RequestedScope.PERSONAL,
        intent=AgentIntent.DELIVERY_BRIEF,
    )


def test_prompt_has_evidence_and_no_scope_expansion_guardrails():
    assert PRODUCT_DELIVERY_PROMPT_VERSION == "product-delivery-v6"
    assert "Never expand the resource allowlist" in PRODUCT_DELIVERY_SYSTEM_PROMPT
    assert "SourceReference" in PRODUCT_DELIVERY_SYSTEM_PROMPT
    assert "durable proposal and" in PRODUCT_DELIVERY_SYSTEM_PROMPT
    assert "Quality acceptance is a" in PRODUCT_DELIVERY_SYSTEM_PROMPT
    assert "You are not a general-purpose assistant" in PRODUCT_DELIVERY_SYSTEM_PROMPT
    assert "politics, geopolitics, territorial sovereignty" in PRODUCT_DELIVERY_SYSTEM_PROMPT
    assert "typed, hash-validated handoffs" in PRODUCT_DELIVERY_SYSTEM_PROMPT
    assert "Final-answer self-check" in PRODUCT_DELIVERY_SYSTEM_PROMPT


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        (_item(due_at=NOW - timedelta(seconds=1)), (DeliveryHealth.OVERDUE,)),
        (_item(due_at=NOW + timedelta(days=7)), (DeliveryHealth.DUE_SOON,)),
        (_item(due_at=NOW + timedelta(days=8)), (DeliveryHealth.ON_TRACK,)),
        (_item(assignee_id=None), (DeliveryHealth.UNASSIGNED, DeliveryHealth.DUE_SOON)),
        (
            _item(status=DeliveryWorkStatus.BLOCKED, blocked_reason="Waiting for platform"),
            (DeliveryHealth.BLOCKED, DeliveryHealth.DUE_SOON),
        ),
        (_item(status=DeliveryWorkStatus.COMPLETED, due_at=NOW - timedelta(days=1)), (DeliveryHealth.ON_TRACK,)),
        (_item(due_at=None), (DeliveryHealth.DATA_GAP,)),
    ],
)
def test_classify_delivery_item_has_deterministic_boundaries(item, expected):
    assert classify_delivery_item(item, now=NOW).health == expected


def test_blocked_item_requires_a_reason():
    with pytest.raises(ValidationError, match="blocked_reason"):
        _item(status=DeliveryWorkStatus.BLOCKED)


def test_delivery_item_rejects_naive_deadline_and_missing_source():
    with pytest.raises(ValidationError, match="due_at"):
        _item(due_at=datetime(2026, 8, 23, 9))
    with pytest.raises(ValidationError):
        _item(sources=())


def test_delivery_brief_requires_evidence_and_workspace_matched_sources():
    item = _item()
    payload = DeliveryBriefPayload(
        agent_workspace_id="delivery-workspace",
        period_start=NOW - timedelta(days=7),
        period_end=NOW,
        generated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        headline="One API dependency needs a decision.",
        headline_source_ids=("conversation-1",),
        due_soon_items=(item,),
        recommendations=(
            {"text": "Confirm the API contract owner.", "based_on_source_ids": ("conversation-1",)},
        ),
    )

    assert payload.due_soon_items == (item,)

    with pytest.raises(ValidationError, match="headline_source_ids"):
        DeliveryBriefPayload(
            agent_workspace_id="delivery-workspace",
            period_start=NOW - timedelta(days=7),
            period_end=NOW,
            generated_at=NOW,
            expires_at=NOW + timedelta(hours=1),
            headline="Ungrounded claim",
            headline_source_ids=("unknown-source",),
            due_soon_items=(item,),
        )


def test_delivery_brief_rejects_release_readiness_and_unknown_fields():
    with pytest.raises(ValidationError):
        DeliveryBriefPayload(
            agent_workspace_id="delivery-workspace",
            period_start=NOW - timedelta(days=7),
            period_end=NOW,
            generated_at=NOW,
            expires_at=NOW + timedelta(hours=1),
            headline="No evidence",
            headline_source_ids=("conversation-1",),
            release_readiness="READY",
        )


def test_empty_delivery_brief_reports_data_gap_without_inventing_a_source():
    payload = DeliveryBriefPayload(
        agent_workspace_id="delivery-workspace",
        period_start=NOW - timedelta(days=7),
        period_end=NOW,
        generated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        headline="No Delivery source is currently available.",
        data_gaps=("NO_CONSENTED_DELIVERY_SOURCE",),
    )

    assert payload.headline_source_ids == ()

    with pytest.raises(ValidationError, match="data gap"):
        DeliveryBriefPayload(
            agent_workspace_id="delivery-workspace",
            period_start=NOW - timedelta(days=7),
            period_end=NOW,
            generated_at=NOW,
            expires_at=NOW + timedelta(hours=1),
            headline="No evidence",
        )


def test_brief_rejects_items_in_an_incorrect_health_bucket():
    with pytest.raises(ValidationError, match="overdue"):
        DeliveryBriefPayload(
            agent_workspace_id="delivery-workspace",
            period_start=NOW - timedelta(days=7),
            period_end=NOW,
            generated_at=NOW,
            expires_at=NOW + timedelta(hours=1),
            headline="One task is overdue.",
            headline_source_ids=("conversation-1",),
            overdue_items=(_item(due_at=NOW + timedelta(days=1)),),
        )


def test_group_snapshot_requires_exactly_one_selected_conversation():
    values = {
        "agent_workspace_id": "delivery-workspace",
        "view_scope": DeliveryViewScope.GROUP,
        "period_start": NOW - timedelta(days=7),
        "period_end": NOW,
        "generated_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
        "headline": "One scoped group is at risk.",
        "headline_source_ids": ("conversation-1",),
        "due_soon_items": (_item(),),
    }
    with pytest.raises(ValidationError, match="conversation_id"):
        DeliveryBriefPayload(**values)

    snapshot = DeliveryBriefPayload(**(values | {"conversation_id": "conversation-1"}))
    assert snapshot.view_scope == DeliveryViewScope.GROUP
    assert snapshot.conversation_id == "conversation-1"

    with pytest.raises(ValidationError, match="conversation_id"):
        DeliveryBriefPayload(**(values | {"view_scope": DeliveryViewScope.MEMBER, "conversation_id": "conversation-1"}))


def test_delivery_golden_cases_map_to_supported_rules_and_source_requirements():
    cases = [case for case in build_cases() if case["category"] == "delivery_summary"]
    expected_statuses = {"blocked", "overdue", "due_soon", "in_progress", "unassigned"}

    assert len(cases) == 15
    for case in cases:
        expected = case["expected"]
        assert expected["agent_profile"] == AgentProfile.PRODUCT_DELIVERY.value
        assert expected["expected_action"] == "build_delivery_brief"
        assert len(expected["required_source_ids"]) == 2
        status = expected["expected_facts"][0].rsplit(":", maxsplit=1)[1]
        assert status in expected_statuses
