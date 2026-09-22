from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceActionProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal[
        "delivery_dependency_status",
        "delivery_decision_status",
        "delivery_task_status",
        "delivery_task_assignment",
        "delivery_task_due_date",
        "delivery_group_update",
        "delivery_group_reminder_schedule",
        "quality_record_transition",
    ]
    payload: dict[str, Any]
    workflow_id: str | None = Field(default=None, min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=128)
    expires_in_minutes: int = Field(default=15, ge=1, le=60)


class WorkspaceActionProposalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    expected_row_version: int = Field(ge=1)


class WorkspaceActionProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    agent_workspace_id: str
    agent_profile: str
    workflow_id: str | None
    actor_user_id: str
    action: str
    payload: dict[str, Any]
    payload_hash: str
    idempotency_key: str
    status: str
    expires_at: datetime
    decided_by_user_id: str | None
    decided_at: datetime | None
    executed_at: datetime | None
    result_json: dict[str, Any] | None
    row_version: int
    created_at: datetime
    updated_at: datetime
