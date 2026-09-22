"""Seed rich, idempotent Personal Agent demo data for the four public accounts.

The fixture extends the canonical Product Delivery seed without deleting user
data. It adds realistic direct and personal-group chat history, balanced work and personal
tasks, confirmed memories, and task-linked reminders so Personal Agent search, planning,
memory, deadline, and proactive flows can be demonstrated together.
"""

# ruff: noqa: E402 -- direct execution bootstraps the repository root below.

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import seed_delivery_demo as base_seed
from scripts import seed_delivery_extended_demo as extended_seed
from src.config import get_settings
from src.db.models import (
    AgentWorkspace,
    AIPermission,
    Conversation,
    ConversationParticipant,
    Memory,
    Message,
    Reminder,
    Task,
    User,
    Workspace,
)
from src.db.session import async_session_maker
from src.services.consent_service import get_consent_scope_hash
from src.services.reminder_service import reconcile_user_task_reminders

FIXTURE_NAMESPACE = "personal-agent-demo-v1"
PUBLIC_USER_KEYS = ("lead", "member", "release_manager", "ux")

DIRECT_CONVERSATIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "lead-minh",
        "participants": ("lead", "member"),
        "messages": (
            ("lead", "Minh cập nhật giúp chị tình hình OAuth E2E để chuẩn bị buổi demo nhé."),
            ("member", "Callback v2 đã chạy ổn; phần retry khi vendor trả 429 còn thiếu jitter và circuit breaker."),
            ("lead", "Rủi ro lớn nhất hiện tại là gì, và có ảnh hưởng mốc demo thứ Ba không?"),
            ("member", "Rủi ro là quota sandbox. Em cam kết hoàn thiện retry jitter trước 10:00 ngày mai để giữ mốc demo."),
            ("lead", "Nhớ đính kèm log rollback và bằng chứng token cũ đã bị revoke."),
            ("member", "Em xác nhận sẽ gửi log rollback cùng ảnh chụp audit trước 14:00 ngày mai."),
            ("lead", "Khi báo cáo cho chị, ưu tiên kết luận, blocker và hành động tiếp theo; không cần kể dài."),
            ("member", "Đã rõ, em sẽ cập nhật theo ba mục: kết luận, blocker và next action."),
        ),
    },
    {
        "key": "lead-mai",
        "participants": ("lead", "release_manager"),
        "messages": (
            ("release_manager", "Release 34 đã đủ rollback evidence, nhưng crash-free iOS vẫn chưa qua quality gate."),
            ("lead", "Mai chuẩn bị cho chị hai phương án rollout và điều kiện dừng cụ thể nhé."),
            ("release_manager", "Em đề xuất 10%-50%-100% hoặc hoãn 24 giờ; dừng nếu crash-free thấp hơn 99%."),
            ("lead", "Mình cần go/no-go pack trước cuộc họp chiều mai, có kịp không?"),
            ("release_manager", "Em xác nhận hoàn tất go/no-go pack trước 13:30 ngày mai và gửi link evidence."),
            ("lead", "Sau đó kiểm tra luôn lịch trực hypercare với Phúc SRE."),
            ("release_manager", "Em sẽ chốt roster hypercare trước 16:00 ngày mai, nếu thiếu người em báo ngay."),
            ("lead", "Tốt, bản cập nhật cuối chỉ cần nêu gate nào pass, gate nào fail và quyết định đề xuất."),
        ),
    },
    {
        "key": "lead-an",
        "participants": ("lead", "ux"),
        "messages": (
            ("ux", "Prototype Customer Portal đã xong luồng onboarding và tra cứu đơn hàng."),
            ("lead", "Phần accessibility còn vấn đề gì có thể làm demo bị vấp?"),
            ("ux", "Còn hai lỗi keyboard focus và thông báo lỗi CRM chưa đủ rõ cho screen reader."),
            ("lead", "An xử lý focus trước, UX copy có thể chốt sau nhưng không được trễ buổi review."),
            ("ux", "Em cam kết sửa keyboard focus trước 11:00 ngày mai và gửi bản preview để chị duyệt."),
            ("lead", "Nhờ em chuẩn bị thêm năm câu hỏi usability cho nhóm khách hàng thử nghiệm."),
            ("ux", "Em sẽ gửi bộ câu hỏi usability trước 15:00 ngày mai."),
            ("lead", "Khi có feedback mâu thuẫn, gom theo mức ảnh hưởng thay vì theo người góp ý nhé."),
        ),
    },
    {
        "key": "minh-mai",
        "participants": ("member", "release_manager"),
        "messages": (
            ("release_manager", "Mai cần danh sách breaking change OAuth để khóa release notes."),
            ("member", "Có hai thay đổi: callback contract v2 và cơ chế revoke token khi rollback."),
            ("release_manager", "Minh gửi giúp impact và hướng rollback trước trưa mai được không?"),
            ("member", "Được, mình sẽ gửi bảng impact trước 11:30 ngày mai."),
            ("release_manager", "Nếu vendor sandbox tiếp tục 429 thì Release 34 có phải no-go không?"),
            ("member", "Không nhất thiết; có thể giữ OAuth sau feature flag và dùng mock contract cho phần demo."),
            ("release_manager", "Mai sẽ đưa phương án đó vào go/no-go pack, nhưng ghi rõ chưa phải quyết định cuối."),
            ("member", "Chuẩn, quyết định cuối vẫn cần Linh phê duyệt trong DecisionRecord."),
        ),
    },
    {
        "key": "minh-an",
        "participants": ("member", "ux"),
        "messages": (
            ("ux", "Màn lỗi đăng nhập hiện chỉ báo 'Có lỗi xảy ra', người dùng không biết phải làm gì."),
            ("member", "Backend có thể trả mã TOKEN_EXPIRED, RATE_LIMITED và CONSENT_REQUIRED để UI phân loại."),
            ("ux", "An cần mapping thông điệp cho ba mã đó trước khi chốt UX copy."),
            ("member", "Mình sẽ gửi response mẫu và contract trước 09:30 ngày mai."),
            ("ux", "An sẽ dựa vào đó hoàn thiện copy và trạng thái retry trước 14:30 ngày mai."),
            ("member", "Nhớ trường hợp rate limit phải hiển thị thời gian thử lại từ Retry-After."),
            ("ux", "Đã ghi nhận, UI sẽ có countdown nhưng không tự gửi lại form nếu chưa có xác nhận."),
            ("member", "Cách đó ổn và tránh tạo request trùng trong lúc sandbox không ổn định."),
        ),
    },
    {
        "key": "mai-an",
        "participants": ("release_manager", "ux"),
        "messages": (
            ("release_manager", "Mai đang chuẩn bị ảnh cho release notes, An có thể xuất bộ screenshot mới không?"),
            ("ux", "Được, nhưng cần xác nhận feature flag nào bật trong build demo."),
            ("release_manager", "Build demo bật onboarding mới, tắt OAuth doanh nghiệp và ẩn analytics chưa consent."),
            ("ux", "An xác nhận sẽ xuất sáu screenshot theo cấu hình đó trước 16:30 ngày mai."),
            ("release_manager", "Thêm giúp một ảnh mobile 390px và một ảnh trạng thái CRM unavailable."),
            ("ux", "Được, hai ảnh đó nằm trong cùng gói bàn giao."),
            ("release_manager", "Mai sẽ review và phản hồi trong vòng một giờ sau khi nhận."),
            ("ux", "Nếu không có phản hồi trước 18:00, An sẽ coi bản đó là ứng viên cho demo chứ chưa phải final."),
        ),
    },
)


# Personal group chats are deliberately not linked to an Agent Workspace. They appear under
# Chats for every participant and use the same single, manager-owned AI policy as groups created
# from the UI. The content covers commitments, deadlines, meetings, blockers and decisions so the
# conversation AI panel and Personal Agent cross-chat search have realistic demo evidence.
GROUP_CONVERSATIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "oauth-demo-war-room",
        "name": "OAuth Demo War Room",
        "creator": "lead",
        "participants": ("lead", "member", "release_manager", "ux"),
        "messages": (
            ("lead", "Mở war room để chốt toàn bộ việc còn lại cho demo OAuth E2E."),
            ("member", "Backend callback v2 đã ổn; sandbox vẫn thỉnh thoảng trả 429 khi chạy song song."),
            ("release_manager", "Nếu 429 chưa hạ trước 12:00 ngày mai, Release 34 cần phương án không phụ thuộc sandbox."),
            ("member", "Em cam kết gửi kết quả retry jitter và circuit breaker trước 10:30 ngày mai."),
            ("ux", "Em cần response mẫu RATE_LIMITED trước 11:00 để chốt countdown và nội dung thử lại."),
            ("member", "Minh xác nhận gửi response mẫu cho An trước 09:30 ngày mai."),
            ("lead", "Phương án dự phòng là dùng mock contract, OAuth thật để sau feature flag; đây chưa phải quyết định cuối."),
            ("release_manager", "Mai sẽ cập nhật go/no-go pack với hai nhánh thật và mock trước 13:30 ngày mai."),
            ("ux", "An sẽ kiểm tra lại luồng lỗi và keyboard focus trước 14:00 ngày mai."),
            ("lead", "Họp review war room lúc 15:00 ngày mai trong 45 phút, online."),
            ("member", "Nếu log revoke token chưa đủ lúc 14:30, em sẽ đánh dấu blocker thay vì báo pass."),
            ("lead", "Kết luận buổi review phải có owner, deadline và điều kiện chuyển sang mock contract."),
        ),
    },
    {
        "key": "customer-demo-prep",
        "name": "Chuẩn bị Demo Khách hàng",
        "creator": "ux",
        "participants": ("lead", "member", "ux"),
        "messages": (
            ("ux", "Em tạo nhóm này để gom nội dung demo Customer Portal và phần hỏi đáp khách hàng."),
            ("lead", "Kịch bản cần đi từ onboarding, tra cứu đơn hàng đến tình huống CRM unavailable."),
            ("member", "API demo đã có dữ liệu ổn định cho onboarding và order detail."),
            ("ux", "An sẽ hoàn thiện prototype mobile 390px trước 16:00 ngày mai."),
            ("lead", "Nhớ có một ví dụ người dùng keyboard-only và một ví dụ screen reader."),
            ("ux", "Em xác nhận gửi bản accessibility walkthrough trước 17:30 ngày mai."),
            ("member", "Minh sẽ chuẩn bị response mẫu TOKEN_EXPIRED, RATE_LIMITED và CONSENT_REQUIRED trước 13:00 ngày mai."),
            ("lead", "Diễn tập demo lúc 09:00 thứ Năm trong 60 phút; ưu tiên phát hiện đoạn chuyển màn bị chậm."),
            ("ux", "Nếu CRM UAT chưa có quyền ghi, mình dùng fixture read-only và nói rõ giới hạn."),
            ("member", "Em sẽ kiểm tra fixture không chứa dữ liệu thật trước buổi diễn tập."),
            ("lead", "Quyết định: không demo thao tác ghi CRM nếu chưa có xác nhận quyền trước 18:00 ngày mai."),
            ("ux", "Đã rõ, em cập nhật script và gửi link cho cả nhóm sau khi chốt prototype."),
        ),
    },
    {
        "key": "release34-gonogo-room",
        "name": "Release 34 Go-No-Go",
        "creator": "release_manager",
        "participants": ("lead", "member", "release_manager"),
        "messages": (
            ("release_manager", "Nhóm này dùng để chốt gate Release 34 và chuẩn bị DecisionRecord."),
            ("lead", "Gate nào đang có nguy cơ làm no-go?"),
            ("release_manager", "Crash-free iOS còn 98,7%, thấp hơn ngưỡng 99%; rollback rehearsal đã pass."),
            ("member", "OAuth có thể giữ sau feature flag nên chưa buộc release phải no-go."),
            ("lead", "Cần evidence riêng cho crash và OAuth, không gộp thành một kết luận chung."),
            ("release_manager", "Mai cam kết hoàn thiện evidence pack trước 14:00 ngày mai."),
            ("member", "Minh sẽ gửi impact của callback v2 và rollback path trước 11:30 ngày mai."),
            ("lead", "Họp go/no-go lúc 16:00 ngày mai trong 30 phút tại phòng Atlas."),
            ("release_manager", "Nếu crash-free vẫn dưới 99% lúc 15:00, đề xuất hoãn rollout iOS 24 giờ."),
            ("member", "Android và backend không bị phụ thuộc gate crash iOS."),
            ("lead", "Quyết định cuối chỉ hợp lệ khi được ghi vào DecisionRecord sau cuộc họp."),
            ("release_manager", "Đã rõ, em sẽ gửi agenda gồm gate, evidence, owner và quyết định cần chốt."),
        ),
    },
    {
        "key": "orbit-agent-demo-rehearsal",
        "name": "Diễn tập Orbit Agent",
        "creator": "member",
        "participants": ("lead", "member", "release_manager", "ux"),
        "messages": (
            ("member", "Mình diễn tập các luồng Personal Agent: tìm tin cũ, task, reminder và Calendar nhé."),
            ("lead", "Mỗi người chuẩn bị một tình huống có deadline rõ và một tình huống mơ hồ."),
            ("release_manager", "Mai sẽ dùng câu hỏi tổng hợp gate Release 34 trong 7 ngày tới."),
            ("ux", "An sẽ test tìm cam kết accessibility trong nhiều cuộc trò chuyện."),
            ("member", "Minh chuẩn bị marker ORBIT-DEMO-GROUP-01 cho blocker quota sandbox."),
            ("lead", "Deadline hoàn thành dữ liệu diễn tập là 17:00 ngày mai."),
            ("release_manager", "Em cam kết kiểm tra lại task của cả bốn tài khoản trước 15:30 ngày mai."),
            ("ux", "Em sẽ bổ sung hội thoại về keyboard focus trước 14:30 ngày mai."),
            ("member", "Họp diễn tập lúc 10:00 thứ Sáu trong 45 phút, dùng Google Meet."),
            ("lead", "Khi test reminder phải kiểm tra cả nhánh Hủy và Xác nhận, không chỉ nhìn câu trả lời."),
            ("release_manager", "Khi test kế hoạch nhiều bước phải mở Xem tiến trình và đối chiếu nguồn thật."),
            ("ux", "Đã chốt: không dùng dữ liệu khách hàng thật và dọn toàn bộ marker E2E sau demo."),
        ),
    },
)


TASK_SPECS: tuple[dict[str, Any], ...] = (
    # Lead: three workspace decisions plus two private preparation items.
    {"key": "lead-vendor-decision", "owner": "lead", "group": "apollo", "source_message": "ext-apollo-decision-chat", "title": "Phê duyệt phương án xử lý quota vendor cho demo", "status": "pending", "priority": "High", "due_hours": 26},
    {"key": "lead-rollout-approval", "owner": "lead", "group": "release34", "source_message": "ext-release-conflict", "title": "Ký xác nhận staged rollout Release 34", "status": "pending", "priority": "High", "due_hours": 50},
    {"key": "lead-portal-scope", "owner": "lead", "group": "customer_portal", "source_message": "ext-portal-scope-chat", "title": "Phê duyệt phạm vi Customer Portal cho bản demo", "status": "in_progress", "priority": "High", "due_hours": 74},
    {"key": "lead-demo-script", "owner": "lead", "title": "Chuẩn bị kịch bản demo Orbit Personal Agent", "status": "in_progress", "priority": "High", "due_hours": 20},
    {"key": "lead-stakeholder-summary", "owner": "lead", "title": "Gửi bản tóm tắt ba rủi ro cho stakeholder", "status": "pending", "priority": "Medium", "due_hours": 96},
    # Minh Backend: three Apollo work items plus two private follow-ups.
    {"key": "minh-retry-jitter", "owner": "member", "group": "apollo", "source_message": "ext-apollo-rate-limit", "title": "Hoàn thiện retry jitter và circuit breaker OAuth", "status": "in_progress", "priority": "High", "due_hours": 30},
    {"key": "minh-revoke-evidence", "owner": "member", "group": "apollo", "source_message": "ext-apollo-security", "title": "Tạo bằng chứng revoke token sau rollback", "status": "blocked", "priority": "High", "due_hours": 54, "blocked_reason": "Chờ sandbox vendor ổn định để chạy lại rollback"},
    {"key": "minh-callback-contract", "owner": "member", "group": "apollo", "source_message": "ext-apollo-history", "title": "Bổ sung contract test cho OAuth callback v2", "status": "pending", "priority": "Medium", "due_hours": 78},
    {"key": "minh-architecture-notes", "owner": "member", "title": "Chuẩn bị phần giải thích kiến trúc OAuth cho demo", "status": "pending", "priority": "Medium", "due_hours": 25},
    {"key": "minh-vendor-questions", "owner": "member", "title": "Tổng hợp câu hỏi kỹ thuật gửi vendor sandbox", "status": "pending", "priority": "Low", "due_hours": 100},
    # Mai Release: three Release 34 items plus two private demo items.
    {"key": "mai-gonogo-pack", "owner": "release_manager", "group": "release34", "source_message": "ext-release-store", "title": "Đóng gói checklist go/no-go Release 34", "status": "in_progress", "priority": "High", "due_hours": 28},
    {"key": "mai-hypercare-roster", "owner": "release_manager", "group": "release34", "source_message": "ext-release-observability", "title": "Xác nhận lịch trực hypercare với SRE", "status": "pending", "priority": "High", "due_hours": 52},
    {"key": "mai-rollout-message", "owner": "release_manager", "group": "release34", "source_message": "ext-release-conflict", "title": "Chuẩn bị thông báo staged rollout cho stakeholder", "status": "pending", "priority": "Medium", "due_hours": 76},
    {"key": "mai-rehearse-demo", "owner": "release_manager", "title": "Diễn tập phần go/no-go trong buổi demo", "status": "in_progress", "priority": "High", "due_hours": 22},
    {"key": "mai-review-accounts", "owner": "release_manager", "title": "Kiểm tra quyền của bốn tài khoản demo", "status": "pending", "priority": "Medium", "due_hours": 110},
    # An UX: three Customer Portal items plus two private research items.
    {"key": "an-keyboard-focus", "owner": "ux", "group": "customer_portal", "source_message": "ext-portal-accessibility", "title": "Sửa keyboard focus trong onboarding demo", "status": "in_progress", "priority": "High", "due_hours": 27},
    {"key": "an-crm-copy", "owner": "ux", "group": "customer_portal", "source_message": "ext-portal-crm", "title": "Chốt UX copy cho trạng thái lỗi CRM", "status": "pending", "priority": "High", "due_hours": 51},
    {"key": "an-design-handoff", "owner": "ux", "group": "customer_portal", "source_message": "ext-portal-history", "title": "Bàn giao design token và responsive spec", "status": "pending", "priority": "Medium", "due_hours": 75},
    {"key": "an-usability-questions", "owner": "ux", "title": "Chuẩn bị bộ câu hỏi usability cho khách hàng", "status": "in_progress", "priority": "High", "due_hours": 32},
    {"key": "an-feedback-map", "owner": "ux", "title": "Phân nhóm feedback theo mức ảnh hưởng", "status": "pending", "priority": "Low", "due_hours": 105},
)


MEMORY_SPECS: dict[str, tuple[tuple[str, str, str, str], ...]] = {
    "lead": (
        ("Preference", "Cách xưng hô", "Gọi người dùng là sếp trong các câu trả lời tiếng Việt.", "preference"),
        ("Work", "Kiểu cập nhật ưu tiên", "Tóm tắt theo thứ tự: kết luận, blocker, hành động tiếp theo.", "preference"),
        ("Work", "Khung giờ tập trung", "Ưu tiên các việc cần quyết định vào buổi sáng từ 09:00 đến 11:30.", "semantic"),
    ),
    "member": (
        ("Work", "Vai trò dự án", "Phụ trách backend OAuth và tích hợp vendor trong Apollo Platform.", "semantic"),
        ("Preference", "Kiểu nhắc việc", "Nhắc kỹ thuật trước deadline 30 phút và nêu rõ dependency đang chặn.", "preference"),
        ("Work", "Cách trình bày bằng chứng", "Ưu tiên log, contract test và link pull request thay cho mô tả chung.", "preference"),
    ),
    "release_manager": (
        ("Work", "Vai trò dự án", "Điều phối Release 34, go/no-go, rollout và hypercare.", "semantic"),
        ("Preference", "Kiểu nhắc việc", "Nhắc trước deadline 60 phút và luôn kèm quality gate liên quan.", "preference"),
        ("Work", "Nguyên tắc release", "Chat không thay thế DecisionRecord cho quyết định go/no-go cuối cùng.", "semantic"),
    ),
    "ux": (
        ("Work", "Vai trò dự án", "Phụ trách UX và accessibility của Customer Portal.", "semantic"),
        ("Preference", "Kiểu nhắc việc", "Nhắc trước deadline một ngày cho review thiết kế và usability session.", "preference"),
        ("Work", "Cách xử lý feedback", "Nhóm feedback theo mức ảnh hưởng và luồng người dùng, không theo người góp ý.", "preference"),
    ),
}

REMINDER_LEAD_MINUTES = {
    "lead": 60,
    "member": 30,
    "release_manager": 60,
    "ux": 1_440,
}


def _validate_fixture() -> None:
    expected_pairs = {frozenset(pair) for pair in DIRECT_CONVERSATIONS for pair in [pair["participants"]]}
    if len(DIRECT_CONVERSATIONS) != 6 or len(expected_pairs) != 6:
        raise ValueError("The four public users must have exactly six unique direct conversations")
    for spec in DIRECT_CONVERSATIONS:
        participants = set(spec["participants"])
        if len(participants) != 2 or not participants.issubset(PUBLIC_USER_KEYS):
            raise ValueError(f"Invalid direct conversation participants: {spec['key']}")
        if len(spec["messages"]) != 8:
            raise ValueError(f"Direct conversation must contain eight messages: {spec['key']}")
        if any(sender not in participants for sender, _ in spec["messages"]):
            raise ValueError(f"Message sender is outside direct conversation: {spec['key']}")
    group_keys = {spec["key"] for spec in GROUP_CONVERSATIONS}
    group_names = {spec["name"] for spec in GROUP_CONVERSATIONS}
    if len(GROUP_CONVERSATIONS) != 4 or len(group_keys) != 4 or len(group_names) != 4:
        raise ValueError("Personal Agent fixture must contain four unique personal group chats")
    for spec in GROUP_CONVERSATIONS:
        participants = set(spec["participants"])
        if len(participants) < 3 or not participants.issubset(PUBLIC_USER_KEYS):
            raise ValueError(f"Invalid personal group participants: {spec['key']}")
        if spec["creator"] not in participants:
            raise ValueError(f"Personal group creator must be a participant: {spec['key']}")
        if len(spec["messages"]) != 12:
            raise ValueError(f"Personal group must contain twelve messages: {spec['key']}")
        if any(sender not in participants for sender, _ in spec["messages"]):
            raise ValueError(f"Message sender is outside personal group: {spec['key']}")
    task_keys = {spec["key"] for spec in TASK_SPECS}
    if len(task_keys) != len(TASK_SPECS) or len(TASK_SPECS) != 20:
        raise ValueError("Personal Agent fixture must contain twenty unique tasks")
    if set(MEMORY_SPECS) != set(PUBLIC_USER_KEYS):
        raise ValueError("Every public account must have a memory fixture")


async def _upsert_by_id(session, model, identity: str, values: dict[str, Any]):
    row = await session.get(model, identity)
    if row is None:
        row = model(id=identity, **values)
        session.add(row)
    else:
        for field, value in values.items():
            setattr(row, field, value)
    return row


async def _find_direct_conversation(
    session,
    *,
    workspace_id: str,
    user_a_id: str,
    user_b_id: str,
) -> Conversation | None:
    candidate_ids = list(
        (
            await session.execute(
                select(ConversationParticipant.conversation_id)
                .join(Conversation, Conversation.id == ConversationParticipant.conversation_id)
                .where(
                    Conversation.workspace_id == workspace_id,
                    Conversation.type == "direct",
                    ConversationParticipant.user_id == user_a_id,
                    ConversationParticipant.revoked_at.is_(None),
                )
            )
        ).scalars()
    )
    for conversation_id in candidate_ids:
        participant_ids = set(
            (
                await session.execute(
                    select(ConversationParticipant.user_id).where(
                        ConversationParticipant.conversation_id == conversation_id,
                        ConversationParticipant.revoked_at.is_(None),
                    )
                )
            ).scalars()
        )
        if participant_ids == {user_a_id, user_b_id}:
            return await session.get(Conversation, conversation_id)
    return None


async def _upsert_ai_permission(session, conversation_id: str, user_id: str, now: datetime) -> None:
    identity = {"conversation_id": conversation_id, "user_id": user_id}
    row = await session.get(AIPermission, identity)
    if row is None:
        session.add(
            AIPermission(
                conversation_id=conversation_id,
                user_id=user_id,
                granted=True,
                contribution_allowed=True,
                updated_at=now,
            )
        )
    else:
        row.granted = True
        row.contribution_allowed = True
        row.updated_at = now


async def seed_personal_agent_demo() -> dict[str, Any]:
    _validate_fixture()
    settings = get_settings()
    if settings.app_env == "production":
        raise RuntimeError("Refusing to seed synthetic Personal Agent data in APP_ENV=production")

    # Establish the canonical organization, channels, memberships, and extended Delivery facts.
    await extended_seed.seed_extended_demo()
    now = datetime.now(UTC).replace(microsecond=0)
    new_task_ids: list[str] = []
    fixture_message_ids: list[str] = []
    fixture_memory_ids: list[str] = []

    async with async_session_maker() as session:
        users: dict[str, User] = {}
        for key in PUBLIC_USER_KEYS:
            email = base_seed.DEMO_USERS[key][0]
            users[key] = (await session.execute(select(User).where(User.email == email))).scalar_one()

        delivery = (
            await session.execute(select(AgentWorkspace).where(AgentWorkspace.key == "delivery-demo"))
        ).scalar_one()
        company_id = delivery.organization_workspace_id
        personal_workspaces = {
            key: (
                await session.execute(
                    select(Workspace).where(
                        Workspace.type == "personal",
                        Workspace.personal_owner_user_id == user.id,
                        Workspace.status == "active",
                    )
                )
            ).scalar_one()
            for key, user in users.items()
        }
        channel_conversations = {
            key: await session.get(Conversation, base_seed.stable_id(f"conversation:{key}"))
            for key in base_seed.LINKED_GROUPS
        }
        if any(conversation is None for conversation in channel_conversations.values()):
            raise RuntimeError("Canonical Product Delivery channels are unavailable")

        # Preserve user-controlled settings while enabling the deadline automation being demoed.
        for key, user in users.items():
            preferences = dict(user.preferences or {})
            preferences.update(
                {
                    "fixture_namespace": base_seed.DEMO_NAMESPACE,
                    "demo_dataset": FIXTURE_NAMESPACE,
                    "language": "Tiếng Việt",
                    "auto_task_reminders": True,
                    "default_reminder_lead_minutes": REMINDER_LEAD_MINUTES[key],
                    "desktop_notifications": True,
                    "ai_suggestion_alerts": True,
                    "personalized_suggestions": True,
                }
            )
            user.preferences = preferences

        direct_conversations: dict[str, Conversation] = {}
        direct_messages: dict[str, Message] = {}
        for pair_index, spec in enumerate(DIRECT_CONVERSATIONS):
            user_a_key, user_b_key = spec["participants"]
            conversation = await _find_direct_conversation(
                session,
                workspace_id=company_id,
                user_a_id=users[user_a_key].id,
                user_b_id=users[user_b_key].id,
            )
            if conversation is None:
                conversation = Conversation(
                    id=base_seed.stable_id(f"personal-direct:{spec['key']}"),
                    workspace_id=company_id,
                    type="direct",
                    name=None,
                    created_by=users[user_a_key].id,
                    ai_enabled=False,
                    ai_policy_version=0,
                    created_at=now - timedelta(days=14 - pair_index),
                    updated_at=now,
                )
                session.add(conversation)
                await session.flush()
            direct_conversations[spec["key"]] = conversation
            for participant_key in spec["participants"]:
                await base_seed._upsert_participant(
                    session,
                    conversation_id=conversation.id,
                    user_id=users[participant_key].id,
                    resource_role="manager" if participant_key == user_a_key else "participant",
                    invited_by_user_id=users[user_a_key].id,
                )
                await _upsert_ai_permission(session, conversation.id, users[participant_key].id, now)

            message_count = len(spec["messages"])
            for message_index, (sender_key, content) in enumerate(spec["messages"]):
                message_key = f"{spec['key']}:{message_index + 1}"
                # All messages remain inside the proactive detector's bounded six-hour window.
                created_at = now - timedelta(
                    minutes=(message_count - message_index) * 24 + pair_index * 3
                )
                direct_messages[message_key] = await _upsert_by_id(
                    session,
                    Message,
                    base_seed.stable_id(f"personal-message:{message_key}"),
                    {
                        "conversation_id": conversation.id,
                        "sender_id": users[sender_key].id,
                        "content": content,
                        "created_at": created_at,
                    },
                )
                fixture_message_ids.append(direct_messages[message_key].id)
            conversation.updated_at = now - timedelta(minutes=pair_index * 3)

        personal_group_conversations: dict[str, Conversation] = {}
        for group_index, spec in enumerate(GROUP_CONVERSATIONS):
            creator = users[spec["creator"]]
            conversation = await _upsert_by_id(
                session,
                Conversation,
                base_seed.stable_id(f"personal-group:{spec['key']}"),
                {
                    "workspace_id": company_id,
                    "type": "group",
                    "name": spec["name"],
                    "created_by": creator.id,
                    "ai_enabled": True,
                    "ai_policy_version": 1,
                    "ai_enabled_by_user_id": creator.id,
                    "ai_enabled_at": now - timedelta(days=4 - group_index),
                    "created_at": now - timedelta(days=4 - group_index),
                    "updated_at": now,
                },
            )
            personal_group_conversations[spec["key"]] = conversation
            await session.flush()

            for participant_key in spec["participants"]:
                await base_seed._upsert_participant(
                    session,
                    conversation_id=conversation.id,
                    user_id=users[participant_key].id,
                    resource_role="manager" if participant_key == spec["creator"] else "participant",
                    invited_by_user_id=creator.id,
                )

            message_count = len(spec["messages"])
            for message_index, (sender_key, content) in enumerate(spec["messages"]):
                message_key = f"{spec['key']}:{message_index + 1}"
                # Keep the seeded group discussion recent enough for the default request windows
                # and the proactive worker's bounded recent-context logic.
                created_at = now - timedelta(
                    minutes=(message_count - message_index) * 12 + group_index * 4
                )
                message = await _upsert_by_id(
                    session,
                    Message,
                    base_seed.stable_id(f"personal-group-message:{message_key}"),
                    {
                        "conversation_id": conversation.id,
                        "sender_id": users[sender_key].id,
                        "content": content,
                        "created_at": created_at,
                    },
                )
                fixture_message_ids.append(message.id)
            conversation.updated_at = now - timedelta(minutes=group_index * 4)

        await session.flush()
        consent_hashes = {
            group_key: await get_consent_scope_hash(session, conversation.id)
            for group_key, conversation in channel_conversations.items()
        }

        for index, spec in enumerate(TASK_SPECS):
            owner = users[spec["owner"]]
            group_key = spec.get("group")
            if group_key:
                conversation = channel_conversations[group_key]
                source_message = await session.get(
                    Message,
                    base_seed.stable_id(f"message:{spec['source_message']}"),
                )
                if source_message is None or source_message.conversation_id != conversation.id:
                    raise RuntimeError(f"Invalid task source message: {spec['key']}")
                workspace_id = company_id
                agent_workspace_id = delivery.id
                conversation_id = conversation.id
                source = "ai_extracted"
                source_message_ids = [source_message.id]
                source_sender_id = source_message.sender_id
                consent_scope_hash = consent_hashes[group_key]
            else:
                workspace_id = personal_workspaces[spec["owner"]].id
                agent_workspace_id = None
                conversation_id = None
                source = "manual"
                source_message_ids = None
                source_sender_id = None
                consent_scope_hash = None

            due_at = now + timedelta(hours=spec["due_hours"])
            task_id = base_seed.stable_id(f"personal-task:{spec['key']}")
            task = await _upsert_by_id(
                session,
                Task,
                task_id,
                {
                    "workspace_id": workspace_id,
                    "agent_workspace_id": agent_workspace_id,
                    "owner_id": owner.id,
                    "conversation_id": conversation_id,
                    "title": spec["title"],
                    "due_at": due_at,
                    "auto_reminder_enabled": True,
                    "priority": spec["priority"],
                    "status": spec["status"],
                    "blocked_reason": spec.get("blocked_reason"),
                    "source": source,
                    "source_message_ids": source_message_ids,
                    "source_sender_id": source_sender_id,
                    "consent_scope_hash": consent_scope_hash,
                    "invalidated_reason": None,
                    "requires_review": False,
                    "submission_note": None,
                    "evidence_urls": [],
                    "submitted_by_user_id": None,
                    "submitted_at": None,
                    "reviewed_by_user_id": None,
                    "reviewed_at": None,
                    "review_note": None,
                    "created_at": now - timedelta(days=5, hours=index % 6),
                    "updated_at": now - timedelta(hours=index % 5),
                    "started_at": (
                        now - timedelta(days=2, hours=index % 4)
                        if spec["status"] in {"in_progress", "blocked"}
                        else None
                    ),
                    "completed_at": None,
                },
            )
            new_task_ids.append(task.id)

        for owner_key, memories in MEMORY_SPECS.items():
            for index, (category, title, detail, memory_type) in enumerate(memories):
                memory_id = base_seed.stable_id(f"personal-memory:{owner_key}:{index + 1}")
                await _upsert_by_id(
                    session,
                    Memory,
                    memory_id,
                    {
                        "workspace_id": personal_workspaces[owner_key].id,
                        "owner_id": users[owner_key].id,
                        "category": category,
                        "title": title,
                        "detail": detail,
                        "memory_type": memory_type,
                        "source_conversation_id": None,
                        "source_message_ids": [],
                        "consent_scope_hash": None,
                        "sensitivity": "normal",
                        "confidence": 1.0,
                        "expires_at": None,
                        "last_accessed_at": None,
                        "created_at": now - timedelta(days=10 - index),
                        "updated_at": now,
                    },
                )
                fixture_memory_ids.append(memory_id)

        await session.commit()
        public_user_ids = [user.id for user in users.values()]
        direct_conversation_ids = [conversation.id for conversation in direct_conversations.values()]
        personal_group_conversation_ids = [
            conversation.id for conversation in personal_group_conversations.values()
        ]

    # Reconcile through the production service so reminder ownership, lead time, and lifecycle
    # follow exactly the same business rules as tasks created through the API.
    for user_id in public_user_ids:
        await reconcile_user_task_reminders(user_id)

    async with async_session_maker() as session:
        per_account_rows = (
            await session.execute(
                select(
                    User.email,
                    func.count(func.distinct(Task.id)).label("tasks"),
                    func.count(func.distinct(Reminder.id)).label("reminders"),
                    func.count(func.distinct(Memory.id)).label("memories"),
                )
                .outerjoin(Task, Task.owner_id == User.id)
                .outerjoin(Reminder, Reminder.owner_id == User.id)
                .outerjoin(Memory, Memory.owner_id == User.id)
                .where(User.id.in_(public_user_ids))
                .group_by(User.email)
                .order_by(User.email)
            )
        ).all()
        direct_message_count = await session.scalar(
            select(func.count(Message.id)).where(Message.conversation_id.in_(direct_conversation_ids))
        )
        personal_group_message_count = await session.scalar(
            select(func.count(Message.id)).where(
                Message.conversation_id.in_(personal_group_conversation_ids)
            )
        )
        fixture_message_count = await session.scalar(
            select(func.count(Message.id)).where(Message.id.in_(fixture_message_ids))
        )
        fixture_task_rows = list(
            (await session.execute(select(Task).where(Task.id.in_(new_task_ids)))).scalars()
        )
        fixture_memory_count = await session.scalar(
            select(func.count(Memory.id)).where(Memory.id.in_(fixture_memory_ids))
        )
        granted_permission_count = await session.scalar(
            select(func.count())
            .select_from(AIPermission)
            .where(
                AIPermission.conversation_id.in_(direct_conversation_ids),
                AIPermission.granted.is_(True),
                AIPermission.contribution_allowed.is_(True),
            )
        )
        delivery_message_count = await session.scalar(
            select(func.count(Message.id)).where(
                Message.conversation_id.in_([row.id for row in channel_conversations.values()])
            )
        )
        enabled_personal_group_count = await session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.id.in_(personal_group_conversation_ids),
                Conversation.type == "group",
                Conversation.ai_enabled.is_(True),
                Conversation.ai_policy_version >= 1,
            )
        )
        personal_group_participant_count = await session.scalar(
            select(func.count())
            .select_from(ConversationParticipant)
            .where(
                ConversationParticipant.conversation_id.in_(personal_group_conversation_ids),
                ConversationParticipant.revoked_at.is_(None),
            )
        )

        personal_workspace_ids = {workspace.id for workspace in personal_workspaces.values()}
        invalid_fixture_tasks = 0
        for task in fixture_task_rows:
            if task.agent_workspace_id is None:
                valid = (
                    task.workspace_id in personal_workspace_ids
                    and task.conversation_id is None
                    and task.source == "manual"
                    and not task.source_message_ids
                )
            else:
                valid = (
                    task.agent_workspace_id == delivery.id
                    and task.workspace_id == company_id
                    and task.conversation_id is not None
                    and task.source == "ai_extracted"
                    and bool(task.source_message_ids)
                    and bool(task.consent_scope_hash)
                )
            invalid_fixture_tasks += 0 if valid else 1

        expected_permission_count = len(DIRECT_CONVERSATIONS) * 2
        expected_direct_message_count = sum(len(item["messages"]) for item in DIRECT_CONVERSATIONS)
        expected_group_message_count = sum(len(item["messages"]) for item in GROUP_CONVERSATIONS)
        expected_message_count = expected_direct_message_count + expected_group_message_count
        expected_group_participant_count = sum(
            len(item["participants"]) for item in GROUP_CONVERSATIONS
        )
        if len(fixture_task_rows) != len(TASK_SPECS) or invalid_fixture_tasks:
            raise RuntimeError("Personal Agent fixture task integrity check failed")
        if fixture_message_count != expected_message_count:
            raise RuntimeError("Personal Agent fixture message integrity check failed")
        if fixture_memory_count != sum(len(items) for items in MEMORY_SPECS.values()):
            raise RuntimeError("Personal Agent fixture memory integrity check failed")
        if granted_permission_count != expected_permission_count:
            raise RuntimeError("Personal Agent fixture AI permission integrity check failed")
        if personal_group_message_count != expected_group_message_count:
            raise RuntimeError("Personal Agent fixture group message integrity check failed")
        if enabled_personal_group_count != len(GROUP_CONVERSATIONS):
            raise RuntimeError("Personal Agent fixture group-wide AI policy check failed")
        if personal_group_participant_count != expected_group_participant_count:
            raise RuntimeError("Personal Agent fixture group participant integrity check failed")

    return {
        "fixture_namespace": FIXTURE_NAMESPACE,
        "public_accounts": [base_seed.DEMO_USERS[key][0] for key in PUBLIC_USER_KEYS],
        "direct_conversations": len(direct_conversation_ids),
        "personal_group_conversations": len(personal_group_conversation_ids),
        "fixture_direct_messages": expected_direct_message_count,
        "fixture_personal_group_messages": expected_group_message_count,
        "fixture_messages_total": fixture_message_count,
        "direct_messages_total": direct_message_count,
        "personal_group_messages_total": personal_group_message_count,
        "delivery_channel_messages": delivery_message_count,
        "fixture_tasks": len(new_task_ids),
        "fixture_memories": sum(len(items) for items in MEMORY_SPECS.values()),
        "integrity_checks": {
            "invalid_fixture_tasks": invalid_fixture_tasks,
            "granted_direct_ai_permissions": granted_permission_count,
            "enabled_personal_group_ai_policies": enabled_personal_group_count,
            "personal_group_participants": personal_group_participant_count,
        },
        "per_account_totals": [
            {"email": email, "tasks": tasks, "reminders": reminders, "memories": memories}
            for email, tasks, reminders, memories in per_account_rows
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Create or update the Personal Agent demo fixture")
    args = parser.parse_args()
    if not args.apply:
        print("Preview only. Run with --apply to seed the Personal Agent demo fixture.")
        print(
            f"Adds {len(DIRECT_CONVERSATIONS)} direct conversations, "
            f"{sum(len(item['messages']) for item in DIRECT_CONVERSATIONS)} direct messages, "
            f"{len(GROUP_CONVERSATIONS)} personal group chats, "
            f"{sum(len(item['messages']) for item in GROUP_CONVERSATIONS)} personal group messages, "
            f"{len(TASK_SPECS)} tasks, and {sum(len(items) for items in MEMORY_SPECS.values())} memories."
        )
        return 0
    try:
        manifest = asyncio.run(seed_personal_agent_demo())
    except Exception as exc:  # CLI boundary with a concise, non-secret diagnostic.
        print(f"PERSONAL AGENT DEMO SEED FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("PERSONAL AGENT DEMO SEED COMPLETE")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
