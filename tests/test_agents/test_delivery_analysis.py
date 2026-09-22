from datetime import UTC, datetime, timedelta

import pytest

from src.agents.contracts import SourceReference, ToolResultStatus
from src.agents.schemas.delivery import (
    DeliveryDecision,
    DeliveryDependency,
    DeliveryDependencyStatus,
    DeliveryItem,
    DeliveryPortfolioHealth,
    DeliveryReleaseStatus,
    DeliveryWorkStatus,
    evaluate_delivery_portfolio,
)
from src.agents.tools.delivery_analysis import (
    get_delivery_capacity_summary,
    get_delivery_dependencies,
    get_delivery_flow_metrics,
)
from src.services.delivery_workspace_service import DeliveryScopeError
from tests.test_agents.test_delivery_tools import _scope

NOW = datetime(2026, 8, 25, 9, tzinfo=UTC)


def _source() -> tuple[SourceReference, ...]:
    return (
        SourceReference(
            resource_id="group-apollo",
            resource_type="conversation",
            agent_workspace_id="delivery-workspace",
            classification="delivery",
            captured_at=NOW,
        ),
    )


def _item(
    *,
    status: DeliveryWorkStatus,
    due_at: datetime | None = None,
    created_at: datetime | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> DeliveryItem:
    return DeliveryItem(
        id=f"item-{status.value}",
        title=f"Item {status.value}",
        status=status,
        assignee_id="lead-user",
        due_at=due_at,
        created_at=created_at,
        started_at=started_at,
        completed_at=completed_at,
        blocked_reason="External contract is unavailable"
        if status == DeliveryWorkStatus.BLOCKED
        else None,
        sources=_source(),
    )


def test_portfolio_health_is_blocked_by_explicit_blocker_and_qa_rejection():
    assessment = evaluate_delivery_portfolio(
        items=(_item(status=DeliveryWorkStatus.BLOCKED, due_at=NOW),),
        dependencies=(
            DeliveryDependency(
                id="dep-1",
                title="External API",
                status=DeliveryDependencyStatus.BLOCKED,
                sources=_source(),
            ),
        ),
        decisions=(
            DeliveryDecision(id="decision-1", title="Select API", sources=_source()),
        ),
        releases=(
            DeliveryReleaseStatus(
                id="release-1",
                release_key="R-42",
                status="rejected",
                quality_policy_version="quality-gate-v1",
                sources=_source(),
            ),
        ),
        now=NOW,
    )

    assert assessment.health == DeliveryPortfolioHealth.BLOCKED
    assert "WORK_ITEM_BLOCKED" in assessment.reasons
    assert "QA_RELEASE_REJECTED" in assessment.reasons


def test_portfolio_health_is_at_risk_for_overdue_work_without_blocker():
    assessment = evaluate_delivery_portfolio(
        items=(
            _item(
                status=DeliveryWorkStatus.IN_PROGRESS,
                due_at=NOW - timedelta(hours=1),
            ),
        ),
        now=NOW,
    )

    assert assessment.health == DeliveryPortfolioHealth.AT_RISK
    assert assessment.reasons == ("WORK_ITEM_OVERDUE",)


def test_empty_portfolio_fails_closed_as_insufficient_data():
    assessment = evaluate_delivery_portfolio(items=(), now=NOW)

    assert assessment.health == DeliveryPortfolioHealth.INSUFFICIENT_DATA
    assert assessment.data_gaps == ("NO_DELIVERY_FACTS",)


@pytest.mark.asyncio
async def test_capacity_is_aggregate_and_does_not_score_people():
    result = await get_delivery_capacity_summary(
        scope=_scope(),
        items=(
            _item(status=DeliveryWorkStatus.IN_PROGRESS, due_at=NOW + timedelta(days=2)),
            _item(status=DeliveryWorkStatus.PENDING, due_at=NOW - timedelta(days=1)),
        ),
        now=NOW,
    )

    assert result.status == ToolResultStatus.SUCCESS
    assert result.payload["capacity"]["total_active"] == 2
    assert "productivity" not in result.model_dump_json().casefold()
    assert "score" not in result.model_dump_json().casefold()


@pytest.mark.asyncio
async def test_flow_metrics_report_no_completed_history_instead_of_fabricating_cycle_time():
    result = await get_delivery_flow_metrics(
        scope=_scope(),
        items=(_item(status=DeliveryWorkStatus.IN_PROGRESS, due_at=NOW),),
        now=NOW,
    )

    assert result.status == ToolResultStatus.PARTIAL
    assert result.payload["flow_metrics"]["cycle_time_hours_p50"] is None
    assert result.payload["flow_metrics"]["completed_in_period"] == 0
    assert result.data_gaps == ("NO_COMPLETED_WORK_ITEMS",)


@pytest.mark.asyncio
async def test_flow_metrics_use_task_lifecycle_timestamps_without_llm_estimation():
    result = await get_delivery_flow_metrics(
        scope=_scope(),
        items=(
            _item(
                status=DeliveryWorkStatus.COMPLETED,
                created_at=NOW - timedelta(days=10),
                started_at=NOW - timedelta(days=7),
                completed_at=NOW - timedelta(days=1),
            ),
        ),
        now=NOW,
    )

    assert result.status == ToolResultStatus.SUCCESS
    assert result.data_gaps == ()
    assert result.payload["flow_metrics"] == {
        "active_wip": 0,
        "completed_in_period": 1,
        "throughput_per_week": 1.0,
        "cycle_time_hours_p50": 144.0,
        "lead_time_hours_p50": 216.0,
        "data_gaps": [],
    }


@pytest.mark.asyncio
async def test_dependency_tool_revalidates_source_and_rejects_cross_workspace_record():
    class Repository:
        async def list_dependencies(self, scope):
            del scope
            return (
                DeliveryDependency(
                    id="dep-cross-scope",
                    title="Forbidden dependency",
                    sources=(
                        SourceReference(
                            resource_id="group-quality",
                            resource_type="conversation",
                            agent_workspace_id="delivery-workspace",
                            classification="delivery",
                            captured_at=NOW,
                        ),
                    ),
                ),
            )

        async def list_decisions(self, scope):
            del scope
            return ()

    revalidated: list[str] = []

    async def revalidate(resource_id: str) -> None:
        revalidated.append(resource_id)

    with pytest.raises(DeliveryScopeError, match="outside Delivery scope"):
        await get_delivery_dependencies(
            scope=_scope(),
            repository=Repository(),
            revalidate_resource=revalidate,
        )

    assert revalidated == ["group-apollo"]
