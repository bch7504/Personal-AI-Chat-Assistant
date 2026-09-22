from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator


class CalendarEventOut(BaseModel):
    id: str
    title: str
    start: str
    end: str | None
    url: str | None


class CalendarEventCreateRequest(BaseModel):
    summary: str = Field(..., min_length=1, max_length=200)
    start_iso: datetime
    end_iso: datetime
    description: str = Field(default="", max_length=5000)
    attendees: list[EmailStr] | None = None
    create_reminder: bool = False
    reminder_lead_minutes: int = Field(default=30, ge=0, le=10080)

    @model_validator(mode="after")
    def validate_range(self):
        if self.end_iso <= self.start_iso:
            raise ValueError("end_iso must be later than start_iso")
        return self


class CalendarEventUpdateRequest(BaseModel):
    summary: str | None = Field(default=None, min_length=1, max_length=200)
    start_iso: datetime | None = None
    end_iso: datetime | None = None
    description: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def validate_range(self):
        if self.start_iso is not None and self.end_iso is not None and self.end_iso <= self.start_iso:
            raise ValueError("end_iso must be later than start_iso")
        return self


class EventCandidateOut(BaseModel):
    id: str
    workspace_id: str
    conversation_id: str
    operation: Literal["create", "update", "cancel"]
    target_candidate_id: str | None
    title: str
    start_at: datetime | None
    end_at: datetime | None
    location: str | None
    attendees: list[str]
    status: Literal["suggested", "confirmed", "superseded", "dismissed", "cancelled", "invalidated"]
    confidence: float
    missing_fields: list[str]
    source_message_ids: list[str]
    calendar_event_id: str | None
    calendar_owner_user_id: str | None
    invalidated_reason: str | None
    created_at: datetime
    updated_at: datetime


class EventCandidateConfirmRequest(BaseModel):
    create_reminder: bool = True
    reminder_lead_minutes: int = Field(default=30, ge=0, le=10080)


class EventBackfillRequest(BaseModel):
    batch_size: int = Field(default=200, ge=1, le=500)


class EventBackfillOut(BaseModel):
    status: Literal["disabled", "idle", "running", "paused", "completed", "failed"]
    processed: int
    extracted: int = 0
    has_more: bool


class CalendarConnectionStatusOut(BaseModel):
    connected: bool
    google_email: str | None = None
    connected_at: datetime | None = None
