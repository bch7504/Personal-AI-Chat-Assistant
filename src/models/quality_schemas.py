from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QualityBriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2_000)
    release_id: str = Field(min_length=1, max_length=128)
    selected_conversation_id: str | None = Field(default=None, min_length=1)
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)


class QualityGroupCapability(BaseModel):
    id: str
    name: str


class QualityCapabilitiesOut(BaseModel):
    current_user_business_role: Literal["lead", "member"]
    view_scope: Literal["workspace", "member"]
    can_select_group: bool
    can_manage_control_plane: bool
    can_execute_tests: bool
    can_submit_evidence: bool
    can_report_defects: bool
    can_verify_evidence: bool
    can_decide_release: bool
    can_update_own_work_items: bool
    can_propose_actions: bool
    groups: list[QualityGroupCapability]
    release_ids: list[str]


class QualityWorkItemCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=1, max_length=128)
    release_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    work_item_type: Literal["bug", "test_case", "release_check"]
    severity: Literal["low", "medium", "high", "critical"] | None = None
    quality_status: Literal["open", "testing", "passed", "failed", "blocked"] = "open"
    required: bool = False
    owner_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_shape(self) -> QualityWorkItemCreateRequest:
        if self.work_item_type == "bug" and self.severity is None:
            raise ValueError("Bug severity is required")
        if self.work_item_type != "bug" and self.severity is not None:
            raise ValueError("Only a bug can have severity")
        if self.required and self.work_item_type != "release_check":
            raise ValueError("Only a release check can be required")
        return self


class QualityWorkItemStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality_status: Literal["open", "testing", "passed", "failed", "blocked"]
    expected_row_version: int = Field(ge=1)


class QualityWorkItemOut(BaseModel):
    id: str
    conversation_id: str
    release_id: str
    title: str
    work_item_type: Literal["bug", "test_case", "release_check"]
    severity: Literal["low", "medium", "high", "critical"] | None
    quality_status: Literal["open", "testing", "passed", "failed", "blocked"]
    required: bool
    owner_id: str
    row_version: int = Field(ge=1)
