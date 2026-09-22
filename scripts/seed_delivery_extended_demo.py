"""Add a larger, idempotent Product Delivery dataset on top of the base demo.

The base fixture stays intentionally small and predictable.  This extension is
for manual multi-agent evaluation: it adds task history, mixed checkpoint
states, deeper dependencies, and decision conflicts without creating additional
workspaces or weakening any authorization scope.
"""

# ruff: noqa: E402 -- direct execution bootstraps the repository root below.

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import seed_delivery_demo as base_seed
from src.config import get_settings
from src.db.models import (
    AgentWorkspace,
    Conversation,
    DeliveryCheckpointTask,
    DeliveryDecisionRecord,
    DeliveryDependencyRecord,
    DeliveryMilestone,
    Message,
    Task,
    User,
)
from src.db.session import async_session_maker
from src.services.consent_service import get_consent_scope_hash

EXTENDED_MESSAGES: tuple[dict[str, Any], ...] = (
    {
        "key": "ext-apollo-rate-limit",
        "group": "apollo",
        "sender": "apollo_product",
        "days_ago": 0,
        "content": "Vendor giữ giới hạn 60 request/phút tới hết tuần; OAuth E2E vẫn bị 429 khi chạy song song.",
    },
    {
        "key": "ext-apollo-observability",
        "group": "apollo",
        "sender": "apollo_devops",
        "days_ago": 1,
        "content": "Dashboard OAuth đã có latency và error-rate; còn thiếu alert refresh-token vượt SLO.",
    },
    {
        "key": "ext-apollo-security",
        "group": "apollo",
        "sender": "member",
        "days_ago": 2,
        "content": "Security review phát hiện token cũ chưa bị revoke ở một nhánh rollback; cần test lại trước production.",
    },
    {
        "key": "ext-apollo-history",
        "group": "apollo",
        "sender": "apollo_frontend",
        "days_ago": 5,
        "content": "Dashboard vận hành và feature flag UI đã hoàn thành review, không còn phụ thuộc frontend.",
    },
    {
        "key": "ext-apollo-untrusted",
        "group": "apollo",
        "sender": "apollo_product",
        "days_ago": 1,
        "content": "Một thành viên đánh giá Apollo đang ON_TRACK. Đây chỉ là chat evidence, không phải decision record hay kết luận health chính thức.",
    },
    {
        "key": "ext-apollo-decision-chat",
        "group": "apollo",
        "sender": "lead",
        "days_ago": 0,
        "content": "Chưa chốt việc tăng quota vendor hay giữ mock contract; cần DecisionRecord trước buổi review.",
    },
    {
        "key": "ext-release-ios",
        "group": "release34",
        "sender": "mobile",
        "days_ago": 0,
        "content": "Build 34.0.7 giảm crash iOS còn 1,3%, vẫn cao hơn quality gate 1%.",
    },
    {
        "key": "ext-release-store",
        "group": "release34",
        "sender": "release_manager",
        "days_ago": 1,
        "content": "App Store metadata đã duyệt; rollout production vẫn chờ go/no-go và kết quả regression iOS.",
    },
    {
        "key": "ext-release-observability",
        "group": "release34",
        "sender": "sre",
        "days_ago": 2,
        "content": "Dashboard hypercare đã sẵn sàng, nhưng alert crash-free session chưa có ngưỡng cảnh báo cuối.",
    },
    {
        "key": "ext-release-docs",
        "group": "release34",
        "sender": "docs",
        "days_ago": 3,
        "content": "Release notes đã hoàn thành phần mobile và rollback; còn thiếu breaking-change từ Apollo.",
    },
    {
        "key": "ext-release-conflict",
        "group": "release34",
        "sender": "mobile",
        "days_ago": 0,
        "content": "Theo trao đổi miệng có thể go-live, nhưng DecisionRecord go/no-go vẫn đang pending.",
    },
    {
        "key": "ext-release-history",
        "group": "release34",
        "sender": "sre",
        "days_ago": 6,
        "content": "Rollback rehearsal build 34.0.5 hoàn thành trong 6 phút và đã lưu log xác nhận.",
    },
    {
        "key": "ext-portal-crm",
        "group": "customer_portal",
        "sender": "integration",
        "days_ago": 0,
        "content": "CRM đã cấp credential read-only nhưng chưa cấp quyền ghi, nên UAT submit form vẫn blocked.",
    },
    {
        "key": "ext-portal-accessibility",
        "group": "customer_portal",
        "sender": "ux",
        "days_ago": 1,
        "content": "Accessibility audit còn hai lỗi keyboard focus ở onboarding; contrast đã đạt AA.",
    },
    {
        "key": "ext-portal-analytics",
        "group": "customer_portal",
        "sender": "analyst",
        "days_ago": 2,
        "content": "Analytics event schema đã chốt 18/20 event; hai event consent cần privacy review.",
    },
    {
        "key": "ext-portal-tests",
        "group": "customer_portal",
        "sender": "delivery_tester",
        "days_ago": 3,
        "content": "Smoke suite pass 26/30; bốn case submit CRM chờ credential ghi.",
    },
    {
        "key": "ext-portal-scope-chat",
        "group": "customer_portal",
        "sender": "lead",
        "days_ago": 0,
        "content": "Đề xuất tách onboarding khỏi tra cứu đơn hàng chưa được phê duyệt; không coi chat này là quyết định chính thức.",
    },
    {
        "key": "ext-portal-history",
        "group": "customer_portal",
        "sender": "ux",
        "days_ago": 7,
        "content": "Design system và responsive shell đã hoàn thành từ tuần trước, không còn blocker UI nền.",
    },
)


EXTENDED_TASKS: tuple[dict[str, Any], ...] = (
    # Apollo Platform: complete history, active work, and two independent blockers.
    {"key": "ext-apollo-callback", "group": "apollo", "message": "ext-apollo-history", "title": "Hoàn thành OAuth callback contract v2", "status": "completed", "priority": "High", "owner": "member", "due_days": -5, "created_days": 16, "started_days": 13, "completed_days": 7, "requires_review": True, "submission_note": "Contract tests và rollback proof đã hoàn thành.", "evidence_urls": ("https://github.example/apollo/pull/142",), "submitted_days": 8, "reviewed_days": 7, "review_note": "Lead đã xác minh evidence."},
    {"key": "ext-apollo-feature-flag", "group": "apollo", "message": "ext-apollo-history", "title": "Hoàn thành feature flag OAuth trên dashboard", "status": "completed", "priority": "Medium", "owner": "apollo_frontend", "due_days": -3, "created_days": 14, "started_days": 11, "completed_days": 5},
    {"key": "ext-apollo-rollback-proof", "group": "apollo", "message": "ext-apollo-security", "title": "Xác nhận revoke token trong rollback path", "status": "blocked", "priority": "High", "owner": "member", "due_days": 1, "created_days": 9, "started_days": 6, "blocked_reason": "Token cũ chưa bị revoke trong rollback test"},
    {"key": "ext-apollo-rate-limit-mitigation", "group": "apollo", "message": "ext-apollo-rate-limit", "title": "Triển khai backoff cho vendor rate limit", "status": "in_progress", "priority": "High", "owner": "member", "due_days": 2, "created_days": 8, "started_days": 5},
    {"key": "ext-apollo-load-test", "group": "apollo", "message": "ext-apollo-rate-limit", "title": "Chạy OAuth load test 200 phiên đồng thời", "status": "blocked", "priority": "High", "owner": "apollo_devops", "due_days": -1, "created_days": 7, "started_days": 4, "blocked_reason": "Vendor quota không đủ cho kịch bản tải"},
    {"key": "ext-apollo-alert", "group": "apollo", "message": "ext-apollo-observability", "title": "Bổ sung alert refresh-token vượt SLO", "status": "in_progress", "priority": "Medium", "owner": "apollo_devops", "due_days": 3, "created_days": 6, "started_days": 2},
    {"key": "ext-apollo-security-signoff", "group": "apollo", "message": "ext-apollo-security", "title": "Chuẩn bị security sign-off OAuth", "status": "pending", "priority": "High", "owner": "apollo_product", "due_days": 4, "created_days": 5},
    {"key": "ext-apollo-runbook", "group": "apollo", "message": "ext-apollo-observability", "title": "Hoàn thành runbook sự cố OAuth", "status": "completed", "priority": "Medium", "owner": "apollo_devops", "due_days": -1, "created_days": 10, "started_days": 8, "completed_days": 2},
    {"key": "ext-apollo-quota-decision", "group": "apollo", "message": "ext-apollo-decision-chat", "title": "Chuẩn bị dữ liệu quyết định quota vendor", "status": "suggested", "priority": "High", "owner": "apollo_product", "due_days": 1, "created_days": 3},
    {"key": "ext-apollo-cleanup", "group": "apollo", "message": "ext-apollo-history", "title": "Dọn feature flag thử nghiệm cũ", "status": "dismissed", "priority": "Low", "owner": "apollo_frontend", "due_days": 8, "created_days": 12},

    # Release 34: a go/no-go path with completed proof and unresolved mobile risk.
    {"key": "ext-release-android-smoke", "group": "release34", "message": "ext-release-history", "title": "Hoàn thành Android production smoke", "status": "completed", "priority": "High", "owner": "mobile", "due_days": -4, "created_days": 13, "started_days": 10, "completed_days": 6},
    {"key": "ext-release-store-metadata", "group": "release34", "message": "ext-release-store", "title": "Hoàn thành App Store metadata", "status": "completed", "priority": "Medium", "owner": "release_manager", "due_days": -2, "created_days": 11, "started_days": 9, "completed_days": 3},
    {"key": "ext-release-crash-symbols", "group": "release34", "message": "ext-release-ios", "title": "Đối chiếu symbol crash iOS build 34.0.7", "status": "in_progress", "priority": "High", "owner": "mobile", "due_days": 1, "created_days": 6, "started_days": 3},
    {"key": "ext-release-crash-threshold", "group": "release34", "message": "ext-release-ios", "title": "Đưa crash-free session vượt quality gate", "status": "blocked", "priority": "High", "owner": "mobile", "due_days": 1, "created_days": 8, "started_days": 6, "blocked_reason": "Crash rate 1,3% vẫn cao hơn ngưỡng 1%"},
    {"key": "ext-release-hypercare-alert", "group": "release34", "message": "ext-release-observability", "title": "Chốt ngưỡng alert hypercare", "status": "submitted", "priority": "High", "owner": "sre", "due_days": 2, "created_days": 5, "started_days": 3, "requires_review": True, "submission_note": "Đã cấu hình threshold và chạy thử cảnh báo staging.", "evidence_urls": ("https://observability.example/reports/release-34",), "submitted_days": 1},
    {"key": "ext-release-breaking-change", "group": "release34", "message": "ext-release-docs", "title": "Bổ sung breaking-change Apollo vào release notes", "status": "blocked", "priority": "Medium", "owner": "docs", "due_days": 0, "created_days": 5, "started_days": 2, "blocked_reason": "Chưa nhận danh sách breaking-change từ Apollo"},
    {"key": "ext-release-rollback-evidence", "group": "release34", "message": "ext-release-history", "title": "Lưu bằng chứng rollback rehearsal", "status": "completed", "priority": "High", "owner": "sre", "due_days": -3, "created_days": 12, "started_days": 8, "completed_days": 6},
    {"key": "ext-release-go-no-go-pack", "group": "release34", "message": "ext-release-conflict", "title": "Hoàn thiện go/no-go evidence pack", "status": "in_progress", "priority": "High", "owner": "release_manager", "due_days": 1, "created_days": 4, "started_days": 2},
    {"key": "ext-release-hypercare-roster", "group": "release34", "message": "ext-release-observability", "title": "Xác nhận roster hypercare 48 giờ", "status": "pending", "priority": "Medium", "owner": "sre", "due_days": 3, "created_days": 3},
    {"key": "ext-release-old-build", "group": "release34", "message": "ext-release-history", "title": "Kiểm tra lại build 34.0.4 đã superseded", "status": "invalidated", "priority": "Low", "owner": "release_manager", "due_days": -5, "created_days": 15, "invalidated_reason": "Build 34.0.4 đã được thay bởi 34.0.7"},

    # Customer Portal: UAT, accessibility, analytics, and scope decision.
    {"key": "ext-portal-design-shell", "group": "customer_portal", "message": "ext-portal-history", "title": "Hoàn thành responsive portal shell", "status": "completed", "priority": "Medium", "owner": "ux", "due_days": -6, "created_days": 18, "started_days": 14, "completed_days": 9},
    {"key": "ext-portal-contrast", "group": "customer_portal", "message": "ext-portal-accessibility", "title": "Hoàn thành contrast audit AA", "status": "completed", "priority": "Medium", "owner": "ux", "due_days": -2, "created_days": 10, "started_days": 8, "completed_days": 4},
    {"key": "ext-portal-keyboard", "group": "customer_portal", "message": "ext-portal-accessibility", "title": "Sửa keyboard focus onboarding", "status": "in_progress", "priority": "High", "owner": "ux", "due_days": 2, "created_days": 7, "started_days": 4},
    {"key": "ext-portal-crm-write", "group": "customer_portal", "message": "ext-portal-crm", "title": "Nhận quyền ghi CRM UAT", "status": "blocked", "priority": "High", "owner": "integration", "due_days": -1, "created_days": 8, "started_days": 5, "blocked_reason": "CRM mới cấp credential read-only"},
    {"key": "ext-portal-submit-smoke", "group": "customer_portal", "message": "ext-portal-tests", "title": "Chạy smoke test submit CRM", "status": "blocked", "priority": "High", "owner": "delivery_tester", "due_days": 1, "created_days": 6, "started_days": 3, "blocked_reason": "Chờ quyền ghi CRM UAT"},
    {"key": "ext-portal-analytics-schema", "group": "customer_portal", "message": "ext-portal-analytics", "title": "Hoàn thiện analytics event schema", "status": "in_progress", "priority": "Medium", "owner": "analyst", "due_days": 3, "created_days": 7, "started_days": 2},
    {"key": "ext-portal-privacy-review", "group": "customer_portal", "message": "ext-portal-analytics", "title": "Review consent cho analytics events", "status": "changes_requested", "priority": "High", "owner": "analyst", "due_days": 2, "created_days": 4, "started_days": 3, "requires_review": True, "submission_note": "Đã lập mapping consent cho các event chính.", "evidence_urls": ("https://docs.example/portal/analytics-consent",), "submitted_days": 2, "reviewed_days": 1, "review_note": "Bổ sung retention policy cho event chứa định danh."},
    {"key": "ext-portal-support-playbook", "group": "customer_portal", "message": "ext-portal-tests", "title": "Soạn support playbook cho rollout", "status": "suggested", "priority": "Low", "owner": "delivery_tester", "due_days": 5, "created_days": 3},
    {"key": "ext-portal-scope-pack", "group": "customer_portal", "message": "ext-portal-scope-chat", "title": "Chuẩn bị impact pack cho quyết định scope", "status": "pending", "priority": "High", "owner": "analyst", "due_days": 1, "created_days": 3},
    {"key": "ext-portal-legacy-copy", "group": "customer_portal", "message": "ext-portal-history", "title": "Import nội dung onboarding cũ", "status": "dismissed", "priority": "Low", "owner": "ux", "due_days": 10, "created_days": 13},
)


EXTENDED_MILESTONES: tuple[dict[str, Any], ...] = (
    {"key": "ext-apollo-foundation", "group": "apollo", "title": "Apollo OAuth foundation", "status": "completed", "owner": "lead", "due_days": -3, "quality": "accepted", "tasks": ("ext-apollo-callback", "ext-apollo-feature-flag", "ext-apollo-runbook")},
    {"key": "ext-apollo-hardening", "group": "apollo", "title": "Apollo production hardening", "status": "blocked", "owner": "apollo_product", "due_days": 2, "blocked_reason": "Rollback proof và load test chưa hoàn thành", "tasks": ("ext-apollo-rollback-proof", "ext-apollo-load-test", "ext-apollo-security-signoff")},
    {"key": "ext-release-freeze", "group": "release34", "title": "Release 34 freeze readiness", "status": "blocked", "owner": "release_manager", "due_days": -1, "blocked_reason": "Crash gate và release notes chưa hoàn thành", "tasks": ("ext-release-crash-threshold", "ext-release-breaking-change", "ext-release-go-no-go-pack")},
    {"key": "ext-release-operations", "group": "release34", "title": "Release 34 operations readiness", "status": "in_progress", "owner": "sre", "due_days": 3, "quality": "rejected", "tasks": ("ext-release-rollback-evidence", "ext-release-hypercare-alert", "ext-release-hypercare-roster")},
    {"key": "ext-portal-experience", "group": "customer_portal", "title": "Portal experience acceptance", "status": "in_progress", "owner": "ux", "due_days": 2, "tasks": ("ext-portal-design-shell", "ext-portal-contrast")},
    {"key": "ext-portal-uat", "group": "customer_portal", "title": "Customer Portal UAT readiness", "status": "blocked", "owner": "analyst", "due_days": 4, "blocked_reason": "CRM write credential chưa được cấp", "tasks": ("ext-portal-crm-write", "ext-portal-submit-smoke", "ext-portal-privacy-review")},
)


EXTENDED_DEPENDENCIES: tuple[dict[str, Any], ...] = (
    {"key": "ext-dep-apollo-quota-load", "group": "apollo", "title": "Vendor quota trước OAuth load test", "status": "blocked", "owner": "apollo_product", "predecessor": "ext-apollo-rate-limit-mitigation", "successor": "ext-apollo-load-test", "due_days": 1},
    {"key": "ext-dep-apollo-rollback-signoff", "group": "apollo", "title": "Rollback proof trước security sign-off", "status": "blocked", "owner": "member", "predecessor": "ext-apollo-rollback-proof", "successor": "ext-apollo-security-signoff", "due_days": 2},
    {"key": "ext-dep-apollo-alert-release", "group": "apollo", "title": "OAuth alert trước production hardening", "status": "open", "owner": "apollo_devops", "predecessor": "ext-apollo-alert", "successor": "ext-apollo-security-signoff", "due_days": 3},
    {"key": "ext-dep-release-crash-gonogo", "group": "release34", "title": "Crash gate trước go/no-go pack", "status": "blocked", "owner": "mobile", "predecessor": "ext-release-crash-threshold", "successor": "ext-release-go-no-go-pack", "due_days": 1},
    {"key": "ext-dep-release-notes-gonogo", "group": "release34", "title": "Breaking-change trước go/no-go", "status": "blocked", "owner": "docs", "predecessor": "ext-release-breaking-change", "successor": "ext-release-go-no-go-pack", "due_days": 1},
    {"key": "ext-dep-release-alert-hypercare", "group": "release34", "title": "Alert threshold trước xác nhận hypercare", "status": "open", "owner": "sre", "predecessor": "ext-release-hypercare-alert", "successor": "ext-release-hypercare-roster", "due_days": 2},
    {"key": "ext-dep-portal-credential-smoke", "group": "customer_portal", "title": "CRM write credential trước submit smoke", "status": "blocked", "owner": "integration", "predecessor": "ext-portal-crm-write", "successor": "ext-portal-submit-smoke", "due_days": 1},
    {"key": "ext-dep-portal-privacy-analytics", "group": "customer_portal", "title": "Privacy review trước chốt analytics schema", "status": "open", "owner": "analyst", "predecessor": "ext-portal-privacy-review", "successor": "ext-portal-analytics-schema", "due_days": 2},
    {"key": "ext-dep-portal-smoke-scope", "group": "customer_portal", "title": "UAT smoke trước quyết định scope", "status": "blocked", "owner": "delivery_tester", "predecessor": "ext-portal-submit-smoke", "successor": "ext-portal-scope-pack", "due_days": 2},
)


EXTENDED_DECISIONS: tuple[dict[str, Any], ...] = (
    {"key": "ext-decision-apollo-quota", "group": "apollo", "title": "Mua thêm quota vendor hay giữ mock contract", "status": "pending", "owner": "lead", "due_days": 1, "options": ("Mua quota tạm thời", "Giữ mock contract", "Giảm concurrency test")},
    {"key": "ext-decision-apollo-token", "group": "apollo", "title": "Chọn cơ chế revoke token rollback", "status": "decided", "owner": "lead", "due_days": -2, "options": ("Revoke đồng bộ", "Revoke qua queue"), "outcome": "Revoke đồng bộ trong rollback path và ghi audit."},
    {"key": "ext-decision-release-rollout", "group": "release34", "title": "Chọn staged rollout cho Release 34", "status": "pending", "owner": "release_manager", "due_days": 1, "options": ("5%-25%-100%", "10%-50%-100%", "Hoãn rollout")},
    {"key": "ext-decision-release-build", "group": "release34", "title": "Dùng build 34.0.4 cho production", "status": "superseded", "owner": "release_manager", "due_days": -4, "options": ("Dùng 34.0.4", "Tạo build mới")},
    {"key": "ext-decision-portal-scope", "group": "customer_portal", "title": "Tách onboarding khỏi tra cứu đơn hàng", "status": "pending", "owner": "lead", "due_days": 1, "options": ("Tách onboarding", "Giữ chung release", "Feature flag onboarding")},
    {"key": "ext-decision-portal-analytics", "group": "customer_portal", "title": "Ẩn analytics events chưa có consent", "status": "decided", "owner": "analyst", "due_days": -1, "options": ("Ẩn event", "Thu thập tạm thời"), "outcome": "Ẩn hai event cho tới khi privacy review hoàn thành."},
)


def validate_extended_fixture() -> None:
    message_keys = {item["key"] for item in EXTENDED_MESSAGES}
    task_keys = {item["key"] for item in EXTENDED_TASKS}
    if len(message_keys) != len(EXTENDED_MESSAGES) or len(task_keys) != len(EXTENDED_TASKS):
        raise ValueError("Extended Delivery fixture keys must be unique")
    for message in EXTENDED_MESSAGES:
        if message["sender"] not in base_seed.GROUP_PARTICIPANTS[message["group"]]:
            raise ValueError(f"Extended message sender is outside group: {message['key']}")
    for task in EXTENDED_TASKS:
        if task["message"] not in message_keys:
            raise ValueError(f"Extended task has no source message: {task['key']}")
        if task["owner"] not in base_seed.GROUP_PARTICIPANTS[task["group"]]:
            raise ValueError(f"Extended task owner is outside group: {task['key']}")
    for milestone in EXTENDED_MILESTONES:
        if not set(milestone["tasks"]).issubset(task_keys):
            raise ValueError(f"Extended milestone references an unknown task: {milestone['key']}")
    for dependency in EXTENDED_DEPENDENCIES:
        if {dependency["predecessor"], dependency["successor"]} - task_keys:
            raise ValueError(f"Extended dependency references an unknown task: {dependency['key']}")


async def _upsert(session, model, identity: str, values: dict[str, Any]):
    row = await session.get(model, identity)
    if row is None:
        row = model(id=identity, **values)
        session.add(row)
    else:
        for field, value in values.items():
            setattr(row, field, value)
    return row


async def seed_extended_demo() -> dict[str, Any]:
    validate_extended_fixture()
    settings = get_settings()
    if settings.app_env == "production":
        raise RuntimeError("Refusing to seed synthetic Delivery data in APP_ENV=production")

    await base_seed.seed_demo()
    now = datetime.now(UTC).replace(microsecond=0)
    async with async_session_maker() as session:
        delivery = (
            await session.execute(select(AgentWorkspace).where(AgentWorkspace.key == "delivery-demo"))
        ).scalar_one()
        users: dict[str, User] = {}
        for key, (email, *_rest) in base_seed.DEMO_USERS.items():
            users[key] = (await session.execute(select(User).where(User.email == email))).scalar_one()
        conversations = {
            key: await session.get(Conversation, base_seed.stable_id(f"conversation:{key}"))
            for key in base_seed.LINKED_GROUPS
        }
        if any(row is None for row in conversations.values()):
            raise RuntimeError("Base Delivery conversations are unavailable")
        consent_hashes = {
            key: await get_consent_scope_hash(session, conversation.id)
            for key, conversation in conversations.items()
        }

        message_rows: dict[str, Message] = {}
        for spec in EXTENDED_MESSAGES:
            message_rows[spec["key"]] = await _upsert(
                session,
                Message,
                base_seed.stable_id(f"message:{spec['key']}"),
                {
                    "conversation_id": conversations[spec["group"]].id,
                    "sender_id": users[spec["sender"]].id,
                    "content": spec["content"],
                    "created_at": now - timedelta(days=spec["days_ago"]),
                },
            )
        await session.flush()

        task_rows: dict[str, Task] = {}
        for spec in EXTENDED_TASKS:
            status = spec["status"]
            created_at = now - timedelta(days=spec["created_days"])
            started_at = (
                now - timedelta(days=spec["started_days"])
                if spec.get("started_days") is not None
                else None
            )
            completed_at = (
                now - timedelta(days=spec["completed_days"])
                if spec.get("completed_days") is not None
                else None
            )
            source_message = message_rows[spec["message"]]
            task_rows[spec["key"]] = await _upsert(
                session,
                Task,
                base_seed.stable_id(f"task:{spec['key']}"),
                {
                    "workspace_id": delivery.organization_workspace_id,
                    "agent_workspace_id": delivery.id,
                    "owner_id": users[spec["owner"]].id,
                    "conversation_id": conversations[spec["group"]].id,
                    "title": spec["title"],
                    "due_at": now + timedelta(days=spec["due_days"]),
                    "priority": spec["priority"],
                    "status": status,
                    "blocked_reason": spec.get("blocked_reason"),
                    "source": "ai_extracted",
                    "source_message_ids": [source_message.id],
                    "source_sender_id": source_message.sender_id,
                    "consent_scope_hash": consent_hashes[spec["group"]],
                    "invalidated_reason": spec.get("invalidated_reason"),
                    "requires_review": spec.get("requires_review", False),
                    "submission_note": spec.get("submission_note"),
                    "evidence_urls": list(spec.get("evidence_urls", ())),
                    "submitted_by_user_id": (
                        users[spec["owner"]].id if spec.get("submitted_days") is not None else None
                    ),
                    "submitted_at": (
                        now - timedelta(days=spec["submitted_days"])
                        if spec.get("submitted_days") is not None
                        else None
                    ),
                    "reviewed_by_user_id": (
                        users["lead"].id if spec.get("reviewed_days") is not None else None
                    ),
                    "reviewed_at": (
                        now - timedelta(days=spec["reviewed_days"])
                        if spec.get("reviewed_days") is not None
                        else None
                    ),
                    "review_note": spec.get("review_note"),
                    "created_at": created_at,
                    "updated_at": completed_at or started_at or now,
                    "started_at": started_at,
                    "completed_at": completed_at,
                },
            )
        await session.flush()

        milestone_rows: dict[str, DeliveryMilestone] = {}
        for spec in EXTENDED_MILESTONES:
            quality = spec.get("quality", "pending")
            milestone_rows[spec["key"]] = await _upsert(
                session,
                DeliveryMilestone,
                base_seed.stable_id(f"milestone:{spec['key']}"),
                {
                    "workspace_id": delivery.organization_workspace_id,
                    "agent_workspace_id": delivery.id,
                    "conversation_id": conversations[spec["group"]].id,
                    "title": spec["title"],
                    "status": spec["status"],
                    "owner_id": users[spec["owner"]].id,
                    "due_at": now + timedelta(days=spec["due_days"]),
                    "blocked_reason": spec.get("blocked_reason"),
                    "plan_key": "delivery-extended-plan",
                    "quality_review_status": quality,
                    "quality_review_note": (
                        "Lead đã xác nhận checkpoint đạt yêu cầu."
                        if quality == "accepted"
                        else "Lead yêu cầu hoàn thiện tiêu chí vận hành."
                        if quality == "rejected"
                        else None
                    ),
                    "quality_reviewed_by_user_id": users["lead"].id if quality != "pending" else None,
                    "quality_reviewed_at": now - timedelta(hours=8) if quality != "pending" else None,
                    "updated_at": now,
                },
            )
        await session.flush()

        for spec in EXTENDED_MILESTONES:
            milestone = milestone_rows[spec["key"]]
            for task_key in spec["tasks"]:
                task = task_rows[task_key]
                await _upsert(
                    session,
                    DeliveryCheckpointTask,
                    base_seed.stable_id(f"checkpoint-task:{spec['key']}:{task.id}"),
                    {
                        "workspace_id": delivery.organization_workspace_id,
                        "agent_workspace_id": delivery.id,
                        "conversation_id": conversations[spec["group"]].id,
                        "milestone_id": milestone.id,
                        "task_id": task.id,
                        "required": True,
                        "created_by_user_id": users["lead"].id,
                    },
                )

        for spec in EXTENDED_DEPENDENCIES:
            await _upsert(
                session,
                DeliveryDependencyRecord,
                base_seed.stable_id(f"dependency:{spec['key']}"),
                {
                    "workspace_id": delivery.organization_workspace_id,
                    "agent_workspace_id": delivery.id,
                    "conversation_id": conversations[spec["group"]].id,
                    "title": spec["title"],
                    "status": spec["status"],
                    "owner_id": users[spec["owner"]].id,
                    "predecessor_task_id": task_rows[spec["predecessor"]].id,
                    "successor_task_id": task_rows[spec["successor"]].id,
                    "due_at": now + timedelta(days=spec["due_days"]),
                    "created_by_user_id": users["lead"].id,
                    "updated_at": now,
                },
            )

        for spec in EXTENDED_DECISIONS:
            await _upsert(
                session,
                DeliveryDecisionRecord,
                base_seed.stable_id(f"decision:{spec['key']}"),
                {
                    "workspace_id": delivery.organization_workspace_id,
                    "agent_workspace_id": delivery.id,
                    "conversation_id": conversations[spec["group"]].id,
                    "title": spec["title"],
                    "status": spec["status"],
                    "owner_id": users[spec["owner"]].id,
                    "due_at": now + timedelta(days=spec["due_days"]),
                    "options": list(spec["options"]),
                    "outcome": spec.get("outcome"),
                    "created_by_user_id": users["lead"].id,
                    "updated_at": now,
                },
            )

        await session.commit()
        counts = {
            "tasks": await session.scalar(select(func.count(Task.id)).where(Task.agent_workspace_id == delivery.id)),
            "milestones": await session.scalar(select(func.count(DeliveryMilestone.id)).where(DeliveryMilestone.agent_workspace_id == delivery.id)),
            "dependencies": await session.scalar(select(func.count(DeliveryDependencyRecord.id)).where(DeliveryDependencyRecord.agent_workspace_id == delivery.id)),
            "decisions": await session.scalar(select(func.count(DeliveryDecisionRecord.id)).where(DeliveryDecisionRecord.agent_workspace_id == delivery.id)),
        }
    return {
        "agent_workspace_id": delivery.id,
        "extended_messages_added": len(EXTENDED_MESSAGES),
        "extended_tasks_added": len(EXTENDED_TASKS),
        "extended_milestones_added": len(EXTENDED_MILESTONES),
        "extended_dependencies_added": len(EXTENDED_DEPENDENCIES),
        "extended_decisions_added": len(EXTENDED_DECISIONS),
        "totals": counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Create/update the extended fixture")
    args = parser.parse_args()
    if not args.apply:
        print("Preview only. Run with --apply to seed the extended Product Delivery fixture.")
        print(
            f"Adds {len(EXTENDED_TASKS)} tasks, {len(EXTENDED_MESSAGES)} messages, "
            f"{len(EXTENDED_MILESTONES)} milestones, {len(EXTENDED_DEPENDENCIES)} dependencies, "
            f"and {len(EXTENDED_DECISIONS)} decisions."
        )
        return 0
    manifest = asyncio.run(seed_extended_demo())
    print(manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
