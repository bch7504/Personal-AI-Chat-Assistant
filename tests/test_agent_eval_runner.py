from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.eval_user_agent import (
    CaseResult,
    aggregate_metrics,
    normalize_text,
    release_gate,
    score_task_output,
    semantic_token_match,
    validate_eval_database_url,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "eval" / "datasets" / "user_agent_acceptance_v1.json"


def _dataset() -> dict:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def test_text_matching_is_case_and_diacritic_insensitive():
    assert normalize_text("Báo cáo TIẾN ĐỘ") == "bao cao tien do"
    assert semantic_token_match("Lan là đầu mối migration dữ liệu", "Lan Phương phụ trách migration", 0.4)


def test_task_scorer_measures_title_due_priority_and_false_positives():
    expected = next(case["expected"] for case in _dataset()["evaluation_cases"] if case["id"] == "TASK-01")
    anchor = datetime(2026, 8, 14, 14, 20, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    response = json.dumps(
        [
            {"title": "Lan xử lý migration email trùng", "due_at": "2026-08-15T16:00:00+07:00", "priority": "High"},
            {"title": "Huy kiểm tra responsive", "due_at": "2026-08-17T10:00:00+07:00", "priority": "Medium"},
            {"title": "Mai gửi báo cáo regression", "due_at": "2026-08-16T17:00:00+07:00", "priority": "High"},
            {"title": "Minh xác nhận quota production", "due_at": None, "priority": "Medium"},
        ],
        ensure_ascii=False,
    )
    checks = []

    stats = score_task_output(expected, response, anchor, ZoneInfo("Asia/Ho_Chi_Minh"), checks)

    assert stats == {
        "tp": 4,
        "fp": 0,
        "fn": 0,
        "due_correct": 4,
        "due_checked": 4,
        "priority_correct": 4,
        "priority_checked": 4,
    }
    assert all(check.passed for check in checks)


def test_task_scorer_rejects_non_json_even_when_no_tasks_are_expected():
    expected = {"tasks": [], "task_count": 0}
    anchor = datetime(2026, 8, 14, 14, 20, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    checks = []

    stats = score_task_output(
        expected,
        "Không có task nào.",
        anchor,
        ZoneInfo("Asia/Ho_Chi_Minh"),
        checks,
    )

    assert stats == {
        "tp": 0,
        "fp": 0,
        "fn": 0,
        "due_correct": 0,
        "due_checked": 0,
        "priority_correct": 0,
        "priority_checked": 0,
    }
    assert next(check for check in checks if check.name == "task_json_array").passed is False


def test_release_gate_handles_higher_and_lower_is_better_metrics():
    data = _dataset()
    metrics = {
        "case_pass_rate": 1.0,
        "tool_routing_accuracy": 1.0,
        "task_precision": 1.0,
        "task_recall": 1.0,
        "task_due_accuracy": 1.0,
        "memory_isolation_pass_rate": 1.0,
        "forbidden_claim_rate": 0.0,
        "hitl_preconfirmation_side_effect_rate": 0.0,
    }

    assert release_gate(data, metrics)["passed"] is True
    metrics["forbidden_claim_rate"] = 0.1
    assert release_gate(data, metrics)["passed"] is False


def test_eval_database_guard_accepts_only_local_postgres_with_test_marker():
    safe_url = "postgresql+asyncpg://orbit:secret@localhost:5432/orbit_agent_test"

    assert validate_eval_database_url(safe_url) == "orbit_agent_test"

    for unsafe_url in (
        "postgresql+asyncpg://orbit:secret@localhost:5432/orbit",
        "postgresql+asyncpg://orbit:secret@db.example.com:5432/orbit_agent_test",
        "sqlite:///agent_test.db",
    ):
        try:
            validate_eval_database_url(unsafe_url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Unsafe eval URL was accepted: {unsafe_url}")


def test_aggregate_metrics_computes_task_precision_recall_and_latency():
    result = CaseResult(
        case_id="TASK-X",
        capability="task_extraction",
        passed=False,
        score=0.5,
        latency_ms=1200,
        expected_tool="extract_tasks",
        actual_tools=["extract_tasks"],
        interrupted=False,
        response="[]",
        task_stats={
            "tp": 3,
            "fp": 1,
            "fn": 1,
            "due_correct": 2,
            "due_checked": 3,
            "priority_correct": 3,
            "priority_checked": 3,
        },
    )

    metrics = aggregate_metrics(_dataset(), [result], {})

    assert metrics["task_precision"] == 0.75
    assert metrics["task_recall"] == 0.75
    assert metrics["task_f1"] == 0.75
    assert metrics["latency_p50_ms"] == 1200
