from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"] = "user"
    sender: str | None = None
    content: str = Field(..., min_length=1, max_length=10_000)
    timestamp: str | None = Field(default=None, description="ISO 8601 datetime, optional")


class MessageScope(BaseModel):
    kind: Literal["latest_n", "unread", "today", "yesterday", "this_week", "rolling_hours", "custom_range"]
    count: int | None = Field(default=None, ge=1, le=200)
    hours: int | None = Field(default=None, ge=1, le=168)
    since: datetime | None = None
    until: datetime | None = None

    @model_validator(mode="after")
    def validate_scope_fields(self):
        if self.count and self.count > 50 and self.kind != "unread":
            raise ValueError("only unread scope supports more than 50 messages")
        if self.kind == "custom_range" and (self.since is None or self.until is None):
            raise ValueError("custom_range requires both since and until")
        if self.since and self.until and self.since >= self.until:
            raise ValueError("scope since must be before until")
        return self


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000, description="Tin nhắn từ user")
    thread_id: str | None = Field(
        default=None, max_length=128, description="Conversation thread id; generated if omitted"
    )
    workspace_id: str | None = Field(
        default=None,
        description="Conversation workspace validation only; omit for Personal Assistant",
    )
    context_limit: int = Field(default=20, ge=1, le=200)
    scope: MessageScope | None = None
    messages: list[ChatMessage] | None = Field(
        default=None,
        max_length=200,
        description="Raw message history to summarize (read by summarize_conversation via state)",
    )
    conversation_id: str | None = Field(
        default=None,
        description=(
            "If `messages` come from a real 1-1/group chat conversation, its id - the server "
            "verifies the caller is actually a participant before letting the agent see them, "
            "rather than trusting whatever `messages` the client attached."
        ),
    )


class InterruptPayload(BaseModel):
    type: Literal[
        "calendar_event",
        "calendar_event_update",
        "calendar_event_delete",
        "reminder",
        "reminder_update",
        "reminder_cancel",
        "reminder_snooze",
    ]
    draft: dict


class AuthorizedContextMetadata(BaseModel):
    included_participants: list[str] = Field(default_factory=list)
    excluded_participants: list[str] = Field(default_factory=list)
    included_message_count: int = 0
    window_message_count: int = 0
    coverage: float = 0.0
    source_message_ids: list[str] = Field(default_factory=list)
    consent_scope_hash: str = ""


class ChatResponse(BaseModel):
    response: str = Field(default="", description="Phản hồi từ agent")
    analysis: str = Field(
        default="",
        description="Tóm tắt routing/tool đã dùng; không chứa chain-of-thought nội bộ",
    )
    analysis_steps: list[str] = Field(
        default_factory=list,
        description="Các bước xử lý quan sát được để hiển thị dạng activity trace",
    )
    thread_id: str
    status: Literal["completed", "interrupted", "error"] = "completed"
    interrupt: InterruptPayload | None = None
    context_scope: AuthorizedContextMetadata | None = None


class ResumeRequest(BaseModel):
    thread_id: str
    approved: bool
    edits: dict | None = None
