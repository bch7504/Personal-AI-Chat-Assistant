"""Explicit read-only tool composition boundary for Quality Assurance."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.agents.contracts import ToolResult
from src.agents.profiles.quality_assurance_runner import PreparedQualityInvocation
from src.agents.schemas.quality import QualityReadScope

QualityReadTool = Callable[..., Awaitable[ToolResult]]
QualityWorkspaceRevalidator = Callable[[str], Awaitable[None]]

READ_ONLY_QUALITY_TOOL_NAMES = frozenset(
    {
        "get_quality_work_items",
        "get_release_test_status",
        "search_quality_messages",
        "get_quality_people",
        "build_quality_brief",
        "get_defect_register",
        "get_test_execution_summary",
        "get_release_gate_evidence",
        "get_requirement_traceability",
        "get_release_candidate",
        "get_quality_control_plane",
        "get_quality_policy",
        "get_quality_evidence_catalog",
        "get_quality_waivers",
    }
)


class QualityExecutionError(PermissionError):
    """Raised before an unapproved or mismatched tool can execute."""


class QualityReadOnlyExecutor:
    def __init__(
        self,
        *,
        tool_bindings: Mapping[str, QualityReadTool],
        revalidate_workspace: QualityWorkspaceRevalidator,
    ) -> None:
        unexpected = set(tool_bindings) - READ_ONLY_QUALITY_TOOL_NAMES
        if unexpected:
            raise QualityExecutionError(
                f"Non-read-only Quality tools cannot be bound: {', '.join(sorted(unexpected))}"
            )
        self._tool_bindings = dict(tool_bindings)
        self._revalidate_workspace = revalidate_workspace

    async def invoke(
        self,
        *,
        prepared: PreparedQualityInvocation,
        scope: QualityReadScope,
        tool_name: str,
        tool_input: Mapping[str, Any] | None = None,
    ) -> ToolResult:
        if scope.context != prepared.context:
            raise QualityExecutionError("Quality scope does not match the prepared context")
        if tool_name not in READ_ONLY_QUALITY_TOOL_NAMES:
            raise QualityExecutionError("Quality action or unknown tool is not executable")
        if tool_name not in prepared.allowed_tools:
            raise QualityExecutionError("Tool is outside the prepared Quality allowlist")
        tool = self._tool_bindings.get(tool_name)
        if tool is None:
            raise QualityExecutionError("Approved Quality tool is not bound by this runtime")
        target = prepared.context.request.target_agent_workspace_id
        if target is None:
            raise QualityExecutionError("Prepared Quality target workspace is missing")
        await self._revalidate_workspace(target)
        return await tool(scope=scope, **dict(tool_input or {}))
