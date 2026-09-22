from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from src.agents.contracts import SourceReference, ToolResult
from src.agents.delivery_orchestration.contracts import DeliverySpecialist, DeliverySpecialistResult

_KEYS = {
    DeliverySpecialist.TASK_INTELLIGENCE: (
        "work_items",
        "capacity",
        "portfolio_health",
        "checkpoint_progress",
        "groups",
        "scope_context",
        "analysis_target",
    ),
    DeliverySpecialist.RISK_DEPENDENCY: (
        "risks",
        "dependencies",
        "portfolio_health",
        "work_items",
        "groups",
        "scope_context",
        "analysis_target",
    ),
    DeliverySpecialist.PLANNING_FORECAST: (
        "milestones",
        "releases",
        "portfolio_health",
        "flow_metrics",
        "work_items",
        "checkpoint_progress",
        "groups",
        "scope_context",
        "analysis_target",
    ),
    DeliverySpecialist.EVIDENCE_KNOWLEDGE: (
        "decisions",
        "message_evidence",
        "portfolio_health",
        "people",
        "groups",
        "scope_context",
        "analysis_target",
    ),
    DeliverySpecialist.CAPACITY_FLOW: (
        "people",
        "capacity",
        "flow_metrics",
        "work_items",
    ),
}

_GAP_PREFIXES = {
    DeliverySpecialist.TASK_INTELLIGENCE: ("WORK_ITEM_", "TASK_", "DELIVERY_TASK_"),
    DeliverySpecialist.RISK_DEPENDENCY: ("RISK_", "DEPENDENCY_", "DELIVERY_DEPENDENCIES_"),
    DeliverySpecialist.PLANNING_FORECAST: ("MILESTONE_", "RELEASE_", "FLOW_", "WORKFLOW_HISTORY_", "DELIVERY_RELEASE_"),
    DeliverySpecialist.EVIDENCE_KNOWLEDGE: ("DECISION_", "EVIDENCE_", "MESSAGE_", "DELIVERY_DECISIONS_"),
    DeliverySpecialist.CAPACITY_FLOW: ("CAPACITY_", "FLOW_", "WORKLOAD_"),
}


def _relevant_gaps(snapshot: ToolResult, specialist: DeliverySpecialist) -> tuple[str, ...]:
    prefixes = _GAP_PREFIXES[specialist]
    scoped = tuple(gap for gap in snapshot.data_gaps if gap.startswith(prefixes))
    # Unknown gaps can affect the whole snapshot and therefore remain visible.
    known_prefixes = tuple(prefix for values in _GAP_PREFIXES.values() for prefix in values)
    global_gaps = tuple(gap for gap in snapshot.data_gaps if not gap.startswith(known_prefixes))
    return tuple(dict.fromkeys((*scoped, *global_gaps)))


def _walk_sources(value: Any) -> Iterable[SourceReference]:
    if isinstance(value, dict):
        if {"resource_id", "resource_type", "agent_workspace_id", "classification", "captured_at"}.issubset(value):
            try:
                yield SourceReference.model_validate(value)
            except ValidationError:
                pass
        for child in value.values():
            yield from _walk_sources(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_sources(child)


def build_specialist_context(snapshot: ToolResult, specialist: DeliverySpecialist) -> ToolResult:
    """Create a minimal model-visible slice from an already authorized snapshot."""

    payload = {key: snapshot.payload.get(key) for key in _KEYS[specialist] if key in snapshot.payload}
    discovered = tuple(_walk_sources(payload))
    sources_by_key = {
        (source.resource_id, source.resource_type, source.agent_workspace_id): source
        for source in (*discovered, *snapshot.sources)
    }
    relevant_gaps = _relevant_gaps(snapshot, specialist)
    scoped_status = snapshot.status
    if snapshot.status.value == "partial" and not relevant_gaps:
        scoped_status = type(snapshot.status).SUCCESS
    # Snapshot-level sources are already authorized. They are retained for provenance
    # when normalized payload rows do not embed their SourceReference after transport.
    return ToolResult(
        status=scoped_status,
        payload=payload,
        sources=tuple(sources_by_key.values()),
        data_gaps=relevant_gaps,
        error_code=snapshot.error_code,
        error_message=snapshot.error_message,
    )


def attach_validated_upstream_results(
    context: ToolResult,
    results: tuple[DeliverySpecialistResult, ...],
) -> ToolResult:
    """Attach a minimal A2A pack; recommendations never become downstream facts."""

    if not results:
        return context
    upstream = [
        {
            "specialist": result.specialist.value,
            "status": result.status.value,
            "facts": list(result.facts[:30]),
            "metrics": result.metrics,
            "artifact": result.artifact.model_dump(mode="json") if result.artifact else None,
            "data_gaps": list(result.data_gaps),
            "output_hash": result.output_hash,
        }
        for result in results
    ]
    sources_by_key = {
        (source.resource_id, source.resource_type, source.agent_workspace_id): source
        for source in (
            *context.sources,
            *(source for result in results for source in result.sources),
        )
    }
    return context.model_copy(
        update={
            "payload": {**context.payload, "upstream_results": upstream},
            "sources": tuple(sources_by_key.values()),
        }
    )
