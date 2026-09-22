from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.agents.contracts import SourceReference, WorkspaceBrief
from src.agents.schemas.delivery import DeliveryItem, DeliveryReadScope, DeliveryViewScope, DeliveryWorkStatus
from src.agents.tools.delivery_brief import (
    as_delivery_brief_result,
    build_delivery_payload,
    to_workspace_brief,
)
from tests.test_agents.test_delivery_tools import _scope

NOW = datetime(2026, 8, 22, 9, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]


def _item(*, item_id: str, status: DeliveryWorkStatus, due_at: datetime | None) -> DeliveryItem:
    return DeliveryItem(
        id=item_id,
        title=item_id,
        status=status,
        assignee_id="lead-user",
        due_at=due_at,
        blocked_reason="Waiting for API" if status == DeliveryWorkStatus.BLOCKED else None,
        sources=(
            SourceReference(
                resource_id="group-apollo",
                resource_type="conversation",
                agent_workspace_id="delivery-workspace",
                classification="delivery",
                captured_at=NOW,
            ),
        ),
    )


def _workspace_scope() -> DeliveryReadScope:
    group_scope = _scope()
    context = group_scope.context.model_copy(
        update={
            "authorization": group_scope.context.authorization.model_copy(
                update={"allowed_resource_ids": ("group-apollo", "group-release")}
            )
        }
    )
    return DeliveryReadScope(
        context=context,
        view_scope=DeliveryViewScope.WORKSPACE,
        effective_group_ids=("group-apollo", "group-release"),
    )


def test_workspace_producer_classifies_items_and_maps_a_valid_common_brief():
    scope = _workspace_scope()
    payload = build_delivery_payload(
        scope=scope,
        items=(
            _item(item_id="blocked", status=DeliveryWorkStatus.BLOCKED, due_at=NOW + timedelta(days=1)),
            _item(item_id="overdue", status=DeliveryWorkStatus.IN_PROGRESS, due_at=NOW - timedelta(days=1)),
        ),
        period_start=NOW - timedelta(days=7),
        period_end=NOW,
        generated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    assert [item.id for item in payload.blocked_items] == ["blocked"]
    assert [item.id for item in payload.overdue_items] == ["overdue"]
    brief = to_workspace_brief(payload=payload, scope=scope, brief_id="brief-1", trace_id="trace-1")
    assert brief.producer_profile == "product_delivery"
    assert brief.release_readiness is None
    assert {source.resource_id for source in brief.sources} == {"group-apollo"}


def test_group_snapshot_is_valid_but_cannot_be_published_as_workspace_handoff():
    scope = _scope()
    payload = build_delivery_payload(
        scope=scope,
        items=(_item(item_id="due-soon", status=DeliveryWorkStatus.IN_PROGRESS, due_at=NOW + timedelta(days=1)),),
        period_start=NOW - timedelta(days=7),
        period_end=NOW,
        generated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    assert payload.view_scope == DeliveryViewScope.GROUP
    with pytest.raises(ValueError, match="workspace overview"):
        to_workspace_brief(payload=payload, scope=scope, brief_id="brief-2", trace_id="trace-2")


def test_empty_payload_is_partial_and_does_not_invent_sources():
    scope = _workspace_scope()
    payload = build_delivery_payload(
        scope=scope,
        items=(),
        period_start=NOW - timedelta(days=7),
        period_end=NOW,
        generated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    assert payload.data_gaps == ("NO_DELIVERY_FACTS",)
    assert payload.headline_source_ids == ()


def test_stale_brief_is_partial_and_explicitly_not_current():
    payload = build_delivery_payload(
        scope=_workspace_scope(),
        items=(_item(item_id="due-soon", status=DeliveryWorkStatus.IN_PROGRESS, due_at=NOW),),
        period_start=NOW - timedelta(days=7),
        period_end=NOW,
        generated_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
    )

    result = as_delivery_brief_result(payload=payload, checked_at=NOW + timedelta(minutes=30))

    assert result.status.value == "partial"
    assert result.payload["freshness"] == "stale"
    assert result.payload["is_current"] is False
    assert "DELIVERY_BRIEF_STALE" in result.data_gaps
    assert {source.resource_id for source in result.sources} == {"group-apollo"}


def test_fresh_brief_with_known_data_gap_remains_partial_not_currently_healthy():
    payload = build_delivery_payload(
        scope=_workspace_scope(),
        items=(),
        period_start=NOW - timedelta(days=7),
        period_end=NOW,
        generated_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
    )

    result = as_delivery_brief_result(payload=payload, checked_at=NOW)

    assert result.status.value == "partial"
    assert result.payload["freshness"] == "fresh"
    assert result.payload["is_current"] is True
    assert result.data_gaps == ("NO_DELIVERY_FACTS",)


def test_delivery_common_handoff_fixture_remains_compatible():
    fixture = ROOT / "eval" / "fixtures" / "delivery_brief_v1.json"

    brief = WorkspaceBrief.model_validate_json(fixture.read_text(encoding="utf-8"))

    assert brief.brief_type == "delivery"
    assert brief.producer_profile == "product_delivery"
    assert brief.release_readiness is None
    assert brief.brief_id == "brief-delivery-v1"
    assert brief.schema_version == "1.0"
    assert [(source.resource_id, source.agent_workspace_id) for source in brief.sources] == [
        ("group-delivery-apollo", "agent-workspace-delivery")
    ]
