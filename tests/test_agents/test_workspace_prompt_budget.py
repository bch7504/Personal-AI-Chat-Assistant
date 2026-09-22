import json

from src.agents.contracts import AgentProfile, ToolResult, ToolResultStatus
from src.agents.profiles.workspace_prompt_budget import compact_snapshot_for_prompt
from src.config import get_settings


def test_delivery_prompt_snapshot_is_bounded_and_preserves_authoritative_health():
    snapshot = ToolResult(
        status=ToolResultStatus.PARTIAL,
        payload={
            "portfolio_health": {"health": "BLOCKED", "reasons": ["WORK_ITEM_BLOCKED"]},
            "brief": {"headline": "Blocked delivery portfolio"},
            "risks": [
                {"severity": "critical", "title": f"Risk {index}", "detail": "x" * 5_000}
                for index in range(100)
            ],
            "message_evidence": [
                {"message_id": str(index), "excerpt": "e" * 5_000}
                for index in range(100)
            ],
            "people": [{"id": str(index), "bio": "p" * 5_000} for index in range(100)],
        },
        data_gaps=("WORKFLOW_HISTORY_NOT_CAPTURED",),
    )

    evidence = compact_snapshot_for_prompt(snapshot, AgentProfile.PRODUCT_DELIVERY)
    document = json.loads(evidence.text)

    assert evidence.included_chars <= get_settings().workspace_agent_snapshot_prompt_max_chars
    assert evidence.compacted is True
    assert document["payload"]["portfolio_health"]["health"] == "BLOCKED"
    assert document["data_gaps"] == ["WORKFLOW_HISTORY_NOT_CAPTURED"]


def test_delivery_prompt_compaction_prioritizes_checkpoint_and_specialist_results(monkeypatch):
    settings = get_settings().model_copy(update={"workspace_agent_snapshot_prompt_max_chars": 4_000})
    monkeypatch.setattr(
        "src.agents.profiles.workspace_prompt_budget.get_settings",
        lambda: settings,
    )
    snapshot = ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={
            "scope_context": {
                "mode": "selected_group",
                "selection_verified": True,
                "selected_group": {"id": "group-release", "name": "Release 34"},
                "effective_group_count": 1,
            },
            "portfolio_health": {"health": "BLOCKED"},
            "brief": {"noise": "x" * 20_000},
            "checkpoint_progress": [
                {
                    "title": "R1",
                    "completion_percent": 60,
                    "schedule_status": "at_risk",
                    "quality_review_status": "pending",
                }
            ],
            "specialist_results": [
                {
                    "specialist": "planning_forecast",
                    "summary": "R1 is at risk",
                    "facts": [{"title": "R1", "completion_percent": 60}],
                }
            ],
        },
    )

    prompt = compact_snapshot_for_prompt(snapshot, AgentProfile.PRODUCT_DELIVERY)
    document = json.loads(prompt.text)

    assert document["payload"]["checkpoint_progress"][0]["completion_percent"] == 60
    assert document["payload"]["specialist_results"][0]["specialist"] == "planning_forecast"
    assert document["payload"]["scope_context"]["selected_group"]["name"] == "Release 34"


def test_dependency_analysis_compaction_never_drops_dependency_rows(monkeypatch):
    settings = get_settings().model_copy(update={"workspace_agent_snapshot_prompt_max_chars": 4_000})
    monkeypatch.setattr(
        "src.agents.profiles.workspace_prompt_budget.get_settings",
        lambda: settings,
    )
    snapshot = ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={
            "orchestration_intent": "dependency_analysis",
            "scope_context": {"mode": "workspace"},
            "task_group_progress": [{"group_name": "Apollo", "completion_percent": 20}],
            "dependencies": [
                {
                    "id": "dep-1",
                    "title": "OAuth E2E waits for vendor sandbox",
                    "status": "blocked",
                    "assignee_id": "owner-1",
                    "predecessor_task_id": "task-a",
                    "successor_task_id": "task-b",
                }
            ],
            "brief": {"noise": "x" * 20_000},
            "risks": [{"title": f"risk-{index}", "detail": "y" * 2_000} for index in range(30)],
            "groups": [{"id": "group-a", "name": "Apollo"}],
            "specialist_results": [],
        },
    )

    prompt = compact_snapshot_for_prompt(snapshot, AgentProfile.PRODUCT_DELIVERY)
    document = json.loads(prompt.text)

    assert prompt.included_chars <= settings.workspace_agent_snapshot_prompt_max_chars
    assert document["payload"]["dependencies"][0]["id"] == "dep-1"
    assert document["payload"]["dependencies"][0]["assignee_id"] == "owner-1"


def test_task_progress_compaction_keeps_weakest_team_task_reasons(monkeypatch):
    settings = get_settings().model_copy(update={"workspace_agent_snapshot_prompt_max_chars": 4_000})
    monkeypatch.setattr(
        "src.agents.profiles.workspace_prompt_budget.get_settings",
        lambda: settings,
    )
    snapshot = ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={
            "orchestration_intent": "task_progress_summary",
            "brief": {"noise": "x" * 20_000},
            "task_group_progress": [{"group_name": "Customer Portal", "completion_percent": 15}],
            "team_delivery_assessments": [
                {
                    "group_name": "Customer Portal",
                    "assessment": "Cần can thiệp ngay",
                    "attention_tasks": [
                        {
                            "title": "Nhận credential CRM UAT",
                            "status": "blocked",
                            "blocked_reason": "Đội CRM chưa cấp credential UAT",
                            "owner_name": "Sơn Integration",
                            "due_at": "2026-08-28T10:00:00+07:00",
                        }
                    ],
                }
            ],
            "specialist_results": [],
            "groups": [{"id": "portal", "name": "Customer Portal"}],
        },
    )

    document = json.loads(compact_snapshot_for_prompt(snapshot, AgentProfile.PRODUCT_DELIVERY).text)
    task = document["payload"]["team_delivery_assessments"][0]["attention_tasks"][0]

    assert task["title"] == "Nhận credential CRM UAT"
    assert task["blocked_reason"] == "Đội CRM chưa cấp credential UAT"
    assert task["owner_name"] == "Sơn Integration"


def test_blocker_compaction_keeps_owner_deadline_and_concrete_reason(monkeypatch):
    settings = get_settings().model_copy(update={"workspace_agent_snapshot_prompt_max_chars": 4_000})
    monkeypatch.setattr(
        "src.agents.profiles.workspace_prompt_budget.get_settings",
        lambda: settings,
    )
    snapshot = ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={
            "orchestration_intent": "blocker_analysis",
            "portfolio_health": {"health": "BLOCKED"},
            "brief": {"noise": "x" * 20_000},
            "team_delivery_assessments": [
                {
                    "group_name": "Release 34",
                    "dependencies": [
                        {
                            "predecessor": "Giảm crash rate iOS xuống dưới 1%",
                            "successor": "Chuẩn bị dữ liệu go/no-go",
                            "status": "blocked",
                            "owner_name": "Nhóm Mobile",
                            "due_at": "2026-08-30T10:00:00+07:00",
                            "predecessor_blocked_reason": "Crash rate iOS đang ở mức 2,4%",
                        }
                    ],
                }
            ],
            "dependencies": [{"title": "Crash gate trước go/no-go", "owner_name": "Nhóm Mobile"}],
            "risks": [{"title": "Release 34 có thể trễ", "severity": "critical"}],
            "specialist_results": [],
            "groups": [{"id": "release", "name": "Release 34"}],
        },
    )

    document = json.loads(compact_snapshot_for_prompt(snapshot, AgentProfile.PRODUCT_DELIVERY).text)
    dependency = document["payload"]["team_delivery_assessments"][0]["dependencies"][0]

    assert dependency["owner_name"] == "Nhóm Mobile"
    assert dependency["due_at"] == "2026-08-30T10:00:00+07:00"
    assert dependency["predecessor_blocked_reason"] == "Crash rate iOS đang ở mức 2,4%"


def test_quality_prompt_snapshot_is_bounded_and_preserves_readiness():
    snapshot = ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={
            "assessment": {"release_readiness": "NOT_READY"},
            "brief": {"headline": "Release R1 is not ready"},
            "quality_control_plane": {
                "test_runs": [{"id": str(index), "log": "x" * 8_000} for index in range(100)]
            },
        },
    )

    evidence = compact_snapshot_for_prompt(snapshot, AgentProfile.QUALITY_ASSURANCE)
    document = json.loads(evidence.text)

    assert evidence.included_chars <= get_settings().workspace_agent_snapshot_prompt_max_chars
    assert document["payload"]["assessment"]["release_readiness"] == "NOT_READY"
