from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.models.memory_schemas import MemoryOut
from src.models.reminder_schemas import ReminderOut
from src.models.task_schemas import TaskOut


class AdminUserOut(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    platform_role: Literal["user", "platform_admin"]
    is_active: bool
    created_at: datetime


class AdminStats(BaseModel):
    total_users: int
    total_conversations: int
    total_messages: int
    new_users_last_7_days: int
    tokens_used_today: int
    prompt_tokens_today: int
    completion_tokens_today: int
    requests_today: int
    estimated_cost_usd_today: float
    unpriced_tokens_today: int
    daily_token_budget: int
    budget_used_pct: float


class AdminHealthComponent(BaseModel):
    key: str
    label: str
    status: Literal["operational", "degraded", "down"]
    detail: str


class AdminSystemHealth(BaseModel):
    overall_status: Literal["operational", "degraded", "down"]
    checked_at: datetime
    components: list[AdminHealthComponent]


class AdminAIManagement(BaseModel):
    provider: str
    model: str
    temperature: float
    daily_token_budget: int
    llm_configured: bool
    human_confirmation_required: bool
    conversation_consent_required: bool
    granted_permissions: int
    revoked_permissions: int
    proactive_suggestions: int
    proactive_accepted: int
    proactive_dismissed: int
    configured_providers: list[str]
    model_options: dict[str, list[dict[str, str]]]


class UpdateAIConfigurationRequest(BaseModel):
    provider: Literal["google", "groq", "openai"]
    model: str = Field(min_length=1, max_length=120)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class AdminUsageTotals(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    request_count: int
    estimated_cost_usd: float
    unpriced_tokens: int


class AdminUsageDay(AdminUsageTotals):
    date: date


class AdminUsageModel(AdminUsageTotals):
    provider: str
    model: str


class AdminAIUsageReport(BaseModel):
    days: int
    since: datetime
    totals: AdminUsageTotals
    daily: list[AdminUsageDay]
    models: list[AdminUsageModel]


class AdminAuditLogOut(BaseModel):
    id: str
    workspace_id: str | None
    actor_user_id: str | None
    actor_email: str | None
    actor_display_name: str | None
    actor_type: str
    action: str
    target_type: str
    target_id: str | None
    metadata: dict[str, Any]
    ip_address: str | None
    created_at: datetime


class AdminAuditLogPage(BaseModel):
    total: int
    items: list[AdminAuditLogOut]


class UpdateRoleRequest(BaseModel):
    role: Literal["user", "admin"]


class UpdateBudgetRequest(BaseModel):
    daily_token_budget: int = Field(..., ge=0)


class UpdateStatusRequest(BaseModel):
    is_active: bool


class AdminConversationOut(BaseModel):
    id: str
    type: str
    name: str | None
    created_by: str
    created_at: datetime
    participant_count: int
    message_count: int


class AdminMessageOut(BaseModel):
    id: str
    sender_id: str
    sender_display_name: str
    content: str
    created_at: datetime


class AdminTaskOut(TaskOut):
    owner_id: str
    owner_email: str
    owner_display_name: str
    conversation_label: str | None


class AdminReminderOut(ReminderOut):
    owner_id: str | None
    owner_email: str | None
    owner_display_name: str | None


class AdminMemoryOut(MemoryOut):
    owner_id: str
    owner_email: str
    owner_display_name: str
