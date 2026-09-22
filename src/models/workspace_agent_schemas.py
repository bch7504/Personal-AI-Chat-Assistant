"""Strict public contracts for the server-owned workspace-agent router."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceAgentInvokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_agent_workspace_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=2_000)
    selected_conversation_id: str | None = Field(default=None, min_length=1, max_length=128)
    release_id: str | None = Field(default=None, min_length=1, max_length=128)
    period_days: int = Field(default=7, ge=1, le=31)
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)


class WorkspaceAgentThreadSummaryOut(BaseModel):
    thread_id: str
    title: str
    preview: str
    message_count: int
    updated_at: datetime
    created_at: datetime


class WorkspaceAgentMessageOut(BaseModel):
    id: str
    sequence_number: int
    role: str
    content: str
    created_at: datetime
    run_history: dict[str, Any] | None = None
