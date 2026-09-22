from __future__ import annotations

from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from src.agents.contracts import AgentIntent, AgentProfile, BusinessRole, PolicyDecision, RequestedScope


class AgentState(TypedDict, total=False):
    """State schema cho LangGraph agent.

    Mỗi node đọc và ghi vào state này.
    total=False cho phép tất cả fields là optional.
    """

    query: str
    context: str
    analysis: str
    response: str
    error: str
    metadata: dict
    # Deterministic pre/post LLM policy checks. These flags make a blocked turn terminal
    # without allowing it to reach the planner or any tool.
    guardrail_blocked: bool
    guardrail_requires_clarification: bool
    personal_intent: str
    routing_strategy: str
    personal_plan: dict
    action_requires_clarification: bool
    user_id: str | None  # id of the user driving this run, for tools that push WS updates to them
    workspace_id: str | None  # active workspace for tenant-scoped tools
    trace_id: str | None
    agent_workspace_id: str | None
    business_role: BusinessRole | None
    agent_profile: AgentProfile | None
    intent: AgentIntent | None
    requested_scope: RequestedScope | None
    allowed_agent_workspace_ids: list[str]
    allowed_resource_ids: list[str]
    policy_decision: PolicyDecision | None
    policy_reason: str | None
    prompt_version: str | None
    conversation_id: str | None
    consent_scope_hash: str | None
    source_message_ids: list[str]
    thread_summary: str

    # Tool-calling planner loop (messages, ToolNode, tools_condition all require this).
    messages: Annotated[list[AnyMessage], add_messages]

    # Structured outputs of the summarize/calendar/reminder tools.
    summary: str
    calendar_event_draft: dict | None
    reminder_draft: dict | None
