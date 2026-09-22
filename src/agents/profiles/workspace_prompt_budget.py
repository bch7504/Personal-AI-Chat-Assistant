"""Deterministic, profile-aware prompt compaction for workspace agents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.agents.contracts import AgentProfile, ToolResult
from src.config import get_settings


@dataclass(frozen=True)
class PromptEvidence:
    text: str
    original_chars: int
    included_chars: int
    compacted: bool


_PROFILE_KEYS = {
    AgentProfile.PRODUCT_DELIVERY: (
        "scope_context", "analysis_target", "meeting_plan", "team_delivery_assessments", "task_group_progress", "portfolio_health", "brief", "risks", "dependencies", "decisions", "releases",
        "capacity", "flow_metrics", "checkpoint_progress", "groups", "message_evidence", "people",
        "specialist_results",
    ),
    AgentProfile.QUALITY_ASSURANCE: (
        "assessment", "brief", "release_candidate", "requirement_traceability",
        "defect_register", "test_execution", "gate_evidence", "quality_control_plane",
        "message_evidence", "groups", "people",
    ),
}

_LIST_LIMITS = {
    "risks": 12,
    "dependencies": 10,
    "decisions": 10,
    "releases": 8,
    "groups": 12,
    "task_group_progress": 12,
    "team_delivery_assessments": 12,
    "message_evidence": 8,
    "people": 12,
    "specialist_results": 4,
    "dependency_brief": 12,
    "risk_brief": 12,
    "agenda": 12,
    "questions": 12,
    "decisions_required": 12,
    "action_items": 16,
    "requirements": 12,
    "test_cases": 12,
    "test_runs": 12,
    "defects": 12,
    "evidence": 10,
}


def _compact_value(value: Any, *, key: str = "", depth: int = 0, tight: bool = False) -> Any:
    if depth >= 6:
        return "[nested data omitted]"
    if isinstance(value, str):
        limit = 320 if tight else 800
        return value if len(value) <= limit else f"{value[: limit - 15]} [truncated]"
    if isinstance(value, list | tuple):
        default_limit = 4 if tight else 8
        limit = min(_LIST_LIMITS.get(key, default_limit), 4) if tight else _LIST_LIMITS.get(key, default_limit)
        return [
            _compact_value(item, key=key, depth=depth + 1, tight=tight)
            for item in value[:limit]
        ]
    if isinstance(value, dict):
        limit = 14 if tight else 28
        return {
            str(child_key): _compact_value(child_value, key=str(child_key), depth=depth + 1, tight=tight)
            for child_key, child_value in list(value.items())[:limit]
        }
    return value


def _document(snapshot: ToolResult, profile: AgentProfile, *, tight: bool) -> dict[str, Any]:
    allowed_keys = _PROFILE_KEYS.get(profile, tuple(snapshot.payload.keys()))
    payload = {
        key: _compact_value(snapshot.payload[key], key=key, tight=tight)
        for key in allowed_keys
        if key in snapshot.payload
    }
    source_limit = 8 if tight else 20
    return {
        "schema_version": snapshot.schema_version,
        "status": snapshot.status.value,
        "payload": payload,
        "sources": [source.model_dump(mode="json") for source in snapshot.sources[:source_limit]],
        "data_gaps": list(snapshot.data_gaps[:20]),
    }


def compact_snapshot_for_prompt(snapshot: ToolResult, profile: AgentProfile) -> PromptEvidence:
    """Return bounded JSON while preserving deterministic status and high-value evidence."""

    original = snapshot.model_dump_json()
    maximum = get_settings().workspace_agent_snapshot_prompt_max_chars
    document = _document(snapshot, profile, tight=False)
    text = json.dumps(document, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(text) > maximum:
        document = _document(snapshot, profile, tight=True)
        text = json.dumps(document, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(text) > maximum:
        # The final bound remains valid JSON and retains authoritative summaries.
        if profile == AgentProfile.PRODUCT_DELIVERY:
            intent = str(snapshot.payload.get("orchestration_intent") or "")
            if intent == "meeting_plan":
                minimal_keys = (
                    "scope_context",
                    "analysis_target",
                    "meeting_plan",
                    "task_group_progress",
                    "specialist_results",
                    "groups",
                )
            elif intent == "dependency_analysis":
                minimal_keys = (
                    "scope_context",
                    "team_delivery_assessments",
                    "task_group_progress",
                    "dependencies",
                    "risks",
                    "checkpoint_progress",
                    "milestones",
                    "releases",
                    "people",
                    "specialist_results",
                    "groups",
                )
            elif intent == "blocker_analysis":
                minimal_keys = (
                    "portfolio_health",
                    "scope_context",
                    "team_delivery_assessments",
                    "task_group_progress",
                    "dependencies",
                    "risks",
                    "checkpoint_progress",
                    "releases",
                    "people",
                    "specialist_results",
                    "groups",
                )
            elif intent == "task_progress_summary":
                minimal_keys = (
                    "scope_context",
                    "team_delivery_assessments",
                    "task_group_progress",
                    "checkpoint_progress",
                    "specialist_results",
                    "groups",
                )
            else:
                minimal_keys = (
                    "portfolio_health",
                    "scope_context",
                    "task_group_progress",
                    "checkpoint_progress",
                    "specialist_results",
                    "groups",
                )
        else:
            minimal_keys = ("assessment", "release_candidate", "brief", "groups")
        minimal_payload = {
            key: document["payload"][key]
            for key in minimal_keys
            if key in document["payload"]
        }
        document["payload"] = minimal_payload
        text = json.dumps(document, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(text) > maximum:
        document["sources"] = document["sources"][:4]
        document["data_gaps"] = document["data_gaps"][:10]
        text = json.dumps(document, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(text) > maximum:
        # Defensive last resort for exceptionally large single fields; keep valid JSON.
        document = {
            "schema_version": snapshot.schema_version,
            "status": snapshot.status.value,
            "payload": _compact_value(minimal_payload, tight=True),
            "source_ids": [source.resource_id[:160] for source in snapshot.sources[:4]],
            "data_gaps": [str(gap)[:160] for gap in snapshot.data_gaps[:10]],
            "prompt_data_truncated": True,
        }
        text = json.dumps(document, ensure_ascii=False, separators=(",", ":"), default=str)
    return PromptEvidence(
        text=text,
        original_chars=len(original),
        included_chars=len(text),
        compacted=len(text) < len(original),
    )
