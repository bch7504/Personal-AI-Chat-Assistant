from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph

from src.agents.contracts import ToolResult, ToolResultStatus
from src.agents.delivery_orchestration.context_builder import (
    attach_validated_upstream_results,
    build_specialist_context,
)
from src.agents.delivery_orchestration.contracts import (
    DeliveryIntent,
    DeliveryOrchestrationContext,
    DeliverySpecialist,
    DeliverySpecialistResult,
    canonical_payload_hash,
)
from src.agents.delivery_specialists import run_delivery_specialist
from src.agents.delivery_specialists.prompts import PROMPT_VERSIONS, SPECIALIST_TOOL_ALLOWLISTS
from src.agents.delivery_supervisor.state import DeliverySupervisorState
from src.agents.profiles.workspace_delivery_graph import build_workspace_delivery_graph


def _merge_usage(*values: dict[str, Any]) -> dict[str, int]:
    return {
        key: sum(int(value.get(key, 0) or 0) for value in values)
        for key in ("input_tokens", "output_tokens", "total_tokens")
    }


async def _run_child(
    *,
    orchestration: DeliveryOrchestrationContext,
    snapshot: ToolResult,
    task,
    user_message: str,
    upstream_results: tuple[DeliverySpecialistResult, ...] = (),
) -> tuple[DeliverySpecialistResult, dict[str, Any]]:
    if frozenset(task.allowed_tools) != SPECIALIST_TOOL_ALLOWLISTS[task.specialist]:
        raise ValueError("Specialist task tool allowlist does not match the server registry")
    base_context = build_specialist_context(snapshot, task.specialist)
    if canonical_payload_hash(base_context.model_dump(mode="json")) != task.input_hash:
        raise ValueError("Specialist context hash does not match the trusted child task")
    expected_dependencies = tuple(result.specialist for result in upstream_results)
    if expected_dependencies != task.depends_on:
        raise ValueError("Specialist upstream result order does not match the workflow DAG")
    context = attach_validated_upstream_results(base_context, upstream_results)
    expected_upstream_hashes = tuple(result.output_hash for result in upstream_results)
    for attempt in (1, 2):
        remaining = max(0.1, (orchestration.deadline_at - datetime.now(UTC)).total_seconds())
        timeout = remaining if attempt == 2 else min(8.0, max(0.1, remaining * 0.45))
        try:
            result, metadata = await asyncio.wait_for(
                run_delivery_specialist(
                    workflow_id=orchestration.workflow_id,
                    task=task,
                    context=context,
                    user_message=user_message,
                ),
                timeout=timeout,
            )
            if (
                result.workflow_id != orchestration.workflow_id
                or result.run_id != task.run_id
                or result.specialist != task.specialist
                or result.input_hash != task.input_hash
                or result.upstream_result_hashes != expected_upstream_hashes
            ):
                raise ValueError("Specialist result identity does not match the delegated task")
            allowed_sources = {
                (source.resource_id, source.resource_type, source.agent_workspace_id) for source in context.sources
            }
            returned_sources = {
                (source.resource_id, source.resource_type, source.agent_workspace_id) for source in result.sources
            }
            if not returned_sources.issubset(allowed_sources):
                raise ValueError("Specialist result returned a source outside delegated context")
            return result.model_copy(update={"attempt_count": attempt}), {
                **metadata,
                "attempt_count": attempt,
            }
        except (TimeoutError, OSError):
            if attempt == 2 or datetime.now(UTC) >= orchestration.deadline_at:
                raise
    raise RuntimeError("Specialist retry loop ended unexpectedly")


def _failed_result(
    *,
    orchestration,
    task,
    reason: str,
    upstream_results: tuple[DeliverySpecialistResult, ...] = (),
) -> DeliverySpecialistResult:
    upstream_hashes = tuple(result.output_hash for result in upstream_results)
    material = {"specialist": task.specialist.value, "error": reason, "upstream_result_hashes": upstream_hashes}
    return DeliverySpecialistResult(
        workflow_id=orchestration.workflow_id,
        run_id=task.run_id,
        specialist=task.specialist,
        status=ToolResultStatus.ERROR,
        summary=f"{task.specialist.value} tạm thời không khả dụng.",
        facts=(),
        inferences=(),
        recommendations=(),
        metrics={},
        sources=(),
        data_gaps=(reason,),
        input_hash=task.input_hash,
        output_hash=canonical_payload_hash(material),
        prompt_version=PROMPT_VERSIONS[task.specialist],
        llm_used=False,
        upstream_result_hashes=upstream_hashes,
        attempt_count=2 if reason == "SPECIALIST_TIMEOUT" else 1,
        generated_at=datetime.now(UTC),
    )


def _evidence_not_required_result(
    *,
    orchestration,
    task,
    upstream_results: tuple[DeliverySpecialistResult, ...] = (),
) -> DeliverySpecialistResult:
    upstream_hashes = tuple(result.output_hash for result in upstream_results)
    material = {
        "specialist": task.specialist.value,
        "branch": "not_required",
        "upstream_result_hashes": upstream_hashes,
    }
    return DeliverySpecialistResult(
        workflow_id=orchestration.workflow_id,
        run_id=task.run_id,
        specialist=task.specialist,
        status=ToolResultStatus.SUCCESS,
        summary="Không phát hiện điều kiện cần mở nhánh kiểm tra bằng chứng bổ sung.",
        metrics={"conditional_branch_executed": False},
        input_hash=task.input_hash,
        output_hash=canonical_payload_hash(material),
        prompt_version=PROMPT_VERSIONS[task.specialist],
        upstream_result_hashes=upstream_hashes,
        generated_at=datetime.now(UTC),
    )


def _requires_evidence_branch(snapshot: ToolResult, results: list[DeliverySpecialistResult]) -> bool:
    decisions = snapshot.payload.get("decisions", [])
    if isinstance(decisions, list) and any(
        isinstance(item, dict) and item.get("status") == "pending" for item in decisions
    ):
        return True
    if any(result.status != ToolResultStatus.SUCCESS for result in results):
        return True
    trigger_metrics = {
        "critical_risk_count",
        "blocked_dependency_count",
        "blocked",
        "blocked_milestones",
        "pending_qa_releases",
    }
    return any(int(result.metrics.get(metric, 0) or 0) > 0 for result in results for metric in trigger_metrics)


def _source_group_id(item: dict[str, Any]) -> str:
    return next(
        (
            str(source.get("resource_id") or "")
            for source in item.get("sources", [])
            if isinstance(source, dict) and source.get("resource_type") == "conversation"
        ),
        str(item.get("conversation_id") or ""),
    )


def _build_team_delivery_assessments(
    payload: dict[str, Any],
    group_progress: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Join specialist outputs into a meeting-ready record for every team."""

    groups = [item for item in payload.get("groups", []) if isinstance(item, dict)]
    group_ids = {str(item.get("name") or ""): str(item.get("id") or "") for item in groups}
    people = {
        str(item.get("user_id") or ""): str(item.get("display_name") or "")
        for item in payload.get("people", [])
        if isinstance(item, dict)
    }
    dependencies = [item for item in payload.get("dependencies", []) if isinstance(item, dict)]
    risks = [item for item in payload.get("risks", []) if isinstance(item, dict)]
    checkpoints = [item for item in payload.get("checkpoint_progress", []) if isinstance(item, dict)]
    decisions = [item for item in payload.get("decisions", []) if isinstance(item, dict)]
    work_items = [item for item in payload.get("work_items", []) if isinstance(item, dict)]
    work_items_by_id = {str(item.get("id") or ""): item for item in work_items if item.get("id")}
    task_groups = {str(item.get("id") or ""): _source_group_id(item) for item in work_items}
    now = datetime.now(UTC)
    assessments: list[dict[str, Any]] = []

    for progress in group_progress:
        group_name = str(progress.get("group_name") or "Untitled group")
        group_id = group_ids.get(group_name, "")
        completion = int(progress.get("completion_percent", 0) or 0)
        blocked = int(progress.get("blocked_task_count", 0) or 0)
        overdue = int(progress.get("overdue_task_count", 0) or 0)
        if completion <= 20 or blocked >= 3 or overdue >= 2:
            assessment = "Cần can thiệp ngay"
            assessment_reason = "Tiến độ thấp hoặc có nhiều task bị chặn/quá hạn."
        elif completion < 60 or blocked or overdue:
            assessment = "Có rủi ro"
            assessment_reason = "Tiến độ chưa an toàn và vẫn còn blocker hoặc task quá hạn."
        else:
            assessment = "Cần theo dõi"
            assessment_reason = "Tiến độ tương đối ổn nhưng vẫn cần theo dõi cam kết còn lại."

        scoped_items = [item for item in work_items if _source_group_id(item) == group_id]
        attention_tasks: list[dict[str, Any]] = []
        for item in scoped_items:
            due_raw = item.get("due_at")
            try:
                due_at = datetime.fromisoformat(str(due_raw).replace("Z", "+00:00")) if due_raw else None
                if due_at is not None and due_at.tzinfo is None:
                    due_at = due_at.replace(tzinfo=UTC)
            except ValueError:
                due_at = None
            status = str(item.get("status") or "unknown")
            is_overdue = status != "completed" and due_at is not None and due_at < now
            if status in {"blocked", "changes_requested", "submitted"} or is_overdue:
                attention_tasks.append(
                    {
                        "title": item.get("title"),
                        "status": status,
                        "owner_name": people.get(str(item.get("assignee_id") or item.get("owner_id") or "")) or None,
                        "due_at": due_raw,
                        "is_overdue": is_overdue,
                        "blocked_reason": item.get("blocked_reason"),
                        "review_note": item.get("review_note"),
                    }
                )

        def scoped(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [
                item
                for item in rows
                if _source_group_id(item) == group_id
                or any(
                    isinstance(source, dict)
                    and task_groups.get(str(source.get("resource_id") or "")) == group_id
                    for source in item.get("sources", [])
                )
            ]

        assessments.append(
            {
                "group_name": group_name,
                "assessment": assessment,
                "assessment_reason": assessment_reason,
                "task_metrics": progress,
                "attention_tasks": attention_tasks[:6],
                "dependencies": [
                    {
                        "title": item.get("title"),
                        "status": item.get("status"),
                        "owner_name": item.get("owner_name")
                        or people.get(str(item.get("assignee_id") or ""))
                        or None,
                        "due_at": item.get("due_at"),
                        "predecessor": item.get("predecessor_task_title"),
                        "successor": item.get("successor_task_title"),
                        "predecessor_blocked_reason": work_items_by_id.get(
                            str(item.get("predecessor_task_id") or ""), {}
                        ).get("blocked_reason"),
                        "successor_status": work_items_by_id.get(
                            str(item.get("successor_task_id") or ""), {}
                        ).get("status"),
                    }
                    for item in scoped(dependencies)[:6]
                ],
                "risks": [
                    {
                        "title": item.get("title"),
                        "severity": item.get("severity"),
                        "reason_code": item.get("reason_code"),
                    }
                    for item in scoped(risks)[:6]
                ],
                "checkpoints": [
                    {
                        "title": item.get("title"),
                        "schedule_status": item.get("schedule_status"),
                        "completion_percent": item.get("completion_percent"),
                        "quality_review_status": item.get("quality_review_status"),
                        "completion_decision": item.get("completion_decision"),
                        "due_at": item.get("due_at"),
                    }
                    for item in checkpoints
                    if str(item.get("conversation_id") or "") == group_id
                ][:4],
                "pending_decisions": [
                    {
                        "title": item.get("title"),
                        "due_at": item.get("due_at"),
                        "owner_name": people.get(str(item.get("owner_id") or "")) or None,
                    }
                    for item in scoped(decisions)
                    if item.get("status") == "pending"
                ][:4],
            }
        )
    return sorted(
        assessments,
        key=lambda item: (
            int(item["task_metrics"].get("completion_percent", 0) or 0),
            -int(item["task_metrics"].get("blocked_task_count", 0) or 0),
            item["group_name"],
        ),
    )


ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


def build_delivery_supervisor_graph(progress_callback: ProgressCallback | None = None):
    task_positions: dict[DeliverySpecialist, int] = {}

    async def emit(phase: str, **payload: Any) -> None:
        if progress_callback is None:
            return
        try:
            await progress_callback({"phase": phase, **payload})
        except Exception:  # noqa: BLE001 - progress must never break execution.
            return

    async def dispatch(state: DeliverySupervisorState) -> dict[str, Any]:
        orchestration = state["orchestration"]
        task_positions.update(
            {task.specialist: index for index, task in enumerate(orchestration.child_tasks, start=1)}
        )
        total_steps = len(orchestration.child_tasks)
        if datetime.now(UTC) >= orchestration.deadline_at:
            results = [
                _failed_result(orchestration=orchestration, task=task, reason="SPECIALIST_DEADLINE_EXPIRED")
                for task in orchestration.child_tasks
            ]
            return {
                "specialist_results": results,
                "metadata": {"specialist_usage": {}, "specialists_failed": len(results)},
            }
        user_message = next(
            (
                str(message.content)
                for message in reversed(state.get("messages", []))
                if getattr(message, "type", "") == "human"
            ),
            "Phân tích Product Delivery trong phạm vi được cấp quyền.",
        )
        results: list[DeliverySpecialistResult] = []
        usages: list[dict[str, Any]] = []
        specialist_llm_attempts = 0
        specialist_fallbacks: dict[str, str] = {}
        specialist_model_attempts: dict[str, list[dict[str, Any]]] = {}
        evidence_branch_executed = False
        pending = list(orchestration.child_tasks)
        results_by_specialist: dict[DeliverySpecialist, DeliverySpecialistResult] = {}

        while pending:
            ready = [
                task
                for task in pending
                if all(dependency in results_by_specialist for dependency in task.depends_on)
            ]
            if not ready:
                for task in pending:
                    failed = _failed_result(
                            orchestration=orchestration,
                            task=task,
                            reason="SPECIALIST_DAG_DEPENDENCY_UNRESOLVED",
                    )
                    results.append(failed)
                    await emit(
                        "specialist_failed",
                        specialist=task.specialist.value,
                        depends_on=[item.value for item in task.depends_on],
                        step_index=task_positions[task.specialist],
                        total_steps=total_steps,
                        error_code="SPECIALIST_DAG_DEPENDENCY_UNRESOLVED",
                    )
                break

            executable = []
            for task in ready:
                upstream = tuple(results_by_specialist[item] for item in task.depends_on)
                is_conditional_evidence = (
                    orchestration.intent == DeliveryIntent.DELIVERY_HEALTH
                    and task.specialist == DeliverySpecialist.EVIDENCE_KNOWLEDGE
                )
                if is_conditional_evidence and not _requires_evidence_branch(state["snapshot"], results):
                    skipped = _evidence_not_required_result(
                        orchestration=orchestration,
                        task=task,
                        upstream_results=upstream,
                    )
                    results.append(skipped)
                    results_by_specialist[task.specialist] = skipped
                    await emit(
                        "specialist_completed",
                        specialist=task.specialist.value,
                        depends_on=[item.value for item in task.depends_on],
                        tools=list(task.allowed_tools),
                        step_index=task_positions[task.specialist],
                        total_steps=total_steps,
                        output_hash=skipped.output_hash,
                        metrics=skipped.metrics,
                    )
                else:
                    if is_conditional_evidence:
                        evidence_branch_executed = True
                    executable.append((task, upstream))

            for task, upstream in executable:
                for upstream_result in upstream:
                    await emit(
                        "specialist_handoff",
                        from_specialist=upstream_result.specialist.value,
                        to_specialist=task.specialist.value,
                        output_hash=upstream_result.output_hash,
                        total_steps=total_steps,
                    )
                await emit(
                    "specialist_started",
                    specialist=task.specialist.value,
                    depends_on=[item.value for item in task.depends_on],
                    tools=list(task.allowed_tools),
                    step_index=task_positions[task.specialist],
                    total_steps=total_steps,
                )

            outcomes = await asyncio.gather(
                *(
                    _run_child(
                        orchestration=orchestration,
                        snapshot=state["snapshot"],
                        task=task,
                        user_message=user_message,
                        upstream_results=upstream,
                    )
                    for task, upstream in executable
                ),
                return_exceptions=True,
            )
            for (task, upstream), outcome in zip(executable, outcomes, strict=True):
                if isinstance(outcome, BaseException):
                    reason = "SPECIALIST_TIMEOUT" if isinstance(outcome, TimeoutError) else "SPECIALIST_RUNTIME_FAILED"
                    result = _failed_result(
                        orchestration=orchestration,
                        task=task,
                        reason=reason,
                        upstream_results=upstream,
                    )
                    await emit(
                        "specialist_failed",
                        specialist=task.specialist.value,
                        depends_on=[item.value for item in task.depends_on],
                        tools=list(task.allowed_tools),
                        step_index=task_positions[task.specialist],
                        total_steps=total_steps,
                        output_hash=result.output_hash,
                        error_code=reason,
                    )
                else:
                    result, metadata = outcome
                    usage = metadata.get("usage")
                    if isinstance(usage, dict):
                        usages.append(usage)
                    specialist_llm_attempts += int(
                        metadata.get("llm_attempt_count", int(bool(metadata.get("llm_attempted", False))))
                    )
                    model_attempts = metadata.get("model_attempts", [])
                    if isinstance(model_attempts, list) and model_attempts:
                        specialist_model_attempts[task.specialist.value] = model_attempts
                    fallback_reason = str(metadata.get("fallback_reason", ""))
                    if fallback_reason:
                        specialist_fallbacks[task.specialist.value] = fallback_reason
                    await emit(
                        "specialist_completed",
                        specialist=task.specialist.value,
                        depends_on=[item.value for item in task.depends_on],
                        tools=list(task.allowed_tools),
                        step_index=task_positions[task.specialist],
                        total_steps=total_steps,
                        output_hash=result.output_hash,
                        artifact_type=(result.artifact.artifact_type if result.artifact else None),
                        metrics=result.metrics,
                    )
                results.append(result)
                results_by_specialist[task.specialist] = result

            for task in ready:
                pending.remove(task)
        return {
            "specialist_results": results,
            "metadata": {
                **state.get("metadata", {}),
                "specialist_usage": _merge_usage(*usages),
                "specialists_requested": len(orchestration.child_tasks),
                "specialists_completed": sum(item.status != ToolResultStatus.ERROR for item in results),
                "specialists_failed": sum(item.status == ToolResultStatus.ERROR for item in results),
                "specialist_llm_attempts": specialist_llm_attempts,
                "specialist_fallbacks": specialist_fallbacks,
                "specialist_model_attempts": specialist_model_attempts,
                "evidence_branch_executed": evidence_branch_executed,
            },
        }

    async def synthesize(state: DeliverySupervisorState) -> dict[str, Any]:
        await emit(
            "synthesis_started",
            total_steps=len(state["orchestration"].child_tasks),
        )
        specialist_results = state.get("specialist_results", [])
        extra_gaps = tuple(dict.fromkeys(gap for result in specialist_results for gap in result.data_gaps))
        task_group_progress = next(
            (
                result.metrics.get("group_progress", [])
                for result in specialist_results
                if result.specialist == DeliverySpecialist.TASK_INTELLIGENCE
                and isinstance(result.metrics.get("group_progress"), list)
            ),
            [],
        )
        meeting_plan = next(
            (
                result.artifact.model_dump(mode="json")
                for result in specialist_results
                if result.specialist == DeliverySpecialist.PLANNING_FORECAST
                and result.artifact is not None
                and result.artifact.artifact_type == "meeting_plan.v1"
            ),
            None,
        )
        specialist_payload = {
            "specialist_results": [result.model_dump(mode="json") for result in specialist_results],
            "orchestration_intent": state["orchestration"].intent.value,
            "task_group_progress": task_group_progress,
            "meeting_plan": meeting_plan,
            "team_delivery_assessments": _build_team_delivery_assessments(
                state["snapshot"].payload,
                task_group_progress,
            ),
            "groups": state["snapshot"].payload.get("groups", []),
            "scope_context": state["snapshot"].payload.get("scope_context", {}),
            "analysis_target": state["snapshot"].payload.get("analysis_target", {}),
            "authorized_view_scope": (
                state["snapshot"].payload.get("brief", {}).get("view_scope")
                if isinstance(state["snapshot"].payload.get("brief"), dict)
                else None
            ),
        }
        if state["orchestration"].execution_mode.value == "single_specialist":
            # A specialist result intentionally contains a compact narrative artifact, but
            # synthesis still needs the typed, authorized rows behind that artifact.  In
            # particular, checkpoint/decision rows cannot be reconstructed reliably from
            # aggregate metrics.  Reuse the same minimal context slice that was delegated
            # to the sole specialist instead of falling back to the full portfolio.
            single_context_payload: dict[str, Any] = {}
            if len(specialist_results) == 1:
                single_context_payload = build_specialist_context(
                    state["snapshot"], specialist_results[0].specialist
                ).payload
            combined_payload = {**single_context_payload, **specialist_payload}
        elif state["orchestration"].intent in {
            DeliveryIntent.MEETING_PLAN,
            DeliveryIntent.DEPENDENCY_ANALYSIS,
        }:
            # Specialist results and team assessments are the handoff boundary.
            # Avoid feeding the final model the entire raw portfolio again.
            combined_payload = {
                **specialist_payload,
                "portfolio_health": state["snapshot"].payload.get("portfolio_health"),
                "checkpoint_progress": state["snapshot"].payload.get("checkpoint_progress", []),
                "releases": state["snapshot"].payload.get("releases", []),
                "people": state["snapshot"].payload.get("people", []),
            }
        else:
            combined_payload = {**state["snapshot"].payload, **specialist_payload}
        combined = state["snapshot"].model_copy(
            update={
                "status": (
                    ToolResultStatus.PARTIAL
                    if extra_gaps or any(result.status != ToolResultStatus.SUCCESS for result in specialist_results)
                    else state["snapshot"].status
                ),
                "payload": combined_payload,
                "data_gaps": tuple(dict.fromkeys((*state["snapshot"].data_gaps, *extra_gaps))),
            }
        )
        delivery_graph = build_workspace_delivery_graph(snapshot=combined)
        nested = await delivery_graph.ainvoke(
            {"messages": state.get("messages", [])},
            {"recursion_limit": 8},
        )
        nested_metadata = dict(nested.get("metadata", {}))
        specialist_usage = state.get("metadata", {}).get("specialist_usage", {})
        final_usage = nested_metadata.get("runtime_usage", {})
        metadata = {
            **state.get("metadata", {}),
            **nested_metadata,
            "supervisor_usage": final_usage,
            "runtime_usage": _merge_usage(specialist_usage, final_usage),
            "llm_calls": int(nested_metadata.get("llm_calls", 0) or 0)
            + int(state.get("metadata", {}).get("specialist_llm_attempts", 0) or 0),
            "execution_mode": state["orchestration"].execution_mode.value,
            "intent": state["orchestration"].intent.value,
            "plan_version": state["orchestration"].plan_version,
        }
        messages = [message for message in nested.get("messages", []) if isinstance(message, AIMessage)]
        return {"messages": messages[-1:] if messages else [], "metadata": metadata}

    graph = StateGraph(DeliverySupervisorState)
    graph.add_node("dispatch_specialists", dispatch)
    graph.add_node("synthesize", synthesize)
    graph.set_entry_point("dispatch_specialists")
    graph.add_edge("dispatch_specialists", "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile()


_SUPERVISOR_GRAPH = build_delivery_supervisor_graph()


async def run_delivery_supervisor(
    *,
    snapshot: ToolResult,
    orchestration: DeliveryOrchestrationContext,
    messages: list,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    graph = build_delivery_supervisor_graph(progress_callback) if progress_callback else _SUPERVISOR_GRAPH
    return await graph.ainvoke(
        {
            "snapshot": snapshot,
            "orchestration": orchestration,
            "messages": messages,
        },
        {"recursion_limit": 8},
    )
