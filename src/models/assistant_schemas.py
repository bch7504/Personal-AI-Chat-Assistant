from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AssistantThreadOut(BaseModel):
    thread_id: str
    title: str
    preview: str
    updated_at: datetime


class AssistantMessageOut(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    analysis: str = ""
    analysis_steps: list[str] = Field(default_factory=list)
