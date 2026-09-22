from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TimelineKind = Literal["message", "task", "reminder", "calendar"]
TimelinePriority = Literal["High", "Medium", "Low"]
TimelineScope = Literal["personal", "workspace"]


class TimelineItem(BaseModel):
    id: str
    kind: TimelineKind
    occurred_at: datetime
    end_at: datetime | None = None
    title: str
    detail: str = ""
    status: str
    source_id: str
    conversation_id: str | None = None
    source_message_ids: list[str] = Field(default_factory=list)
    url: str | None = None
    priority: TimelinePriority | None = None
    blocked_reason: str | None = None
    overdue: bool = False
    scope: TimelineScope | None = None
    linked_task_id: str | None = None
    linked_calendar_event_id: str | None = None
    reminder_lead_minutes: int | None = None
    auto_reminder_enabled: bool | None = None


class TimelineSourceStatus(BaseModel):
    source: TimelineKind
    status: Literal["ok", "unavailable", "not_connected"]
    item_count: int = 0
    detail: str | None = None


class PersonalTimelineOut(BaseModel):
    workspace_id: str
    timezone: str
    from_at: datetime
    to_at: datetime
    items: list[TimelineItem]
    sources: list[TimelineSourceStatus]
