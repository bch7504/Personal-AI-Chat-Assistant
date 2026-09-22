"""Deterministic enterprise QA analysis tools over an already-authorized item set."""

from __future__ import annotations

from collections import Counter

from src.agents.contracts import ToolResult, ToolResultStatus
from src.agents.schemas.quality import (
    QualityReadScope,
    QualityStatus,
    QualityWorkItem,
    QualityWorkItemType,
    evaluate_release_readiness,
)


def _sources(items: tuple[QualityWorkItem, ...]):
    return tuple(dict.fromkeys(source for item in items for source in item.sources))


async def get_defect_register(
    *, scope: QualityReadScope, items: tuple[QualityWorkItem, ...]
) -> ToolResult:
    defects = [item for item in items if item.work_item_type == QualityWorkItemType.BUG]
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={
            "release_id": scope.release_id,
            "defects": [item.model_dump(mode="json") for item in defects],
            "active_count": sum(
                item.quality_status not in {QualityStatus.PASSED} for item in defects
            ),
            "by_severity": dict(Counter(item.severity.value for item in defects if item.severity)),
        },
        sources=_sources(tuple(defects)),
    )


async def get_test_execution_summary(
    *, scope: QualityReadScope, items: tuple[QualityWorkItem, ...]
) -> ToolResult:
    tests = [
        item
        for item in items
        if item.work_item_type in {QualityWorkItemType.TEST_CASE, QualityWorkItemType.RELEASE_CHECK}
    ]
    counts = Counter(item.quality_status.value for item in tests)
    completed = counts[QualityStatus.PASSED.value] + counts[QualityStatus.FAILED.value]
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={
            "release_id": scope.release_id,
            "total": len(tests),
            "completed": completed,
            "completion_percent": round((completed / len(tests)) * 100) if tests else 0,
            "by_status": dict(counts),
        },
        sources=_sources(tuple(tests)),
    )


async def get_release_gate_evidence(
    *, scope: QualityReadScope, items: tuple[QualityWorkItem, ...]
) -> ToolResult:
    assessment = evaluate_release_readiness(items, release_id=scope.release_id)
    required_checks = [
        item for item in items
        if item.work_item_type == QualityWorkItemType.RELEASE_CHECK and item.required
    ]
    return ToolResult(
        status=ToolResultStatus.PARTIAL if assessment.data_gaps else ToolResultStatus.SUCCESS,
        payload={
            "release_id": scope.release_id,
            "release_readiness": assessment.release_readiness.value,
            "reasons": list(assessment.reasons),
            "required_checks": [item.model_dump(mode="json") for item in required_checks],
        },
        sources=_sources(tuple(required_checks)),
        data_gaps=assessment.data_gaps,
    )


async def get_requirement_traceability(
    *, scope: QualityReadScope, items: tuple[QualityWorkItem, ...]
) -> ToolResult:
    """Report an explicit gap until requirement IDs are normalized in the QA domain model."""

    covered_checks = [
        item for item in items
        if item.work_item_type in {QualityWorkItemType.TEST_CASE, QualityWorkItemType.RELEASE_CHECK}
    ]
    gap = "REQUIREMENT_TRACEABILITY_NOT_CAPTURED"
    return ToolResult(
        status=ToolResultStatus.PARTIAL,
        payload={
            "release_id": scope.release_id,
            "requirement_count": None,
            "linked_test_count": len(covered_checks),
            "coverage_percent": None,
        },
        sources=_sources(tuple(covered_checks)),
        data_gaps=(gap,),
    )
