"""Runtime-visible deterministic tools over a server-authorized Delivery pack.

The core Tool Gateway remains the authorization authority.  This module gives
each specialist an observable, allowlisted tool execution boundary instead of
letting model code read the entire delegated snapshot directly.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from src.agents.contracts import SourceReference, ToolResult, ToolResultStatus
from src.agents.delivery_orchestration.contracts import RuntimeChildTask
from src.agents.delivery_specialists.prompts import SPECIALIST_TOOL_ALLOWLISTS

_TOOL_KEYS: dict[str, tuple[str, ...]] = {
    "get_delivery_task_details": ("work_items",),
    "search_delivery_tasks": ("work_items",),
    "get_delivery_tasks": ("work_items", "capacity"),
    "get_delivery_portfolio_health": ("portfolio_health",),
    "get_delivery_risks": ("risks",),
    "get_delivery_dependencies": ("dependencies",),
    "get_delivery_milestones": ("milestones",),
    "get_delivery_release_status": ("releases",),
    "get_delivery_flow_metrics": ("flow_metrics",),
    "get_delivery_decisions": ("decisions",),
    "search_delivery_messages": ("message_evidence",),
    "get_delivery_people": ("people",),
    "get_delivery_capacity_summary": ("capacity",),
    "get_delivery_checkpoint_progress": ("checkpoint_progress",),
}


def _source_key(source: SourceReference) -> tuple[str, str, str]:
    return source.resource_id, source.resource_type, source.agent_workspace_id


def _embedded_sources(value: Any) -> tuple[SourceReference, ...]:
    collected: dict[tuple[str, str, str], SourceReference] = {}

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            if {"resource_id", "resource_type", "agent_workspace_id", "classification", "captured_at"}.issubset(item):
                try:
                    source = SourceReference.model_validate(item)
                    collected[_source_key(source)] = source
                except ValidationError:
                    pass
            for child in item.values():
                walk(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                walk(child)

    walk(value)
    return tuple(collected.values())


def _selected_tool_names(task: RuntimeChildTask) -> tuple[str, ...]:
    if task.specialist.value == "task_intelligence":
        intent = task.goal.partition(":")[0]
        if task.subject_refs and intent == "task_lookup":
            return ("get_delivery_task_details",)
        selected = ["get_delivery_tasks"]
        if intent in {"my_schedule", "task_progress_summary", "work_health", "delivery_health", "meeting_plan"}:
            selected.append("get_delivery_checkpoint_progress")
        if intent in {"task_progress_summary", "work_health", "delivery_health", "meeting_plan"}:
            selected.append("get_delivery_portfolio_health")
        return tuple(selected)
    return tuple(sorted(task.allowed_tools))


def execute_delegated_delivery_tools(
    *,
    context: ToolResult,
    task: RuntimeChildTask,
) -> tuple[ToolResult, tuple[dict[str, Any], ...]]:
    """Execute a bounded specialist tool selection against an authorized pack."""

    registered = SPECIALIST_TOOL_ALLOWLISTS[task.specialist]
    if frozenset(task.allowed_tools) != registered:
        raise ValueError("Specialist tool allowlist does not match the trusted registry")
    selected_tools = _selected_tool_names(task)
    if len(selected_tools) > task.max_tool_calls:
        raise ValueError("Specialist tool budget exceeded")

    payload: dict[str, Any] = {}
    if "upstream_results" in context.payload:
        payload["upstream_results"] = context.payload["upstream_results"]
    # Authorized scope metadata is not a business-data tool result, but task facts
    # need it to translate conversation source IDs into human-readable group names.
    for metadata_key in ("groups", "scope_context", "analysis_target"):
        if metadata_key in context.payload:
            payload[metadata_key] = context.payload[metadata_key]
    calls: list[dict[str, Any]] = []
    gaps = list(context.data_gaps)
    for tool_name in selected_tools:
        if tool_name not in registered or tool_name not in _TOOL_KEYS:
            raise ValueError("Specialist attempted a tool outside its delegated capability")
        keys = _TOOL_KEYS[tool_name]
        for key in keys:
            if key in context.payload:
                payload[key] = context.payload[key]
        result_count = 0
        if tool_name == "get_delivery_task_details":
            subject_ids = set(task.subject_refs)
            items = context.payload.get("work_items", [])
            filtered = [item for item in items if isinstance(item, dict) and str(item.get("id")) in subject_ids]
            payload["work_items"] = filtered
            result_count = len(filtered)
            if not filtered:
                gaps.append("TASK_NOT_FOUND_IN_AUTHORIZED_SCOPE")
        else:
            result_count = sum(
                len(context.payload.get(key, []))
                for key in keys
                if isinstance(context.payload.get(key), list)
            )
        calls.append({"tool_name": tool_name, "status": "success", "result_count": result_count})

    embedded = _embedded_sources(payload)
    sources = embedded or context.sources
    status = ToolResultStatus.PARTIAL if gaps else context.status
    return (
        ToolResult(
            status=status,
            payload=payload,
            sources=sources,
            data_gaps=tuple(dict.fromkeys(gaps)),
            error_code=context.error_code,
            error_message=context.error_message,
        ),
        tuple(calls),
    )
