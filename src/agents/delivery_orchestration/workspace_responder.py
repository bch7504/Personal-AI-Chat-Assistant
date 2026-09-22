"""Policy-owned responses that need no Delivery data or specialist execution."""

from __future__ import annotations

from src.agents.contracts import BusinessRole
from src.agents.delivery_orchestration.contracts import DeliveryIntent


def build_workspace_only_response(
    *,
    intent: DeliveryIntent,
    role: BusinessRole,
    authorized_group_count: int,
) -> str:
    """Return a safe, role-aware response without reading business records.

    These responses are deliberately deterministic: greetings, capability
    descriptions and clarification questions do not benefit from specialist
    fan-out or access to a Delivery snapshot.
    """

    if intent == DeliveryIntent.GREETING:
        if role == BusinessRole.LEAD:
            return (
                "Xin chào Lead. Tôi là Product Delivery Workspace Agent. "
                "Bạn muốn xem task, tiến độ, blocker, milestone hay release readiness?"
            )
        return (
            "Xin chào. Tôi là Product Delivery Workspace Agent. "
            "Tôi có thể hỗ trợ các task, deadline và blocker trong phạm vi bạn được cấp quyền."
        )

    if intent == DeliveryIntent.ACKNOWLEDGEMENT:
        return "Không có gì. Khi cần, bạn hãy cho tôi biết task hoặc vấn đề Delivery muốn xử lý."

    if intent == DeliveryIntent.CAPABILITY_HELP:
        if role == BusinessRole.LEAD:
            return (
                "Tôi có thể phân tích task, tiến độ, blocker, dependency, milestone, quyết định "
                f"và release readiness trong {authorized_group_count} group được cấp quyền. "
                "Bạn có thể hỏi toàn workspace hoặc chọn một group cụ thể. Các thay đổi quan trọng "
                "vẫn phải qua phê duyệt của con người."
            )
        return (
            "Tôi có thể xem và phân tích task, deadline, blocker và thông tin Delivery liên quan "
            "trực tiếp đến bạn trong group được cấp quyền. Tôi không thể mở rộng sang task của "
            "người khác hoặc group mà bạn không tham gia."
        )

    if intent == DeliveryIntent.OUT_OF_SCOPE:
        return (
            "Yêu cầu này nằm ngoài phạm vi Product Delivery Workspace Agent. "
            "Tôi có thể hỗ trợ task, tiến độ, blocker, dependency, milestone, quyết định và release readiness."
        )

    if intent == DeliveryIntent.POLICY_REFUSAL:
        return (
            "Tôi không thể cung cấp chat nội bộ QA hoặc log defect thô từ profile QA. "
            "Product Delivery chỉ được sử dụng handoff đã công bố và dữ liệu typed đã được cấp quyền; "
            "hãy mở QA Workspace Agent nếu bạn cần làm việc với dữ liệu QA trong đúng phạm vi quyền hạn."
        )

    return (
        "Bạn muốn tôi hỗ trợ nội dung nào của Product Delivery: xem task, công việc của bạn, "
        "phân tích blocker/dependency, kiểm tra milestone hay đánh giá release readiness?"
    )
