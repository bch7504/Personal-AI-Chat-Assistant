from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReleaseCandidateCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality_agent_workspace_id: str = Field(min_length=1, max_length=128)
    source_conversation_id: str = Field(min_length=1, max_length=128)
    delivery_milestone_id: str | None = Field(default=None, min_length=1, max_length=128)
    release_key: str = Field(min_length=1, max_length=128)
    version: str = Field(default="", max_length=64)
    build_number: str = Field(default="", max_length=64)
    commit_sha: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{7,64}$")
    environment: Literal["development", "staging", "production"] = "staging"
    submit_to_qa: bool = True


class ReleaseCandidateStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["qa_in_progress", "approved", "rejected"]
    expected_row_version: int = Field(ge=1)


class DeliveryReleaseCandidateStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["qa_requested", "released", "cancelled"]
    expected_row_version: int = Field(ge=1)


class ReleaseCandidateOut(BaseModel):
    id: str
    organization_workspace_id: str
    delivery_agent_workspace_id: str
    quality_agent_workspace_id: str | None
    source_conversation_id: str
    delivery_milestone_id: str | None
    release_key: str
    version: str
    build_number: str
    commit_sha: str | None
    environment: str
    status: str
    quality_policy_version: str
    row_version: int
    created_at: datetime
    updated_at: datetime
