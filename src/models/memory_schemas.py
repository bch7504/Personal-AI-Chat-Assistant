from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

MemoryType = Literal["preference", "relationship", "episodic", "semantic"]
MemorySensitivity = Literal["normal", "sensitive"]


class MemoryOut(BaseModel):
    id: str
    workspace_id: str
    category: str
    title: str
    detail: str
    memory_type: MemoryType
    source_conversation_id: str | None
    source_message_ids: list[str]
    consent_scope_hash: str | None
    sensitivity: MemorySensitivity
    confidence: float
    expires_at: datetime | None
    last_accessed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MemoryCreateRequest(BaseModel):
    workspace_id: str | None = None
    category: str = Field(..., min_length=1, max_length=40)
    title: str = Field(..., min_length=1, max_length=200)
    detail: str = Field(default="", max_length=10000)
    memory_type: MemoryType = "semantic"
    source_conversation_id: str | None = None
    source_message_ids: list[str] = Field(default_factory=list, max_length=100)
    consent_scope_hash: str | None = Field(default=None, max_length=128)
    sensitivity: MemorySensitivity = "normal"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_provenance(self):
        provenance_fields = (
            self.source_conversation_id,
            self.source_message_ids,
            self.consent_scope_hash,
        )
        if any(provenance_fields) and not all(provenance_fields):
            raise ValueError(
                "source_conversation_id, source_message_ids and consent_scope_hash must be provided together"
            )
        return self


class MemoryUpdateRequest(BaseModel):
    category: str | None = Field(default=None, min_length=1, max_length=40)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    detail: str | None = Field(default=None, max_length=10000)
    memory_type: MemoryType | None = None
    sensitivity: MemorySensitivity | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    expires_at: datetime | None = None
