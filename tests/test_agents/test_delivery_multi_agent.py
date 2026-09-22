from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select

import src.db.session as db_session
from src.agents.contracts import BusinessRole, ToolResult, ToolResultStatus
from src.agents.delivery_orchestration.context_builder import build_specialist_context
from src.agents.delivery_orchestration.contracts import (
    DeliveryExecutionMode,
    DeliveryIntent,
    DeliveryOrchestrationContext,
    DeliverySpecialist,
    DeliverySpecialistResult,
    RuntimeChildTask,
    canonical_payload_hash,
)
from src.agents.delivery_orchestration.request_router import (
    constrain_delivery_route,
    route_delivery_request,
)
from src.agents.delivery_orchestration.semantic_router import (
    SemanticDeliveryRoute,
    resolve_delivery_route,
)
from src.agents.delivery_specialists.graph import (
    _meeting_plan_analysis,
    _risk_analysis,
    _task_analysis,
)
from src.agents.delivery_specialists.prompts import SPECIALIST_TOOL_ALLOWLISTS
from src.agents.delivery_specialists.tools import execute_delegated_delivery_tools
from src.agents.delivery_supervisor import run_delivery_supervisor
from src.agents.delivery_supervisor.graph import _build_team_delivery_assessments
from src.agents.profiles.workspace_delivery_conversation_graph import (
    build_workspace_delivery_conversation_graph,
)
from src.agents.runtime.contracts import RuntimeConversationMessage
from src.config import Settings
from src.db.models import (
    DeliveryAgentRun,
    DeliverySpecialistResultRecord,
    DeliveryWorkflowEventRecord,
)
from src.services.delivery_event_inbox_service import accept_delivery_event_once
from src.services.delivery_workflow_service import (
    complete_delivery_workflow,
    create_delivery_workflow,
    mark_delivery_workflow_running,
)
from src.services.llm import LLMConfiguration
from tests.test_agent_workspaces import _seed_agent_workspaces


def test_router_uses_task_intelligence_for_an_exact_task_lookup():
    task_id = "a" * 32

    task_lookup = route_delivery_request(f"Xem task {task_id}")
    analysis = route_delivery_request("Phân tích blocker của release tuần này")

    assert task_lookup.execution_mode == DeliveryExecutionMode.SINGLE_SPECIALIST
    assert task_lookup.intent == DeliveryIntent.TASK_LOOKUP
    assert task_lookup.subject_id == task_id
    assert task_lookup.specialists == (DeliverySpecialist.TASK_INTELLIGENCE,)
    assert analysis.execution_mode == DeliveryExecutionMode.MULTI_SPECIALIST
    assert analysis.specialists == (
        DeliverySpecialist.TASK_INTELLIGENCE,
        DeliverySpecialist.RISK_DEPENDENCY,
        DeliverySpecialist.PLANNING_FORECAST,
    )


def test_legacy_work_specialist_value_normalizes_to_unified_task_agent():
    assert DeliverySpecialist("work_intelligence") is DeliverySpecialist.TASK_INTELLIGENCE


def test_risk_agent_classifies_dependencies_by_authorized_group():
    payload = {
        "groups": [
            {"id": "group-a", "name": "Apollo"},
            {"id": "group-b", "name": "Portal"},
        ],
        "dependencies": [
            {
                "id": "dep-1",
                "status": "blocked",
                "assignee_id": "owner-1",
                "predecessor_task_id": "task-a",
                "successor_task_id": "task-b",
                "sources": [{"resource_type": "conversation", "resource_id": "group-a"}],
            },
            {
                "id": "dep-2",
                "status": "open",
                "assignee_id": "owner-2",
                "predecessor_task_id": "task-c",
                "successor_task_id": "task-d",
                "sources": [{"resource_type": "conversation", "resource_id": "group-b"}],
            },
        ],
        "risks": [],
    }

    analysis = _risk_analysis(payload)
    summaries = analysis["metrics"]["dependency_group_summary"]

    assert summaries[0]["group_name"] == "Apollo"
    assert summaries[0]["blocked_dependency_count"] == 1
    assert summaries[0]["linked_dependency_count"] == 1
    assert summaries[1]["group_name"] == "Portal"
    assert summaries[1]["open_dependency_count"] == 1


def test_risk_agent_explains_dependency_chain_and_prioritizes_blockers():
    payload = {
        "groups": [{"id": "group-a", "name": "Apollo"}],
        "work_items": [
            {"id": "task-a", "title": "Chốt API contract", "blocked_reason": "Vendor chưa xác nhận schema"},
            {"id": "task-b", "title": "Tích hợp checkout"},
        ],
        "dependencies": [
            {
                "id": "dep-open",
                "title": "API contract",
                "status": "open",
                "assignee_id": "owner-1",
                "owner_name": "Lan",
                "predecessor_task_id": "task-a",
                "successor_task_id": "task-b",
                "due_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
                "sources": [{"resource_type": "conversation", "resource_id": "group-a"}],
            },
            {
                "id": "dep-blocked",
                "title": "Credential UAT",
                "status": "blocked",
                "predecessor_task_title": "Cấp credential UAT",
                "successor_task_title": "Chạy regression",
                "sources": [{"resource_type": "conversation", "resource_id": "group-a"}],
            },
        ],
        "risks": [{"id": "risk-1", "title": "Release trễ", "severity": "high", "group_name": "Apollo"}],
    }

    analysis = _risk_analysis(payload)
    artifact = analysis["artifact"]
    dependencies = artifact.groups[0]["dependencies"]

    assert dependencies[0]["dependency_id"] == "dep-blocked"
    assert dependencies[0]["status_label"] == "đang chặn công việc sau"
    assert dependencies[0]["missing_fields"] == ["owner", "deadline"]
    assert dependencies[1]["business_meaning"] == (
        "“Chốt API contract” phải hoàn tất trước; nếu chưa xong thì “Tích hợp checkout” chưa thể tiếp tục."
    )
    assert dependencies[1]["blocker_reason"] == "Vendor chưa xác nhận schema"
    assert analysis["metrics"]["priority_dependencies"][0]["dependency_id"] == "dep-blocked"
    assert artifact.groups[0]["risks"][0]["severity_label"] == "cao"


def test_risk_agent_keeps_unmapped_records_visible_as_a_data_quality_bucket():
    analysis = _risk_analysis(
        {
            "groups": [],
            "work_items": [],
            "dependencies": [{"id": "dep-1", "title": "External input", "status": "open", "sources": []}],
            "risks": [{"id": "risk-1", "title": "Unknown impact", "severity": "medium", "sources": []}],
        }
    )

    assert analysis["artifact"].groups[0]["group_name"] == "Chưa xác định nhóm"
    assert analysis["metrics"]["dependency_group_summary"][0]["dependency_count"] == 1
    assert analysis["artifact"].groups[0]["risks"][0]["title"] == "Unknown impact"


def test_team_assessment_preserves_task_reason_owner_and_dependency_context():
    due_at = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    payload = {
        "groups": [{"id": "group-release", "name": "Release 34"}],
        "people": [{"user_id": "mobile-owner", "display_name": "Nhóm Mobile"}],
        "work_items": [
            {
                "id": "crash-task",
                "title": "Giảm crash rate iOS xuống dưới 1%",
                "status": "blocked",
                "assignee_id": "mobile-owner",
                "due_at": due_at,
                "blocked_reason": "Crash rate iOS đang ở mức 2,4%",
                "sources": [{"resource_type": "conversation", "resource_id": "group-release"}],
            },
            {
                "id": "go-no-go",
                "title": "Chuẩn bị dữ liệu go/no-go",
                "status": "in_progress",
                "sources": [{"resource_type": "conversation", "resource_id": "group-release"}],
            },
        ],
        "dependencies": [
            {
                "title": "Crash gate trước go/no-go",
                "status": "blocked",
                "assignee_id": "mobile-owner",
                "owner_name": "Nhóm Mobile",
                "due_at": due_at,
                "predecessor_task_id": "crash-task",
                "successor_task_id": "go-no-go",
                "predecessor_task_title": "Giảm crash rate iOS xuống dưới 1%",
                "successor_task_title": "Chuẩn bị dữ liệu go/no-go",
                "sources": [{"resource_type": "conversation", "resource_id": "group-release"}],
            }
        ],
        "risks": [],
        "checkpoint_progress": [],
        "decisions": [],
    }
    progress = [
        {
            "group_name": "Release 34",
            "total_task_count": 2,
            "completed_task_count": 0,
            "blocked_task_count": 1,
            "overdue_task_count": 0,
            "completion_percent": 0,
        }
    ]

    assessment = _build_team_delivery_assessments(payload, progress)[0]

    assert assessment["attention_tasks"][0]["blocked_reason"] == "Crash rate iOS đang ở mức 2,4%"
    assert assessment["attention_tasks"][0]["owner_name"] == "Nhóm Mobile"
    assert assessment["dependencies"][0]["predecessor_blocked_reason"] == "Crash rate iOS đang ở mức 2,4%"
    assert assessment["dependencies"][0]["successor_status"] == "in_progress"


def test_weakest_team_meeting_plan_routes_to_a_three_agent_dag_without_hardcoded_team():
    route = route_delivery_request("Lên kế hoạch họp cho nhóm bị đánh giá thấp nhất")

    assert route.intent == DeliveryIntent.MEETING_PLAN
    assert route.target_selector == "lowest_completion"
    assert route.specialists == (
        DeliverySpecialist.TASK_INTELLIGENCE,
        DeliverySpecialist.RISK_DEPENDENCY,
        DeliverySpecialist.PLANNING_FORECAST,
    )


@pytest.mark.parametrize(
    ("message", "intent", "specialists"),
    (
        (
            "Phân tích chuỗi phụ thuộc của các nhóm. Với mỗi chuỗi, nói việc nào phải xong trước, "
            "việc nào bị chặn và rủi ro nếu chưa gỡ.",
            DeliveryIntent.DEPENDENCY_ANALYSIS,
            (
                DeliverySpecialist.TASK_INTELLIGENCE,
                DeliverySpecialist.RISK_DEPENDENCY,
                DeliverySpecialist.PLANNING_FORECAST,
            ),
        ),
        (
            "Các milestone hiện khỏe hay có nguy cơ? Phân tích task, kế hoạch và blocker liên quan.",
            DeliveryIntent.MILESTONE_HEALTH,
            (
                DeliverySpecialist.TASK_INTELLIGENCE,
                DeliverySpecialist.PLANNING_FORECAST,
                DeliverySpecialist.RISK_DEPENDENCY,
            ),
        ),
        (
            "Phân tích tác động thay đổi scope Customer Portal so với baseline trước tới task, lịch và dependency.",
            DeliveryIntent.CHANGE_IMPACT,
            (
                DeliverySpecialist.TASK_INTELLIGENCE,
                DeliverySpecialist.PLANNING_FORECAST,
                DeliverySpecialist.RISK_DEPENDENCY,
            ),
        ),
        (
            "Release 34 đã sẵn sàng phát hành và giao đúng hạn chưa? Tổng hợp task, lịch, blocker và bằng chứng quyết định.",
            DeliveryIntent.RELEASE_DELIVERY_READINESS,
            (
                DeliverySpecialist.TASK_INTELLIGENCE,
                DeliverySpecialist.PLANNING_FORECAST,
                DeliverySpecialist.RISK_DEPENDENCY,
                DeliverySpecialist.EVIDENCE_KNOWLEDGE,
            ),
        ),
        (
            "Tổng hợp task, phân loại dependency và lập agenda họp cho các nhóm tiến độ yếu.",
            DeliveryIntent.MEETING_PLAN,
            (
                DeliverySpecialist.TASK_INTELLIGENCE,
                DeliverySpecialist.RISK_DEPENDENCY,
                DeliverySpecialist.PLANNING_FORECAST,
            ),
        ),
    ),
)
def test_chat_playbook_outcome_phrases_take_precedence_over_input_nouns(
    message, intent, specialists
):
    route = route_delivery_request(message)

    assert route.intent == intent
    assert route.execution_mode == DeliveryExecutionMode.MULTI_SPECIALIST
    assert route.specialists == specialists


@pytest.mark.asyncio
async def test_semantic_router_resumes_a_confirmed_meeting_plan_from_thread_context(monkeypatch):
    class StructuredRouter:
        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, _messages):
            return SemanticDeliveryRoute(
                intent="meeting_plan",
                confidence=0.98,
                target_group_name="Customer Portal",
                reason="User confirmed the previously proposed target group.",
            )

    monkeypatch.setattr(
        "src.agents.delivery_orchestration.semantic_router.get_workspace_llm",
        lambda *_args, **_kwargs: StructuredRouter(),
    )
    route = await resolve_delivery_route(
        "đúng rồi",
        history=(
            RuntimeConversationMessage(role="user", content="Lập plan cho nhóm yếu nhất"),
            RuntimeConversationMessage(
                role="assistant",
                content="Bạn muốn tôi lập kế hoạch cho Customer Portal đúng không?",
            ),
        ),
        authorized_groups=(
            {"id": "portal-id", "name": "Customer Portal"},
            {"id": "apollo-id", "name": "Apollo Platform"},
        ),
    )

    assert route.intent == DeliveryIntent.MEETING_PLAN
    assert route.target_group_id == "portal-id"
    assert route.target_group_name == "Customer Portal"
    assert route.execution_mode == DeliveryExecutionMode.MULTI_SPECIALIST


@pytest.mark.asyncio
async def test_semantic_router_fails_over_and_exposes_provider_attempts(monkeypatch):
    class RateLimitedRouter:
        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, _messages):
            raise RuntimeError("429 quota exhausted")

    class WorkingRouter:
        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, _messages):
            return SemanticDeliveryRoute(
                intent="out_of_scope",
                confidence=0.99,
                reason="General-knowledge request outside Product Delivery.",
            )

    primary = LLMConfiguration("groq", "router-primary", 0.0, 384)
    fallback = LLMConfiguration("openrouter", "router-fallback", 0.0, 384)
    monkeypatch.setattr(
        "src.agents.delivery_orchestration.semantic_router.get_workspace_llm_candidate_configurations",
        lambda *_args, **_kwargs: (("routing", primary), ("specialist", fallback)),
    )
    monkeypatch.setattr(
        "src.agents.delivery_orchestration.semantic_router.get_workspace_llm",
        lambda *_args, purpose, **_kwargs: (
            RateLimitedRouter() if purpose == "routing" else WorkingRouter()
        ),
    )

    route = await resolve_delivery_route("từ cung là gì")

    assert route.intent == DeliveryIntent.OUT_OF_SCOPE
    assert route.routing_strategy == "semantic_failover"
    assert [attempt.status for attempt in route.routing_llm_attempts] == ["failed", "succeeded"]
    assert route.routing_llm_attempts[0].error_code == "LLM_RATE_LIMITED"


@pytest.mark.asyncio
async def test_context_router_resumes_named_group_clarification_without_llm(monkeypatch):
    monkeypatch.setattr(
        "src.agents.delivery_orchestration.semantic_router.get_workspace_llm",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM must not be called")),
    )

    route = await resolve_delivery_route(
        "Customer Portal.",
        history=(
            RuntimeConversationMessage(role="user", content="Lên kế hoạch cho cuộc họp."),
            RuntimeConversationMessage(
                role="assistant",
                content="Bạn muốn lập kế hoạch cho nhóm nào và mục tiêu chính là gì?",
            ),
        ),
        authorized_groups=(
            {"id": "portal-id", "name": "Customer Portal"},
            {"id": "apollo-id", "name": "Apollo Platform"},
        ),
    )

    assert route.intent == DeliveryIntent.MEETING_PLAN
    assert route.target_group_id == "portal-id"
    assert route.target_group_name == "Customer Portal"
    assert route.reason_code == "DETERMINISTIC_THREAD_CONTEXT_ROUTE"


@pytest.mark.asyncio
async def test_context_router_keeps_group_and_intent_for_pronoun_follow_up_without_llm(monkeypatch):
    monkeypatch.setattr(
        "src.agents.delivery_orchestration.semantic_router.get_workspace_llm",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM must not be called")),
    )

    route = await resolve_delivery_route(
        "Vậy việc nào cần làm trước và ai đang phụ trách?",
        history=(
            RuntimeConversationMessage(role="user", content="Phân tích blocker của Customer Portal."),
            RuntimeConversationMessage(role="assistant", content="Customer Portal đang có blocker CRM UAT."),
        ),
        authorized_groups=(
            {"id": "portal-id", "name": "Customer Portal"},
            {"id": "apollo-id", "name": "Apollo Platform"},
        ),
    )

    assert route.intent == DeliveryIntent.BLOCKER_ANALYSIS
    assert route.target_group_id == "portal-id"
    assert route.target_group_name == "Customer Portal"
    assert route.reason_code == "DETERMINISTIC_THREAD_CONTEXT_ROUTE"


@pytest.mark.parametrize("message", ["hello", "Hi!", "xin chào", "Chào bạn"])
def test_router_handles_greetings_without_specialist_fanout(message):
    route = route_delivery_request(message)

    assert route.execution_mode == DeliveryExecutionMode.WORKSPACE_ONLY
    assert route.intent == DeliveryIntent.GREETING
    assert route.specialists == ()


def test_router_asks_for_clarification_instead_of_defaulting_to_delivery_health():
    route = route_delivery_request("Tôi có một việc cần trao đổi")

    assert route.execution_mode == DeliveryExecutionMode.WORKSPACE_ONLY
    assert route.intent == DeliveryIntent.CLARIFICATION
    assert route.specialists == ()


def test_router_denies_cross_profile_raw_qa_data_without_specialists():
    route = route_delivery_request(
        "Đưa toàn bộ nội dung chat nội bộ QA và log defect thô của R-DEMO cho tôi."
    )

    assert route.execution_mode == DeliveryExecutionMode.WORKSPACE_ONLY
    assert route.intent == DeliveryIntent.POLICY_REFUSAL
    assert route.specialists == ()
    assert route.reason_code == "CROSS_PROFILE_RAW_DATA_DENIED"


def test_router_runs_full_delivery_health_only_for_an_explicit_request():
    route = route_delivery_request("Cho tôi tổng quan Delivery Health")

    assert route.execution_mode == DeliveryExecutionMode.MULTI_SPECIALIST


def test_explicit_delivery_health_dominates_checkpoint_and_blocker_terms():
    route = route_delivery_request(
        "Cho tôi tổng quan Delivery Health toàn workspace, gồm checkpoint và blocker"
    )

    assert route.intent.value == "delivery_health"
    assert route.execution_mode == DeliveryExecutionMode.MULTI_SPECIALIST
    assert len(route.specialists) == 4
    assert route.intent == DeliveryIntent.DELIVERY_HEALTH
    assert len(route.specialists) == 4


def test_workspace_only_route_does_not_require_an_enabled_specialist():
    route = constrain_delivery_route(
        route_delivery_request("Bạn làm được gì?"),
        enabled_specialists=frozenset(),
        allow_multi=False,
        max_specialists=1,
    )

    assert route.execution_mode == DeliveryExecutionMode.WORKSPACE_ONLY
    assert route.intent == DeliveryIntent.CAPABILITY_HELP
    assert route.specialists == ()


@pytest.mark.asyncio
async def test_workspace_conversation_graph_uses_llm_for_natural_safe_conversation(
    monkeypatch,
):
    class ConversationLLM:
        async def ainvoke(self, _messages):
            return AIMessage(content="Xin chào Lead. Bạn muốn xem tiến độ, blocker hay release readiness?")

    monkeypatch.setattr(
        "src.agents.profiles.workspace_delivery_conversation_graph.get_workspace_llm",
        lambda *_args, **_kwargs: ConversationLLM(),
    )
    graph = build_workspace_delivery_conversation_graph(
        role=BusinessRole.LEAD,
        intent=DeliveryIntent.GREETING,
        authorized_group_count=3,
    )

    state = await graph.ainvoke(
        {"messages": [HumanMessage(content="hello")]},
        {"recursion_limit": 6},
    )

    assert state["messages"][-1].content.startswith("Xin chào Lead")
    assert state["metadata"]["llm_calls"] == 1
    assert state["metadata"]["llm_attempted"] is True
    assert state["metadata"]["llm_successes"] == 1
    assert state["metadata"]["synthesis_fallback"] is False


@pytest.mark.asyncio
async def test_workspace_conversation_graph_uses_safe_llm_boundary_for_out_of_scope(
    monkeypatch,
):
    class ConversationLLM:
        async def ainvoke(self, _messages):
            return AIMessage(
                content="Câu hỏi này nằm ngoài Product Delivery. Bạn có thể chuyển sang Personal Agent; ở đây tôi có thể hỗ trợ blocker hoặc tiến độ."
            )

    monkeypatch.setattr(
        "src.agents.profiles.workspace_delivery_conversation_graph.get_workspace_llm",
        lambda *_args, **_kwargs: ConversationLLM(),
    )
    graph = build_workspace_delivery_conversation_graph(
        role=BusinessRole.LEAD,
        intent=DeliveryIntent.OUT_OF_SCOPE,
        authorized_group_count=3,
    )

    state = await graph.ainvoke(
        {"messages": [HumanMessage(content="Hoàng Sa Trường Sa thuộc nước nào?")]},
        {"recursion_limit": 6},
    )

    assert "ngoài Product Delivery" in state["messages"][-1].content
    assert state["metadata"].get("llm_calls", 0) == 1
    assert state["metadata"].get("llm_attempted", False) is True


def test_deployment_flags_can_reduce_a_multi_specialist_plan_without_prompt_control():
    route = route_delivery_request("Đánh giá release readiness")

    constrained = constrain_delivery_route(
        route,
        enabled_specialists=frozenset({DeliverySpecialist.TASK_INTELLIGENCE}),
        allow_multi=True,
        max_specialists=4,
    )

    assert constrained.execution_mode == DeliveryExecutionMode.SINGLE_SPECIALIST
    assert constrained.specialists == (DeliverySpecialist.TASK_INTELLIGENCE,)
    assert constrained.reason_code.endswith("FEATURE_GATED")


def test_specialist_contexts_are_minimal_and_do_not_leak_other_domain_payloads():
    snapshot = ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={
            "work_items": [{"id": "task-1"}],
            "capacity": {"overdue": 1},
            "portfolio_health": {"health": "AT_RISK"},
            "groups": [{"id": "group-1", "name": "Apollo"}],
            "scope_context": {"mode": "workspace"},
            "message_evidence": [{"message_id": "private-evidence"}],
            "decisions": [{"id": "decision-1"}],
        },
    )

    task_context = build_specialist_context(snapshot, DeliverySpecialist.TASK_INTELLIGENCE)
    evidence_context = build_specialist_context(snapshot, DeliverySpecialist.EVIDENCE_KNOWLEDGE)

    assert "work_items" in task_context.payload
    assert "portfolio_health" in task_context.payload
    assert task_context.payload["groups"] == [{"id": "group-1", "name": "Apollo"}]
    assert task_context.payload["scope_context"] == {"mode": "workspace"}
    assert "message_evidence" not in task_context.payload
    assert "decisions" not in task_context.payload
    assert "message_evidence" in evidence_context.payload
    assert "work_items" not in evidence_context.payload


def test_task_analysis_builds_deterministic_progress_for_every_authorized_group():
    def task(task_id, group_id, status):
        return {
            "id": task_id,
            "status": status,
            "sources": [{"resource_type": "conversation", "resource_id": group_id}],
        }

    analysis = _task_analysis(
        {
            "groups": [
                {"id": "apollo", "name": "Apollo Platform"},
                {"id": "portal", "name": "Customer Portal"},
            ],
            "work_items": [
                task("a1", "apollo", "completed"),
                task("a2", "apollo", "blocked"),
                task("p1", "portal", "in_progress"),
                task("p2", "portal", "submitted"),
            ],
            "capacity": {},
        }
    )

    progress = analysis["metrics"]["group_progress"]
    assert progress == [
        {
            "group_name": "Apollo Platform",
            "total_task_count": 2,
            "completed_task_count": 1,
            "active_task_count": 1,
            "blocked_task_count": 1,
            "submitted_task_count": 0,
            "changes_requested_task_count": 0,
            "overdue_task_count": 0,
            "suggested_task_count": 0,
            "completion_percent": 50,
        },
        {
            "group_name": "Customer Portal",
            "total_task_count": 2,
            "completed_task_count": 0,
            "active_task_count": 2,
            "blocked_task_count": 0,
            "submitted_task_count": 1,
            "changes_requested_task_count": 0,
            "overdue_task_count": 0,
            "suggested_task_count": 0,
            "completion_percent": 0,
        },
    ]
    assert [fact["group_name"] for fact in analysis["facts"][:2]] == [
        "Apollo Platform",
        "Customer Portal",
    ]
    assert analysis["artifact"].artifact_type == "team_task_assessment.v1"
    assert analysis["artifact"].weakest_group_name == "Customer Portal"


def test_meeting_plan_is_built_from_typed_task_and_dependency_handoffs():
    base = {"facts": (), "metrics": {}, "data_gaps": (), "fallback": "fallback"}
    analysis = _meeting_plan_analysis(
        {
            "analysis_target": {"selector": "lowest_completion"},
            "upstream_results": [
                {
                    "specialist": "task_intelligence",
                    "artifact": {
                        "artifact_type": "team_task_assessment.v1",
                        "weakest_group_name": "Customer Portal",
                        "teams": [
                            {
                                "group_name": "Customer Portal",
                                "total_task_count": 13,
                                "completed_task_count": 2,
                                "blocked_task_count": 3,
                                "overdue_task_count": 2,
                                "completion_percent": 15,
                            }
                        ],
                    },
                },
                {
                    "specialist": "risk_dependency",
                    "artifact": {
                        "artifact_type": "dependency_risk_analysis.v1",
                        "groups": [
                            {
                                "group_name": "Customer Portal",
                                "dependencies": [
                                    {
                                        "input_required": "Nhận credential CRM UAT",
                                        "blocked_work": "Hoàn thiện bộ 35 test case",
                                        "status": "blocked",
                                        "owner_name": "Sơn Integration",
                                        "due_at": "2026-08-29T10:00:00+07:00",
                                        "business_meaning": "Nếu chưa có credential thì test case chưa thể hoàn tất.",
                                    }
                                ],
                                "risks": [{"title": "UAT bị trì hoãn", "severity": "high"}],
                            }
                        ],
                    },
                },
            ],
        },
        base,
    )

    artifact = analysis["artifact"]
    assert artifact.artifact_type == "meeting_plan.v1"
    assert artifact.target_group_name == "Customer Portal"
    assert artifact.task_assessment["completion_percent"] == 15
    assert artifact.dependency_brief[0]["input_required"] == "Nhận credential CRM UAT"
    assert artifact.action_items[0]["owner"] == "Sơn Integration"
    assert "MEETING_TARGET_DEPENDENCIES_NOT_RECORDED" not in artifact.data_gaps


def test_task_intelligence_executes_exact_subject_tool_within_allowlist():
    task_id = "a" * 32
    context = ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={
            "work_items": [
                {"id": task_id, "title": "Authorized task", "status": "blocked"},
                {"id": "b" * 32, "title": "Another authorized task", "status": "pending"},
            ],
            "capacity": {"overdue": 1},
        },
    )
    task = RuntimeChildTask(
        run_id="task-run",
        specialist=DeliverySpecialist.TASK_INTELLIGENCE,
        goal=f"task_lookup:{task_id}",
        allowed_tools=tuple(sorted(SPECIALIST_TOOL_ALLOWLISTS[DeliverySpecialist.TASK_INTELLIGENCE])),
        max_tool_calls=3,
        subject_refs=(task_id,),
        input_hash=canonical_payload_hash(context.model_dump(mode="json")),
    )

    result, calls = execute_delegated_delivery_tools(context=context, task=task)

    assert [item["id"] for item in result.payload["work_items"]] == [task_id]
    assert calls == ({"tool_name": "get_delivery_task_details", "status": "success", "result_count": 1},)


def test_unified_task_intelligence_reads_aggregate_task_checkpoint_and_health_data():
    context = ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={
            "work_items": [{"id": "task-1", "status": "in_progress"}],
            "capacity": {"overdue": 0},
            "checkpoint_progress": [{"id": "checkpoint-1", "schedule_status": "on_track"}],
            "portfolio_health": {"health": "ON_TRACK"},
        },
    )
    task = RuntimeChildTask(
        run_id="task-summary-run",
        specialist=DeliverySpecialist.TASK_INTELLIGENCE,
        goal="task_progress_summary:workspace",
        allowed_tools=tuple(sorted(SPECIALIST_TOOL_ALLOWLISTS[DeliverySpecialist.TASK_INTELLIGENCE])),
        max_tool_calls=len(SPECIALIST_TOOL_ALLOWLISTS[DeliverySpecialist.TASK_INTELLIGENCE]),
        input_hash=canonical_payload_hash(context.model_dump(mode="json")),
    )

    result, calls = execute_delegated_delivery_tools(context=context, task=task)

    assert [call["tool_name"] for call in calls] == [
        "get_delivery_tasks",
        "get_delivery_checkpoint_progress",
        "get_delivery_portfolio_health",
    ]
    assert set(result.payload) == {
        "work_items",
        "capacity",
        "checkpoint_progress",
        "portfolio_health",
    }


def test_specialist_tool_executor_rejects_tampered_allowlist():
    context = ToolResult(status=ToolResultStatus.SUCCESS, payload={"work_items": []})
    task = RuntimeChildTask(
        run_id="tampered-run",
        specialist=DeliverySpecialist.TASK_INTELLIGENCE,
        goal="task_lookup:task-1",
        allowed_tools=("get_delivery_risks",),
        max_tool_calls=1,
        subject_refs=("task-1",),
        input_hash=canonical_payload_hash(context.model_dump(mode="json")),
    )

    with pytest.raises(ValueError, match="trusted registry"):
        execute_delegated_delivery_tools(context=context, task=task)


@pytest.mark.asyncio
async def test_supervisor_runs_specialists_and_returns_structured_results(
    monkeypatch,
    fake_llm_factory,
):
    settings = Settings(_env_file=None, product_delivery_specialist_llm_enabled=False)
    monkeypatch.setattr("src.agents.delivery_specialists.graph.get_settings", lambda: settings)
    final_llm = fake_llm_factory([AIMessage(content="Tổng hợp Delivery từ hai specialist.")])
    monkeypatch.setattr(
        "src.agents.profiles.workspace_delivery_graph.get_workspace_llm",
        lambda _profile: final_llm,
    )
    snapshot = ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={
            "work_items": [{"id": "task-1", "title": "Ship API", "status": "blocked", "assignee_id": None}],
            "capacity": {"overdue": 1, "due_soon": 0},
            "portfolio_health": {"health": "BLOCKED"},
            "risks": [{"id": "risk-1", "title": "Vendor", "severity": "critical"}],
            "dependencies": [{"id": "dep-1", "title": "Vendor", "status": "blocked"}],
        },
    )
    workflow_id = uuid4().hex
    tasks = []
    for specialist in (
        DeliverySpecialist.TASK_INTELLIGENCE,
        DeliverySpecialist.RISK_DEPENDENCY,
    ):
        context = build_specialist_context(snapshot, specialist)
        tasks.append(
            RuntimeChildTask(
                run_id=uuid4().hex,
                specialist=specialist,
                goal="delivery_health:workspace",
                allowed_tools=tuple(sorted(SPECIALIST_TOOL_ALLOWLISTS[specialist])),
                max_tool_calls=len(SPECIALIST_TOOL_ALLOWLISTS[specialist]),
                input_hash=canonical_payload_hash(context.model_dump(mode="json")),
            )
        )
    orchestration = DeliveryOrchestrationContext(
        workflow_id=workflow_id,
        execution_mode=DeliveryExecutionMode.MULTI_SPECIALIST,
        intent=DeliveryIntent.DELIVERY_HEALTH,
        plan_version="delivery-routing-v1",
        child_tasks=tuple(tasks),
        authorization_capability_ref="cap:test",
        authorization_scope_hash="scope-hash",
        deadline_at=datetime.now(UTC) + timedelta(seconds=10),
    )

    state = await run_delivery_supervisor(
        snapshot=snapshot,
        orchestration=orchestration,
        messages=[HumanMessage(content="Tình hình Delivery thế nào?")],
    )

    assert state["messages"][-1].content.startswith(
        "Trạng thái Delivery được xác định theo dữ liệu: BLOCKED."
    )
    assert state["messages"][-1].content.endswith("Tổng hợp Delivery từ hai specialist.")
    assert {result.specialist for result in state["specialist_results"]} == {
        DeliverySpecialist.TASK_INTELLIGENCE,
        DeliverySpecialist.RISK_DEPENDENCY,
    }
    assert state["metadata"]["execution_mode"] == "multi_specialist"
    assert state["metadata"]["specialists_completed"] == 2
    assert len(final_llm.invocations) == 1


@pytest.mark.asyncio
async def test_single_planning_specialist_preserves_checkpoint_rows_for_synthesis(
    monkeypatch,
    fake_llm_factory,
):
    settings = Settings(_env_file=None, product_delivery_specialist_llm_enabled=False)
    monkeypatch.setattr("src.agents.delivery_specialists.graph.get_settings", lambda: settings)
    final_llm = fake_llm_factory(
        [AIMessage(content="Snapshot hiện không cung cấp dữ liệu checkpoint tiến triển.")]
    )
    monkeypatch.setattr(
        "src.agents.profiles.workspace_delivery_graph.get_workspace_llm",
        lambda _profile: final_llm,
    )
    snapshot = ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={
            "checkpoint_progress": [
                {
                    "checkpoint_id": "checkpoint-release-freeze",
                    "title": "Release 34 freeze readiness",
                    "due_at": "2026-08-28T10:00:00+07:00",
                    "schedule_status": "overdue",
                    "completion_percent": 0,
                    "required_task_count": 3,
                    "completed_required_task_count": 0,
                    "quality_review_status": "pending",
                    "completion_decision": "pending_tasks",
                }
            ],
            "milestones": [],
            "releases": [],
            "flow_metrics": {},
            "groups": [{"id": "release-34", "name": "Release 34"}],
        },
    )
    context = build_specialist_context(snapshot, DeliverySpecialist.PLANNING_FORECAST)
    child = RuntimeChildTask(
        run_id=uuid4().hex,
        specialist=DeliverySpecialist.PLANNING_FORECAST,
        goal="checkpoint_progress:workspace",
        allowed_tools=tuple(
            sorted(SPECIALIST_TOOL_ALLOWLISTS[DeliverySpecialist.PLANNING_FORECAST])
        ),
        max_tool_calls=len(SPECIALIST_TOOL_ALLOWLISTS[DeliverySpecialist.PLANNING_FORECAST]),
        input_hash=canonical_payload_hash(context.model_dump(mode="json")),
    )
    orchestration = DeliveryOrchestrationContext(
        workflow_id=uuid4().hex,
        execution_mode=DeliveryExecutionMode.SINGLE_SPECIALIST,
        intent=DeliveryIntent.CHECKPOINT_PROGRESS,
        plan_version="delivery-routing-v1",
        child_tasks=(child,),
        authorization_capability_ref="cap:test",
        authorization_scope_hash="scope-hash",
        deadline_at=datetime.now(UTC) + timedelta(seconds=10),
    )

    state = await run_delivery_supervisor(
        snapshot=snapshot,
        orchestration=orchestration,
        messages=[HumanMessage(content="Checkpoint nào quá hạn?")],
    )

    assert "Release 34 freeze readiness" in state["messages"][-1].content
    assert "quá hạn" in state["messages"][-1].content
    assert "không cung cấp dữ liệu checkpoint" not in state["messages"][-1].content
    assert "AVAILABLE_CHECKPOINT_DETAILS_RESTORED" in state["metadata"]["narrative_repairs"]


@pytest.mark.asyncio
async def test_supervisor_dag_passes_validated_task_result_to_risk_and_planning(
    monkeypatch,
    fake_llm_factory,
):
    settings = Settings(_env_file=None, product_delivery_specialist_llm_enabled=False)
    monkeypatch.setattr("src.agents.delivery_specialists.graph.get_settings", lambda: settings)
    final_llm = fake_llm_factory([AIMessage(content="Tổng hợp blocker từ DAG.")])
    monkeypatch.setattr(
        "src.agents.profiles.workspace_delivery_graph.get_workspace_llm",
        lambda _profile: final_llm,
    )
    snapshot = ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={
            "work_items": [{"id": "task-1", "title": "OAuth", "status": "blocked"}],
            "capacity": {"overdue": 1},
            "portfolio_health": {"health": "BLOCKED"},
            "risks": [{"id": "risk-1", "title": "Vendor", "severity": "critical"}],
            "dependencies": [{"id": "dep-1", "title": "Vendor", "status": "blocked"}],
            "milestones": [],
            "releases": [],
            "flow_metrics": {},
        },
    )
    workflow_id = uuid4().hex
    dependency_map = {
        DeliverySpecialist.TASK_INTELLIGENCE: (),
        DeliverySpecialist.RISK_DEPENDENCY: (DeliverySpecialist.TASK_INTELLIGENCE,),
        DeliverySpecialist.PLANNING_FORECAST: (DeliverySpecialist.TASK_INTELLIGENCE,),
    }
    tasks = []
    for specialist, depends_on in dependency_map.items():
        context = build_specialist_context(snapshot, specialist)
        tasks.append(
            RuntimeChildTask(
                run_id=uuid4().hex,
                specialist=specialist,
                goal="blocker_analysis:workspace",
                allowed_tools=tuple(sorted(SPECIALIST_TOOL_ALLOWLISTS[specialist])),
                max_tool_calls=len(SPECIALIST_TOOL_ALLOWLISTS[specialist]),
                depends_on=depends_on,
                input_hash=canonical_payload_hash(context.model_dump(mode="json")),
            )
        )
    orchestration = DeliveryOrchestrationContext(
        workflow_id=workflow_id,
        execution_mode=DeliveryExecutionMode.MULTI_SPECIALIST,
        intent=DeliveryIntent.BLOCKER_ANALYSIS,
        plan_version="delivery-routing-v1",
        child_tasks=tuple(tasks),
        authorization_capability_ref="cap:test",
        authorization_scope_hash="scope-hash",
        deadline_at=datetime.now(UTC) + timedelta(seconds=10),
    )

    progress_events = []

    async def capture_progress(event):
        progress_events.append(event)

    state = await run_delivery_supervisor(
        snapshot=snapshot,
        orchestration=orchestration,
        messages=[HumanMessage(content="Analyze blocker")],
        progress_callback=capture_progress,
    )

    results = {item.specialist: item for item in state["specialist_results"]}
    task_result = results[DeliverySpecialist.TASK_INTELLIGENCE]
    assert task_result.tool_calls[0]["tool_name"] == "get_delivery_tasks"
    assert results[DeliverySpecialist.RISK_DEPENDENCY].upstream_result_hashes == (task_result.output_hash,)
    assert results[DeliverySpecialist.PLANNING_FORECAST].upstream_result_hashes == (task_result.output_hash,)
    assert state["metadata"]["specialists_completed"] == 3
    assert len(final_llm.invocations) == 1
    task_started = next(
        index
        for index, event in enumerate(progress_events)
        if event["phase"] == "specialist_started"
        and event["specialist"] == DeliverySpecialist.TASK_INTELLIGENCE.value
    )
    task_completed = next(
        index
        for index, event in enumerate(progress_events)
        if event["phase"] == "specialist_completed"
        and event["specialist"] == DeliverySpecialist.TASK_INTELLIGENCE.value
    )
    risk_started = next(
        index
        for index, event in enumerate(progress_events)
        if event["phase"] == "specialist_started"
        and event["specialist"] == DeliverySpecialist.RISK_DEPENDENCY.value
    )
    assert task_started < task_completed < risk_started
    assert any(
        event["phase"] == "specialist_handoff"
        and event["from_specialist"] == DeliverySpecialist.TASK_INTELLIGENCE.value
        and event["to_specialist"] == DeliverySpecialist.RISK_DEPENDENCY.value
        for event in progress_events
    )
    assert progress_events[-1]["phase"] == "synthesis_started"


@pytest.mark.asyncio
async def test_daily_health_uses_prior_child_results_to_skip_unneeded_evidence_branch(
    monkeypatch,
    fake_llm_factory,
):
    settings = Settings(_env_file=None, product_delivery_specialist_llm_enabled=False)
    monkeypatch.setattr("src.agents.delivery_specialists.graph.get_settings", lambda: settings)
    final_llm = fake_llm_factory([AIMessage(content="Delivery đang đúng kế hoạch.")])
    monkeypatch.setattr(
        "src.agents.profiles.workspace_delivery_graph.get_workspace_llm",
        lambda _profile: final_llm,
    )
    snapshot = ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={
            "work_items": [],
            "capacity": {"overdue": 0, "due_soon": 0},
            "portfolio_health": {"health": "ON_TRACK"},
            "decisions": [],
            "message_evidence": [],
        },
    )
    workflow_id = uuid4().hex
    tasks = []
    for specialist in (
        DeliverySpecialist.TASK_INTELLIGENCE,
        DeliverySpecialist.EVIDENCE_KNOWLEDGE,
    ):
        context = build_specialist_context(snapshot, specialist)
        tasks.append(
            RuntimeChildTask(
                run_id=uuid4().hex,
                specialist=specialist,
                goal="delivery_health:workspace",
                allowed_tools=tuple(sorted(SPECIALIST_TOOL_ALLOWLISTS[specialist])),
                max_tool_calls=len(SPECIALIST_TOOL_ALLOWLISTS[specialist]),
                input_hash=canonical_payload_hash(context.model_dump(mode="json")),
            )
        )
    orchestration = DeliveryOrchestrationContext(
        workflow_id=workflow_id,
        execution_mode=DeliveryExecutionMode.MULTI_SPECIALIST,
        intent=DeliveryIntent.DELIVERY_HEALTH,
        plan_version="delivery-routing-v1",
        child_tasks=tuple(tasks),
        authorization_capability_ref="cap:test",
        deadline_at=datetime.now(UTC) + timedelta(seconds=10),
    )

    state = await run_delivery_supervisor(
        snapshot=snapshot,
        orchestration=orchestration,
        messages=[HumanMessage(content="Tình hình Delivery hôm nay?")],
    )

    evidence = next(
        result for result in state["specialist_results"] if result.specialist == DeliverySpecialist.EVIDENCE_KNOWLEDGE
    )
    assert evidence.metrics == {"conditional_branch_executed": False}
    assert evidence.llm_used is False
    assert state["metadata"]["evidence_branch_executed"] is False


@pytest.mark.asyncio
async def test_workflow_store_persists_parent_children_results_and_events(client, auth_headers):
    seed = await _seed_agent_workspaces(client, auth_headers)
    route = route_delivery_request("Phân tích blocker của release")
    snapshot = ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={
            "work_items": [],
            "risks": [],
            "dependencies": [],
            "milestones": [],
            "releases": [],
            "portfolio_health": {"health": "ON_TRACK"},
            "flow_metrics": {},
        },
    )
    async with db_session.async_session_maker() as db:
        workflow, orchestration = await create_delivery_workflow(
            db,
            workspace_id=seed["organization_id"],
            agent_workspace_id=seed["delivery_id"],
            actor_user_id=seed["delivery_user_id"],
            actor_role="lead",
            message="Phân tích blocker của release",
            authorization_scope_hash="scope-hash",
            route=route,
            snapshot=snapshot,
            timeout_seconds=30,
        )
        await mark_delivery_workflow_running(db, workflow_id=workflow.id, model_name="test-model")
        results_by_specialist = {}
        result_items = []
        for task in orchestration.child_tasks:
            specialist_result = DeliverySpecialistResult(
                workflow_id=workflow.id,
                run_id=task.run_id,
                specialist=task.specialist,
                status=ToolResultStatus.SUCCESS,
                summary=f"{task.specialist.value} completed",
                input_hash=task.input_hash,
                output_hash=canonical_payload_hash({"run_id": task.run_id}),
                prompt_version="test-v1",
                llm_used=True,
                model_provider="groq",
                model_name="specialist-test-model",
                usage={"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
                upstream_result_hashes=tuple(
                    results_by_specialist[item.value].output_hash for item in task.depends_on
                ),
                generated_at=datetime.now(UTC),
            )
            results_by_specialist[task.specialist.value] = specialist_result
            result_items.append(specialist_result)
        results = tuple(result_items)
        completed = await complete_delivery_workflow(
            db,
            workflow_id=workflow.id,
            results=results,
            answer="Delivery is on track.",
            usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            synthesis_model_name="synthesis-test-model",
        )
        replayed = await complete_delivery_workflow(
            db,
            workflow_id=workflow.id,
            results=results,
            answer="Delivery is on track.",
            usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            synthesis_model_name="synthesis-test-model",
        )

        runs = list(
            (await db.execute(select(DeliveryAgentRun).where(DeliveryAgentRun.workflow_id == workflow.id))).scalars()
        )
        stored_results = list(
            (
                await db.execute(
                    select(DeliverySpecialistResultRecord).where(
                        DeliverySpecialistResultRecord.workflow_id == workflow.id
                    )
                )
            ).scalars()
        )
        events = list(
            (
                await db.execute(
                    select(DeliveryWorkflowEventRecord).where(DeliveryWorkflowEventRecord.workflow_id == workflow.id)
                )
            ).scalars()
        )

    assert completed.status == "completed"
    assert replayed.id == completed.id
    assert len(runs) == len(route.specialists) + 1
    assert all(run.status == "succeeded" for run in runs)
    supervisor_run = next(run for run in runs if run.specialist == "supervisor")
    specialist_runs = [run for run in runs if run.specialist != "supervisor"]
    assert supervisor_run.model_name == "synthesis-test-model"
    assert supervisor_run.usage_json["total_tokens"] == 15
    assert all(run.model_name == "specialist-test-model" for run in specialist_runs)
    assert all(run.usage_json["total_tokens"] == 6 for run in specialist_runs)
    assert len(stored_results) == len(route.specialists)
    assert events[0].event_type == "delivery.workflow.created"
    assert events[-1].event_type == "delivery.workflow.completed"
    assert sum(event.event_type == "delivery.workflow.completed" for event in events) == 1


@pytest.mark.asyncio
async def test_delivery_event_inbox_deduplicates_replay_and_rejects_id_reuse(client):
    del client  # initializes the isolated database/session factory
    async with db_session.async_session_maker() as db:
        assert await accept_delivery_event_once(
            db,
            consumer="delivery-supervisor",
            message_id="release-event-1",
            payload={"release_id": "R1", "status": "qa_requested"},
        )
        assert not await accept_delivery_event_once(
            db,
            consumer="delivery-supervisor",
            message_id="release-event-1",
            payload={"release_id": "R1", "status": "qa_requested"},
        )
        with pytest.raises(ValueError, match="different payload"):
            await accept_delivery_event_once(
                db,
                consumer="delivery-supervisor",
                message_id="release-event-1",
                payload={"release_id": "R1", "status": "approved"},
            )


@pytest.mark.asyncio
async def test_workflow_api_enforces_owner_scope_and_optimistic_cancel(client, auth_headers, monkeypatch):
    seed = await _seed_agent_workspaces(client, auth_headers)
    monkeypatch.setattr(
        "src.api.delivery_routes.get_settings",
        lambda: Settings(
            _env_file=None,
            multi_agent_enabled=True,
            product_delivery_agent_enabled=True,
        ),
    )
    snapshot = ToolResult(status=ToolResultStatus.SUCCESS, payload={"work_items": []})
    route = constrain_delivery_route(
        route_delivery_request("Công việc của tôi"),
        enabled_specialists=frozenset({DeliverySpecialist.TASK_INTELLIGENCE}),
        allow_multi=True,
        max_specialists=4,
    )
    async with db_session.async_session_maker() as db:
        workflow, _orchestration = await create_delivery_workflow(
            db,
            workspace_id=seed["organization_id"],
            agent_workspace_id=seed["delivery_id"],
            actor_user_id=seed["delivery_user_id"],
            actor_role="lead",
            message="Công việc của tôi",
            authorization_scope_hash="scope-hash",
            route=route,
            snapshot=snapshot,
            timeout_seconds=30,
        )

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "delivery@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    base = (
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/"
        f"{seed['delivery_id']}/delivery/workflows/{workflow.id}"
    )
    fetched = await client.get(base, headers=headers)
    assert fetched.status_code == 200
    assert len(fetched.json()["runs"]) == 2

    cancelled = await client.post(
        f"{base}/cancel",
        headers=headers,
        json={"expected_row_version": fetched.json()["row_version"]},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert {run["status"] for run in cancelled.json()["runs"]} == {"cancelled"}

    stale = await client.post(
        f"{base}/cancel",
        headers=headers,
        json={"expected_row_version": fetched.json()["row_version"]},
    )
    assert stale.status_code == 409
