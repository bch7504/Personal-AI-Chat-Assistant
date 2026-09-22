from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.contracts import AgentProfile
from src.agents.delivery_orchestration.contracts import DeliveryIntent
from src.agents.delivery_supervisor import run_delivery_supervisor
from src.agents.profiles.product_delivery import PRODUCT_DELIVERY_PROMPT_VERSION
from src.agents.profiles.quality_assurance import QUALITY_ASSURANCE_PROMPT_VERSION
from src.agents.profiles.workspace_delivery_conversation_graph import (
    build_workspace_delivery_conversation_graph,
)
from src.agents.profiles.workspace_delivery_graph import build_workspace_delivery_graph
from src.agents.profiles.workspace_quality_graph import build_workspace_quality_graph
from src.agents.runtime.contracts import (
    AgentRuntimeRequest,
    AgentRuntimeResponse,
    AgentRuntimeStatus,
    RuntimeMetadata,
    RuntimeUsage,
)
from src.config import get_settings
from src.services.llm import get_workspace_llm_configuration


def _conversation_messages(request: AgentRuntimeRequest) -> list:
    remaining = get_settings().workspace_agent_history_prompt_max_chars
    bounded_reversed = []
    for item in reversed(request.history):
        if remaining <= 0:
            break
        content = item.content[: min(2_000, remaining)]
        remaining -= len(content)
        bounded_reversed.append((item.role, content))
    history = [
        HumanMessage(content=content) if role == "user" else AIMessage(content=content)
        for role, content in reversed(bounded_reversed)
    ]
    return [*history, HumanMessage(content=request.message)]


def _usage_from_messages(messages: list) -> RuntimeUsage:
    input_tokens = output_tokens = total_tokens = 0
    for message in messages:
        metadata = getattr(message, "usage_metadata", None)
        if not isinstance(metadata, dict):
            continue
        input_tokens += int(metadata.get("input_tokens", 0) or 0)
        output_tokens += int(metadata.get("output_tokens", 0) or 0)
        total_tokens += int(metadata.get("total_tokens", 0) or 0)
    return RuntimeUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=max(total_tokens, input_tokens + output_tokens),
    )


def _usage_from_state(state: dict, messages: list) -> RuntimeUsage:
    usage = state.get("metadata", {}).get("runtime_usage")
    if isinstance(usage, dict):
        return RuntimeUsage.model_validate(usage)
    return _usage_from_messages(messages)


async def execute_product_delivery(
    request: AgentRuntimeRequest,
    *,
    progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> AgentRuntimeResponse:
    if request.target.profile != AgentProfile.PRODUCT_DELIVERY:
        raise ValueError("Product Delivery runtime received a different profile")
    started = perf_counter()
    if request.interaction_mode == "workspace_conversation":
        context = request.snapshot.payload.get("workspace_conversation_context", {})
        role = request.actor.business_role
        intent = DeliveryIntent(request.interaction_intent)
        graph = build_workspace_delivery_conversation_graph(
            role=role,
            intent=intent,
            authorized_group_count=max(0, int(context.get("authorized_group_count", 0) or 0)),
            clarification_hint=str(context.get("clarification_hint", "") or ""),
        )
        state = await graph.ainvoke(
            {"messages": _conversation_messages(request)},
            {"recursion_limit": 6},
        )
    elif request.orchestration is not None:
        state = await run_delivery_supervisor(
            snapshot=request.snapshot,
            orchestration=request.orchestration,
            messages=_conversation_messages(request),
            progress_callback=progress_callback,
        )
    else:
        graph = build_workspace_delivery_graph(snapshot=request.snapshot)
        state = await graph.ainvoke(
            {"messages": _conversation_messages(request)},
            {"recursion_limit": 8},
        )
    messages = list(state.get("messages", []))
    metadata = state.get("metadata", {})
    synthesis_fallback = bool(metadata.get("synthesis_fallback", False))
    model = get_workspace_llm_configuration(AgentProfile.PRODUCT_DELIVERY)
    specialist_model = (
        get_workspace_llm_configuration(AgentProfile.PRODUCT_DELIVERY, purpose="specialist")
        if request.orchestration is not None
        else None
    )
    verifier_applied = bool(metadata.get("verifier_applied", False))
    specialist_results = tuple(state.get("specialist_results", ()))
    verifier_model = (
        get_workspace_llm_configuration(AgentProfile.PRODUCT_DELIVERY, purpose="verification")
        if verifier_applied
        else None
    )
    answer = next(
        (
            message.content
            for message in reversed(messages)
            if isinstance(message, AIMessage) and isinstance(message.content, str) and message.content
        ),
        None,
    )
    if answer is None:
        raise RuntimeError("Delivery agent returned no final response")
    base_gaps = () if request.orchestration is not None else request.snapshot.data_gaps
    effective_sources = (
        tuple(
            {
                (source.resource_id, source.resource_type, source.agent_workspace_id): source
                for result in specialist_results
                for source in result.sources
            }.values()
        )
        if request.orchestration is not None
        else request.snapshot.sources
    )
    effective_gaps = tuple(
        dict.fromkeys(
            (
                *base_gaps,
                *(gap for result in specialist_results for gap in result.data_gaps),
                *((str(metadata.get("fallback_reason") or "LLM_SYNTHESIS_UNAVAILABLE"),)
                  if synthesis_fallback else ()),
            )
        )
    )
    return AgentRuntimeResponse(
        run_id=request.run_id,
        trace_id=request.trace_id,
        status=(
            AgentRuntimeStatus.DEGRADED
            if (
                effective_gaps
                or synthesis_fallback
                or any(result.status.value != "success" for result in specialist_results)
            )
            else AgentRuntimeStatus.SUCCESS
        ),
        answer=answer,
        sources=effective_sources,
        data_gaps=effective_gaps,
        usage=_usage_from_state(state, messages),
        runtime=RuntimeMetadata(
            profile=AgentProfile.PRODUCT_DELIVERY,
            runtime_version=request.target.runtime_version,
            duration_ms=max(0, round((perf_counter() - started) * 1000)),
            prompt_version=PRODUCT_DELIVERY_PROMPT_VERSION,
            model_provider=str(metadata.get("model_provider") or model.provider),
            model_name=str(metadata.get("model_name") or model.model),
            specialist_model_provider=specialist_model.provider if specialist_model else "",
            specialist_model_name=specialist_model.model if specialist_model else "",
            llm_calls=int(metadata.get("llm_calls", 0) or 0),
            llm_attempts=int(metadata.get("llm_attempts", metadata.get("llm_calls", 0)) or 0),
            llm_successes=int(metadata.get("llm_successes", 0) or 0),
            model_attempts=tuple(metadata.get("model_attempts", ())),
            verifier_applied=verifier_applied,
            verifier_model_provider=verifier_model.provider if verifier_model else "",
            verifier_model_name=verifier_model.model if verifier_model else "",
            synthesis_usage=RuntimeUsage.model_validate(metadata.get("synthesis_usage", {})),
            specialist_usage=RuntimeUsage.model_validate(metadata.get("specialist_usage", {})),
            verifier_usage=RuntimeUsage.model_validate(metadata.get("verifier_usage", {})),
            synthesis_fallback=synthesis_fallback,
            fallback_reason=str(metadata.get("fallback_reason", "")),
            prompt_input_chars=int(metadata.get("prompt_input_chars", 0) or 0),
            snapshot_original_chars=int(metadata.get("snapshot_original_chars", 0) or 0),
            snapshot_included_chars=int(metadata.get("snapshot_included_chars", 0) or 0),
            snapshot_compacted=bool(metadata.get("snapshot_compacted", False)),
            execution_mode=(
                "workspace_only"
                if request.interaction_mode == "workspace_conversation"
                else request.orchestration.execution_mode.value
                if request.orchestration is not None
                else "single_snapshot"
            ),
            intent=(
                request.interaction_intent
                if request.interaction_mode == "workspace_conversation"
                else request.orchestration.intent.value
                if request.orchestration is not None
                else ""
            ),
            plan_version=(
                request.routing_plan_version
                if request.interaction_mode == "workspace_conversation"
                else request.orchestration.plan_version
                if request.orchestration is not None
                else ""
            ),
            workflow_id=(request.orchestration.workflow_id if request.orchestration is not None else ""),
            specialists_requested=tuple(task.specialist.value for task in request.orchestration.child_tasks)
            if request.orchestration is not None
            else (),
            specialists_completed=tuple(
                result.specialist.value for result in specialist_results if result.status.value != "error"
            ),
            specialists_failed=tuple(
                result.specialist.value for result in specialist_results if result.status.value == "error"
            ),
            specialist_llm_attempts=int(metadata.get("specialist_llm_attempts", 0) or 0),
            specialist_fallbacks=dict(metadata.get("specialist_fallbacks", {})),
            specialist_model_attempts={
                key: tuple(value)
                for key, value in dict(metadata.get("specialist_model_attempts", {})).items()
            },
            evidence_branch_executed=bool(metadata.get("evidence_branch_executed", False)),
            specialist_results=specialist_results,
        ),
    )


async def execute_quality_assurance(request: AgentRuntimeRequest) -> AgentRuntimeResponse:
    """Explain a deterministic QA assessment through the isolated QA graph."""

    if request.target.profile != AgentProfile.QUALITY_ASSURANCE:
        raise ValueError("Quality Assurance runtime received a different profile")
    started = perf_counter()
    graph = build_workspace_quality_graph(snapshot=request.snapshot)
    state = await graph.ainvoke(
        {"messages": _conversation_messages(request)},
        {"recursion_limit": 8},
    )
    messages = list(state.get("messages", []))
    metadata = state.get("metadata", {})
    synthesis_fallback = bool(metadata.get("synthesis_fallback", False))
    model = get_workspace_llm_configuration(AgentProfile.QUALITY_ASSURANCE)
    verifier_applied = bool(metadata.get("verifier_applied", False))
    verifier_model = (
        get_workspace_llm_configuration(AgentProfile.QUALITY_ASSURANCE, purpose="verification")
        if verifier_applied
        else None
    )
    answer = next(
        (
            message.content
            for message in reversed(messages)
            if isinstance(message, AIMessage) and isinstance(message.content, str) and message.content
        ),
        None,
    )
    if answer is None:
        raise RuntimeError("Quality agent returned no final response")
    return AgentRuntimeResponse(
        run_id=request.run_id,
        trace_id=request.trace_id,
        status=(
            AgentRuntimeStatus.DEGRADED
            if request.snapshot.data_gaps or synthesis_fallback
            else AgentRuntimeStatus.SUCCESS
        ),
        answer=answer,
        sources=request.snapshot.sources,
        data_gaps=tuple(
            dict.fromkeys(
                (
                    *request.snapshot.data_gaps,
                    *(("LLM_SYNTHESIS_UNAVAILABLE",) if synthesis_fallback else ()),
                )
            )
        ),
        usage=_usage_from_state(state, messages),
        runtime=RuntimeMetadata(
            profile=AgentProfile.QUALITY_ASSURANCE,
            runtime_version=request.target.runtime_version,
            duration_ms=max(0, round((perf_counter() - started) * 1000)),
            prompt_version=QUALITY_ASSURANCE_PROMPT_VERSION,
            model_provider=model.provider,
            model_name=model.model,
            llm_calls=int(metadata.get("llm_calls", 0) or 0),
            verifier_applied=verifier_applied,
            verifier_model_provider=verifier_model.provider if verifier_model else "",
            verifier_model_name=verifier_model.model if verifier_model else "",
            synthesis_usage=RuntimeUsage.model_validate(metadata.get("synthesis_usage", {})),
            verifier_usage=RuntimeUsage.model_validate(metadata.get("verifier_usage", {})),
            synthesis_fallback=synthesis_fallback,
            fallback_reason=str(metadata.get("fallback_reason", "")),
            prompt_input_chars=int(metadata.get("prompt_input_chars", 0) or 0),
            snapshot_original_chars=int(metadata.get("snapshot_original_chars", 0) or 0),
            snapshot_included_chars=int(metadata.get("snapshot_included_chars", 0) or 0),
            snapshot_compacted=bool(metadata.get("snapshot_compacted", False)),
        ),
    )


async def execute_workspace_agent(request: AgentRuntimeRequest) -> AgentRuntimeResponse:
    if request.target.profile == AgentProfile.PRODUCT_DELIVERY:
        return await execute_product_delivery(request)
    if request.target.profile == AgentProfile.QUALITY_ASSURANCE:
        return await execute_quality_assurance(request)
    raise ValueError(f"Unsupported workspace runtime profile: {request.target.profile.value}")
