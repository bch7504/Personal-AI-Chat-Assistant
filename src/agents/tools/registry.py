from pydantic import Field, model_validator

from src.agents.contracts import AgentIntent, AgentProfile, FrozenContract, RequestedScope
from src.agents.profiles.product_delivery import PRODUCT_DELIVERY_PROMPT_VERSION
from src.agents.profiles.quality_assurance import QUALITY_ASSURANCE_PROMPT_VERSION


class AgentProfileRegistration(FrozenContract):
    profile: AgentProfile
    prompt_version: str = Field(min_length=1)
    allowed_scopes: tuple[RequestedScope, ...]
    allowed_intents: tuple[AgentIntent, ...]
    allowed_tools: tuple[str, ...]

    @model_validator(mode="after")
    def registration_has_unique_capabilities(self) -> "AgentProfileRegistration":
        if not self.allowed_scopes or not self.allowed_intents:
            raise ValueError("A profile registration requires scopes and intents")
        if len(set(self.allowed_scopes)) != len(self.allowed_scopes):
            raise ValueError("allowed_scopes must be unique")
        if len(set(self.allowed_intents)) != len(self.allowed_intents):
            raise ValueError("allowed_intents must be unique")
        if len(set(self.allowed_tools)) != len(self.allowed_tools):
            raise ValueError("allowed_tools must be unique")
        return self


_PROFILE_REGISTRY = {
    AgentProfile.PERSONAL: AgentProfileRegistration(
        profile=AgentProfile.PERSONAL,
        prompt_version="personal-v1",
        allowed_scopes=(RequestedScope.PERSONAL,),
        allowed_intents=(
            AgentIntent.PERSONAL_ASSISTANCE,
            AgentIntent.SUMMARIZE,
            AgentIntent.SEARCH,
            AgentIntent.EXTRACT_TASK,
            AgentIntent.MANAGE_TASK,
            AgentIntent.CALENDAR,
            AgentIntent.REMINDER,
        ),
        allowed_tools=(
            "summarize_conversation",
            "extract_tasks",
            "create_calendar_event",
            "list_calendar_events",
            "update_calendar_event",
            "delete_calendar_event",
            "create_reminder",
            "list_reminders",
            "update_reminder",
            "cancel_reminder",
            "snooze_reminder",
            "list_my_tasks",
            "search_my_memories",
            "save_personal_memory",
            "search_people_context",
            "search_messages",
            "get_personal_timeline",
            "check_request_policy",
        ),
    ),
    AgentProfile.PRODUCT_DELIVERY: AgentProfileRegistration(
        profile=AgentProfile.PRODUCT_DELIVERY,
        prompt_version=PRODUCT_DELIVERY_PROMPT_VERSION,
        allowed_scopes=(RequestedScope.WORKSPACE,),
        allowed_intents=(AgentIntent.DELIVERY_BRIEF,),
        allowed_tools=(
            "get_delivery_tasks",
            "search_delivery_messages",
            "get_delivery_milestones",
            "get_delivery_people",
            "get_delivery_dependencies",
            "get_delivery_risks",
            "get_delivery_decisions",
            "get_delivery_release_status",
            "get_delivery_capacity_summary",
            "get_delivery_flow_metrics",
            "get_delivery_portfolio_health",
            "build_delivery_brief",
        ),
    ),
    AgentProfile.QUALITY_ASSURANCE: AgentProfileRegistration(
        profile=AgentProfile.QUALITY_ASSURANCE,
        prompt_version=QUALITY_ASSURANCE_PROMPT_VERSION,
        allowed_scopes=(RequestedScope.WORKSPACE,),
        allowed_intents=(AgentIntent.QUALITY_READINESS, AgentIntent.QUALITY_BRIEF),
        allowed_tools=(
            "get_quality_work_items",
            "get_release_test_status",
            "search_quality_messages",
            "get_quality_people",
            "build_quality_brief",
            "get_defect_register",
            "get_test_execution_summary",
            "get_release_gate_evidence",
            "get_requirement_traceability",
            "get_release_candidate",
            "get_quality_control_plane",
            "get_quality_policy",
            "get_quality_evidence_catalog",
            "get_quality_waivers",
        ),
    ),
    AgentProfile.EXECUTIVE: AgentProfileRegistration(
        profile=AgentProfile.EXECUTIVE,
        prompt_version="executive-v1",
        allowed_scopes=(RequestedScope.AGGREGATE,),
        allowed_intents=(AgentIntent.EXECUTIVE_BRIEF,),
        allowed_tools=(
            "get_workspace_briefs",
            "get_cross_workspace_dependencies",
            "build_executive_brief",
            "get_my_calendar",
            "propose_executive_meeting",
        ),
    ),
}


def get_profile_registration(profile: AgentProfile) -> AgentProfileRegistration:
    return _PROFILE_REGISTRY[profile]


def list_profile_registrations() -> tuple[AgentProfileRegistration, ...]:
    return tuple(_PROFILE_REGISTRY[profile] for profile in AgentProfile)


def assert_tool_allowed(profile: AgentProfile, tool_name: str) -> None:
    registration = get_profile_registration(profile)
    if tool_name not in registration.allowed_tools:
        raise PermissionError(f"Tool '{tool_name}' is not allowed for profile '{profile.value}'")
