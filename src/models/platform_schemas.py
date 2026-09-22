from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PlatformStats(BaseModel):
    total_users: int
    total_workspaces: int
    total_conversations: int
    total_messages: int
    new_users_last_7_days: int


class SupportAccessGrantRequest(BaseModel):
    workspace_id: str
    requested_scope: Literal["conversation:read", "personal_data:read", "personal_data:manage"]
    reason: str = Field(min_length=10, max_length=1000)
    duration_minutes: int = Field(ge=5, le=60)


class SupportAccessGrantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    platform_admin_id: str
    workspace_id: str
    requested_scope: str
    scope_json: dict[str, Any]
    reason: str
    status: Literal["requested", "approved", "expired", "revoked", "rejected"]
    approved_by_owner_id: str | None
    created_at: datetime
    approved_at: datetime | None
    expires_at: datetime
    revoked_at: datetime | None
