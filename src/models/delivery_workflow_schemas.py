from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DeliveryWorkflowRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    parent_run_id: str | None
    specialist: str
    status: str
    attempt: int
    prompt_version: str
    model_name: str
    error_code: str | None
    usage_json: dict[str, Any]
    lineage_json: dict[str, Any]
    started_at: datetime | None
    completed_at: datetime | None


class DeliveryWorkflowEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class DeliveryWorkflowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    agent_workspace_id: str
    actor_user_id: str
    actor_role: str
    workflow_type: str
    execution_mode: str
    status: str
    subject_type: str | None
    subject_id: str | None
    plan_version: str
    result_json: dict[str, Any] | None
    data_gaps: list[str]
    row_version: int
    deadline_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    runs: list[DeliveryWorkflowRunOut] = Field(default_factory=list)


class DeliveryWorkflowCancelRequest(BaseModel):
    expected_row_version: int = Field(ge=1)


class DeliveryWorkflowResumeRequest(BaseModel):
    action: Literal["evidence_provided", "approval_recorded"]
    expected_row_version: int = Field(ge=1)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)
