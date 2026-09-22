from datetime import datetime
from zoneinfo import ZoneInfo

from src.models.timeline_schemas import PersonalTimelineOut, TimelineItem, TimelineSourceStatus
from src.services.personal_schedule_analysis_service import build_personal_schedule_analysis


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))


def test_schedule_analysis_deduplicates_reminders_and_separates_conflict_from_load_risk():
    overdue = TimelineItem(
        id="task:overdue",
        kind="task",
        occurred_at=_at(1, 8),
        title="Xử lý blocker OAuth",
        status="blocked",
        source_id="overdue",
        priority="High",
        blocked_reason="Chờ quota vendor",
        overdue=True,
        scope="workspace",
        auto_reminder_enabled=True,
    )
    first = TimelineItem(
        id="task:first",
        kind="task",
        occurred_at=_at(2, 9),
        title="Chuẩn bị go/no-go",
        status="in_progress",
        source_id="first",
        priority="High",
        scope="workspace",
        auto_reminder_enabled=True,
    )
    second = TimelineItem(
        id="task:second",
        kind="task",
        occurred_at=_at(2, 11).replace(second=2),
        title="Ký staged rollout",
        status="pending",
        source_id="second",
        priority="Medium",
        scope="workspace",
        auto_reminder_enabled=True,
    )
    linked_reminder = TimelineItem(
        id="reminder:first",
        kind="reminder",
        occurred_at=_at(2, 8),
        end_at=_at(2, 9),
        title=first.title,
        status="scheduled",
        source_id="reminder-first",
        linked_task_id="first",
        reminder_lead_minutes=60,
    )
    meeting = TimelineItem(
        id="calendar:meeting",
        kind="calendar",
        occurred_at=_at(2, 8, 45),
        end_at=_at(2, 9, 45),
        title="Họp điều phối",
        status="confirmed",
        source_id="meeting",
    )
    overlapping = TimelineItem(
        id="calendar:review",
        kind="calendar",
        occurred_at=_at(2, 9, 30),
        end_at=_at(2, 10),
        title="Review release",
        status="confirmed",
        source_id="review",
    )
    timeline = PersonalTimelineOut(
        workspace_id="personal",
        timezone="Asia/Ho_Chi_Minh",
        from_at=_at(1, 12),
        to_at=_at(8, 12),
        items=[overdue, linked_reminder, meeting, first, overlapping, second],
        sources=[
            TimelineSourceStatus(source="task", status="ok", item_count=3),
            TimelineSourceStatus(source="reminder", status="ok", item_count=1),
            TimelineSourceStatus(source="calendar", status="ok", item_count=2),
        ],
    )

    report = build_personal_schedule_analysis(
        timeline,
        suggest_reminder_lead_minutes=60,
    )

    assert [row["task_id"] for row in report["priority_order"]] == [
        "overdue",
        "first",
        "second",
    ]
    assert report["priority_order"][1]["reminder"]["id"] == "reminder-first"
    assert report["summary"] == {
        "tasks": 3,
        "overdue_tasks": 1,
        "linked_reminders": 1,
        "standalone_reminders": 0,
        "calendar_events": 2,
    }
    assert {row["type"] for row in report["hard_conflicts"]} == {
        "calendar_overlap",
        "task_deadline_during_calendar_event",
    }
    assert "clustered_deadlines" in {row["type"] for row in report["workload_risks"]}
    assert [row["task_id"] for row in report["missing_reminder_tasks"]] == ["second"]
    assert "## Việc cần ưu tiên" in report["report_markdown"]
    assert "## Xung đột và rủi ro" in report["report_markdown"]
    assert "Đây mới là đề xuất, chưa tự động tạo" in report["report_markdown"]
    assert "2026-09-02T" not in report["report_markdown"]


def test_schedule_analysis_reports_zero_calendar_events_without_claiming_a_conflict():
    timeline = PersonalTimelineOut(
        workspace_id="personal",
        timezone="Asia/Ho_Chi_Minh",
        from_at=_at(1, 0),
        to_at=_at(8, 0),
        items=[],
        sources=[
            TimelineSourceStatus(source="task", status="ok", item_count=0),
            TimelineSourceStatus(source="reminder", status="ok", item_count=0),
            TimelineSourceStatus(source="calendar", status="ok", item_count=0),
        ],
    )

    report = build_personal_schedule_analysis(timeline)

    assert report["hard_conflicts"] == []
    assert "Google Calendar không có sự kiện" in report["report_markdown"]
    assert "Không phát hiện xung đột lịch trực tiếp" in report["report_markdown"]


def test_schedule_analysis_marks_calendar_failure_as_an_incomplete_conclusion():
    timeline = PersonalTimelineOut(
        workspace_id="personal",
        timezone="Asia/Ho_Chi_Minh",
        from_at=_at(1, 0),
        to_at=_at(8, 0),
        items=[],
        sources=[
            TimelineSourceStatus(source="task", status="ok", item_count=0),
            TimelineSourceStatus(source="reminder", status="ok", item_count=0),
            TimelineSourceStatus(source="calendar", status="unavailable", detail="provider error"),
        ],
    )

    report = build_personal_schedule_analysis(timeline)

    assert "kết luận xung đột chỉ là tạm thời" in report["report_markdown"]
    assert "Chưa đọc được Google Calendar" in report["report_markdown"]
