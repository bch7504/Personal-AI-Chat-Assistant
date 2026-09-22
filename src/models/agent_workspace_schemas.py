from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from src.agents.contracts import AgentProfile


class AgentWorkspaceCreate(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    agent_profile: Literal[
        AgentProfile.PRODUCT_DELIVERY,
        AgentProfile.QUALITY_ASSURANCE,
        AgentProfile.EXECUTIVE,
    ]
    lead_email: EmailStr

    @field_validator("key", "name")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized


class AgentWorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_workspace_id: str
    key: str
    name: str
    agent_profile: Literal["product_delivery", "quality_assurance", "executive"]
    status: Literal["active", "suspended", "archived"]
    created_at: datetime
    updated_at: datetime
    lead_user_id: str | None = None
    lead_email: str | None = None
    lead_display_name: str | None = None
    current_user_business_role: Literal["member", "lead", "executive_viewer"] | None = None


class AgentWorkspaceLeadUpdate(BaseModel):
    email: EmailStr


class AgentWorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: Literal["active", "suspended", "archived"] | None = None

    @field_validator("name")
    @classmethod
    def strip_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized


class AdminWorkspaceSummaryOut(BaseModel):
    id: str
    name: str
    status: Literal["active", "suspended", "deleting"]
    owner_email: str | None = None
    owner_display_name: str | None = None
    agent_workspace_count: int
    created_at: datetime


class AgentWorkspaceMemberCreate(BaseModel):
    email: EmailStr
    business_role: Literal["member", "executive_viewer"]


class AgentWorkspaceMemberOut(BaseModel):
    id: str
    agent_workspace_id: str
    user_id: str
    email: str
    display_name: str
    business_role: Literal["member", "lead", "executive_viewer"]
    status: Literal["active", "invited", "suspended", "revoked"]
    created_at: datetime
    updated_at: datetime


class AgentWorkspaceConversationCreate(BaseModel):
    conversation_id: str = Field(min_length=1)
    classification: Literal["delivery", "quality"]


class AgentWorkspaceConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_workspace_id: str
    conversation_id: str
    classification: Literal["delivery", "quality"]
    channel_kind: Literal["announcement", "team", "project", "release"] = "project"
    linked_by_user_id: str
    created_at: datetime
