from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DeliveryBriefRequest(BaseModel):
    """Untrusted input for one deterministic Product Delivery read."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2_000)
    selected_conversation_id: str | None = Field(default=None, min_length=1)
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)
    client_request_id: str | None = Field(default=None, min_length=8, max_length=128)
    period_days: int = Field(default=7, ge=1, le=31)
    persist_history: bool = True

    @model_validator(mode="after")
    def validate_ephemeral_turn(self):
        if not self.persist_history and self.thread_id is not None:
            raise ValueError("An ephemeral Delivery turn cannot resume a persisted thread")
        return self


class DeliveryDependencyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_conversation_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    owner_id: str | None = Field(default=None, max_length=128)
    predecessor_task_id: str | None = Field(default=None, max_length=128)
    successor_task_id: str | None = Field(default=None, max_length=128)
    due_at: datetime | None = None


class DeliveryDependencyStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["open", "blocked", "resolved", "invalidated"]
    expected_row_version: int = Field(ge=1)


class DeliveryDependencyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    agent_workspace_id: str
    conversation_id: str
    title: str
    status: Literal["open", "blocked", "resolved", "invalidated"]
    owner_id: str | None
    predecessor_task_id: str | None
    successor_task_id: str | None
    due_at: datetime | None
    row_version: int
    created_at: datetime
    updated_at: datetime


class DeliveryDecisionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_conversation_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    owner_id: str | None = Field(default=None, max_length=128)
    due_at: datetime | None = None
    options: list[str] = Field(default_factory=list, max_length=20)


class DeliveryDecisionStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["pending", "decided", "superseded", "invalidated"]
    expected_row_version: int = Field(ge=1)
    outcome: str | None = Field(default=None, max_length=2000)


class DeliveryDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    agent_workspace_id: str
    conversation_id: str
    title: str
    status: Literal["pending", "decided", "superseded", "invalidated"]
    owner_id: str | None
    due_at: datetime | None
    options: list[str]
    outcome: str | None
    row_version: int
    created_at: datetime
    updated_at: datetime


class DeliveryGroupCapability(BaseModel):
    id: str
    name: str


class DeliveryCapabilitiesOut(BaseModel):
    current_user_business_role: Literal["lead", "member"]
    view_scope: Literal["workspace", "member"]
    can_select_group: bool
    can_manage_control_plane: bool
    can_manage_release_handoffs: bool
    can_update_own_tasks: bool
    can_propose_actions: bool
    can_create_team_tasks: bool = False
    can_review_task_submissions: bool = False
    groups: list[DeliveryGroupCapability]


class DeliveryTaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_conversation_id: str = Field(min_length=1, max_length=128)
    owner_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    due_at: datetime | None = None
    priority: Literal["High", "Medium", "Low"] = "Medium"
    requires_review: bool = False

    @model_validator(mode="after")
    def validate_due_at(self):
        if self.due_at is not None and self.due_at.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        return self


class DeliveryTaskReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "changes_requested"]
    review_note: str | None = Field(default=None, max_length=4_000)
    expected_row_version: int = Field(ge=1)

    @model_validator(mode="after")
    def require_change_note(self):
        self.review_note = (self.review_note or "").strip() or None
        if self.decision == "changes_requested" and not self.review_note:
            raise ValueError("Requesting changes requires a review note")
        return self


class DeliveryTaskReviewItemOut(BaseModel):
    id: str
    conversation_id: str
    conversation_name: str
    owner_id: str
    owner_name: str
    title: str
    priority: Literal["High", "Medium", "Low"]
    status: str
    due_at: datetime | None
    submission_note: str | None
    evidence_urls: list[str]
    submitted_at: datetime | None
    review_note: str | None
    row_version: int


class DeliveryDashboardWorkItem(BaseModel):
    id: str
    title: str
    status: str
    assignee_id: str | None = None
    assignee_name: str | None = None
    due_at: datetime | None = None
    blocked_reason: str | None = None
    requires_review: bool = False
    submission_note: str | None = None
    evidence_urls: list[str] = Field(default_factory=list)
    submitted_at: datetime | None = None
    review_note: str | None = None


class DeliveryDashboardWorkStats(BaseModel):
    total: int = Field(ge=0)
    completed: int = Field(ge=0)
    in_progress: int = Field(ge=0)
    pending: int = Field(ge=0)
    blocked: int = Field(ge=0)
    overdue: int = Field(ge=0)
    due_soon: int = Field(ge=0)
    unassigned: int = Field(ge=0)
    completion_percent: int = Field(ge=0, le=100)
    submitted: int = Field(default=0, ge=0)
    changes_requested: int = Field(default=0, ge=0)


class DeliveryDashboardMember(BaseModel):
    user_id: str
    display_name: str
    email: str
    job_title: str
    business_role: Literal["lead", "member"] | None = None
    groups: list[DeliveryGroupCapability]
    task_stats: DeliveryDashboardWorkStats | None = None
    milestone_count: int | None = Field(default=None, ge=0)


class DeliveryDashboardGroupMember(BaseModel):
    user_id: str
    display_name: str
    email: str
    job_title: str
    business_role: Literal["lead", "member"] | None = None
    resource_role: Literal["manager", "participant", "viewer"]


class DeliveryDashboardLastMessage(BaseModel):
    sender_name: str
    excerpt: str
    created_at: datetime


class DeliveryDashboardGroup(BaseModel):
    id: str
    name: str
    ai_enabled: bool
    member_count: int = Field(ge=0)
    message_count: int = Field(ge=0)
    members: list[DeliveryDashboardGroupMember]
    task_stats: DeliveryDashboardWorkStats
    milestone_stats: DeliveryDashboardWorkStats
    tasks: list[DeliveryDashboardWorkItem]
    milestones: list[DeliveryDashboardWorkItem]
    last_message: DeliveryDashboardLastMessage | None = None
    updated_at: datetime


class DeliveryDashboardOut(BaseModel):
    workspace_id: str
    agent_workspace_id: str
    current_user_business_role: Literal["lead", "member"]
    total_groups: int = Field(ge=0)
    total_members: int = Field(ge=0)
    blocked_groups: int = Field(ge=0)
    at_risk_groups: int = Field(ge=0)
    task_stats: DeliveryDashboardWorkStats
    milestone_stats: DeliveryDashboardWorkStats
    members: list[DeliveryDashboardMember]
    groups: list[DeliveryDashboardGroup]
    generated_at: datetime
