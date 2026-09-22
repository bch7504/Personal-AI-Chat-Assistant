"""Durable lifecycle for Product Delivery Supervisor and specialist runs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.contracts import ToolResult
from src.agents.delivery_orchestration.context_builder import build_specialist_context
from src.agents.delivery_orchestration.contracts import (
    DeliveryIntent,
    DeliveryOrchestrationContext,
    DeliveryRoutingDecision,
    DeliveryRunStatus,
    DeliverySpecialist,
    DeliverySpecialistResult,
    DeliveryWorkflowStatus,
    RuntimeChildTask,
    canonical_payload_hash,
)
from src.agents.delivery_specialists.prompts import PROMPT_VERSIONS, SPECIALIST_TOOL_ALLOWLISTS
from src.db.models import (
    DeliveryAgentRun,
    DeliveryAgentWorkflow,
    DeliverySpecialistResultRecord,
    DeliveryWorkflowEventRecord,
)


def _event(workflow_id: str, event_type: str, payload: dict[str, Any] | None = None):
    return DeliveryWorkflowEventRecord(
        workflow_id=workflow_id,
        event_type=event_type,
        payload=payload or {},
        created_at=datetime.now(UTC),
    )


def _dependencies_for(
    route: DeliveryRoutingDecision,
    specialist: DeliverySpecialist,
) -> tuple[DeliverySpecialist, ...]:
    available = set(route.specialists)
    dependency_map: dict[DeliveryIntent, dict[DeliverySpecialist, tuple[DeliverySpecialist, ...]]] = {
        DeliveryIntent.BLOCKER_ANALYSIS: {
            DeliverySpecialist.RISK_DEPENDENCY: (DeliverySpecialist.TASK_INTELLIGENCE,),
            DeliverySpecialist.PLANNING_FORECAST: (DeliverySpecialist.TASK_INTELLIGENCE,),
        },
        DeliveryIntent.DEPENDENCY_ANALYSIS: {
            DeliverySpecialist.RISK_DEPENDENCY: (DeliverySpecialist.TASK_INTELLIGENCE,),
            DeliverySpecialist.PLANNING_FORECAST: (DeliverySpecialist.RISK_DEPENDENCY,),
        },
        DeliveryIntent.MEETING_PLAN: {
            DeliverySpecialist.RISK_DEPENDENCY: (DeliverySpecialist.TASK_INTELLIGENCE,),
            DeliverySpecialist.PLANNING_FORECAST: (
                DeliverySpecialist.TASK_INTELLIGENCE,
                DeliverySpecialist.RISK_DEPENDENCY,
            ),
        },
        DeliveryIntent.MILESTONE_HEALTH: {
            DeliverySpecialist.RISK_DEPENDENCY: (
                DeliverySpecialist.TASK_INTELLIGENCE,
                DeliverySpecialist.PLANNING_FORECAST,
            ),
        },
        DeliveryIntent.CHANGE_IMPACT: {
            DeliverySpecialist.PLANNING_FORECAST: (DeliverySpecialist.TASK_INTELLIGENCE,),
            DeliverySpecialist.RISK_DEPENDENCY: (DeliverySpecialist.PLANNING_FORECAST,),
        },
        DeliveryIntent.RELEASE_DELIVERY_READINESS: {
            DeliverySpecialist.PLANNING_FORECAST: (DeliverySpecialist.TASK_INTELLIGENCE,),
            DeliverySpecialist.RISK_DEPENDENCY: (DeliverySpecialist.TASK_INTELLIGENCE,),
            DeliverySpecialist.EVIDENCE_KNOWLEDGE: (
                DeliverySpecialist.PLANNING_FORECAST,
                DeliverySpecialist.RISK_DEPENDENCY,
            ),
        },
        DeliveryIntent.DELIVERY_HEALTH: {
            DeliverySpecialist.EVIDENCE_KNOWLEDGE: (
                DeliverySpecialist.TASK_INTELLIGENCE,
                DeliverySpecialist.PLANNING_FORECAST,
                DeliverySpecialist.RISK_DEPENDENCY,
            ),
        },
        DeliveryIntent.CAPACITY_ANALYSIS: {
            DeliverySpecialist.CAPACITY_FLOW: (DeliverySpecialist.TASK_INTELLIGENCE,),
        },
        DeliveryIntent.TASK_PROGRESS_SUMMARY: {
            DeliverySpecialist.PLANNING_FORECAST: (DeliverySpecialist.TASK_INTELLIGENCE,),
        },
    }
    dependencies = dependency_map.get(route.intent, {}).get(specialist, ())
    return tuple(item for item in dependencies if item in available)


async def create_delivery_workflow(
    db: AsyncSession,
    *,
    workspace_id: str,
    agent_workspace_id: str,
    actor_user_id: str,
    actor_role: str,
    message: str,
    authorization_scope_hash: str | None,
    route: DeliveryRoutingDecision,
    snapshot: ToolResult,
    timeout_seconds: float,
) -> tuple[DeliveryAgentWorkflow, DeliveryOrchestrationContext]:
    if not route.specialists:
        raise ValueError("A durable Delivery workflow requires at least one specialist")
    now = datetime.now(UTC)
    deadline = now + timedelta(seconds=timeout_seconds)
    workflow_id = uuid4().hex
    request_hash = canonical_payload_hash({"message": message, "route": route.model_dump(mode="json")})
    workflow = DeliveryAgentWorkflow(
        id=workflow_id,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        workflow_type=route.intent.value,
        execution_mode=route.execution_mode.value,
        status=DeliveryWorkflowStatus.CREATED.value,
        subject_type="group" if route.target_group_id else "task" if route.subject_id else None,
        subject_id=route.target_group_id or route.subject_id,
        authorization_scope_hash=authorization_scope_hash,
        request_hash=request_hash,
        plan_version=route.plan_version,
        result_json=None,
        data_gaps=[],
        deadline_at=deadline,
        created_at=now,
        updated_at=now,
    )
    db.add(workflow)
    # Scalar foreign-key values do not give the ORM a dependency relationship;
    # flush the durable parent before inserting supervisor and child runs.
    await db.flush()
    supervisor_run = DeliveryAgentRun(
        id=uuid4().hex,
        workflow_id=workflow_id,
        parent_run_id=None,
        specialist="supervisor",
        status=DeliveryRunStatus.PENDING.value,
        attempt=1,
        input_hash=request_hash,
        prompt_version="product-delivery-supervisor-v1",
        created_at=now,
        updated_at=now,
    )
    db.add(supervisor_run)
    await db.flush()
    child_tasks: list[RuntimeChildTask] = []
    target_ref = route.target_group_id or route.subject_id
    if route.target_group_id:
        goal_target = f"group={route.target_group_id}"
    elif route.target_selector:
        goal_target = f"selector={route.target_selector}"
    elif route.subject_id:
        goal_target = f"subject={route.subject_id}"
    else:
        goal_target = "workspace"
    for specialist in route.specialists:
        context = build_specialist_context(snapshot, specialist)
        input_hash = canonical_payload_hash(context.model_dump(mode="json"))
        run_id = uuid4().hex
        depends_on = _dependencies_for(route, specialist)
        child_tasks.append(
            RuntimeChildTask(
                run_id=run_id,
                specialist=specialist,
                goal=f"{route.intent.value}:{goal_target}",
                allowed_tools=tuple(sorted(SPECIALIST_TOOL_ALLOWLISTS[specialist])),
                max_tool_calls=len(SPECIALIST_TOOL_ALLOWLISTS[specialist]),
                subject_refs=(target_ref,) if target_ref else (),
                depends_on=depends_on,
                input_hash=input_hash,
            )
        )
        db.add(
            DeliveryAgentRun(
                id=run_id,
                workflow_id=workflow_id,
                parent_run_id=supervisor_run.id,
                specialist=specialist.value,
                status=DeliveryRunStatus.PENDING.value,
                attempt=1,
                input_hash=input_hash,
                prompt_version=PROMPT_VERSIONS[specialist],
                lineage_json={
                    "depends_on": [item.value for item in depends_on],
                    "subject_refs": [target_ref] if target_ref else [],
                    "target_selector": route.target_selector,
                    "allowed_tools": sorted(SPECIALIST_TOOL_ALLOWLISTS[specialist]),
                },
                created_at=now,
                updated_at=now,
            )
        )
    db.add(
        _event(
            workflow_id,
            "delivery.workflow.created",
            {
                "intent": route.intent.value,
                "execution_mode": route.execution_mode.value,
                "specialists": [specialist.value for specialist in route.specialists],
            },
        )
    )
    await db.commit()
    await db.refresh(workflow)
    capability_material = {
        "workspace_id": workspace_id,
        "agent_workspace_id": agent_workspace_id,
        "actor_user_id": actor_user_id,
        "scope_hash": authorization_scope_hash,
        "workflow_id": workflow_id,
    }
    orchestration = DeliveryOrchestrationContext(
        workflow_id=workflow_id,
        execution_mode=route.execution_mode,
        intent=route.intent,
        plan_version=route.plan_version,
        child_tasks=tuple(child_tasks),
        authorization_capability_ref=f"cap:{canonical_payload_hash(capability_material)}",
        authorization_scope_hash=authorization_scope_hash,
        max_steps=min(32, 4 + len(child_tasks) * 3),
        deadline_at=deadline,
    )
    return workflow, orchestration


async def mark_delivery_workflow_running(db: AsyncSession, *, workflow_id: str, model_name: str = "") -> None:
    now = datetime.now(UTC)
    workflow = await db.get(DeliveryAgentWorkflow, workflow_id)
    if workflow is None or workflow.status != DeliveryWorkflowStatus.CREATED.value:
        raise ValueError("Delivery workflow is unavailable or already started")
    workflow.status = DeliveryWorkflowStatus.RUNNING.value
    workflow.updated_at = now
    workflow.row_version += 1
    runs = list(
        (await db.execute(select(DeliveryAgentRun).where(DeliveryAgentRun.workflow_id == workflow_id))).scalars().all()
    )
    for run in runs:
        run.status = DeliveryRunStatus.RUNNING.value
        run.started_at = now
        run.updated_at = now
        if model_name:
            run.model_name = model_name
    db.add(_event(workflow_id, "delivery.workflow.started"))
    await db.commit()


async def complete_delivery_workflow(
    db: AsyncSession,
    *,
    workflow_id: str,
    results: tuple[DeliverySpecialistResult, ...],
    answer: str,
    usage: dict[str, Any],
    synthesis_model_name: str = "",
) -> DeliveryAgentWorkflow:
    now = datetime.now(UTC)
    workflow = await db.get(DeliveryAgentWorkflow, workflow_id)
    if workflow is None:
        raise ValueError("Delivery workflow is unavailable")
    if workflow.status in {
        DeliveryWorkflowStatus.COMPLETED.value,
        DeliveryWorkflowStatus.PARTIAL.value,
    }:
        # Runtime transports may retry a successful response. The durable
        # workflow is the idempotency boundary; never duplicate results/events.
        return workflow
    if workflow.status in {
        DeliveryWorkflowStatus.CANCELLED.value,
        DeliveryWorkflowStatus.EXPIRED.value,
    }:
        raise ValueError("Delivery workflow is no longer resumable")
    run_rows = {
        run.id: run
        for run in (await db.execute(select(DeliveryAgentRun).where(DeliveryAgentRun.workflow_id == workflow_id)))
        .scalars()
        .all()
    }
    results_by_specialist = {result.specialist.value: result for result in results}
    gaps: list[str] = []
    for result in results:
        run = run_rows.get(result.run_id)
        if run is None or run.specialist != result.specialist.value:
            raise ValueError("Specialist result does not belong to the workflow plan")
        if run.input_hash != result.input_hash:
            raise ValueError("Specialist result input hash changed")
        dependency_names = list((run.lineage_json or {}).get("depends_on", []))
        try:
            expected_upstream_hashes = tuple(
                results_by_specialist[name].output_hash for name in dependency_names
            )
        except KeyError:
            raise ValueError("Specialist result is missing a declared upstream result") from None
        if result.upstream_result_hashes != expected_upstream_hashes:
            raise ValueError("Specialist result upstream lineage changed")
        existing = (
            await db.execute(
                select(DeliverySpecialistResultRecord).where(DeliverySpecialistResultRecord.run_id == result.run_id)
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                DeliverySpecialistResultRecord(
                    workflow_id=workflow_id,
                    run_id=result.run_id,
                    specialist=result.specialist.value,
                    result_type=(result.artifact.artifact_type if result.artifact else result.specialist.value),
                    schema_version=result.schema_version,
                    status=result.status.value,
                    payload={
                        "summary": result.summary,
                        "facts": list(result.facts),
                        "inferences": list(result.inferences),
                        "recommendations": list(result.recommendations),
                        "metrics": result.metrics,
                        "artifact": result.artifact.model_dump(mode="json") if result.artifact else None,
                        "prompt_version": result.prompt_version,
                        "llm_used": result.llm_used,
                        "upstream_result_hashes": list(result.upstream_result_hashes),
                        "tool_calls": list(result.tool_calls),
                    },
                    source_references=[source.model_dump(mode="json") for source in result.sources],
                    data_gaps=list(result.data_gaps),
                    input_hash=result.input_hash,
                    output_hash=result.output_hash,
                    generated_at=result.generated_at,
                    expires_at=result.generated_at + timedelta(minutes=15),
                    created_at=now,
                )
            )
        run.output_hash = result.output_hash
        run.attempt = result.attempt_count
        run.model_name = result.model_name
        run.usage_json = result.usage
        run.lineage_json = {
            **(run.lineage_json or {}),
            "upstream_result_hashes": list(result.upstream_result_hashes),
            "tool_calls": list(result.tool_calls),
        }
        run.status = {
            "success": DeliveryRunStatus.SUCCEEDED.value,
            "partial": DeliveryRunStatus.PARTIAL.value,
            "error": DeliveryRunStatus.FAILED.value,
        }[result.status.value]
        run.error_code = result.data_gaps[0] if result.status.value == "error" and result.data_gaps else None
        run.completed_at = now
        run.updated_at = now
        gaps.extend(result.data_gaps)
        db.add(
            _event(
                workflow_id,
                "delivery.specialist.completed" if result.status.value != "error" else "delivery.specialist.failed",
                {
                    "run_id": result.run_id,
                    "specialist": result.specialist.value,
                    "status": result.status.value,
                    "upstream_result_hashes": list(result.upstream_result_hashes),
                    "tool_calls": [item.get("tool_name") for item in result.tool_calls],
                },
            )
        )

    supervisor = next((run for run in run_rows.values() if run.specialist == "supervisor"), None)
    if supervisor is not None:
        supervisor.status = (
            DeliveryRunStatus.PARTIAL.value
            if gaps or any(result.status.value != "success" for result in results)
            else DeliveryRunStatus.SUCCEEDED.value
        )
        supervisor.output_hash = canonical_payload_hash({"answer": answer})
        supervisor.model_name = synthesis_model_name
        supervisor.usage_json = usage
        supervisor.completed_at = now
        supervisor.updated_at = now
    is_partial = bool(gaps) or any(result.status.value != "success" for result in results)
    workflow.status = DeliveryWorkflowStatus.PARTIAL.value if is_partial else DeliveryWorkflowStatus.COMPLETED.value
    workflow.result_json = {
        "answer": answer[:8_000],
        "specialists": [result.specialist.value for result in results],
        "specialist_statuses": {result.specialist.value: result.status.value for result in results},
        "agent_communication": {
            result.specialist.value: {
                "upstream_result_hashes": list(result.upstream_result_hashes),
                "tool_calls": [item.get("tool_name") for item in result.tool_calls],
            }
            for result in results
        },
    }
    workflow.data_gaps = list(dict.fromkeys(gaps))
    workflow.completed_at = now
    workflow.updated_at = now
    workflow.row_version += 1
    db.add(_event(workflow_id, "delivery.workflow.completed", {"status": workflow.status}))
    await db.commit()
    await db.refresh(workflow)
    return workflow


async def fail_delivery_workflow(db: AsyncSession, *, workflow_id: str, error_code: str) -> None:
    workflow = await db.get(DeliveryAgentWorkflow, workflow_id)
    if workflow is None or workflow.status in {
        DeliveryWorkflowStatus.COMPLETED.value,
        DeliveryWorkflowStatus.PARTIAL.value,
        DeliveryWorkflowStatus.CANCELLED.value,
    }:
        return
    now = datetime.now(UTC)
    workflow.status = DeliveryWorkflowStatus.FAILED.value
    workflow.data_gaps = list(dict.fromkeys((*workflow.data_gaps, error_code)))
    workflow.completed_at = now
    workflow.updated_at = now
    workflow.row_version += 1
    runs = list(
        (await db.execute(select(DeliveryAgentRun).where(DeliveryAgentRun.workflow_id == workflow_id))).scalars().all()
    )
    for run in runs:
        if run.status in {DeliveryRunStatus.PENDING.value, DeliveryRunStatus.RUNNING.value}:
            run.status = DeliveryRunStatus.FAILED.value
            run.error_code = error_code
            run.completed_at = now
            run.updated_at = now
    db.add(_event(workflow_id, "delivery.workflow.failed", {"error_code": error_code}))
    await db.commit()
