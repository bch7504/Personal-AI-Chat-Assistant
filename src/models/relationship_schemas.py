from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

RelationshipType = Literal[
    "colleague",
    "manager",
    "direct_report",
    "client",
    "partner",
    "vendor",
    "friend",
    "mentor",
    "other",
]


class ExternalContactCreate(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    organization: str | None = Field(default=None, max_length=160)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("display_name cannot be blank")
        return normalized

    @field_validator("organization")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class ExternalContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    email: str
    display_name: str
    organization: str | None
    linked_user_id: str | None
    status: Literal["invited", "active", "revoked"]
    created_at: datetime
    updated_at: datetime


class RelationshipCreate(BaseModel):
    subject_kind: Literal["workspace_user", "external_contact"]
    subject_id: str
    relationship_type: RelationshipType
    custom_label: str | None = Field(default=None, max_length=80)
    strength: int = Field(default=3, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_custom_label(self):
        if self.relationship_type == "other" and not (self.custom_label or "").strip():
            raise ValueError("custom_label is required when relationship_type is other")
        if self.relationship_type != "other":
            self.custom_label = None
        return self

    @field_validator("custom_label", "notes")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class RelationshipUpdate(BaseModel):
    relationship_type: RelationshipType | None = None
    custom_label: str | None = Field(default=None, max_length=80)
    strength: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=2000)
    status: Literal["active", "archived"] | None = None
    last_interaction_at: datetime | None = None

    @field_validator("custom_label", "notes")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class RelationshipOut(BaseModel):
    id: str
    workspace_id: str
    subject_kind: Literal["workspace_user", "external_contact"]
    subject_id: str
    display_name: str
    email: str
    organization: str | None
    relationship_type: RelationshipType
    custom_label: str | None
    strength: int
    status: Literal["suggested", "active", "archived", "rejected"]
    source: Literal["manual", "ai_suggested", "imported"]
    notes: str | None
    last_interaction_at: datetime | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime
