from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

PeopleTag = Literal["pinned", "frequent", "recent", "follow_up", "directory"]


class PeoplePreferenceUpdate(BaseModel):
    is_pinned: bool | None = None
    private_note: str | None = Field(default=None, max_length=2000)
    follow_up_at: datetime | None = None

    @field_validator("private_note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PeopleInsightOut(BaseModel):
    user_id: str
    display_name: str
    email: str
    job_title: str
    workspace_role: Literal["owner", "admin", "member", "guest"]
    is_pinned: bool
    private_note: str | None
    follow_up_at: datetime | None
    relationship_type: str | None
    message_count_30d: int = Field(ge=0)
    direct_message_count_30d: int = Field(ge=0)
    shared_conversation_count: int = Field(ge=0)
    shared_open_task_count: int = Field(ge=0)
    last_interaction_at: datetime | None
    interaction_score: float = Field(ge=0, le=100)
    tags: list[PeopleTag]
    explanations: list[str]
    metric_window_days: int = 30
    score_version: Literal["v1"] = "v1"
