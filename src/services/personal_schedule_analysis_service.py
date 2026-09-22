"""Deterministic business analysis for a Personal Agent timeline.

The LLM may decide which read tools to call and explain the result naturally, but priority,
task/reminder linkage, and time-overlap calculations are owned by code so the answer does not
depend on model arithmetic or on whichever tool happened to run last.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from src.models.timeline_schemas import PersonalTimelineOut, TimelineItem
from src.services import guardrail_service

_PRIORITY_RANK = {"High": 0, "Medium": 1, "Low": 2, None: 3}
_STATUS_VI = {
    "suggested": "đề xuất",
    "pending": "đang chờ",
    "in_progress": "đang thực hiện",
    "blocked": "đang bị chặn",
    "submitted": "đã gửi duyệt",
    "changes_requested": "cần chỉnh sửa",
    "completed": "hoàn thành",
    "scheduled": "đã lên lịch",
    "fired": "đã nhắc",
    "confirmed": "đã xác nhận",
}


def _safe(value: str | None) -> str:
    return guardrail_service.sanitize_untrusted_text(str(value or "")).strip()


def _format_time(value: datetime) -> str:
    return value.strftime("%H:%M, %d/%m/%Y")


def _task_priority_score(item: TimelineItem, reference: datetime) -> int:
    score = {"High": 300, "Medium": 200, "Low": 100, None: 0}.get(item.priority, 0)
    blocked = item.status == "blocked" or bool(item.blocked_reason)
    if item.overdue:
        score += 10_000
    if blocked:
        score += 5_000
    until_due = item.occurred_at - reference
    if timedelta(0) <= until_due <= timedelta(hours=6):
        score += 900
    elif timedelta(0) <= until_due <= timedelta(hours=24):
        score += 700
    elif timedelta(0) <= until_due <= timedelta(hours=48):
        score += 500
    elif timedelta(0) <= until_due <= timedelta(days=7):
        score += 300
    if item.status == "in_progress":
        score += 50
    return score


def _task_priority_reason(item: TimelineItem, reference: datetime) -> str:
    reasons = []
    if item.overdue:
        reasons.append("đã quá hạn")
    if item.status == "blocked" or item.blocked_reason:
        reasons.append("đang bị chặn")
    until_due = item.occurred_at - reference
    if timedelta(0) <= until_due <= timedelta(hours=6):
        reasons.append("đến hạn trong 6 giờ")
    elif timedelta(0) <= until_due <= timedelta(hours=24):
        reasons.append("đến hạn trong 24 giờ")
    elif timedelta(0) <= until_due <= timedelta(hours=48):
        reasons.append("đến hạn trong 48 giờ")
    if item.priority:
        reasons.append(f"priority {item.priority}")
    return ", ".join(reasons) or "deadline gần nhất"


def _task_rank(item: TimelineItem, reference: datetime) -> tuple[int, datetime, int, str]:
    return (
        -_task_priority_score(item, reference),
        item.occurred_at,
        _PRIORITY_RANK.get(item.priority, 3),
        item.id,
    )


def _overlaps(first: TimelineItem, second: TimelineItem) -> bool:
    if first.end_at is None or second.end_at is None:
        return False
    return first.occurred_at < second.end_at and second.occurred_at < first.end_at


def _inside_event(moment: datetime, event: TimelineItem) -> bool:
    return event.end_at is not None and event.occurred_at <= moment < event.end_at


def _source_summary(timeline: PersonalTimelineOut) -> list[dict[str, Any]]:
    return [source.model_dump(mode="json") for source in timeline.sources]


def build_personal_schedule_analysis(
    timeline: PersonalTimelineOut,
    *,
    suggest_reminder_lead_minutes: int | None = None,
) -> dict[str, Any]:
    """Return a structured report and a safe Vietnamese rendering for the final answer."""

    if suggest_reminder_lead_minutes is not None:
        suggest_reminder_lead_minutes = max(1, min(suggest_reminder_lead_minutes, 10_080))

    tasks = [item for item in timeline.items if item.kind == "task"]
    reminders = [item for item in timeline.items if item.kind == "reminder"]
    calendar_events = [item for item in timeline.items if item.kind == "calendar"]
    linked_reminders: dict[str, list[TimelineItem]] = defaultdict(list)
    standalone_reminders: list[TimelineItem] = []
    task_ids = {task.source_id for task in tasks}
    for reminder in reminders:
        if reminder.linked_task_id and reminder.linked_task_id in task_ids:
            linked_reminders[reminder.linked_task_id].append(reminder)
        else:
            standalone_reminders.append(reminder)

    ordered_tasks = sorted(tasks, key=lambda item: _task_rank(item, timeline.from_at))
    priority_order: list[dict[str, Any]] = []
    missing_reminder_tasks: list[dict[str, Any]] = []
    reminder_disabled_tasks: list[dict[str, Any]] = []
    for rank, task in enumerate(ordered_tasks, start=1):
        task_reminders = sorted(linked_reminders.get(task.source_id, []), key=lambda row: row.occurred_at)
        active_reminder = next((row for row in task_reminders if row.status == "scheduled"), None)
        row = {
            "rank": rank,
            "priority_score": _task_priority_score(task, timeline.from_at),
            "priority_reason": _task_priority_reason(task, timeline.from_at),
            "task_id": task.source_id,
            "title": _safe(task.title),
            "due_at": task.occurred_at.isoformat(),
            "priority": task.priority,
            "status": task.status,
            "blocked_reason": _safe(task.blocked_reason) or None,
            "overdue": task.overdue,
            "scope": task.scope,
            "reminder": (
                {
                    "id": active_reminder.source_id,
                    "fire_at": active_reminder.occurred_at.isoformat(),
                    "lead_minutes": active_reminder.reminder_lead_minutes,
                    "status": active_reminder.status,
                }
                if active_reminder
                else None
            ),
        }
        priority_order.append(row)
        if active_reminder is None and not task.overdue:
            if task.auto_reminder_enabled is False:
                reminder_disabled_tasks.append(row)
            elif suggest_reminder_lead_minutes is not None:
                missing_reminder_tasks.append(
                    {
                        **row,
                        "suggested_lead_minutes": suggest_reminder_lead_minutes,
                        "suggested_fire_at": (
                            task.occurred_at - timedelta(minutes=suggest_reminder_lead_minutes)
                        ).isoformat(),
                    }
                )

    hard_conflicts: list[dict[str, Any]] = []
    for index, first in enumerate(calendar_events):
        for second in calendar_events[index + 1 :]:
            if _overlaps(first, second):
                hard_conflicts.append(
                    {
                        "type": "calendar_overlap",
                        "first_id": first.source_id,
                        "second_id": second.source_id,
                        "message": (
                            f"Lịch “{_safe(first.title)}” chồng thời gian với "
                            f"“{_safe(second.title)}”."
                        ),
                    }
                )
    for task in tasks:
        for event in calendar_events:
            if _inside_event(task.occurred_at, event):
                hard_conflicts.append(
                    {
                        "type": "task_deadline_during_calendar_event",
                        "task_id": task.source_id,
                        "calendar_event_id": event.source_id,
                        "message": (
                            f"Deadline “{_safe(task.title)}” rơi trong lịch "
                            f"“{_safe(event.title)}”."
                        ),
                    }
                )

    workload_risks: list[dict[str, Any]] = []
    future_tasks = sorted((task for task in tasks if not task.overdue), key=lambda row: row.occurred_at)
    for index, first in enumerate(future_tasks):
        for second in future_tasks[index + 1 :]:
            distance = second.occurred_at - first.occurred_at
            distance_minutes = int(distance.total_seconds() // 60)
            if distance_minutes > 120:
                break
            if first.occurred_at.date() != second.occurred_at.date():
                continue
            workload_risks.append(
                {
                    "type": "clustered_deadlines",
                    "first_task_id": first.source_id,
                    "second_task_id": second.source_id,
                    "distance_minutes": distance_minutes,
                    "message": (
                        f"Hai deadline “{_safe(first.title)}” và “{_safe(second.title)}” "
                        f"chỉ cách nhau {distance_minutes} phút."
                    ),
                }
            )
    for reminder in reminders:
        for event in calendar_events:
            if _inside_event(reminder.occurred_at, event):
                workload_risks.append(
                    {
                        "type": "reminder_during_calendar_event",
                        "reminder_id": reminder.source_id,
                        "calendar_event_id": event.source_id,
                        "message": (
                            f"Reminder “{_safe(reminder.title)}” sẽ đến trong lúc diễn ra "
                            f"“{_safe(event.title)}”."
                        ),
                    }
                )

    source_rows = _source_summary(timeline)
    report: dict[str, Any] = {
        "schema_version": 1,
        "timezone": timeline.timezone,
        "range": {"from": timeline.from_at.isoformat(), "to": timeline.to_at.isoformat()},
        "summary": {
            "tasks": len(tasks),
            "overdue_tasks": sum(task.overdue for task in tasks),
            "linked_reminders": sum(len(rows) for rows in linked_reminders.values()),
            "standalone_reminders": len(standalone_reminders),
            "calendar_events": len(calendar_events),
        },
        "sources": source_rows,
        "priority_order": priority_order,
        "standalone_reminders": [row.model_dump(mode="json") for row in standalone_reminders],
        "calendar_events": [row.model_dump(mode="json") for row in calendar_events],
        "hard_conflicts": hard_conflicts,
        "workload_risks": workload_risks,
        "missing_reminder_tasks": missing_reminder_tasks,
        "reminder_disabled_tasks": reminder_disabled_tasks,
    }
    report["report_markdown"] = render_personal_schedule_report(report)
    return report


def render_personal_schedule_report(report: dict[str, Any]) -> str:
    """Render the deterministic report without exposing raw ISO/tool pipe output."""

    summary = report["summary"]
    lines = [
        "## Tổng quan",
        (
            f"- Có **{summary['tasks']} task**, **{summary['linked_reminders']} reminder liên kết**, "
            f"**{summary['standalone_reminders']} reminder độc lập** và "
            f"**{summary['calendar_events']} sự kiện Google Calendar** trong báo cáo "
            "(task quá hạn được giữ lại để xếp ưu tiên)."
        ),
    ]
    if summary["overdue_tasks"]:
        lines.append(f"- Có **{summary['overdue_tasks']} task quá hạn** cần xử lý trước.")
    incomplete = [row for row in report["sources"] if row["status"] != "ok"]
    if incomplete:
        source_text = ", ".join(f"{row['source']}: {row['status']}" for row in incomplete)
        lines.append(f"- Nguồn chưa đầy đủ: **{source_text}**; kết luận xung đột chỉ là tạm thời.")

    lines.extend(["", "## Việc cần ưu tiên"])
    if not report["priority_order"]:
        lines.append("- Không có task đang mở có deadline trong phạm vi này.")
    for task in report["priority_order"][:20]:
        flags = []
        if task["overdue"]:
            flags.append("quá hạn")
        if task["status"] == "blocked" or task["blocked_reason"]:
            flags.append("bị chặn")
        suffix = f" — **{', '.join(flags)}**" if flags else ""
        lines.append(
            f"{task['rank']}. **{task['title']}** — {task['priority'] or 'Chưa đặt'} · "
            f"{_STATUS_VI.get(task['status'], task['status'])} · hạn {_format_time(datetime.fromisoformat(task['due_at']))}{suffix}."
        )
        lines.append(f"   - Lý do ưu tiên: {task['priority_reason']}.")
        if task["blocked_reason"]:
            lines.append(f"   - Blocker: {task['blocked_reason']}.")
        if task["reminder"]:
            lines.append(
                "   - Reminder liên kết: "
                + _format_time(datetime.fromisoformat(task["reminder"]["fire_at"]))
                + "."
            )

    lines.extend(["", "## Lịch và reminder"])
    if report["calendar_events"]:
        for event in report["calendar_events"][:20]:
            start = _format_time(datetime.fromisoformat(event["occurred_at"]))
            end = (
                _format_time(datetime.fromisoformat(event["end_at"]))
                if event.get("end_at")
                else "chưa có giờ kết thúc"
            )
            lines.append(f"- Google Calendar: **{_safe(event['title'])}**, {start}–{end}.")
    else:
        calendar_source = next(
            (row for row in report["sources"] if row["source"] == "calendar"), None
        )
        if calendar_source and calendar_source["status"] == "ok":
            lines.append("- Google Calendar không có sự kiện trong phạm vi đã chọn.")
        elif calendar_source:
            lines.append(f"- Chưa đọc được Google Calendar ({calendar_source['status']}).")
    for reminder in report["standalone_reminders"][:20]:
        lines.append(
            f"- Reminder độc lập: **{_safe(reminder['title'])}**, nhắc lúc "
            f"{_format_time(datetime.fromisoformat(reminder['occurred_at']))}."
        )
    if not report["standalone_reminders"]:
        lines.append("- Không có reminder độc lập; reminder gắn task đã được đặt dưới từng task để tránh trùng lặp.")

    lines.extend(["", "## Xung đột và rủi ro"])
    if report["hard_conflicts"]:
        lines.extend(f"- **Xung đột:** {row['message']}" for row in report["hard_conflicts"])
    else:
        lines.append("- Không phát hiện xung đột lịch trực tiếp trong dữ liệu hiện có.")
    if report["workload_risks"]:
        lines.extend(f"- **Rủi ro tải:** {row['message']}" for row in report["workload_risks"])
    else:
        lines.append("- Không phát hiện cụm deadline quá sát nhau trong ngưỡng hai giờ.")

    if report["missing_reminder_tasks"]:
        lines.extend(["", "## Đề xuất reminder"])
        for task in report["missing_reminder_tasks"]:
            lines.append(
                f"- **{task['title']}** chưa có reminder; đề xuất nhắc trước "
                f"{task['suggested_lead_minutes']} phút, lúc "
                f"{_format_time(datetime.fromisoformat(task['suggested_fire_at']))}. "
                "Đây mới là đề xuất, chưa tự động tạo."
            )
    if report["reminder_disabled_tasks"]:
        lines.append(
            "\nCác task đã tắt auto-reminder được giữ nguyên; Orbit không đề xuất bật lại khi chưa có yêu cầu rõ ràng."
        )
    return "\n".join(lines)
