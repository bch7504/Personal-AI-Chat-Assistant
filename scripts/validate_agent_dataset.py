"""Validate the canonical user-agent acceptance dataset without extra dependencies."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "eval" / "datasets" / "user_agent_acceptance_v1.json"
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
CASE_ID_RE = re.compile(r"^[A-Z]+(?:-[A-Z]+)?-\d{2}$")
REQUIRED_CAPABILITIES = {
    "tool_routing",
    "conversation_summary",
    "task_extraction",
    "memory_retrieval",
    "memory_isolation",
    "expired_memory_filtering",
    "prompt_injection_resistance",
    "human_in_the_loop",
}


def _duplicates(values: list[str]) -> list[str]:
    return sorted(key for key, count in Counter(values).items() if count > 1)


def _ids(items: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("id", "")) for item in items]


def _require_relative_date(value: Any, path: str, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append(f"{path} phải là object hoặc null")
        return
    date_type = value.get("type")
    if date_type == "offset_days":
        if not isinstance(value.get("days"), int):
            errors.append(f"{path}.days phải là số nguyên")
    elif date_type == "next_weekday":
        weekday = value.get("weekday")
        if not isinstance(weekday, int) or not 0 <= weekday <= 6:
            errors.append(f"{path}.weekday phải nằm trong 0..6")
    else:
        errors.append(f"{path}.type không được hỗ trợ: {date_type!r}")
    for field, upper in (("hour", 23), ("minute", 59)):
        if field in value:
            field_value = value[field]
            if not isinstance(field_value, int) or not 0 <= field_value <= upper:
                errors.append(f"{path}.{field} phải nằm trong 0..{upper}")


def validate_dataset(data: dict[str, Any]) -> list[str]:
    """Return human-readable validation errors; an empty list means valid."""

    errors: list[str] = []
    required_top = {
        "dataset_id",
        "version",
        "schema_version",
        "locale",
        "timezone",
        "evaluation_policy",
        "safety",
        "coverage",
        "seed",
        "evaluation_cases",
    }
    missing = sorted(required_top - data.keys())
    if missing:
        return [f"Thiếu trường top-level: {', '.join(missing)}"]

    if not SEMVER_RE.fullmatch(str(data["version"])):
        errors.append("version phải theo semantic version, ví dụ 1.0.0")
    if data["schema_version"] != "1.0":
        errors.append("schema_version hiện chỉ hỗ trợ 1.0")
    if data["locale"] != "vi-VN":
        errors.append("locale của bộ chuẩn phải là vi-VN")
    if not str(data["timezone"]).strip():
        errors.append("timezone không được rỗng")

    evaluation_policy = data["evaluation_policy"]
    thresholds = evaluation_policy.get("release_thresholds", {})
    required_thresholds = {
        "case_pass_rate",
        "tool_routing_accuracy",
        "task_precision",
        "task_recall",
        "task_due_accuracy",
        "memory_isolation_pass_rate",
        "forbidden_claim_rate",
        "hitl_preconfirmation_side_effect_rate",
    }
    missing_thresholds = sorted(required_thresholds - thresholds.keys())
    if missing_thresholds:
        errors.append(f"Thiếu release threshold: {', '.join(missing_thresholds)}")
    for metric, threshold in thresholds.items():
        if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
            errors.append(f"evaluation_policy.release_thresholds.{metric} phải nằm trong 0..1")
    if not evaluation_policy.get("reported_metrics"):
        errors.append("evaluation_policy.reported_metrics không được rỗng")

    safety = data["safety"]
    if safety.get("synthetic") is not True:
        errors.append("safety.synthetic phải là true")
    if safety.get("contains_real_personal_data") is not False:
        errors.append("Bộ test chuẩn không được chứa dữ liệu cá nhân thật")
    if safety.get("email_domain") != "example.com":
        errors.append("Email seed phải dùng domain dành riêng example.com")
    if safety.get("prohibited_environment") != "production":
        errors.append("Phải cấm seed vào production")

    seed = data["seed"]
    for field in ("users", "workspace", "conversations", "tasks", "memories"):
        if field not in seed:
            errors.append(f"Thiếu seed.{field}")
    if errors:
        return errors

    users = seed["users"]
    workspace = seed["workspace"]
    conversations = seed["conversations"]
    tasks = seed["tasks"]
    memories = seed["memories"]
    cases = data["evaluation_cases"]

    user_ids = set(_ids(users))
    conversation_ids = set(_ids(conversations))
    task_ids = set(_ids(tasks))
    memory_ids = set(_ids(memories))
    for label, values in (
        ("user", _ids(users)),
        ("conversation", _ids(conversations)),
        ("task", _ids(tasks)),
        ("memory", _ids(memories)),
        ("evaluation case", _ids(cases)),
    ):
        duplicates = _duplicates(values)
        if "" in values:
            errors.append(f"Có {label} thiếu id")
        if duplicates:
            errors.append(f"Trùng {label} id: {', '.join(duplicates)}")

    email_locals = [str(user.get("email_local", "")) for user in users]
    if _duplicates(email_locals):
        errors.append("email_local của user phải duy nhất")
    for user in users:
        if not re.fullmatch(r"[a-z0-9._-]+", str(user.get("email_local", ""))):
            errors.append(f"email_local không hợp lệ ở user {user.get('id')}")
        for field in ("display_name", "job_title", "timezone"):
            if not str(user.get(field, "")).strip():
                errors.append(f"users[{user.get('id')}].{field} không được rỗng")

    primary_user = data["coverage"].get("primary_user_id")
    if primary_user not in user_ids:
        errors.append("coverage.primary_user_id không tham chiếu tới user hợp lệ")
    if data["coverage"].get("workspace_id") != workspace.get("id"):
        errors.append("coverage.workspace_id không khớp seed.workspace.id")

    member_ids = [member.get("user_id") for member in workspace.get("members", [])]
    unknown_members = sorted(set(member_ids) - user_ids)
    if unknown_members:
        errors.append(f"Workspace tham chiếu user không tồn tại: {', '.join(unknown_members)}")
    if member_ids.count(primary_user) != 1:
        errors.append("Primary user phải xuất hiện đúng một lần trong workspace")
    if sum(member.get("role") == "owner" for member in workspace.get("members", [])) != 1:
        errors.append("Workspace chuẩn phải có đúng một owner")

    all_message_ids: list[str] = []
    for conversation in conversations:
        cid = conversation.get("id")
        participant_ids = [item.get("user_id") for item in conversation.get("participants", [])]
        if conversation.get("created_by") not in participant_ids:
            errors.append(f"{cid}: người tạo phải là participant")
        if len(participant_ids) != len(set(participant_ids)):
            errors.append(f"{cid}: participant bị trùng")
        if set(participant_ids) - user_ids:
            errors.append(f"{cid}: participant tham chiếu user không tồn tại")
        if conversation.get("type") == "direct" and len(participant_ids) != 2:
            errors.append(f"{cid}: direct conversation phải có đúng 2 participant")
        if conversation.get("type") == "group" and len(participant_ids) < 2:
            errors.append(f"{cid}: group conversation phải có ít nhất 2 participant")
        if conversation.get("ai_policy", {}).get("enabled_by") not in participant_ids:
            errors.append(f"{cid}: ai_policy.enabled_by phải là participant")
        previous_offset: int | None = None
        for message in conversation.get("messages", []):
            mid = str(message.get("id", ""))
            all_message_ids.append(mid)
            if message.get("sender_id") not in participant_ids:
                errors.append(f"{cid}/{mid}: sender không thuộc hội thoại")
            offset = message.get("offset_minutes")
            if not isinstance(offset, int):
                errors.append(f"{cid}/{mid}: offset_minutes phải là số nguyên")
            elif previous_offset is not None and offset <= previous_offset:
                errors.append(f"{cid}: messages phải tăng dần theo offset_minutes")
            previous_offset = offset if isinstance(offset, int) else previous_offset
            if not str(message.get("content", "")).strip():
                errors.append(f"{cid}/{mid}: content không được rỗng")
    duplicate_messages = _duplicates(all_message_ids)
    if duplicate_messages:
        errors.append(f"Trùng message id: {', '.join(duplicate_messages)}")

    for task in tasks:
        tid = task.get("id")
        if task.get("owner_id") not in user_ids:
            errors.append(f"{tid}: owner_id không hợp lệ")
        if task.get("conversation_id") not in conversation_ids | {None}:
            errors.append(f"{tid}: conversation_id không hợp lệ")
        if task.get("priority") not in {"High", "Medium", "Low"}:
            errors.append(f"{tid}: priority không hợp lệ")
        if task.get("status") not in {"suggested", "pending", "in_progress", "completed", "dismissed", "invalidated"}:
            errors.append(f"{tid}: status không hợp lệ")
        _require_relative_date(task.get("due"), f"tasks[{tid}].due", errors)

    valid_memory_types = {"preference", "relationship", "episodic", "semantic"}
    for memory in memories:
        mid = memory.get("id")
        if memory.get("owner_id") not in user_ids:
            errors.append(f"{mid}: owner_id không hợp lệ")
        if memory.get("memory_type") not in valid_memory_types:
            errors.append(f"{mid}: memory_type không hợp lệ")
        confidence = memory.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            errors.append(f"{mid}: confidence phải nằm trong 0..1")
        _require_relative_date(memory.get("expires"), f"memories[{mid}].expires", errors)

    found_capabilities = {case.get("capability") for case in cases}
    declared_capabilities = set(data["coverage"].get("capabilities", []))
    missing_coverage = REQUIRED_CAPABILITIES - found_capabilities
    if missing_coverage:
        errors.append(f"Thiếu evaluation case cho: {', '.join(sorted(missing_coverage))}")
    if not found_capabilities <= declared_capabilities:
        errors.append("Có capability trong evaluation_cases chưa được khai báo ở coverage")
    if not declared_capabilities <= found_capabilities:
        errors.append("Có capability trong coverage chưa có evaluation case")

    for case in cases:
        case_id = case.get("id")
        if not CASE_ID_RE.fullmatch(str(case_id)):
            errors.append(f"Case id không đúng chuẩn: {case_id}")
        if case.get("actor_id") not in user_ids:
            errors.append(f"{case_id}: actor_id không hợp lệ")
        if case.get("conversation_id") not in conversation_ids | {None}:
            errors.append(f"{case_id}: conversation_id không hợp lệ")
        if not str(case.get("prompt", "")).strip():
            errors.append(f"{case_id}: prompt không được rỗng")
        expected = case.get("expected")
        if not isinstance(expected, dict) or not expected:
            errors.append(f"{case_id}: expected phải là object không rỗng")
            continue
        for memory_id in expected.get("must_include_memory_ids", []):
            if memory_id not in memory_ids:
                errors.append(f"{case_id}: expected memory không tồn tại: {memory_id}")
        for memory_id in expected.get("must_exclude_memory_ids", []):
            if memory_id not in memory_ids:
                errors.append(f"{case_id}: excluded memory không tồn tại: {memory_id}")
        for task_id in expected.get("must_include_seed_task_ids", []):
            if task_id not in task_ids:
                errors.append(f"{case_id}: expected task không tồn tại: {task_id}")
        for task_id in expected.get("must_exclude_seed_task_ids", []):
            if task_id not in task_ids:
                errors.append(f"{case_id}: excluded task không tồn tại: {task_id}")
        for index, task in enumerate(expected.get("tasks", [])):
            _require_relative_date(task.get("due"), f"cases[{case_id}].tasks[{index}].due", errors)

    if len(users) != 4:
        errors.append("Bộ chuẩn phải có đúng 4 persona")
    if len(cases) < 12:
        errors.append("Bộ chuẩn cần ít nhất 12 evaluation cases")
    if not any(memory.get("owner_id") != primary_user for memory in memories):
        errors.append("Thiếu memory của user khác để kiểm tra isolation")
    if not any((memory.get("expires") or {}).get("days", 0) < 0 for memory in memories):
        errors.append("Thiếu memory đã hết hạn để kiểm tra expiry")

    return errors


def load_and_validate(path: Path) -> tuple[dict[str, Any], list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"Không đọc được dataset: {exc}"]
    if not isinstance(data, dict):
        return {}, ["Dataset top-level phải là JSON object"]
    return data, validate_dataset(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", nargs="?", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()

    data, errors = load_and_validate(args.dataset)
    if errors:
        print(f"INVALID: {args.dataset}")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "VALID: "
        f"{data['dataset_id']} v{data['version']} | "
        f"{len(data['seed']['users'])} users | "
        f"{len(data['seed']['conversations'])} conversations | "
        f"{len(data['evaluation_cases'])} cases"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
