from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DeliveryCheckpointCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_conversation_id: str = Field(min_length=1, max_length=128)
    plan_key: str = Field(default="default", min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    due_at: datetime
    required_task_ids: list[str] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_checkpoint(self):
        if self.due_at.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        if len(set(self.required_task_ids)) != len(self.required_task_ids):
            raise ValueError("required_task_ids must be unique")
        return self


class DeliveryCheckpointQualityReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality_review_status: Literal["pending", "accepted", "rejected"]
    quality_review_note: str | None = Field(default=None, max_length=2_000)
    expected_row_version: int = Field(ge=1)


class DeliveryCheckpointTaskOut(BaseModel):
    id: str
    title: str
    status: str
    owner_id: str
    due_at: datetime | None = None
    completed_at: datetime | None = None
    required: bool = True
    requires_review: bool = False
    submission_note: str | None = None
    evidence_urls: list[str] = Field(default_factory=list)
    submitted_at: datetime | None = None
    review_note: str | None = None


class DeliveryCheckpointAssessmentOut(BaseModel):
    checkpoint_id: str
    plan_key: str
    conversation_id: str
    title: str
    due_at: datetime | None
    schedule_status: Literal[
        "completed_on_time",
        "completed_late",
        "on_track",
        "at_risk",
        "overdue",
        "insufficient_data",
    ]
    completion_percent: int = Field(ge=0, le=100)
    required_task_count: int = Field(ge=0)
    completed_required_task_count: int = Field(ge=0)
    required_tasks_complete: bool
    deadline_met: bool | None
    quality_review_status: Literal["pending", "accepted", "rejected"]
    completion_decision: Literal["pending_tasks", "pending_lead_quality_review", "accepted", "rejected"]
    quality_review_note: str | None = None
    quality_reviewed_by_user_id: str | None = None
    quality_reviewed_at: datetime | None = None
    reason_codes: list[str]
    tasks: list[DeliveryCheckpointTaskOut]
    row_version: int = Field(ge=1)


class DeliveryCheckpointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    agent_workspace_id: str
    conversation_id: str
    plan_key: str
    title: str
    status: str
    due_at: datetime | None
    quality_review_status: str
    quality_review_note: str | None
    quality_reviewed_by_user_id: str | None
    quality_reviewed_at: datetime | None
    row_version: int
    created_at: datetime
    updated_at: datetime
