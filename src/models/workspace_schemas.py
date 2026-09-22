from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class OrganizationWorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Workspace name cannot be blank")
        return normalized


class AdminOrganizationWorkspaceCreate(OrganizationWorkspaceCreate):
    owner_email: EmailStr


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: Literal["personal", "organization"]
    name: str
    slug: str | None
    personal_owner_user_id: str | None
    status: Literal["active", "suspended", "deleting"]
    created_at: datetime
    updated_at: datetime
    current_user_role: Literal["owner", "admin", "member", "guest"] | None = None


class WorkspaceMemberCreate(BaseModel):
    email: EmailStr
    role: Literal["admin", "member", "guest"] = "member"


class WorkspaceMemberOut(BaseModel):
    id: str
    user_id: str
    email: str
    display_name: str
    role: Literal["owner", "admin", "member", "guest"]
    status: Literal["active", "invited", "suspended", "revoked"]
    joined_at: datetime | None
