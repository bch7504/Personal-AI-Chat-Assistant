from __future__ import annotations

import re
import unicodedata

from src.agents.delivery_orchestration.contracts import (
    DeliveryExecutionMode,
    DeliveryIntent,
    DeliveryRoutingDecision,
    DeliverySpecialist,
)

_TASK_ID = re.compile(
    r"\b(?:task\s*)?((?:[A-Z][A-Z0-9]{0,9}-\d{1,8})|(?:[0-9a-f]{32})|(?:[0-9a-f]{8}-[0-9a-f-]{27,36}))\b",
    re.IGNORECASE,
)

_GREETING = re.compile(
    r"^(?:hi|hello|hey|xin chào|chào|chào bạn|chào agent|good morning|good afternoon|good evening)[\s!,.?]*$",
    re.IGNORECASE,
)
_ACKNOWLEDGEMENT = re.compile(
    r"^(?:cảm ơn|cám ơn|thanks|thank you|ok|okay|được rồi|hiểu rồi|đúng|đúng rồi|chuẩn)[\s!,.?]*$",
    re.IGNORECASE,
)


def _contains(text: str, *terms: str) -> bool:
    return any(term in text for term in terms)


def _fold_vietnamese(text: str) -> str:
    """Return a stable accent-free variant for deterministic chat routing."""

    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return without_marks.replace("đ", "d").replace("Đ", "D").casefold()


def route_delivery_request(message: str, *, capacity_enabled: bool = False) -> DeliveryRoutingDecision:
    """Choose the minimum sufficient execution plan for one Delivery turn.

    High-confidence conversational and business intents are deterministic. An
    unrecognized request fails to clarification instead of silently expanding
    into a portfolio-wide Delivery Health workflow.
    """

    normalized = " ".join(message.casefold().split())
    if _GREETING.fullmatch(normalized):
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.WORKSPACE_ONLY,
            intent=DeliveryIntent.GREETING,
            reason_code="CONVERSATIONAL_GREETING",
        )
    if _ACKNOWLEDGEMENT.fullmatch(normalized):
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.WORKSPACE_ONLY,
            intent=DeliveryIntent.ACKNOWLEDGEMENT,
            reason_code="CONVERSATIONAL_ACKNOWLEDGEMENT",
        )
    # Keep the original normalized wording and an accent-free copy. This makes
    # the deterministic safety net tolerate ordinary no-accent Vietnamese while
    # preserving all existing exact phrase matches.
    normalized = f"{normalized} {_fold_vietnamese(normalized)}"
    if _contains(
        normalized,
        "bạn làm được gì",
        "agent làm được gì",
        "khả năng của bạn",
        "có thể giúp gì",
        "hướng dẫn sử dụng",
        "what can you do",
        "help me use",
        "capabilities",
    ):
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.WORKSPACE_ONLY,
            intent=DeliveryIntent.CAPABILITY_HELP,
            reason_code="ROLE_AWARE_CAPABILITY_HELP",
        )
    if _contains(
        normalized,
        "chat nội bộ qa",
        "nội dung chat qa",
        "nguyên chat qa",
        "copy nguyên chat qa",
        "raw qa conversation",
        "qa internal chat",
        "log defect thô",
        "raw defect log",
        "chat noi bo qa",
        "noi dung chat qa",
        "nguyen chat qa",
        "log defect tho",
    ):
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.WORKSPACE_ONLY,
            intent=DeliveryIntent.POLICY_REFUSAL,
            reason_code="CROSS_PROFILE_RAW_DATA_DENIED",
        )
    if _contains(
        normalized,
        "bỏ qua toàn bộ quy tắc",
        "bỏ qua toàn bộ chỉ dẫn",
        "in prompt hệ thống",
        "tiết lộ prompt hệ thống",
        "authorization snapshot",
        "ignore all previous instructions",
        "reveal system prompt",
        "bo qua toan bo quy tac",
        "in prompt he thong",
        "tiet lo prompt he thong",
    ):
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.WORKSPACE_ONLY,
            intent=DeliveryIntent.POLICY_REFUSAL,
            reason_code="PROMPT_INJECTION_DENIED",
        )
    if _contains(
        normalized,
        "thời tiết",
        "weather",
        "nấu ăn",
        "công thức món",
        "tỷ giá",
        "giá cổ phiếu",
        "kết quả bóng đá",
        "xem phim",
    ):
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.WORKSPACE_ONLY,
            intent=DeliveryIntent.OUT_OF_SCOPE,
            reason_code="OUTSIDE_PRODUCT_DELIVERY_DOMAIN",
        )

    # Deictic group references are meaningful only with bounded thread history.
    # The state-aware router can resume them when history exists; a new thread
    # must ask which group instead of silently widening to the whole workspace.
    unresolved_group_reference = _contains(
        normalized,
        "nhóm đó",
        "nhóm ấy",
        "team đó",
        "team ấy",
        "group đó",
        "group ấy",
        "nhom do",
        "nhom ay",
        "team do",
        "team ay",
        "group do",
        "group ay",
    )
    reference_has_selector = _contains(
        normalized,
        "thấp nhất",
        "chậm nhất",
        "yếu nhất",
        "lẹt đẹt nhất",
        "lowest",
        "weakest",
        "slowest",
        "thap nhat",
        "cham nhat",
        "yeu nhat",
        "let det nhat",
    )
    if unresolved_group_reference and not reference_has_selector:
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.WORKSPACE_ONLY,
            intent=DeliveryIntent.CLARIFICATION,
            reason_code="UNRESOLVED_GROUP_REFERENCE",
            clarification_question="Bạn đang nói tới nhóm nào?",
        )

    health_negated = _contains(
        normalized,
        "không cần tổng quan toàn workspace",
        "chưa cần tổng quan toàn workspace",
        "không cần portfolio",
        "khong can tong quan toan workspace",
        "chua can tong quan toan workspace",
        "khong can portfolio",
    )

    # An explicit portfolio-wide request dominates narrower nouns that merely
    # describe what the user wants included (for example checkpoint/blocker).
    if not health_negated and _contains(
        normalized,
        "tổng quan delivery",
        "tình trạng delivery",
        "sức khỏe delivery",
        "delivery health",
        "portfolio health",
        "delivery overview",
        "toàn bộ workspace",
        "toàn workspace",
        "toan bo workspace",
        "toan workspace",
    ):
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.MULTI_SPECIALIST,
            intent=DeliveryIntent.DELIVERY_HEALTH,
            specialists=(
                DeliverySpecialist.TASK_INTELLIGENCE,
                DeliverySpecialist.PLANNING_FORECAST,
                DeliverySpecialist.RISK_DEPENDENCY,
                DeliverySpecialist.EVIDENCE_KNOWLEDGE,
            ),
            reason_code="EXPLICIT_DELIVERY_HEALTH_REQUEST",
        )

    task_match = _TASK_ID.search(message)
    task_lookup = task_match and _contains(
        normalized, "xem task", "chi tiết task", "task details", "show task", "lấy task"
    )
    if task_lookup:
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.SINGLE_SPECIALIST,
            intent=DeliveryIntent.TASK_LOOKUP,
            specialists=(DeliverySpecialist.TASK_INTELLIGENCE,),
            subject_id=task_match.group(1),
            reason_code="TASK_LOOKUP_REQUIRES_TASK_AGENT",
        )

    if _contains(
        normalized,
        "lịch của tôi",
        "lịch công việc của tôi",
        "deadline của tôi",
        "my schedule",
        "my deadlines",
        "my calendar",
    ):
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.SINGLE_SPECIALIST,
            intent=DeliveryIntent.MY_SCHEDULE,
            specialists=(DeliverySpecialist.TASK_INTELLIGENCE,),
            reason_code="MEMBER_SCHEDULE_REQUIRES_TASK_AGENT",
        )

    task_summary_requested = _contains(
        normalized,
        "tổng hợp task",
        "tổng hợp các task",
        "tổng hợp công việc",
        "đánh giá tiến độ task",
        "tiến độ task",
        "tiến độ các task",
        "tiến độ của task",
        "tình hình task",
        "task của các nhóm",
        "task của các group",
        "task từng group",
        "task theo group",
        "tiến độ các nhóm",
        "tiến độ của các nhóm",
        "tiến độ các group",
        "tiến độ của các group",
        "tình hình công việc của các nhóm",
        "task progress summary",
        "summarize tasks",
        "lẹt đẹt",
        "nhóm nào thấp nhất",
        "team nào chậm nhất",
        "team nao dang cham nhat",
        "task chậm cụ thể",
        "task dang ket",
        "nhom nao thap nhat",
        "team nao cham nhat",
    )
    dependency_requested = _contains(
        normalized,
        "dependency",
        "dependencies",
        "phụ thuộc",
        "phân loại phụ thuộc",
        "critical path",
        "phải hoàn tất trước",
        "phải xong trước",
        "phải làm trước",
        "phía sau mới",
        "chuỗi ",
        "chuỗi trước",
        "upstream",
        "downstream",
        "map giúp",
        "map giup",
        "phai hoan tat truoc",
        "phai xong truoc",
        "phai lam truoc",
        "phia sau moi",
    )
    planning_requested = _contains(
        normalized,
        "checkpoint",
        "điểm kiểm soát",
        "theo kế hoạch",
        "tiến độ kế hoạch",
        "ảnh hưởng kế hoạch",
        "lên plan",
        "lập plan",
        "lên kế hoạch",
        "lập kế hoạch",
        "kế hoạch họp",
        "plan progress",
        "meeting plan",
        "cổng kiểm soát",
        "ckpoint",
        "lead review",
        "cong kiem soat",
    )
    weak_group_review_requested = _contains(
        normalized,
        "nhóm đánh giá yếu",
        "nhóm yếu",
        "nhóm cần ưu tiên",
        "nhóm tiến độ yếu",
        "nhóm có tiến độ yếu",
        "nhóm chậm",
        "họp với những nhóm",
        "họp với các nhóm",
        "nhóm bị đánh giá thấp nhất",
        "nhóm đánh giá thấp nhất",
        "nhóm có tỷ lệ hoàn thành thấp nhất",
        "lowest-performing team",
        "lowest performing team",
        "lowest-completion team",
        "lowest completion team",
        "weakest team",
        "team chậm nhất",
        "team yếu nhất",
        "team cham nhat",
        "team yeu nhat",
        "lẹt đẹt nhất",
        "let det nhat",
        "nhóm nào thấp nhất",
        "nhom nao thap nhat",
    )
    meeting_requested = _contains(
        normalized,
        "cuộc họp",
        "họp với",
        "agenda",
        "meeting",
        "buổi làm việc",
        "agenda sync",
        "assign owner",
        "buoi lam viec",
    )
    meeting_negated = _contains(
        normalized,
        "chưa cần agenda",
        "không cần agenda",
        "chưa cần họp",
        "không cần họp",
        "chua can agenda",
        "khong can agenda",
        "chua can hop",
        "khong can hop",
    )
    meeting_requested = meeting_requested and not meeting_negated
    change_impact_requested = _contains(
        normalized,
        "change impact",
        "tác động thay đổi",
        "ảnh hưởng thay đổi",
        "scope change",
        "thay đổi scope",
        "tac dong thay doi",
        "anh huong thay doi",
        "thay doi scope",
    )
    change_impact_requested = change_impact_requested or (
        _contains(normalized, "scope")
        and _contains(normalized, "baseline", "bản trước", "ban truoc")
        and _contains(normalized, "đổi", "thay đổi", "doi", "thay doi")
    )
    milestone_requested = _contains(normalized, "milestone", "mốc", "tiến độ mốc")
    release_readiness_requested = _contains(
        normalized, "release", "phát hành", "giao đúng hạn", "readiness", "ship"
    ) and _contains(
        normalized,
        "sẵn sàng",
        "readiness",
        "phát hành",
        "giao đúng hạn",
        "go/no-go",
        "go no go",
        "ship",
        "phat hanh",
        "giao dung han",
    )

    # The requested business outcome owns routing precedence. Nouns such as
    # task/dependency/blocker describe inputs to a meeting, release, milestone
    # or change-impact analysis; they must not downgrade that broader outcome.
    if (planning_requested or meeting_requested) and weak_group_review_requested:
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.MULTI_SPECIALIST,
            intent=DeliveryIntent.MEETING_PLAN,
            specialists=(
                DeliverySpecialist.TASK_INTELLIGENCE,
                DeliverySpecialist.RISK_DEPENDENCY,
                DeliverySpecialist.PLANNING_FORECAST,
            ),
            target_selector="lowest_completion",
            reason_code="WEAKEST_TEAM_MEETING_PLAN",
        )
    if meeting_requested and not dependency_requested:
        # The semantic router resolves a named team against the authorized
        # group set; the keyword layer deliberately does not guess an ID.
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.WORKSPACE_ONLY,
            intent=DeliveryIntent.CLARIFICATION,
            reason_code="MEETING_PLAN_TARGET_REQUIRES_SEMANTIC_RESOLUTION",
        )

    if release_readiness_requested:
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.MULTI_SPECIALIST,
            intent=DeliveryIntent.RELEASE_DELIVERY_READINESS,
            specialists=(
                DeliverySpecialist.TASK_INTELLIGENCE,
                DeliverySpecialist.PLANNING_FORECAST,
                DeliverySpecialist.RISK_DEPENDENCY,
                DeliverySpecialist.EVIDENCE_KNOWLEDGE,
            ),
            reason_code="RELEASE_READINESS_REQUIRES_CROSS_DOMAIN_EVIDENCE",
        )

    if change_impact_requested:
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.MULTI_SPECIALIST,
            intent=DeliveryIntent.CHANGE_IMPACT,
            specialists=(
                DeliverySpecialist.TASK_INTELLIGENCE,
                DeliverySpecialist.PLANNING_FORECAST,
                DeliverySpecialist.RISK_DEPENDENCY,
            ),
            reason_code="CHANGE_IMPACT_REQUIRES_BASELINE_AND_CROSS_DOMAIN_ANALYSIS",
        )

    if milestone_requested:
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.MULTI_SPECIALIST,
            intent=DeliveryIntent.MILESTONE_HEALTH,
            specialists=(
                DeliverySpecialist.TASK_INTELLIGENCE,
                DeliverySpecialist.PLANNING_FORECAST,
                DeliverySpecialist.RISK_DEPENDENCY,
            ),
            reason_code="MILESTONE_HEALTH_REQUIRES_THREE_DOMAINS",
        )

    if task_summary_requested:
        # A single natural-language turn can request several business outcomes.
        # Do not let the first task-summary phrase hide explicit dependency or
        # planning work later in the sentence.
        if dependency_requested:
            return DeliveryRoutingDecision(
                execution_mode=DeliveryExecutionMode.MULTI_SPECIALIST,
                intent=DeliveryIntent.DEPENDENCY_ANALYSIS,
                specialists=(
                    DeliverySpecialist.TASK_INTELLIGENCE,
                    DeliverySpecialist.RISK_DEPENDENCY,
                    DeliverySpecialist.PLANNING_FORECAST,
                ),
                reason_code="TASK_DEPENDENCY_MEETING_PLAN_MULTI_DOMAIN",
            )

        # Identifying the lowest-completion team is part of the typed Task
        # assessment. It must not fan out to Planning unless the user actually
        # asks for checkpoint/schedule context.
        include_planning = planning_requested
        specialists = (
            (DeliverySpecialist.TASK_INTELLIGENCE, DeliverySpecialist.PLANNING_FORECAST)
            if include_planning
            else (DeliverySpecialist.TASK_INTELLIGENCE,)
        )
        return DeliveryRoutingDecision(
            execution_mode=(
                DeliveryExecutionMode.MULTI_SPECIALIST
                if include_planning
                else DeliveryExecutionMode.SINGLE_SPECIALIST
            ),
            intent=DeliveryIntent.TASK_PROGRESS_SUMMARY,
            specialists=specialists,
            reason_code=(
                "TASK_SUMMARY_WITH_CHECKPOINT_CONTEXT"
                if include_planning
                else "GROUP_TASK_SUMMARY_SINGLE_DOMAIN"
            ),
        )

    if _contains(
        normalized,
        "checkpoint",
        "điểm kiểm soát",
        "cổng kiểm soát",
        "ckpoint",
        "lead review",
        "tiến độ kế hoạch",
        "đủ để hoàn thành",
        "plan progress",
        "diem kiem soat",
        "cong kiem soat",
    ):
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.SINGLE_SPECIALIST,
            intent=DeliveryIntent.CHECKPOINT_PROGRESS,
            specialists=(DeliverySpecialist.PLANNING_FORECAST,),
            reason_code="CHECKPOINT_PROGRESS_SINGLE_DOMAIN",
        )

    if _contains(normalized, "capacity", "năng lực", "quá tải", "phân bổ", "workload"):
        specialists = (
            (DeliverySpecialist.TASK_INTELLIGENCE, DeliverySpecialist.CAPACITY_FLOW)
            if capacity_enabled
            else (DeliverySpecialist.TASK_INTELLIGENCE,)
        )
        return DeliveryRoutingDecision(
            execution_mode=(
                DeliveryExecutionMode.MULTI_SPECIALIST
                if len(specialists) > 1
                else DeliveryExecutionMode.SINGLE_SPECIALIST
            ),
            intent=DeliveryIntent.CAPACITY_ANALYSIS,
            specialists=specialists,
            reason_code="CAPACITY_DATA_GATED" if not capacity_enabled else "CAPACITY_ANALYSIS",
        )

    if dependency_requested:
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.MULTI_SPECIALIST,
            intent=DeliveryIntent.DEPENDENCY_ANALYSIS,
            specialists=(
                DeliverySpecialist.TASK_INTELLIGENCE,
                DeliverySpecialist.RISK_DEPENDENCY,
                DeliverySpecialist.PLANNING_FORECAST,
            ),
            reason_code="DEPENDENCY_REQUIRES_WORK_AND_SCHEDULE_CONTEXT",
        )

    if _contains(
        normalized,
        "blocker",
        "bị chặn",
        "đang chặn",
        "gỡ chặn",
        "nút thắt",
        "đang kẹt",
        "dang ket",
        "bi chan",
        "dang chan",
        "go chan",
        "nut that",
    ):
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.MULTI_SPECIALIST,
            intent=DeliveryIntent.BLOCKER_ANALYSIS,
            specialists=(
                DeliverySpecialist.TASK_INTELLIGENCE,
                DeliverySpecialist.RISK_DEPENDENCY,
                DeliverySpecialist.PLANNING_FORECAST,
            ),
            subject_id=task_match.group(1) if task_match else None,
            reason_code="BLOCKER_REQUIRES_IMPACT_ANALYSIS",
        )

    if _contains(normalized, "kế hoạch"):
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.MULTI_SPECIALIST,
            intent=DeliveryIntent.MILESTONE_HEALTH,
            specialists=(
                DeliverySpecialist.TASK_INTELLIGENCE,
                DeliverySpecialist.PLANNING_FORECAST,
                DeliverySpecialist.RISK_DEPENDENCY,
            ),
            reason_code="MILESTONE_HEALTH_REQUIRES_THREE_DOMAINS",
        )

    if _contains(normalized, "release", "phát hành", "giao đúng hạn", "readiness"):
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.MULTI_SPECIALIST,
            intent=DeliveryIntent.RELEASE_DELIVERY_READINESS,
            specialists=(
                DeliverySpecialist.TASK_INTELLIGENCE,
                DeliverySpecialist.PLANNING_FORECAST,
                DeliverySpecialist.RISK_DEPENDENCY,
                DeliverySpecialist.EVIDENCE_KNOWLEDGE,
            ),
            reason_code="RELEASE_READINESS_REQUIRES_CROSS_DOMAIN_EVIDENCE",
        )

    if _contains(
        normalized,
        "quyết định",
        "decision",
        "đã chốt",
        "cần chốt",
        "chưa có người chốt",
        "chuyện gì đang treo",
        "hạn chốt",
        "quyet dinh",
        "da chot",
        "can chot",
        "chua co nguoi chot",
        "chuyen gi dang treo",
        "han chot",
    ):
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.SINGLE_SPECIALIST,
            intent=DeliveryIntent.DECISION_STATUS,
            specialists=(DeliverySpecialist.EVIDENCE_KNOWLEDGE,),
            reason_code="DECISION_EVIDENCE_LOOKUP",
        )

    if _contains(normalized, "của tôi", "tôi cần", "ưu tiên", "my task", "my work"):
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.SINGLE_SPECIALIST,
            intent=DeliveryIntent.MY_WORK_PRIORITY,
            specialists=(DeliverySpecialist.TASK_INTELLIGENCE,),
            reason_code="MEMBER_WORK_ANALYSIS",
        )

    if _contains(
        normalized,
        "tổng quan delivery",
        "tình trạng delivery",
        "sức khỏe delivery",
        "delivery health",
        "portfolio health",
        "delivery overview",
        "toàn bộ workspace",
        "toàn workspace",
    ):
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.MULTI_SPECIALIST,
            intent=DeliveryIntent.DELIVERY_HEALTH,
            specialists=(
                DeliverySpecialist.TASK_INTELLIGENCE,
                DeliverySpecialist.PLANNING_FORECAST,
                DeliverySpecialist.RISK_DEPENDENCY,
                DeliverySpecialist.EVIDENCE_KNOWLEDGE,
            ),
            reason_code="EXPLICIT_DELIVERY_HEALTH_REQUEST",
        )

    if _contains(
        normalized,
        "tiến độ công việc",
        "tình trạng công việc",
        "work health",
        "workstream",
        "work status",
        "công việc đang thế nào",
    ):
        return DeliveryRoutingDecision(
            execution_mode=DeliveryExecutionMode.SINGLE_SPECIALIST,
            intent=DeliveryIntent.WORK_HEALTH,
            specialists=(DeliverySpecialist.TASK_INTELLIGENCE,),
            reason_code="TASK_STATUS_SINGLE_DOMAIN",
        )

    return DeliveryRoutingDecision(
        execution_mode=DeliveryExecutionMode.WORKSPACE_ONLY,
        intent=DeliveryIntent.CLARIFICATION,
        reason_code="AMBIGUOUS_REQUEST_REQUIRES_CLARIFICATION",
    )


def constrain_delivery_route(
    route: DeliveryRoutingDecision,
    *,
    enabled_specialists: frozenset[DeliverySpecialist],
    allow_multi: bool,
    max_specialists: int,
) -> DeliveryRoutingDecision:
    """Apply trusted deployment flags after intent classification."""

    if route.execution_mode == DeliveryExecutionMode.WORKSPACE_ONLY:
        return route

    specialists = tuple(s for s in route.specialists if s in enabled_specialists)[:max_specialists]
    if not specialists:
        raise ValueError("No enabled specialist can handle the routed Delivery intent")
    if not allow_multi:
        specialists = specialists[:1]
    return route.model_copy(
        update={
            "execution_mode": DeliveryExecutionMode.SINGLE_SPECIALIST
            if len(specialists) == 1
            else DeliveryExecutionMode.MULTI_SPECIALIST,
            "specialists": specialists,
            "reason_code": route.reason_code
            if specialists == route.specialists
            else f"{route.reason_code}_FEATURE_GATED",
        }
    )
