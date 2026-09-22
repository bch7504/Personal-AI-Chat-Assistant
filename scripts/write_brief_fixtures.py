"""Generate canonical specialist brief fixtures from the Pydantic contract."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.agents.contracts import (  # noqa: E402, I001
    AgentProfile,
    BriefType,
    ReleaseReadiness,
    SourceReference,
    WorkspaceBrief,
)


FIXTURES = ROOT / "eval" / "fixtures"


def build_briefs() -> dict[str, WorkspaceBrief]:
    generated_at = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)
    period_start = generated_at - timedelta(days=7)
    period_end = generated_at
    expires_at = generated_at + timedelta(days=7)

    return {
        "delivery_brief_v1.json": WorkspaceBrief(
            brief_id="brief-delivery-v1",
            trace_id="trace-delivery-v1",
            organization_workspace_id="workspace-orbit",
            agent_workspace_id="agent-workspace-delivery",
            brief_type=BriefType.DELIVERY,
            producer_profile=AgentProfile.PRODUCT_DELIVERY,
            period_start=period_start,
            period_end=period_end,
            generated_at=generated_at,
            expires_at=expires_at,
            headline="Delivery is on track with one dependency to resolve.",
            facts=(
                {"key": "completed_work_items", "value": 12},
                {"key": "open_work_items", "value": 4},
            ),
            risks=({"key": "external_dependency", "severity": "medium"},),
            dependencies=({"name": "API contract", "owner": "platform"},),
            decisions_needed=({"decision": "Confirm API contract deadline"},),
            data_gaps=(),
            sources=(
                SourceReference(
                    resource_id="group-delivery-apollo",
                    resource_type="conversation",
                    agent_workspace_id="agent-workspace-delivery",
                    classification="delivery",
                    captured_at=generated_at,
                ),
            ),
        ),
        "quality_brief_v1.json": WorkspaceBrief(
            brief_id="brief-quality-v1",
            trace_id="trace-quality-v1",
            organization_workspace_id="workspace-orbit",
            agent_workspace_id="agent-workspace-quality",
            brief_type=BriefType.QUALITY,
            producer_profile=AgentProfile.QUALITY_ASSURANCE,
            period_start=period_start,
            period_end=period_end,
            generated_at=generated_at,
            expires_at=expires_at,
            headline="Release candidate is at risk pending regression coverage.",
            facts=(
                {"key": "passed_checks", "value": 38},
                {"key": "failed_checks", "value": 2},
            ),
            risks=({"key": "regression_coverage", "severity": "high"},),
            dependencies=({"name": "Staging data refresh", "owner": "platform"},),
            decisions_needed=({"decision": "Approve regression test window"},),
            data_gaps=(),
            sources=(
                SourceReference(
                    resource_id="group-quality-release",
                    resource_type="conversation",
                    agent_workspace_id="agent-workspace-quality",
                    classification="quality",
                    captured_at=generated_at,
                ),
            ),
            release_readiness=ReleaseReadiness.AT_RISK,
        ),
    }


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for filename, brief in build_briefs().items():
        (FIXTURES / filename).write_text(brief.model_dump_json(), encoding="utf-8")


if __name__ == "__main__":
    main()
