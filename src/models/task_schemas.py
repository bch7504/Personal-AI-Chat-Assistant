from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TaskStatus = Literal[
    "suggested",
    "pending",
    "in_progress",
    "blocked",
    "submitted",
    "changes_requested",
    "completed",
    "dismissed",
    "invalidated",
]
TaskPriority = Literal["High", "Medium", "Low"]


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    owner_id: str
    conversation_id: str | None
    agent_workspace_id: str | None = None
    workspace_type: Literal["personal", "organization"] | None = None
    workspace_name: str | None = None
    agent_workspace_name: str | None = None
    agent_profile: Literal["product_delivery", "quality_assurance", "executive"] | None = None
    conversation_name: str | None = None
    title: str
    due_at: datetime | None
    auto_reminder_enabled: bool = True
    priority: TaskPriority
    status: TaskStatus
    blocked_reason: str | None = None
    source: Literal["manual", "ai_extracted", "proactive"]
    source_message_ids: list[str] | None = None
    consent_scope_hash: str | None = None
    invalidated_reason: str | None = None
    requires_review: bool = False
    submission_note: str | None = None
    evidence_urls: list[str] = Field(default_factory=list)
    submitted_by_user_id: str | None = None
    submitted_at: datetime | None = None
    reviewed_by_user_id: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    row_version: int
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class TaskCreateRequest(BaseModel):
    workspace_id: str | None = None
    title: str = Field(..., min_length=1, max_length=200)
    due_at: datetime | None = None
    priority: TaskPriority = "Medium"
    conversation_id: str | None = None
    source: Literal["manual", "ai_extracted"] = "manual"
    source_message_ids: list[str] | None = None
    consent_scope_hash: str | None = None
    requires_review: bool = False


class UpdateTaskStatusRequest(BaseModel):
    status: TaskStatus
    blocked_reason: str | None = Field(default=None, min_length=1, max_length=500)
    expected_row_version: int | None = Field(default=None, ge=1)


class UpdateTaskRequest(BaseModel):
    """Owner-controlled task settings.

    Organization task deadlines remain governed by their Workspace Agent workflow; their owner
    may still opt the private reminder out without mutating shared delivery state.
    """

    model_config = ConfigDict(extra="forbid")

    due_at: datetime | None = None
    auto_reminder_enabled: bool | None = None
    expected_row_version: int = Field(ge=1)

    @model_validator(mode="after")
    def has_update(self):
        if not ({"due_at", "auto_reminder_enabled"} & self.model_fields_set):
            raise ValueError("At least one task setting must be supplied")
        return self


class TaskSubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_note: str | None = Field(default=None, max_length=4_000)
    evidence_urls: list[str] = Field(default_factory=list, max_length=20)
    expected_row_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_submission(self):
        note = (self.submission_note or "").strip()
        normalized = [value.strip() for value in self.evidence_urls if value.strip()]
        if not note and not normalized:
            raise ValueError("A submission requires a note or at least one evidence URL")
        if len(normalized) != len(set(normalized)):
            raise ValueError("evidence_urls must be unique")
        if any(len(value) > 2_048 or not value.startswith(("https://", "http://")) for value in normalized):
            raise ValueError("Every evidence URL must be an HTTP(S) URL of at most 2048 characters")
        self.submission_note = note or None
        self.evidence_urls = normalized
        return self
