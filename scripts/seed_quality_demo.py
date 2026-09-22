"""Create idempotent QA Agent Workspace demo data for local UI testing.

The fixture first ensures the Product Delivery demo exists, then creates a
separate QA membership roster, QA-owned groups, source-backed quality tasks and
one Delivery-to-QA release handoff. Accounts are assigned to exactly one active
Agent Workspace; organization-only accounts remain unassigned by design.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.seed_delivery_demo import (  # noqa: E402
    DEMO_PASSWORD,
    _upsert_by_id,
    _upsert_participant,
)
from scripts.seed_delivery_demo import (
    seed_demo as seed_delivery_demo,
)
from src.config import get_settings
from src.db.models import (
    AgentWorkspace,
    AgentWorkspaceConversation,
    AgentWorkspaceMembership,
    Conversation,
    Message,
    ReleaseCandidate,
    Task,
    User,
    Workspace,
)
from src.db.session import async_session_maker
from src.services.agent_workspace_service import add_agent_workspace_member
from src.services.consent_service import get_consent_scope_hash

QA_NAMESPACE = "quality-demo"
QA_RELEASE_ID = "R-DEMO"
QA_MEMBER_EMAILS = {
    "lead": "delivery-demo-huong@example.com",
    "automation": "qa-demo-automation@example.com",
    "manual": "qa-demo-manual@example.com",
    "security": "qa-demo-security@example.com",
    "performance": "qa-demo-performance@example.com",
}
QA_GROUPS = {
    "release": "QA Release R-DEMO",
    "non_functional": "QA Security & Performance",
}
QA_GROUP_PARTICIPANTS = {
    "release": ("lead", "automation", "manual", "performance"),
    "non_functional": ("lead", "security", "performance"),
}
QA_MESSAGES = (
    ("scope", "release", "lead", 5, "R-DEMO đã vào QA; phạm vi gồm regression, release gate và bằng chứng rollback."),
    ("automation", "release", "automation", 4, "Automation suite đã pass 118/120 case; hai case refresh token đang failed."),
    ("manual", "release", "manual", 3, "Manual smoke đã pass luồng checkout; luồng đăng nhập iOS còn bị chặn bởi refresh token."),
    ("critical-bug", "release", "lead", 2, "Defect nghiêm trọng: phiên đăng nhập iOS hết hạn sớm sau khi refresh token."),
    ("evidence", "release", "automation", 1, "Đã đính kèm log regression build 3401 và video tái hiện lỗi iOS."),
    ("gate", "release", "lead", 0, "Release gate chưa thể sign-off cho tới khi retest refresh token đạt và evidence được xác minh."),
    ("security", "non_functional", "security", 3, "Security regression không phát hiện lỗ hổng critical; báo cáo scan đang chờ lead xác minh."),
    ("performance", "non_functional", "performance", 2, "P95 API hiện 780ms, cao hơn quality gate 700ms; cần tối ưu và chạy lại load test."),
    ("rollback", "non_functional", "lead", 1, "Rollback rehearsal hoàn thành trong 5 phút 40 giây, đạt SLO dưới 10 phút."),
)
QA_TASKS = (
    ("ios-bug", "Khắc phục lỗi refresh token iOS", "blocked", "High", "lead", "Lỗi tái hiện trên build 3401", 1, "release", "critical-bug", "bug", "critical", "open", False),
    ("auth-retest", "Chạy lại automation refresh token", "pending", "High", "automation", None, 2, "release", "automation", "test_case", None, "failed", False),
    ("manual-smoke", "Hoàn tất manual smoke R-DEMO", "in_progress", "High", "manual", None, 1, "release", "manual", "test_case", None, "testing", False),
    ("api-regression", "Xác nhận API regression 118 case đã đạt", "completed", "Medium", "automation", None, -1, "release", "automation", "test_case", None, "passed", False),
    ("release-signoff", "QA Lead sign-off release gate", "pending", "High", "lead", None, 3, "release", "gate", "release_check", None, "open", True),
    ("security-evidence", "Xác minh security scan evidence", "in_progress", "High", "security", None, 1, "non_functional", "security", "release_check", None, "testing", True),
    ("performance", "Đưa API P95 xuống dưới 700ms", "blocked", "High", "performance", "P95 hiện tại là 780ms", 2, "non_functional", "performance", "test_case", None, "blocked", False),
    ("rollback", "Xác nhận rollback rehearsal đạt SLO", "completed", "Medium", "lead", None, -1, "non_functional", "rollback", "release_check", None, "passed", True),
)


def stable_id(name: str) -> str:
    return uuid5(NAMESPACE_URL, f"{QA_NAMESPACE}:{name}").hex


async def _upsert_quality_link(session, *, agent_workspace_id: str, conversation_id: str, lead_id: str) -> None:
    row = (
        await session.execute(
            select(AgentWorkspaceConversation).where(
                AgentWorkspaceConversation.conversation_id == conversation_id
            )
        )
    ).scalar_one_or_none()
    values = {
        "agent_workspace_id": agent_workspace_id,
        "conversation_id": conversation_id,
        "classification": "quality",
        "linked_by_user_id": lead_id,
    }
    if row is None:
        session.add(AgentWorkspaceConversation(id=stable_id(f"link:{conversation_id}"), **values))
    else:
        for field, value in values.items():
            setattr(row, field, value)


async def seed_quality_demo() -> dict[str, str | int]:
    settings = get_settings()
    if settings.app_env == "production":
        raise RuntimeError("Refusing to seed synthetic Quality data in APP_ENV=production")

    # Ensures users, company, Delivery workspace and the one-assignment cleanup.
    await seed_delivery_demo()
    now = datetime.now(UTC).replace(microsecond=0)
    async with async_session_maker() as session:
        company = (
            await session.execute(select(Workspace).where(Workspace.slug == "company-root"))
        ).scalar_one()
        users = {
            key: (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one()
            for key, email in QA_MEMBER_EMAILS.items()
        }
        delivery = (
            await session.execute(
                select(AgentWorkspace).where(
                    AgentWorkspace.organization_workspace_id == company.id,
                    AgentWorkspace.key == "delivery-demo",
                )
            )
        ).scalar_one()
        quality = (
            await session.execute(
                select(AgentWorkspace).where(
                    AgentWorkspace.organization_workspace_id == company.id,
                    AgentWorkspace.key == "quality-assurance-demo",
                )
            )
        ).scalar_one_or_none()
        if quality is None:
            quality = AgentWorkspace(
                id=stable_id("agent-workspace"),
                organization_workspace_id=company.id,
                key="quality-assurance-demo",
                name="Quality Assurance Demo",
                agent_profile="quality_assurance",
                status="active",
            )
            session.add(quality)
            await session.flush()
        else:
            quality.name = "Quality Assurance Demo"
            quality.agent_profile = "quality_assurance"
            quality.status = "active"

        for key, user in users.items():
            await add_agent_workspace_member(
                session,
                quality.id,
                user.id,
                "lead" if key == "lead" else "member",
            )

        qa_user_ids = {user.id for user in users.values()}
        stale = (
            await session.execute(
                select(AgentWorkspaceMembership).where(
                    AgentWorkspaceMembership.agent_workspace_id == quality.id,
                    AgentWorkspaceMembership.status == "active",
                    AgentWorkspaceMembership.user_id.not_in(qa_user_ids),
                )
            )
        ).scalars().all()
        for membership in stale:
            membership.status = "revoked"
            membership.updated_at = now

        conversations: dict[str, Conversation] = {}
        for key, name in QA_GROUPS.items():
            conversations[key] = await _upsert_by_id(
                session,
                Conversation,
                stable_id(f"conversation:{key}"),
                {
                    "workspace_id": company.id,
                    "type": "group",
                    "name": name,
                    "created_by": users["lead"].id,
                    "ai_enabled": True,
                    "ai_policy_version": 1,
                    "ai_enabled_by_user_id": users["lead"].id,
                    "ai_enabled_at": now,
                    "updated_at": now,
                },
            )
        await session.flush()

        for group_key, member_keys in QA_GROUP_PARTICIPANTS.items():
            for member_key in member_keys:
                await _upsert_participant(
                    session,
                    conversation_id=conversations[group_key].id,
                    user_id=users[member_key].id,
                    resource_role="manager" if member_key == "lead" else "participant",
                    invited_by_user_id=users["lead"].id,
                )
            await _upsert_quality_link(
                session,
                agent_workspace_id=quality.id,
                conversation_id=conversations[group_key].id,
                lead_id=users["lead"].id,
            )

        desired_conversation_ids = {conversation.id for conversation in conversations.values()}
        stale_links = (
            await session.execute(
                select(AgentWorkspaceConversation).where(
                    AgentWorkspaceConversation.agent_workspace_id == quality.id,
                    AgentWorkspaceConversation.conversation_id.not_in(desired_conversation_ids),
                )
            )
        ).scalars().all()
        for mapping in stale_links:
            await session.delete(mapping)

        messages: dict[str, Message] = {}
        for key, group_key, sender_key, days_ago, content in QA_MESSAGES:
            messages[key] = await _upsert_by_id(
                session,
                Message,
                stable_id(f"message:{key}"),
                {
                    "conversation_id": conversations[group_key].id,
                    "sender_id": users[sender_key].id,
                    "content": content,
                    "created_at": now - timedelta(days=days_ago),
                },
            )
        await session.flush()

        consent_hashes = {
            key: await get_consent_scope_hash(session, conversation.id)
            for key, conversation in conversations.items()
        }
        for (
            key,
            title,
            task_status,
            priority,
            owner_key,
            blocked_reason,
            due_offset,
            group_key,
            message_key,
            work_item_type,
            severity,
            quality_status,
            required,
        ) in QA_TASKS:
            await _upsert_by_id(
                session,
                Task,
                stable_id(f"task:{key}"),
                {
                    "workspace_id": company.id,
                    "agent_workspace_id": quality.id,
                    "owner_id": users[owner_key].id,
                    "conversation_id": conversations[group_key].id,
                    "title": title,
                    "due_at": now + timedelta(days=due_offset),
                    "priority": priority,
                    "status": task_status,
                    "blocked_reason": blocked_reason,
                    "source": "ai_extracted",
                    "source_message_ids": [messages[message_key].id],
                    "source_sender_id": messages[message_key].sender_id,
                    "consent_scope_hash": consent_hashes[group_key],
                    "invalidated_reason": None,
                    "work_item_type": work_item_type,
                    "severity": severity,
                    "quality_status": quality_status,
                    "release_target": QA_RELEASE_ID,
                    "quality_required": required,
                    "row_version": 1,
                    "updated_at": now,
                },
            )

        release_source = (
            await session.execute(
                select(Conversation).where(
                    Conversation.workspace_id == company.id,
                    Conversation.name == "Release 34",
                )
            )
        ).scalar_one()
        await _upsert_by_id(
            session,
            ReleaseCandidate,
            stable_id("release-candidate:R-DEMO"),
            {
                "organization_workspace_id": company.id,
                "delivery_agent_workspace_id": delivery.id,
                "quality_agent_workspace_id": quality.id,
                "source_conversation_id": release_source.id,
                "delivery_milestone_id": None,
                "release_key": QA_RELEASE_ID,
                "version": "1.0.0",
                "build_number": "3401",
                "commit_sha": "a1b2c3d4e5f6a7b8",
                "environment": "staging",
                "status": "qa_in_progress",
                "quality_policy_version": "quality-gate-v1",
                "created_by_user_id": (
                    await session.execute(
                        select(User.id).where(User.email == "delivery-demo-lead@example.com")
                    )
                ).scalar_one(),
                "row_version": 1,
                "updated_at": now,
            },
        )
        await session.commit()

    return {
        "company_workspace_id": company.id,
        "quality_agent_workspace_id": quality.id,
        "lead_email": QA_MEMBER_EMAILS["lead"],
        "member_emails": list(QA_MEMBER_EMAILS.values())[1:],
        "unassigned_email": "delivery-demo-outsider@example.com",
        "password": DEMO_PASSWORD,
        "group_count": len(QA_GROUPS),
        "member_count": len(QA_MEMBER_EMAILS),
        "task_count": len(QA_TASKS),
        "release_id": QA_RELEASE_ID,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write the synthetic QA fixture")
    args = parser.parse_args()
    if not args.apply:
        print("Preview only. Run with --apply to create/update the QA demo fixture.")
        return 0
    try:
        manifest = asyncio.run(seed_quality_demo())
    except Exception as exc:
        print(f"QUALITY DEMO SEED FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("QUALITY DEMO SEED COMPLETE")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
