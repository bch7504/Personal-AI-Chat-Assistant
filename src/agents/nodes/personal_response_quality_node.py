"""Business-completeness validation for Personal Agent multi-source answers."""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.state import AgentState
from src.services import guardrail_service
from src.services.personal_query_router_service import normalize_for_routing


def _latest_human_index(messages: list[Any]) -> int | None:
    return next(
        (index for index in range(len(messages) - 1, -1, -1) if isinstance(messages[index], HumanMessage)),
        None,
    )


def _requirements(user_text: str) -> set[str]:
    normalized = normalize_for_routing(user_text)
    required = set()
    if re.search(r"\b(uu tien|sap xep|lam truoc|quan trong)\b", normalized):
        required.add("priority")
    if re.search(r"\b(xung dot|trung lich|chong lich|overlap|conflict)\b", normalized):
        required.add("conflict")
    if re.search(r"\b(lich|calendar|cuoc hop|su kien)\b", normalized):
        required.add("calendar")
    if re.search(r"\b(reminder|nhac viec|nhac nho|nhac truoc)\b", normalized):
        required.add("reminder")
    return required


def _answer_covers(answer: str, requirement: str) -> bool:
    normalized = normalize_for_routing(answer)
    patterns = {
        "priority": r"\b(uu tien|viec can lam truoc)\b",
        "conflict": r"\b(xung dot|khong phat hien xung dot|rui ro tai|trung lich|chong lich)\b",
        "calendar": r"\b(google calendar|calendar|lich)\b",
        "reminder": r"\b(reminder|nhac viec|nhac nho|nhac luc)\b",
    }
    return bool(re.search(patterns[requirement], normalized))


def _parse_timeline_report(messages: list[Any]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if not isinstance(message, ToolMessage) or message.name != "get_personal_timeline":
            continue
        try:
            payload = json.loads(str(message.content))
        except (TypeError, ValueError):
            return None
        if isinstance(payload, dict) and isinstance(payload.get("report_markdown"), str):
            return payload
    return None


def _search_evidence(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, ToolMessage) and message.name == "search_messages" and message.content:
            safe = guardrail_service.sanitize_untrusted_text(str(message.content)).strip()
            return safe[:2_000]
    return ""


def _requires_verified_message_deadline(user_text: str) -> bool:
    normalized = normalize_for_routing(user_text)
    return bool(
        re.search(r"\b(tin nhan|message|chat|cam ket)\b", normalized)
        and re.search(r"\b(deadline|han chot|han)\b", normalized)
    )


def _search_has_no_match(search_result: str) -> bool:
    normalized = normalize_for_routing(search_result)
    return bool(
        re.search(r"\b(no authorized messages matched|khong tim thay)\b", normalized)
    )


def _evidence_marker(user_text: str) -> str:
    match = re.search(r"\b[A-Z0-9]+(?:-[A-Z0-9]+)+\b", user_text)
    return match.group(0) if match else "dữ kiện được yêu cầu"


async def personal_response_quality_node(state: AgentState) -> dict:
    """Repair raw/incomplete workload answers from trusted structured tool results.

    This is not a second model pass. It deterministically enforces the sections explicitly asked
    for by the user, while the normal output guardrail still validates the repaired text next.
    """

    messages = state.get("messages", [])
    human_index = _latest_human_index(messages)
    if human_index is None:
        return {}
    user_text = str(messages[human_index].content)
    turn_messages = messages[human_index + 1 :]
    search_evidence = _search_evidence(turn_messages)
    if _requires_verified_message_deadline(user_text) and _search_has_no_match(search_evidence):
        marker = _evidence_marker(user_text)
        repaired = (
            "## Kết quả xác minh\n"
            f"Không tìm thấy tin nhắn được cấp quyền chứa **`{marker}`**, nên chưa có deadline "
            "đáng tin cậy để làm mốc đối chiếu.\n\n"
            "## Trạng thái xử lý\n"
            "- Không lấy deadline của task khác để thay thế và không tự đoán dữ kiện thiếu.\n"
            "- Chưa đối chiếu Calendar/reminder theo ngày vì chưa xác định được ngày mục tiêu.\n"
            "- Không đề xuất hoặc tạo reminder khi deadline chưa được xác minh.\n\n"
            "## Cần bổ sung\n"
            "Hãy kiểm tra marker có nằm trong cuộc trò chuyện mà Orbit được bật quyền đọc hay không, "
            "hoặc cung cấp thêm ngữ cảnh chứa cam kết đó."
        )
        final_ai = next(
            (
                message
                for message in reversed(turn_messages)
                if isinstance(message, AIMessage) and message.content
            ),
            None,
        )
        replacement = (
            final_ai.model_copy(update={"content": repaired})
            if final_ai is not None
            else AIMessage(content=repaired)
        )
        return {
            "messages": [replacement],
            "metadata": {
                **state.get("metadata", {}),
                "personal_response_quality": {
                    "passed": False,
                    "repaired": True,
                    "evidence_missing": True,
                    "marker": marker,
                },
            },
        }

    required = _requirements(user_text)
    if not required:
        return {}
    report = _parse_timeline_report(turn_messages)
    if report is None:
        return {}
    final_ai = next(
        (message for message in reversed(turn_messages) if isinstance(message, AIMessage) and message.content),
        None,
    )
    if final_ai is None:
        evidence = _search_evidence(turn_messages)
        report_markdown = report["report_markdown"].strip()
        repaired = (
            f"## Dữ kiện từ tin nhắn cũ\n{evidence}\n\n{report_markdown}"
            if evidence
            else report_markdown
        )
        return {
            "messages": [AIMessage(content=repaired)],
            "metadata": {
                **state.get("metadata", {}),
                "personal_response_quality": {
                    "passed": False,
                    "repaired": True,
                    "missing_answer": True,
                    "missing_requirements": sorted(required),
                },
            },
        }

    answer = str(final_ai.content)
    missing = sorted(requirement for requirement in required if not _answer_covers(answer, requirement))
    raw_tool_echo = bool(
        re.search(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[^\n]*\|\s*(task|reminder|calendar)\s*\|",
            answer,
            flags=re.IGNORECASE,
        )
    )
    if not missing and not raw_tool_echo:
        return {
            "metadata": {
                **state.get("metadata", {}),
                "personal_response_quality": {"passed": True, "requirements": sorted(required)},
            }
        }

    report_markdown = report["report_markdown"].strip()
    evidence = _search_evidence(turn_messages)
    repaired = (
        f"## Dữ kiện từ tin nhắn cũ\n{evidence}\n\n{report_markdown}"
        if evidence
        else report_markdown
    )
    replacement = final_ai.model_copy(update={"content": repaired})
    return {
        "messages": [replacement],
        "metadata": {
            **state.get("metadata", {}),
            "personal_response_quality": {
                "passed": False,
                "repaired": True,
                "raw_tool_echo": raw_tool_echo,
                "missing_requirements": missing,
            },
        },
    }
