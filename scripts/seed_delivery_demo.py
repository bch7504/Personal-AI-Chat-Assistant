"""Create idempotent synthetic data for the Product Delivery Agent demo.

The fixture is explicitly namespaced (``delivery-demo``), never deletes data,
and refuses production. It creates a realistic Product Delivery organization
with three linked teams of five people, an unlinked security-control group,
source-bound tasks, milestones and enterprise chat evidence so the real
UI/API/LLM flow can be demonstrated end-to-end.
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

from src.auth.security import hash_password
from src.config import get_settings
from src.db.models import (
    AgentWorkspace,
    AgentWorkspaceConversation,
    AgentWorkspaceMembership,
    Conversation,
    ConversationParticipant,
    DeliveryCheckpointTask,
    DeliveryDecisionRecord,
    DeliveryDependencyRecord,
    DeliveryMilestone,
    Message,
    Task,
    User,
    Workspace,
    WorkspaceMembership,
)
from src.db.session import async_session_maker
from src.services.consent_service import get_consent_scope_hash
from src.services.workspace_service import ensure_personal_workspace

DEMO_NAMESPACE = "delivery-demo"
DEMO_PASSWORD = "Demo123!"
DEMO_USERS = {
    "admin": ("delivery-demo-admin@example.com", "Hà Platform Admin", "platform_admin", "Platform Admin"),
    "lead": ("delivery-demo-lead@example.com", "Linh Delivery Lead", "user", "Head of Product Delivery"),
    "member": ("delivery-demo-member@example.com", "Minh Backend", "user", "Backend Engineer"),
    "apollo_frontend": ("delivery-demo-huy@example.com", "Huy Frontend", "user", "Frontend Engineer"),
    "apollo_product": ("delivery-demo-lan@example.com", "Lan Product", "user", "Product Owner"),
    "apollo_devops": ("delivery-demo-duc@example.com", "Đức DevOps", "user", "DevOps Engineer"),
    "release_manager": ("delivery-demo-mai@example.com", "Mai Release", "user", "Release Manager"),
    "mobile": ("delivery-demo-nam@example.com", "Nam Mobile", "user", "Mobile Engineer"),
    "docs": ("delivery-demo-thao@example.com", "Thảo Documentation", "user", "Technical Writer"),
    "sre": ("delivery-demo-phuc@example.com", "Phúc SRE", "user", "Site Reliability Engineer"),
    "ux": ("delivery-demo-an@example.com", "An UX", "user", "Product Designer"),
    "analyst": ("delivery-demo-vy@example.com", "Vy Analyst", "user", "Business Analyst"),
    "integration": ("delivery-demo-son@example.com", "Sơn Integration", "user", "Integration Engineer"),
    "qa_engineer": ("delivery-demo-huong@example.com", "Hương QA", "user", "QA Engineer"),
    "delivery_tester": ("delivery-demo-tester@example.com", "Trang Delivery Tester", "user", "Delivery Test Engineer"),
    "qa_automation": ("qa-demo-automation@example.com", "An QA Automation", "user", "QA Automation Engineer"),
    "qa_manual": ("qa-demo-manual@example.com", "Bình QA Manual", "user", "QA Engineer"),
    "qa_security": ("qa-demo-security@example.com", "Chi QA Security", "user", "Application Security Tester"),
    "qa_performance": ("qa-demo-performance@example.com", "Dũng QA Performance", "user", "Performance Test Engineer"),
    "outsider": ("delivery-demo-outsider@example.com", "Quang Outsider", "user", "Security Control User"),
}

LINKED_GROUPS = {
    "apollo": "Apollo Platform",
    "release34": "Release 34",
    "customer_portal": "Customer Portal",
}

GROUP_PARTICIPANTS = {
    "apollo": ("lead", "member", "apollo_frontend", "apollo_product", "apollo_devops"),
    "release34": ("lead", "release_manager", "mobile", "docs", "sre"),
    "customer_portal": ("lead", "ux", "analyst", "integration", "delivery_tester"),
}

MESSAGE_SPECS = (
    (
        "apollo-kickoff",
        "apollo",
        "apollo_product",
        6,
        "Sprint Apollo đã chốt mục tiêu: OAuth doanh nghiệp, dashboard vận hành và pipeline staging.",
    ),
    (
        "apollo-backend",
        "apollo",
        "member",
        5,
        "Nhiệm vụ của Minh: hoàn thiện OAuth callback và migration token trước thứ Tư; hiện đã xong khoảng 70%.",
    ),
    (
        "apollo-frontend",
        "apollo",
        "apollo_frontend",
        4,
        "Huy nhận dashboard vận hành, phụ thuộc API metrics từ backend; dự kiến bàn giao bản review vào thứ Năm.",
    ),
    (
        "apollo-devops",
        "apollo",
        "apollo_devops",
        4,
        "Đức đã dựng pipeline staging và hoàn thành secret rotation; còn chờ endpoint healthcheck mới.",
    ),
    (
        "apollo-blocker",
        "apollo",
        "lead",
        3,
        "Blocker Apollo: sandbox của vendor trả lỗi 429, làm chậm kiểm thử OAuth end-to-end.",
    ),
    (
        "apollo-vendor",
        "apollo",
        "apollo_product",
        2,
        "Lan đã liên hệ vendor; họ cam kết cấp sandbox ổn định trước 15:00 ngày mai.",
    ),
    (
        "apollo-decision",
        "apollo",
        "lead",
        1,
        "Quyết định: nếu vendor tiếp tục lỗi sau deadline, đội sẽ dùng mock contract và giữ feature flag OAuth tắt.",
    ),
    (
        "apollo-progress",
        "apollo",
        "member",
        0,
        "Cập nhật: migration checklist đã hoàn tất 8/10 mục; còn rollback test và xác nhận từ SRE.",
    ),
    (
        "release-freeze",
        "release34",
        "release_manager",
        6,
        "Release 34 bắt đầu code freeze lúc 17:00 thứ Năm; mọi ngoại lệ phải được Mai phê duyệt.",
    ),
    (
        "release-mobile",
        "release34",
        "mobile",
        5,
        "Nam phụ trách regression mobile; Android pass 42/45 test, iOS còn lỗi đăng nhập khi refresh token.",
    ),
    (
        "release-docs",
        "release34",
        "docs",
        4,
        "Thảo đang hoàn thiện release notes và cần danh sách breaking change từ Apollo trước thứ Tư.",
    ),
    (
        "release-sre",
        "release34",
        "sre",
        3,
        "Phúc đã kiểm tra dashboard và alert; rollback script chạy 6 phút, nằm trong SLO 10 phút.",
    ),
    (
        "release-blocker",
        "release34",
        "mobile",
        2,
        "Blocker Release 34: crash rate iOS 2,4%, cao hơn ngưỡng go-live 1%.",
    ),
    (
        "release-decision",
        "release34",
        "lead",
        1,
        "Cần quyết định go/no-go lúc 16:00 thứ Sáu dựa trên crash rate, rollback rehearsal và sign-off QA.",
    ),
    (
        "release-rollback",
        "release34",
        "release_manager",
        1,
        "Mai giao Phúc chạy lại rollback rehearsal và đính kèm log trước cuộc họp go/no-go.",
    ),
    (
        "release-status",
        "release34",
        "sre",
        0,
        "Rollback rehearsal lần hai đã pass trong 5 phút 40 giây; log đã sẵn sàng để review.",
    ),
    (
        "portal-scope",
        "customer_portal",
        "analyst",
        6,
        "Customer Portal chốt phạm vi MVP gồm onboarding, tra cứu đơn hàng và gửi yêu cầu hỗ trợ.",
    ),
    (
        "portal-ux",
        "customer_portal",
        "ux",
        5,
        "An đã hoàn thành prototype onboarding; cần Product duyệt accessibility trước thứ Năm.",
    ),
    (
        "portal-integration",
        "customer_portal",
        "integration",
        4,
        "Sơn nhận tích hợp CRM, đã xong mapping 18/22 trường dữ liệu và đang chờ credential UAT.",
    ),
    (
        "portal-qa",
        "customer_portal",
        "delivery_tester",
        3,
        "Trang đã chuẩn bị 35 test case; smoke test bắt đầu ngay khi CRM UAT hoạt động.",
    ),
    (
        "portal-blocker",
        "customer_portal",
        "integration",
        2,
        "Blocker Customer Portal: đội CRM chưa cấp credential UAT, ảnh hưởng integration test và QA smoke.",
    ),
    (
        "portal-decision",
        "customer_portal",
        "lead",
        1,
        "Quyết định cần chốt: phát hành onboarding trước hay giữ một release cùng tra cứu đơn hàng.",
    ),
    (
        "portal-owner",
        "customer_portal",
        "analyst",
        1,
        "Vy sẽ tổng hợp acceptance criteria và owner cho các trường dữ liệu còn thiếu trước 14:00 mai.",
    ),
    (
        "portal-progress",
        "customer_portal",
        "delivery_tester",
        0,
        "QA đã review prototype, 30/35 test case sẵn sàng; 5 case còn phụ thuộc chính sách phân quyền CRM.",
    ),
)

TASK_SPECS = (
    (
        "apollo-blocked",
        "Ổn định vendor sandbox cho OAuth E2E",
        "blocked",
        "High",
        "lead",
        "Vendor sandbox trả lỗi 429",
        -1,
        "apollo",
        "apollo-blocker",
    ),
    (
        "apollo-due-soon",
        "Hoàn thiện migration checklist",
        "in_progress",
        "High",
        "member",
        None,
        2,
        "apollo",
        "apollo-progress",
    ),
    (
        "apollo-dashboard",
        "Bàn giao dashboard vận hành",
        "in_progress",
        "Medium",
        "apollo_frontend",
        None,
        3,
        "apollo",
        "apollo-frontend",
    ),
    (
        "apollo-pipeline",
        "Thiết lập pipeline staging và secret rotation",
        "completed",
        "Medium",
        "apollo_devops",
        None,
        -1,
        "apollo",
        "apollo-devops",
    ),
    (
        "apollo-acceptance",
        "Xác nhận acceptance criteria OAuth",
        "pending",
        "High",
        "apollo_product",
        None,
        4,
        "apollo",
        "apollo-kickoff",
    ),
    (
        "release-overdue",
        "Phê duyệt kế hoạch rollback Release 34",
        "pending",
        "High",
        "release_manager",
        None,
        -2,
        "release34",
        "release-freeze",
    ),
    (
        "release-mobile-regression",
        "Giảm crash rate iOS xuống dưới 1%",
        "blocked",
        "High",
        "mobile",
        "Crash rate iOS đang ở mức 2,4%",
        1,
        "release34",
        "release-blocker",
    ),
    (
        "release-notes",
        "Hoàn thiện Release 34 release notes",
        "in_progress",
        "Medium",
        "docs",
        None,
        1,
        "release34",
        "release-docs",
    ),
    (
        "release-rollback-rehearsal",
        "Chạy lại rollback rehearsal",
        "completed",
        "High",
        "sre",
        None,
        0,
        "release34",
        "release-status",
    ),
    (
        "release-go-no-go",
        "Chuẩn bị dữ liệu cho quyết định go/no-go",
        "in_progress",
        "High",
        "lead",
        None,
        2,
        "release34",
        "release-decision",
    ),
    (
        "portal-accessibility",
        "Duyệt accessibility cho onboarding",
        "pending",
        "Medium",
        "ux",
        None,
        3,
        "customer_portal",
        "portal-ux",
    ),
    (
        "portal-crm-mapping",
        "Hoàn thiện mapping CRM 22 trường",
        "in_progress",
        "High",
        "integration",
        None,
        2,
        "customer_portal",
        "portal-integration",
    ),
    (
        "portal-uat-credential",
        "Nhận credential CRM UAT",
        "blocked",
        "High",
        "integration",
        "Đội CRM chưa cấp credential UAT",
        -1,
        "customer_portal",
        "portal-blocker",
    ),
    (
        "portal-test-cases",
        "Hoàn thiện bộ 35 test case",
        "in_progress",
        "Medium",
        "delivery_tester",
        None,
        4,
        "customer_portal",
        "portal-progress",
    ),
    (
        "portal-acceptance",
        "Chốt acceptance criteria MVP",
        "pending",
        "High",
        "analyst",
        None,
        1,
        "customer_portal",
        "portal-owner",
    ),
)

MILESTONE_SPECS = (
    ("apollo-milestone", "Apollo OAuth integration", "blocked", "lead", "Vendor sandbox chưa ổn định", 2, "apollo"),
    ("apollo-review", "Apollo technical review", "in_progress", "apollo_product", None, 4, "apollo"),
    ("apollo-unassigned", "Gán owner cho production readiness review", "pending", None, None, 5, "apollo"),
    ("release34-milestone", "Release 34 go/no-go", "in_progress", "release_manager", None, 3, "release34"),
    ("release-mobile-gate", "Mobile quality gate", "blocked", "mobile", "Crash rate vượt ngưỡng 1%", 1, "release34"),
    ("release-unassigned", "Gán owner theo dõi hypercare", "pending", None, None, 5, "release34"),
    ("portal-mvp", "Customer Portal MVP", "in_progress", "analyst", None, 7, "customer_portal"),
    (
        "portal-integration-gate",
        "CRM UAT integration",
        "blocked",
        "integration",
        "Thiếu credential CRM UAT",
        3,
        "customer_portal",
    ),
    ("portal-unassigned", "Gán owner truyền thông rollout", "pending", None, None, 6, "customer_portal"),
)

DEPENDENCY_SPECS = (
    (
        "apollo-vendor-dependency",
        "Vendor sandbox phải ổn định trước OAuth E2E",
        "blocked",
        "apollo_product",
        "apollo-blocked",
        "apollo-acceptance",
        1,
        "apollo",
    ),
    (
        "release-mobile-dependency",
        "Crash rate iOS phải dưới 1% trước go/no-go",
        "blocked",
        "mobile",
        "release-mobile-regression",
        "release-go-no-go",
        1,
        "release34",
    ),
    (
        "portal-crm-dependency",
        "CRM credential UAT phải có trước smoke test",
        "blocked",
        "integration",
        "portal-uat-credential",
        "portal-test-cases",
        1,
        "customer_portal",
    ),
)

DECISION_SPECS = (
    (
        "apollo-fallback-decision",
        "Dùng mock contract nếu vendor tiếp tục lỗi",
        "decided",
        "lead",
        0,
        ("Tiếp tục chờ vendor", "Dùng mock contract và giữ feature flag tắt"),
        "Dùng mock contract và giữ feature flag OAuth tắt nếu quá deadline.",
        "apollo",
    ),
    (
        "release-go-no-go-decision",
        "Chốt go/no-go Release 34",
        "pending",
        "lead",
        2,
        ("Go", "No-go", "Hoãn có điều kiện"),
        None,
        "release34",
    ),
    (
        "portal-scope-decision",
        "Phát hành onboarding riêng hay cùng tra cứu đơn hàng",
        "pending",
        "lead",
        2,
        ("Onboarding trước", "Phát hành cùng một đợt"),
        None,
        "customer_portal",
    ),
)


def validate_fixture_spec() -> None:
    if len(LINKED_GROUPS) != 3:
        raise ValueError("Delivery demo must contain exactly three linked groups")
    message_groups = {key: group_key for key, group_key, *_ in MESSAGE_SPECS}
    for group_key, participants in GROUP_PARTICIPANTS.items():
        if group_key not in LINKED_GROUPS or len(participants) != 5 or len(set(participants)) != 5:
            raise ValueError(f"Delivery group '{group_key}' must contain five unique participants")
        if "lead" not in participants:
            raise ValueError(f"Delivery group '{group_key}' must contain the Delivery lead")
    for message_key, group_key, sender_key, *_ in MESSAGE_SPECS:
        if sender_key not in GROUP_PARTICIPANTS[group_key]:
            raise ValueError(f"Message '{message_key}' sender is outside its group")
    for task in TASK_SPECS:
        task_key, *_, owner_key, _blocked_reason, _offset, group_key, message_key = task
        if owner_key not in GROUP_PARTICIPANTS[group_key]:
            raise ValueError(f"Task '{task_key}' owner is outside its group")
        if message_groups.get(message_key) != group_key:
            raise ValueError(f"Task '{task_key}' source message is outside its group")


def stable_id(name: str) -> str:
    return uuid5(NAMESPACE_URL, f"{DEMO_NAMESPACE}:{name}").hex


async def _upsert_by_id(session, model, identity: str, values: dict):
    row = await session.get(model, identity)
    if row is None:
        row = model(id=identity, **values)
        session.add(row)
    else:
        for field, value in values.items():
            setattr(row, field, value)
    return row


async def _upsert_workspace_membership(
    session, *, workspace_id: str, user_id: str, role: str, invited_by_user_id: str | None
) -> None:
    row = (
        await session.execute(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    values = {
        "workspace_id": workspace_id,
        "user_id": user_id,
        "role": role,
        "status": "active",
        "invited_by_user_id": invited_by_user_id,
        "joined_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    if row is None:
        session.add(WorkspaceMembership(id=stable_id(f"company-membership:{user_id}"), **values))
    else:
        for field, value in values.items():
            setattr(row, field, value)


async def _upsert_agent_membership(session, *, agent_workspace_id: str, user_id: str, business_role: str) -> None:
    row = (
        await session.execute(
            select(AgentWorkspaceMembership).where(
                AgentWorkspaceMembership.agent_workspace_id == agent_workspace_id,
                AgentWorkspaceMembership.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    values = {
        "agent_workspace_id": agent_workspace_id,
        "user_id": user_id,
        "business_role": business_role,
        "status": "active",
        "updated_at": datetime.now(UTC),
    }
    if row is None:
        session.add(AgentWorkspaceMembership(id=stable_id(f"delivery-membership:{user_id}"), **values))
    else:
        for field, value in values.items():
            setattr(row, field, value)


async def _upsert_participant(
    session, *, conversation_id: str, user_id: str, resource_role: str, invited_by_user_id: str
) -> None:
    row = (
        await session.execute(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    values = {
        "conversation_id": conversation_id,
        "principal_kind": "workspace_user",
        "user_id": user_id,
        "external_contact_id": None,
        "resource_role": resource_role,
        "invited_by_user_id": invited_by_user_id,
        "joined_at": datetime.now(UTC),
        "last_read_at": datetime.now(UTC),
        "revoked_at": None,
        "hidden_at": None,
    }
    if row is None:
        session.add(ConversationParticipant(id=stable_id(f"participant:{conversation_id}:{user_id}"), **values))
    else:
        for field, value in values.items():
            setattr(row, field, value)


async def _upsert_agent_conversation(
    session, *, agent_workspace_id: str, conversation_id: str, lead_user_id: str, channel_kind: str
) -> None:
    identity = stable_id(f"delivery-link:{conversation_id}")
    row = await session.get(AgentWorkspaceConversation, identity)
    values = {
        "agent_workspace_id": agent_workspace_id,
        "conversation_id": conversation_id,
        "classification": "delivery",
        "channel_kind": channel_kind,
        "linked_by_user_id": lead_user_id,
    }
    if row is None:
        session.add(AgentWorkspaceConversation(id=identity, **values))
    else:
        for field, value in values.items():
            setattr(row, field, value)


async def seed_demo() -> dict[str, str | int]:
    validate_fixture_spec()
    settings = get_settings()
    if settings.app_env == "production":
        raise RuntimeError("Refusing to seed synthetic Delivery data in APP_ENV=production")

    now = datetime.now(UTC).replace(microsecond=0)
    password_hash = hash_password(DEMO_PASSWORD)
    async with async_session_maker() as session:
        users: dict[str, User] = {}
        for key, (email, display_name, platform_role, job_title) in DEMO_USERS.items():
            user = await session.get(User, stable_id(f"user:{key}"))
            if user is None:
                user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
            values = {
                "email": email,
                "password_hash": password_hash,
                "display_name": display_name,
                "role": "admin" if platform_role == "platform_admin" else "user",
                "platform_role": platform_role,
                "is_active": True,
                "job_title": job_title,
                "timezone": "Asia/Ho_Chi_Minh",
                "preferences": {"fixture_namespace": DEMO_NAMESPACE},
            }
            if user is None:
                user = User(id=stable_id(f"user:{key}"), **values)
                session.add(user)
            else:
                for field, value in values.items():
                    setattr(user, field, value)
            users[key] = user
        await session.flush()

        # Demo users bypass /auth/register, so explicitly preserve the same
        # account invariant used by normal registration and login.
        for user in users.values():
            await ensure_personal_workspace(session, user)

        company = (
            await session.execute(select(Workspace).where(Workspace.slug == "company-root"))
        ).scalar_one_or_none()
        if company is None:
            company = Workspace(
                id=stable_id("company-root"),
                type="organization",
                name="Company Root",
                slug="company-root",
                personal_owner_user_id=None,
                status="active",
            )
            session.add(company)
            await session.flush()
        if company.type != "organization" or company.status != "active":
            raise RuntimeError("company-root must be an active organization workspace")

        for key in DEMO_USERS:
            await _upsert_workspace_membership(
                session,
                workspace_id=company.id,
                user_id=users[key].id,
                role="owner" if key == "admin" else "member",
                invited_by_user_id=None if key == "admin" else users["admin"].id,
            )

        delivery = (
            await session.execute(
                select(AgentWorkspace).where(
                    AgentWorkspace.organization_workspace_id == company.id,
                    AgentWorkspace.key == "delivery-demo",
                )
            )
        ).scalar_one_or_none()
        if delivery is None:
            delivery = AgentWorkspace(
                id=stable_id("agent-workspace"),
                organization_workspace_id=company.id,
                key="delivery-demo",
                name="Product Delivery",
                agent_profile="product_delivery",
                status="active",
            )
            session.add(delivery)
        elif delivery.agent_profile != "product_delivery":
            raise RuntimeError("Agent workspace key 'delivery-demo' belongs to a different profile")
        else:
            delivery.name = "Product Delivery"
            delivery.status = "active"
        await session.flush()

        delivery_user_keys = tuple(
            dict.fromkeys(user_key for participants in GROUP_PARTICIPANTS.values() for user_key in participants)
        )
        for user_key in delivery_user_keys:
            await _upsert_agent_membership(
                session,
                agent_workspace_id=delivery.id,
                user_id=users[user_key].id,
                business_role="lead" if user_key == "lead" else "member",
            )

        # The demo reflects the production invariant: one active Agent Workspace
        # assignment per account. QA specialists remain organization users but do
        # not receive Product Delivery Agent access.
        delivery_user_ids = {users[user_key].id for user_key in delivery_user_keys}
        stale_demo_memberships = (
            await session.execute(
                select(AgentWorkspaceMembership).where(
                    AgentWorkspaceMembership.agent_workspace_id == delivery.id,
                    AgentWorkspaceMembership.user_id.in_([user.id for user in users.values()]),
                    AgentWorkspaceMembership.status == "active",
                    AgentWorkspaceMembership.user_id.not_in(delivery_user_ids),
                )
            )
        ).scalars().all()
        for membership in stale_demo_memberships:
            membership.status = "revoked"
            membership.updated_at = now

        conversations: dict[str, Conversation] = {}
        specs = {
            **{key: (name, users["lead"].id, True) for key, name in LINKED_GROUPS.items()},
            "qa": ("QA Internal — not linked", users["outsider"].id, True),
        }
        for key, (name, creator_id, ai_enabled) in specs.items():
            conversations[key] = await _upsert_by_id(
                session,
                Conversation,
                stable_id(f"conversation:{key}"),
                {
                    "workspace_id": company.id,
                    "type": "group",
                    "name": name,
                    "created_by": creator_id,
                    "ai_enabled": ai_enabled,
                    "ai_policy_version": 1,
                    "ai_enabled_by_user_id": creator_id,
                    "ai_enabled_at": now,
                    "updated_at": now,
                },
            )
        await session.flush()

        participant_specs = {
            **{
                group_key: tuple(
                    (user_key, "manager" if user_key == "lead" else "participant") for user_key in participant_keys
                )
                for group_key, participant_keys in GROUP_PARTICIPANTS.items()
            },
            "qa": (("outsider", "manager"),),
        }
        for key, participant_keys in participant_specs.items():
            for user_key, resource_role in participant_keys:
                await _upsert_participant(
                    session,
                    conversation_id=conversations[key].id,
                    user_id=users[user_key].id,
                    resource_role=resource_role,
                    invited_by_user_id=users["admin"].id,
                )

        for key in LINKED_GROUPS:
            await _upsert_agent_conversation(
                session,
                agent_workspace_id=delivery.id,
                conversation_id=conversations[key].id,
                lead_user_id=users["lead"].id,
                channel_kind="release" if key == "release34" else "project",
            )

        message_rows: dict[str, Message] = {}
        for key, conversation_key, sender_key, days_ago, content in MESSAGE_SPECS:
            message_rows[key] = await _upsert_by_id(
                session,
                Message,
                stable_id(f"message:{key}"),
                {
                    "conversation_id": conversations[conversation_key].id,
                    "sender_id": users[sender_key].id,
                    "content": content,
                    "created_at": now - timedelta(days=days_ago),
                },
            )
        message_rows["qa-private"] = await _upsert_by_id(
            session,
            Message,
            stable_id("message:qa-private"),
            {
                "conversation_id": conversations["qa"].id,
                "sender_id": users["outsider"].id,
                "content": "QA-only evidence; it must never appear in the Delivery brief.",
                "created_at": now,
            },
        )
        await session.flush()

        consent_hashes = {
            group_key: await get_consent_scope_hash(session, conversations[group_key].id) for group_key in LINKED_GROUPS
        }
        task_groups: dict[str, list[Task]] = {key: [] for key in LINKED_GROUPS}
        task_rows: dict[str, Task] = {}
        for (
            key,
            title,
            status,
            priority,
            owner_key,
            blocked_reason,
            offset_days,
            conversation_key,
            message_key,
            ) in TASK_SPECS:
            task_row = await _upsert_by_id(
                session,
                Task,
                stable_id(f"task:{key}"),
                {
                    "workspace_id": company.id,
                    "agent_workspace_id": delivery.id,
                    "owner_id": users[owner_key].id,
                    "conversation_id": conversations[conversation_key].id,
                    "title": title,
                    "due_at": now + timedelta(days=offset_days),
                    "priority": priority,
                    "status": status,
                    "blocked_reason": blocked_reason,
                    "source": "ai_extracted",
                    "source_message_ids": [message_rows[message_key].id],
                    "source_sender_id": message_rows[message_key].sender_id,
                    "consent_scope_hash": consent_hashes[conversation_key],
                    "invalidated_reason": None,
                    "updated_at": now,
                    "created_at": now - timedelta(days=10),
                    "started_at": (
                        now - timedelta(days=7)
                        if status in {"in_progress", "blocked", "completed"}
                        else None
                    ),
                    "completed_at": now - timedelta(days=1) if status == "completed" else None,
                },
            )
            task_rows[key] = task_row
            task_groups[conversation_key].append(task_row)

        milestone_rows: dict[str, DeliveryMilestone] = {}
        for key, title, status, owner_key, blocked_reason, offset_days, conversation_key in MILESTONE_SPECS:
            milestone_rows[key] = await _upsert_by_id(
                session,
                DeliveryMilestone,
                stable_id(f"milestone:{key}"),
                {
                    "workspace_id": company.id,
                    "agent_workspace_id": delivery.id,
                    "conversation_id": conversations[conversation_key].id,
                    "title": title,
                    "status": status,
                    "owner_id": users[owner_key].id if owner_key else None,
                    "due_at": now + timedelta(days=offset_days),
                    "blocked_reason": blocked_reason,
                    "plan_key": "delivery-demo-plan",
                    "quality_review_status": "pending",
                    "quality_review_note": None,
                    "quality_reviewed_by_user_id": None,
                    "quality_reviewed_at": None,
                    "updated_at": now,
                },
            )

        checkpoint_by_group = {
            "apollo": "apollo-milestone",
            "release34": "release34-milestone",
            "customer_portal": "portal-mvp",
        }
        for group_key, milestone_key in checkpoint_by_group.items():
            for task_row in task_groups[group_key]:
                await _upsert_by_id(
                    session,
                    DeliveryCheckpointTask,
                    stable_id(f"checkpoint-task:{milestone_key}:{task_row.id}"),
                    {
                        "workspace_id": company.id,
                        "agent_workspace_id": delivery.id,
                        "conversation_id": conversations[group_key].id,
                        "milestone_id": milestone_rows[milestone_key].id,
                        "task_id": task_row.id,
                        "required": True,
                        "created_by_user_id": users["lead"].id,
                    },
                )

        for (
            key,
            title,
            dependency_status,
            owner_key,
            predecessor_key,
            successor_key,
            offset_days,
            conversation_key,
        ) in DEPENDENCY_SPECS:
            await _upsert_by_id(
                session,
                DeliveryDependencyRecord,
                stable_id(f"dependency:{key}"),
                {
                    "workspace_id": company.id,
                    "agent_workspace_id": delivery.id,
                    "conversation_id": conversations[conversation_key].id,
                    "title": title,
                    "status": dependency_status,
                    "owner_id": users[owner_key].id,
                    "predecessor_task_id": task_rows[predecessor_key].id,
                    "successor_task_id": task_rows[successor_key].id,
                    "due_at": now + timedelta(days=offset_days),
                    "created_by_user_id": users["lead"].id,
                    "updated_at": now,
                },
            )

        for (
            key,
            title,
            decision_status,
            owner_key,
            offset_days,
            options,
            outcome,
            conversation_key,
        ) in DECISION_SPECS:
            await _upsert_by_id(
                session,
                DeliveryDecisionRecord,
                stable_id(f"decision:{key}"),
                {
                    "workspace_id": company.id,
                    "agent_workspace_id": delivery.id,
                    "conversation_id": conversations[conversation_key].id,
                    "title": title,
                    "status": decision_status,
                    "owner_id": users[owner_key].id,
                    "due_at": now + timedelta(days=offset_days),
                    "options": list(options),
                    "outcome": outcome,
                    "created_by_user_id": users["lead"].id,
                    "updated_at": now,
                },
            )

        await session.commit()

    return {
        "company_workspace_id": company.id,
        "agent_workspace_id": delivery.id,
        "admin_email": DEMO_USERS["admin"][0],
        "lead_email": DEMO_USERS["lead"][0],
        "member_email": DEMO_USERS["member"][0],
        "outsider_email": DEMO_USERS["outsider"][0],
        "password": DEMO_PASSWORD,
        "linked_group_count": len(LINKED_GROUPS),
        "delivery_member_count": len(delivery_user_keys),
        "message_count": len(MESSAGE_SPECS),
        "task_count": len(TASK_SPECS),
        "milestone_count": len(MILESTONE_SPECS),
        "dependency_count": len(DEPENDENCY_SPECS),
        "decision_count": len(DECISION_SPECS),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write the synthetic demo fixture to the configured DB")
    args = parser.parse_args()
    if not args.apply:
        print("Preview only. Run with --apply to create/update the Delivery demo fixture.")
        print("Accounts: delivery-demo-*@example.com (15 users, see DEMO_USERS)")
        return 0
    try:
        manifest = asyncio.run(seed_demo())
    except Exception as exc:  # CLI boundary with an actionable, non-secret error.
        print(f"DELIVERY DEMO SEED FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("DELIVERY DEMO SEED COMPLETE")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
