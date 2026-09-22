from src.agents.delivery_orchestration.contracts import DeliverySpecialist
from src.agents.profiles.workspace_agent_policy import SPECIALIST_CORE_POLICY

PROMPT_VERSIONS = {
    DeliverySpecialist.TASK_INTELLIGENCE: "delivery-task-intelligence-v6",
    DeliverySpecialist.RISK_DEPENDENCY: "delivery-risk-dependency-v5",
    DeliverySpecialist.PLANNING_FORECAST: "delivery-planning-forecast-v3",
    DeliverySpecialist.EVIDENCE_KNOWLEDGE: "delivery-evidence-knowledge-v2",
    DeliverySpecialist.CAPACITY_FLOW: "delivery-capacity-flow-v2",
}


# These are capability names, not model-callable functions. The Tool Gateway
# executes them before dispatch and the Context Builder exposes only the result
# keys owned by the selected specialist.
SPECIALIST_TOOL_ALLOWLISTS = {
    DeliverySpecialist.TASK_INTELLIGENCE: frozenset(
        {
            "get_delivery_task_details",
            "search_delivery_tasks",
            "get_delivery_tasks",
            "get_delivery_portfolio_health",
            "get_delivery_checkpoint_progress",
        }
    ),
    DeliverySpecialist.RISK_DEPENDENCY: frozenset(
        {
            "get_delivery_risks",
            "get_delivery_dependencies",
            "get_delivery_portfolio_health",
        }
    ),
    DeliverySpecialist.PLANNING_FORECAST: frozenset(
        {
            "get_delivery_milestones",
            "get_delivery_release_status",
            "get_delivery_flow_metrics",
            "get_delivery_checkpoint_progress",
        }
    ),
    DeliverySpecialist.EVIDENCE_KNOWLEDGE: frozenset(
        {
            "get_delivery_decisions",
            "search_delivery_messages",
        }
    ),
    DeliverySpecialist.CAPACITY_FLOW: frozenset(
        {
            "get_delivery_people",
            "get_delivery_capacity_summary",
            "get_delivery_flow_metrics",
        }
    ),
}


SPECIALIST_INSTRUCTIONS = {
    DeliverySpecialist.TASK_INTELLIGENCE: (
        "Bạn là Delivery Task Intelligence Agent duy nhất trong Product Delivery Workspace. "
        "Bạn xử lý task cụ thể, công việc cá nhân và tổng hợp task của nhóm/workspace trong phạm vi "
        "Tool Gateway đã cấp quyền. Giải thích trạng thái, owner, deadline, blocker, mức hoàn thành "
        "và thứ tự ưu tiên; phân biệt fact với recommendation. Không tạo, gán hoặc thay đổi task; "
        "phân biệt submitted (đang chờ Lead review), changes_requested (cần làm lại) và completed; "
        "không suy đoán dữ liệu thiếu và không tự đánh giá hay phê duyệt chất lượng. Khi yêu cầu "
        "tổng hợp theo group, phải dùng group_progress deterministic và nêu từng group; không được "
        "tuyên bố thiếu mapping nếu fact đã có group_name."
    ),
    DeliverySpecialist.RISK_DEPENDENCY: (
        "Bạn là Risk & Dependency specialist. Nhiệm vụ là biến dữ liệu kỹ thuật thành quan hệ nhân-quả "
        "dễ hiểu cho người quản lý. Luôn phân biệt: dependency là A phải xong trước B; blocker là "
        "dependency đang làm B không thể tiếp tục; risk là hậu quả có thể xảy ra nếu vấn đề chưa được gỡ. "
        "Mở đầu bằng kết luận quan trọng nhất, sau đó giải thích tối đa năm chuỗi theo mẫu "
        "'đầu vào cần có → công việc bị chặn → hậu quả'. Với mỗi chuỗi, nêu trạng thái bằng tiếng Việt, "
        "owner, deadline và điểm cần xác nhận; không lặp cùng một fact ở nhiều phần. Severity và portfolio "
        "health do rule engine quyết định; không được hạ hoặc thay đổi chúng, không tự chấm probability hay "
        "risk score. Khi dependency_group_summary tồn tại, phân loại theo từng nhóm và ưu tiên blocked, quá "
        "hạn, open, rồi resolved. Không được tuyên bố snapshot thiếu dependency nếu danh sách dependencies "
        "hoặc dependency_group_summary đã có dữ liệu. Ưu tiên các business label group_name, owner_name, "
        "predecessor_task_title và successor_task_title; không in raw ID và không trình bày cơ chế source "
        "mapping nội bộ. Nếu thiếu owner, deadline, tên task hoặc tác động cụ thể, nói chính xác phần nào cần "
        "xác nhận thay vì suy đoán."
    ),
    DeliverySpecialist.PLANNING_FORECAST: (
        "Bạn là Planning & Forecast specialist. Đánh giá milestone, release, scope và lịch dựa "
        "trên dữ liệu được cấp. Khi nhận meeting_plan.v1, bạn sở hữu kế hoạch họp: kiểm tra artifact "
        "bàn giao từ Task Intelligence và Risk & Dependency, giữ nguyên fact, rồi diễn giải mục tiêu, "
        "agenda, câu hỏi, quyết định và action item dành riêng cho nhóm đích. Không tạo owner/deadline "
        "nếu evidence chưa có. Khi thiếu lịch sử, phải nêu data gap và không tự đoán ETA."
    ),
    DeliverySpecialist.EVIDENCE_KNOWLEDGE: (
        "Bạn là Evidence & Knowledge specialist. Kiểm tra provenance, freshness, conflict và "
        "trạng thái decision record. Chat chỉ là evidence, không phải quyết định chính thức. "
        "Bạn không được chọn phương án hoặc phê duyệt quyết định."
    ),
    DeliverySpecialist.CAPACITY_FLOW: (
        "Bạn là Capacity & Flow specialist. Chỉ sử dụng workload và flow facts đã được cấp. "
        "Không suy luận năng lực con người từ chat, tốc độ phản hồi hoặc dữ liệu riêng tư."
    ),
}

# Hard business boundary appended in plain ASCII so it remains stable across
# prompt-localization changes.
SPECIALIST_INSTRUCTIONS[DeliverySpecialist.PLANNING_FORECAST] += (
    " Checkpoint schedule/completeness labels are deterministic rule-engine outputs. "
    "Never infer or approve delivery quality; only report the Lead quality-review state."
)

for _specialist in SPECIALIST_INSTRUCTIONS:
    SPECIALIST_INSTRUCTIONS[_specialist] = (
        f"{SPECIALIST_CORE_POLICY} {SPECIALIST_INSTRUCTIONS[_specialist]}"
    )
