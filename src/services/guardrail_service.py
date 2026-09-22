"""Deterministic safety and domain guardrails for the Orbit agent.

The LLM is deliberately not the security boundary. These checks run before the
planner, while the system prompt and policy tool provide a second layer for
novel requests. Conversation text is untrusted data and is escaped/redacted
before being embedded in any prompt.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from src.services.personal_query_router_service import (
    is_capability_request,
    is_explicit_personal_memory_request,
    is_personal_memory_lookup_request,
)

MAX_UNTRUSTED_TEXT_CHARS = 100_000


@dataclass(frozen=True)
class GuardrailDecision:
    allowed: bool
    category: str
    reason: str
    response: str


_INJECTION_PATTERNS = (
    r"\bignore.{0,50}\b(previous|prior|above|system|developer|instruction|rule)",
    r"\b(disregard|override|bypass).{0,50}\b(instruction|rule|policy|guardrail|system|developer)",
    r"\b(system prompt|developer message|hidden instruction|jailbreak|dan mode|developer mode)\b",
    r"\b(show|print|repeat|reveal|leak).{0,40}\b(system prompt|developer message|hidden instruction|secret)",
    r"\bbo qua.{0,50}\b(chi dan|huong dan|quy tac|prompt|he thong|system|guardrail)",
    r"\b(quen|vo hieu hoa|ghi de|pha bo).{0,50}\b(chi dan|huong dan|quy tac|prompt|he thong)",
    r"\b(hien|in|lap lai|tiet lo|cho xem).{0,40}\b(prompt he thong|system prompt|chi dan an|bi mat)",
    r"\b(gia vo|dong vai).{0,60}\b(khong bi gioi han|khong co quy tac|bo qua quy tac)",
    r"\b(act as|pretend to be|you are now).{0,40}\b(system|developer|unrestricted|dan)\b",
    r"\b(tu gio|bay gio).{0,30}\b(ban la|vai tro cua ban).{0,30}\b(he thong|khong gioi han)",
    r"(?:<|\[)\s*(system|developer)\s*(?:>|\])",
    r"\b(new|updated|replacement) instructions?\s*:",
    r"\b(decode|base64|giai ma).{0,40}\b(follow|execute|lam theo|thuc thi).{0,40}\b(instruction|chi dan)",
    r"\b(base64|rot13|hex encoded|encoded payload)\b",
    r"\b(do anything now|no restrictions?|without restrictions?|unfiltered mode)\b",
    r"\b(chi dan moi|lenh moi|quy tac moi)\s*:",
)

_COMPACT_INJECTION_TERMS = (
    "ignorepreviousinstructions",
    "ignoresysteminstructions",
    "revealsystemprompt",
    "showdevelopermessage",
    "bypassguardrail",
    "boquachidanhethong",
    "tietloprompthethong",
    "vohieuhoaquytac",
)

# These are intentionally intent-shaped patterns, not single forbidden words.
# A work reminder such as "nhắc tôi đi khám" must not be blocked merely because
# it mentions health; requests for diagnosis or dangerous instructions are.
_SENSITIVE_CATEGORIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "criminal_activity",
        "lập kế hoạch, hỗ trợ hoặc tạo điều kiện cho hành vi vi phạm pháp luật",
        (
            r"\b(an trom|trom cap|moc tui|cuop|cuop giat|dot nhap|be khoa|pha khoa)\b",
            r"\b(lua dao|gian lan|tong tien|bat coc|buon lau|buon nguoi|rua tien|hoi lo)\b",
            # Accent stripping makes several harmless work phrases collide with crime terms:
            # "khách hàng cam kết" -> "hang cam", "ưu tiên gia hạn" -> "tien gia",
            # "làm gia tăng" -> "lam gia", and "tất cả do" -> "ca do". Keep the
            # policy intent-shaped instead of blocking those ordinary business phrases.
            r"(?<!khach )\bhang cam\b",
            r"(?<!uu )\btien gia\b",
            r"\blam gia\b(?=.{0,35}\b(?:giay to|chung tu|hoa don|bang chung|du lieu|chu ky|"
            r"san pham|hang hoa|nhan mac)\b)",
            r"\b(gia mao|pha hoai|dot nha|phi tang|danh bac)\b",
            r"(?<!tat )\bca do\b(?=.{0,35}\b(?:bong da|the thao|truc tuyen|an tien|nha cai)\b)",
            r"\b(vuot bien|nhap canh trai phep|mai dam|ban dam|mua ban noi tang)\b",
            r"\b(san ban dong vat|chat pha rung|khai thac trai phep|tron lenh trung phat)\b",
            r"\b(pham phap|vi pham phap luat|bat hop phap|hanh vi pham toi)\b",
            r"\b(che giau|xoa|huy|phi tang).{0,35}\b(bang chung|chung cu|dau vet)\b",
            r"\b(tron|ne|vuot).{0,30}\b(canh sat|cong an|truy na|kiem tra an ninh)\b",
            r"\b(steal|theft|burglary|robbery|shoplift|fraud|scam|extortion|kidnap|smuggl)\w*\b",
            r"\b(rob(?:bing|bed)?|mug(?:ging|ged)?|pickpocket)\w*\b",
            r"\b(break into|pick (?:a )?lock).{0,30}\b(house|home|shop|store|office|car|building)\b",
            r"\b(contraband|counterfeit|illegal gambling|tax evasion|trespass)\w*\b",
            r"\b(human trafficking|money laundering|bribery|forge documents?|vandal(?:ism|ize)|arson)\b",
            r"\b(identity theft|organ trafficking|wildlife trafficking|poaching|sanctions evasion)\b",
            r"\b(insider trading|market manipulation|smuggle weapons?)\b",
            r"\b(illegal activity|commit (?:a )?crime|criminal act)\b",
            r"\b(hide|destroy|erase|dispose of).{0,35}\b(evidence|traces?)\b",
            r"\b(evade|escape|avoid).{0,30}\b(police|law enforcement|security check)\b",
        ),
    ),
    (
        "self_harm",
        "tự gây hại hoặc tự sát",
        (
            r"\b(tu tu|tu sat|tu huy hoai|cat tay|self harm|suicide)\b",
            r"\b(cach chet|chet khong dau|ket lieu ban than)\b",
        ),
    ),
    (
        "sexual_content",
        "nội dung tình dục hoặc khiêu dâm",
        (
            r"\b(khieu dam|porn|pornography|nude|anh nong|noi dung 18\+|tinh duc)\b",
            r"\b(sex|sexual).{0,30}\b(explicit|content|story|image|video)\b",
            r"\b(hiep dam|xam hai tinh duc|cuong buc tinh duc|mai dam tre em)\b",
            r"\b(rape|sexual assault|child sexual|sexual exploitation)\b",
        ),
    ),
    (
        "violence_weapons",
        "hướng dẫn bạo lực, vũ khí hoặc chất nổ",
        (
            r"\b(cach|huong dan|che tao|lam|mua|su dung).{0,45}\b(bom|sung|vu khi|thuoc no)\b",
            r"\b(giet|sat hai|tan cong|danh|dam|chem).{0,35}\b(nguoi|dong nghiep|nan nhan|muc tieu)\b",
            # Accent stripping turns both "bạn" and "bắn" into "ban". Require the shooting
            # verb to be immediately action-shaped instead of matching any later word "người".
            r"\bban\s+(?:vao\s+|trung\s+|chet\s+|ha\s+)?(nguoi|dong nghiep|nan nhan|muc tieu)\b",
            r"\b(build|make|buy|use).{0,35}\b(bomb|gun|weapon|explosive)\b",
            r"\b(kill|murder|attack|assault|shoot|stab).{0,30}\b(person|coworker|victim|target|someone)\b",
            r"\b(dau doc|bo thuoc doc|am sat|tra tan).{0,30}\b(nguoi|dong nghiep|nan nhan|muc tieu)?\b",
            r"\b(poison|assassinate|torture).{0,30}\b(person|coworker|victim|target|someone)?\b",
        ),
    ),
    (
        "illegal_drugs",
        "hướng dẫn liên quan đến ma túy hoặc chất cấm",
        (
            r"\b(cach|huong dan|che|nau|mua|su dung|van chuyen).{0,45}\b(ma tuy|meth|cocaine|fentanyl|heroin)\b",
            r"\bban\s+(ma tuy|meth|cocaine|fentanyl|heroin)\b",
            r"\b(make|cook|buy|sell|transport|smuggle).{0,35}\b(meth|cocaine|fentanyl|heroin|illegal drug)\b",
        ),
    ),
    (
        "cyber_abuse",
        "xâm nhập, đánh cắp dữ liệu hoặc phá hoại hệ thống",
        (
            r"\b(hack|phishing|malware|ransomware|ddos|keylogger)\b",
            r"\b(danh cap|lay trom|be khoa|vuot qua|bypass).{0,40}\b(mat khau|otp|tai khoan|xac thuc|auth)\b",
            r"\b(sql injection|credential stuffing|reverse shell)\b",
            r"\b(exploit|backdoor|botnet|zero[ -]?day|session hijack|token theft)\b",
            # Keep the destructive verb as a complete word. Without the trailing boundary,
            # ``pha`` also matched the start of the ordinary business phrase ``pham vi``
            # ("scope"). When a task list later contained ``du lieu`` on the next item, the
            # normalized multi-line text was incorrectly classified as cyber abuse.
            r"\b(pha|xoa|ma hoa|chiem quyen)\b.{0,35}\b(he thong|may chu|du lieu|tai khoan)\b",
        ),
    ),
    (
        "privacy_abuse",
        "thu thập hoặc tiết lộ dữ liệu cá nhân nhạy cảm",
        (
            r"\b(doxx|doxing|theo doi trai phep)\b",
            r"\b(ghi am len|quay len|camera an|nghe len|doc trom tin nhan)\b",
            r"\b(tim|lay|tiet lo|cong khai|danh cap).{0,45}\b(otp|cvv|so the|private key|mat khau|dia chi nha)\b",
            r"\b(stalk|spy on|track secretly|surveil).{0,35}\b(person|coworker|partner|employee|someone)\b",
        ),
    ),
    (
        "harassment_abuse",
        "đe dọa, quấy rối, cưỡng ép hoặc ngược đãi người khác",
        (
            r"\b(quay roi|bat nat|de doa|tong tien|cuong ep|ep buoc|tra tan|khung bo tinh than)\b",
            r"\b(harass|bully|threaten|blackmail|coerce|torture|intimidate)\w*\b",
            r"\b(revenge porn|nonconsensual intimate|khong co su dong thuan)\b",
        ),
    ),
    (
        "intellectual_property_abuse",
        "xâm phạm bản quyền hoặc vượt cơ chế cấp phép",
        (
            r"\b(phan mem crack|crack ban quyen|key crack|tai lau|vi pham ban quyen|pha drm)\b",
            r"\b(keygen|pirated (?:software|movie|book)|software crack|crack(?:ing)? (?:a )?license|bypass drm|copyright piracy)\b",
        ),
    ),
    (
        "deception_abuse",
        "lừa dối, giả danh, bôi nhọ hoặc phát tán thông tin sai lệch có chủ đích",
        (
            r"\b(gia danh|mao danh|boi nho|vu khong|phat tan tin gia|tao bang chung gia)\b",
            r"\b(impersonate|defame|fabricate evidence|spread (?:fake news|disinformation))\b",
            r"\b(deepfake).{0,30}\b(tong tien|lua dao|boi nho|blackmail|fraud|defame)\b",
        ),
    ),
    (
        "regulated_advice",
        "tư vấn chuyên môn y tế, pháp lý hoặc tài chính có rủi ro cao",
        (
            r"\b(chan doan|ke don|lieu dung).{0,45}\b(benh|thuoc|dieu tri)\b",
            r"\b(tu van phap ly|lach luat|tron thue|che giau tai san)\b",
            r"\b(cam ket loi nhuan|bao dam loi|all in).{0,35}\b(co phieu|crypto|tien ao|ca cuoc)\b",
        ),
    ),
    (
        "political_persuasion",
        "vận động hoặc thao túng quan điểm chính trị",
        (
            r"\b(thuyet phuc|van dong|tuyen truyen).{0,45}\b(bau cho|ung vien|dang phai|chinh tri)\b",
            r"\b(persuade|target|campaign).{0,45}\b(voter|candidate|political party)\b",
        ),
    ),
    (
        "hate_extremism",
        "thù ghét, cực đoan hoặc khủng bố",
        (
            r"\b(khung bo|cuc doan|diet chung|thuong dang chung toc)\b",
            r"\b(terroris|genocide|racial supremac|ethnic cleansing)\w*\b",
        ),
    ),
)

# Compact matching catches basic separator/zero-width obfuscation such as
# "ă.n t.r.ộ.m", "p h i  t a n g" and "ignore_previous_instructions".
_COMPACT_SENSITIVE_TERMS: dict[str, tuple[str, ...]] = {
    "criminal_activity": (
        "antrom",
        "tromcap",
        "phitangbangchung",
        "luadao",
        "buonlau",
        "ruatien",
        "lamgiagiayto",
        "breakintoahouse",
        "destroytheevidence",
        "moneylaundering",
        "humantrafficking",
    ),
    "self_harm": ("tutu", "tusat", "selfharm", "suicide"),
    "sexual_content": ("khieudam", "noidung18", "pornography"),
    "violence_weapons": ("chetaobom", "chetaovu khi", "buildabomb", "makeaweapon"),
    "illegal_drugs": ("chetaomatuy", "naumeth", "cookmeth", "sellillegaldrugs"),
    "cyber_abuse": ("danhcapmatkhau", "sqlinjection", "credentialsstuffing", "reverseshell"),
    "privacy_abuse": ("tietlootp", "doxxing", "theodoitraiphep"),
    "harassment_abuse": ("quayroi", "batnat", "khungbotinhthan", "revengeporn"),
    "intellectual_property_abuse": ("phanmemcrack", "bypassdrm", "piratedsoftware"),
    "deception_abuse": ("phattantingia", "maodanh", "fabricateevidence", "spreadfakenews"),
}

_WORK_DOMAIN_PATTERNS = (
    r"\b(cong viec|nhiem vu|tasks?|to[ -]?dos?|deadlines?|han chot|uu tien|priorit(?:y|ies))\b",
    r"\b(lich|calendars?|cuoc hop|meetings?|sync|su kien|events?|dat lich|book)\b",
    # Short calendar follow-ups are common in a private assistant thread. They are still scoped
    # to the authenticated user's calendar by the tool layer; allowing them here avoids turning
    # a legitimate "move the review" into an unnecessary semantic-classifier round trip.
    r"\b(move|cancel|delete|update|reschedul(?:e|ing)|show|list)\b.{0,60}\b(review|demo|sync|meeting|event|calendar|schedule|reminder)\b",
    r"\b(tuan nay|tuan toi|hom nay|ngay mai|this week|next week|today|tomorrow)\b.{0,40}\b(toi co gi|co gi|what do i have|what's on)\b",
    # Natural Vietnamese often puts the time range last: "Tôi có việc gì cần làm ngày mai?".
    # Keep this intent-shaped (work noun + relative date) rather than allowing every "tôi có gì".
    r"\b(toi co|co)\b.{0,20}\b(viec gi|gi can lam|task nao|nhiem vu nao)\b.{0,30}\b(hom nay|ngay mai|tuan nay|tuan toi)\b",
    r"\b(nhac|nhac nho|remind|reminders?|memor(?:y|ies)|schedule)\w*\b",
    r"\b(ghi nho|remember)\b.{0,80}\b(cong viec|du an|task|meeting|cuoc hop|agenda|ticket|build|release)\b",
    r"\b(len ke hoach (?:hom nay|cong viec|du an)|ke hoach (?:cong viec|du an)|work plans?|project plans?)\b",
    r"\b(du an|projects?|nhom|teams?|dong nghiep|khach hang|clients?|workspaces?|standups?)\b",
    r"\b(emails?|bao cao|reports?|tai lieu|documents?|bien ban|agendas?|presentations?)\b",
    r"\b(hoi thoai|conversation|tin nhan|message|chat|tom tat|summar|trich xuat|extract|tim kiem|search)\w*\b",
    r"\b(nang suat|productivity|work profiles?|ho so cong viec)\b",
    r"\b(pham vi|policy|guardrail|quy tac an toan)\b",
    # Engineering/work identifiers are often supplied as terse facts before a follow-up. Requiring
    # the word "project" in "Mã thử nghiệm là BLUE-42" caused a false out-of-domain refusal and
    # broke working-memory tests even though test/release identifiers are normal work context.
    r"\b(ma (?:thu nghiem|du an|ticket|task|release|build)|test (?:code|id|identifier)|"
    r"ticket|sprints?|releases?|builds?|branches?|repositories?|repos?|staging|production)\b",
)

_SMALL_TALK_PATTERNS = (
    r"^(xin chao|chao|hello|hi|hey)(\b|[!.?, ])",
    r"^(cam on|thanks|thank you)(\b|[!.?, ])",
    r"^(tam biet|bye|goodbye)(\b|[!.?, ])",
)

# Workspace Agents are narrow domain applications, not general assistants.  These
# profile patterns sit above the broad Personal Agent work classifier so a word
# such as "plan" cannot turn sport, politics or general knowledge into Delivery
# work.  Matching always runs on accent-stripped normalized variants.
_DELIVERY_WORKSPACE_PATTERNS = (
    r"\b(delivery|tasks?|work items?|blockers?|dependencies|dependency|checkpoints?|milestones?|"
    r"release readiness|release 34|go[ /-]?no[ -]?go|portfolio health|critical path)\b",
    r"\b(tien do|cong viec|nhiem vu|bi chan|go chan|phu thuoc|moc ban giao|diem kiem soat|"
    r"phat hanh|giao dung han|quyet dinh|can chot|cho chot|nguoi phu trach|owner|deadline|"
    r"scope|baseline|uat|crm|crash rate|nhom|group|team)\b",
    r"\b(submitted|changes requested|lead review|quality review|completion percent|overdue|at risk)\b",
)

_QUALITY_WORKSPACE_PATTERNS = (
    r"\b(quality|qa|tests?|test cases?|defects?|bugs?|regression|automation|manual smoke|"
    r"release readiness|release gate|readiness|ready|not ready|sign[ -]?off|evidence|traceability|"
    r"retest|builds?|r-demo|r[0-9][a-z0-9-]*)\b",
    r"\b(kiem thu|chat luong|loi|khuyet tat|bang chung|cong phat hanh|san sang phat hanh|"
    r"xac minh|tieu chi chap nhan|blocked test|failed test|critical defect)\b",
)

_EXPLICIT_NON_WORKSPACE_PATTERNS = (
    r"\b(hoang sa|truong sa|bien dong|chu quyen|lanh tho|territorial sovereignty|south china sea)\b",
    r"\b(chinh tri|bau cu|tong thong|thu tuong|dang phai|quoc hoi|ngoai giao|chien tranh|"
    r"politics|election|president|prime minister|political party|geopolitics)\b",
    r"\b(thu do|nuoc nao|quoc gia nao|lich su|dia ly|capital of|which country|history of|geography)\b",
    r"\b(thoi tiet|weather|ty gia|exchange rate|gia co phieu|stock price|ket qua bong da|"
    r"football score|nau an|cong thuc mon|recipe|phim|movie|tu vi|horoscope)\b",
)


def _workspace_domain_refusal(profile: str) -> GuardrailDecision:
    profile_name = "Quality Assurance" if profile == "quality_assurance" else "Product Delivery"
    capabilities = (
        "test, defect, evidence, release gate và QA readiness"
        if profile == "quality_assurance"
        else "task, tiến độ, blocker, dependency, checkpoint, milestone, decision và release readiness"
    )
    return GuardrailDecision(
        allowed=False,
        category="out_of_domain",
        reason=f"chủ đề nằm ngoài phạm vi {profile_name}",
        response=(
            f"Yêu cầu này nằm ngoài phạm vi {profile_name} Workspace Agent. "
            f"Tôi chỉ có thể hỗ trợ {capabilities} trong phạm vi workspace được cấp quyền."
        ),
    )


def evaluate_workspace_request(
    text: str,
    *,
    profile: str,
    allow_ambiguous: bool = False,
) -> GuardrailDecision:
    """Apply hard safety plus a narrow profile-domain boundary before any model.

    ``allow_ambiguous`` lets the server-owned semantic router resolve terse
    in-thread references. Explicit general-knowledge topics are never allowed by
    that escape hatch.
    """

    normalized_text = " ".join(_normalized_variants(text))
    unsupported_approval_assumption = (
        any(
            phrase in normalized_text
            for phrase in (
                "gia su qa da approve",
                "gia su qa approved",
                "assume qa approved",
                "assume qa has approved",
                "coi nhu qa da approve",
            )
        )
        and any(
            phrase in normalized_text
            for phrase in ("ready", "san sang", "on track", "on_track")
        )
    )
    if unsupported_approval_assumption:
        return GuardrailDecision(
            allowed=False,
            category="unsupported_evidence_override",
            reason="yêu cầu giả định phê duyệt hoặc bằng chứng chưa tồn tại để đổi trạng thái",
            response=(
                "Tôi không thể giả định QA đã phê duyệt hoặc đổi readiness khi chưa có bằng chứng được phép. "
                "Tôi sẽ giữ trạng thái xác định từ dữ liệu hiện có và nêu rõ bằng chứng còn thiếu."
            ),
        )

    base = evaluate_request(text)
    if not base.allowed and base.category != "out_of_domain":
        return base

    domain_patterns = (
        _QUALITY_WORKSPACE_PATTERNS
        if profile == "quality_assurance"
        else _DELIVERY_WORKSPACE_PATTERNS
    )
    if _matches_any(text, domain_patterns):
        return GuardrailDecision(
            allowed=True,
            category=f"{profile}_work",
            reason="Yêu cầu thuộc đúng domain Workspace Agent đang hoạt động.",
            response="",
        )
    if _matches_any(text, _EXPLICIT_NON_WORKSPACE_PATTERNS):
        return _workspace_domain_refusal(profile)
    if base.allowed and base.category == "small_talk":
        return base
    if allow_ambiguous:
        return GuardrailDecision(
            allowed=True,
            category="workspace_ambiguous",
            reason="Yêu cầu chưa rõ được chuyển cho router để hỏi làm rõ, không cấp thêm quyền.",
            response="",
        )
    return _workspace_domain_refusal(profile)

_FOLLOW_UP_PATTERNS = (
    r"\b(khoang thoi gian|time range|date range)\b",
    r"\b(\d+|mot|hai|ba|bay|muoi|may)\s*(phut|gio|ngay|tuan|thang|minutes?|hours?|days?|weeks?|months?)\b",
    r"\b(hom qua|hom truoc|may ngay truoc|tuan truoc|thang truoc|last (?:few )?(?:days?|weeks?|months?))\b",
    r"\b(hom nay|ngay mai|tuan nay|tuan sau|thang nay|thang sau|today|tomorrow|this week|next week)\b",
    r"\b(tu .{1,40} den .{1,40}|from .{1,40} to .{1,40})\b",
    r"^(dung|dung roi|ok|okay|co|khong|yes|no|correct|the first|the second|cai dau|cai thu hai)[!. ]*$",
    r"^(xac nhan|toi xac nhan|dong y|chap nhan|confirm|confirmed|approve|approved)[!. ]*$",
    r"^(cai do|lich do|task do|cuoc hop do|phuong an do|that one|that event|that task)\b",
)

_CLARIFYING_QUESTION_PATTERNS = (
    r"\?\s*$",
    r"\b(ban muon|ban can|khoang thoi gian nao|ngay nao|luc nao|which|what time|what date|how many)\b",
    r"\b(tra loi|go|nhap|chon|bam|reply).{0,50}\b(xac nhan|confirm|approve)\b",
    r"\b(xac nhan|confirm|approve).{0,50}\b(de|to)\s+(tao|create|dat lich|schedule)\b",
)

_SECRET_OUTPUT_PATTERNS = (
    r"(?:postgres(?:ql)?|mysql|mariadb|mongodb|redis)(?:\+\w+)?://[^\s]+",
    r"\bsk-[a-z0-9_-]{16,}\b",
    r"\baiza[a-z0-9_-]{20,}\b",
    r"\bakia[a-z0-9]{16}\b",
    r"\beyj[a-z0-9_-]{10,}\.[a-z0-9_-]{10,}\.[a-z0-9_-]{10,}\b",
    r"\b(?:api[_ -]?key|secret[_ -]?key|database[_ -]?url|password)\s*[:=]\s*[^\s,;]{8,}",
    r"-----begin [^-]*private key-----",
)


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    without_marks = without_marks.replace("đ", "d").replace("Đ", "D")
    without_marks = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]", "", without_marks)
    return without_marks.casefold().strip()


def _normalized_variants(text: str) -> tuple[str, ...]:
    normalized = _normalize(text)
    canonical = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    leetspeak = normalized.translate(
        str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"})
    )
    leetspeak = re.sub(r"[^a-z0-9]+", " ", leetspeak).strip()
    collapsed = re.sub(r"(.)\1{2,}", r"\1\1", leetspeak)
    return tuple(dict.fromkeys((normalized, canonical, leetspeak, collapsed)))


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(
        re.search(pattern, variant, flags=re.IGNORECASE | re.DOTALL)
        for variant in _normalized_variants(text)
        for pattern in patterns
    )


def _compact_variants(text: str) -> tuple[str, ...]:
    return tuple(re.sub(r"[^a-z0-9]", "", variant) for variant in _normalized_variants(text))


def _contains_compact_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in compact for compact in _compact_variants(text) for term in terms)


def _sensitive_decision(text: str) -> GuardrailDecision | None:
    for category, reason, patterns in _SENSITIVE_CATEGORIES:
        compact_terms = _COMPACT_SENSITIVE_TERMS.get(category, ())
        if _matches_any(text, patterns) or _contains_compact_term(text, compact_terms):
            return _refusal(category, reason)
    return None


def _refusal(category: str, reason: str) -> GuardrailDecision:
    return GuardrailDecision(
        allowed=False,
        category=category,
        reason=reason,
        response=(
            f"Orbit từ chối yêu cầu này vì nội dung liên quan đến {reason}. "
            "Yêu cầu nằm ngoài phạm vi hỗ trợ an toàn của hệ thống. Orbit chỉ hỗ trợ công việc, "
            "lịch, nhiệm vụ, nhắc nhở, ghi nhớ và xử lý hội thoại phục vụ công việc."
        ),
    )


def evaluate_request(text: str, *, conversation_mode: bool = False) -> GuardrailDecision:
    """Classify one user request before any LLM or tool is called."""
    if _matches_any(text, _INJECTION_PATTERNS) or _contains_compact_term(
        text, _COMPACT_INJECTION_TERMS
    ):
        return _refusal(
            "prompt_injection",
            "dấu hiệu cố ghi đè chỉ dẫn, vượt guardrail hoặc yêu cầu tiết lộ prompt hệ thống",
        )

    sensitive = _sensitive_decision(text)
    if sensitive is not None:
        return sensitive

    # Lookup questions can contain write-shaped fragments (for example "tôi đã bảo bạn gọi tôi
    # là gì?"). Resolve reads first so asking what was remembered never overwrites Memory.
    if is_personal_memory_lookup_request(text):
        return GuardrailDecision(
            True,
            "personal_memory_lookup",
            "Người dùng đang truy vấn hoặc kiểm tra Personal Memory của chính mình.",
            "",
        )
    if is_explicit_personal_memory_request(text):
        return GuardrailDecision(
            True,
            "personal_memory",
            "Người dùng yêu cầu rõ ràng lưu một sở thích hoặc cách tương tác cá nhân.",
            "",
        )
    if is_capability_request(text):
        return GuardrailDecision(
            True,
            "capability_help",
            "Người dùng đang hỏi về danh tính hoặc phạm vi hỗ trợ của Orbit.",
            "",
        )
    if _matches_any(text, _WORK_DOMAIN_PATTERNS):
        return GuardrailDecision(True, "work", "Yêu cầu thuộc domain công việc của Orbit.", "")
    if _matches_any(text, _SMALL_TALK_PATTERNS):
        return GuardrailDecision(True, "small_talk", "Tương tác xã giao an toàn.", "")

    # ``conversation_mode`` is passed onward to the semantic classifier by guardrail_node. Access
    # to a conversation is permission to analyse that chat, not blanket permission for unrelated
    # questions, so it must no longer auto-allow everything here.
    return _refusal(
        "out_of_domain",
        "chủ đề ngoài domain công việc và xử lý hội thoại của Orbit",
    )


def evaluate_request_with_history(
    text: str,
    *,
    previous_user_text: str = "",
    previous_assistant_text: str = "",
    conversation_mode: bool = False,
) -> GuardrailDecision:
    """Classify a request while preserving safe elliptical follow-ups in one thread.

    Hard policy checks always run on the new message first. History is consulted only when the
    new message was rejected solely as out-of-domain, the preceding user request was a valid work
    request, and the new text looks like a short answer to a time/choice clarification. This keeps
    "7 ngày trước" working without allowing an unrelated question to inherit permission from an
    earlier work turn.
    """
    decision = evaluate_request(text, conversation_mode=conversation_mode)
    if decision.allowed or decision.category != "out_of_domain":
        return decision
    if not previous_user_text or len(text) > 300 or not _matches_any(text, _FOLLOW_UP_PATTERNS):
        return decision

    previous = evaluate_request(previous_user_text, conversation_mode=conversation_mode)
    if not previous.allowed or previous.category not in {"work", "conversation"}:
        return decision

    is_time_or_reference = _matches_any(text, _FOLLOW_UP_PATTERNS[:5] + (_FOLLOW_UP_PATTERNS[-1],))
    assistant_asked = _matches_any(previous_assistant_text, _CLARIFYING_QUESTION_PATTERNS)
    if not is_time_or_reference and not assistant_asked:
        return decision

    return GuardrailDecision(
        True,
        "work_follow_up",
        "Câu trả lời tiếp nối một yêu cầu công việc hợp lệ trong cùng thread.",
        "",
    )


def evaluate_context(text: str) -> GuardrailDecision:
    """Apply hard sensitive-topic checks to conversation data.

    Prompt-injection-looking lines are redacted separately rather than causing
    the whole conversation to fail; this lets users safely summarize a chat in
    which somebody attempted an injection.
    """
    sensitive = _sensitive_decision(text)
    if sensitive is not None:
        return sensitive
    return GuardrailDecision(True, "conversation_data", "Dữ liệu hội thoại được phép.", "")


def evaluate_action_content(text: str) -> GuardrailDecision:
    """Validate tool arguments immediately before a state-changing action.

    This is deliberately separate from domain classification: an ordinary event title such as
    "Dentist" may be valid even though it contains no work keyword. Injection and sensitive or
    illegal objectives still fail closed, including edits made during confirmation.
    """
    if _matches_any(text, _INJECTION_PATTERNS) or _contains_compact_term(
        text, _COMPACT_INJECTION_TERMS
    ):
        return _refusal(
            "prompt_injection",
            "dấu hiệu cố ghi đè chỉ dẫn hoặc lợi dụng nội dung của công cụ để điều khiển hệ thống",
        )
    sensitive = _sensitive_decision(text)
    if sensitive is not None:
        return sensitive
    return GuardrailDecision(True, "safe_action", "Nội dung hành động đạt guardrail.", "")


def evaluate_output(text: str) -> GuardrailDecision:
    """Fail closed if generated output leaks secrets/prompts or unsafe instructions."""
    if _matches_any(text, _SECRET_OUTPUT_PATTERNS):
        return _refusal("secret_leakage", "thông tin xác thực hoặc bí mật hệ thống")
    if _matches_any(
        text,
        (
            r"\b(my|the) system prompt (is|says|:)\b",
            r"\bdeveloper (message|instruction) (is|says|:)\b",
            r"\bprompt he thong (la|noi|:)\b",
            r"<\s*(system|developer)(?:\s|>)",
            r"\bnon-negotiable safety and domain policy\b",
        ),
    ):
        return _refusal("prompt_leakage", "nội dung prompt hoặc chỉ dẫn nội bộ")
    sensitive = _sensitive_decision(text)
    if sensitive is not None:
        return sensitive
    return GuardrailDecision(True, "safe_output", "Phản hồi đạt guardrail.", "")


_CYBER_REPORTING_PATTERNS = (
    r"\b(report|assessment|finding|risk|defect|vulnerabilit|severity|remediat|mitigat|"
    r"fix|patch|test|scan|audit|gate|readiness|evidence|release|blocked|passed|failed|"
    r"open|closed|monitor|prevent)\w*\b",
    r"\b(bao cao|danh gia|rui ro|lo hong|khac phuc|giam thieu|kiem thu|quet|"
    r"bang chung|phat hanh|bi chan|da dat|chua dat|theo doi|phong ngua)\b",
)

_CYBER_ENABLEMENT_PATTERNS = (
    r"\b(how to|step by step|steps to|huong dan|cach).{0,80}\b(hack|phishing|malware|"
    r"ransomware|ddos|keylogger|sql injection|credential stuffing|reverse shell|exploit)\b",
    r"\b(run|execute|use|send|inject|deploy|write|create|build|thuc thi|chay|gui|tao|"
    r"viet).{0,50}\b(payload|malware|ransomware|keylogger|reverse shell|sql injection|"
    r"credential stuffing)\b",
    r"\b(steal|exfiltrate|danh cap|lay trom).{0,50}\b(password|credential|token|session|"
    r"data|mat khau|tai khoan|du lieu)\b",
)

_DELIVERY_BUSINESS_THREAT_PATTERNS = (
    r"\b(threat|threaten|de doa).{0,60}\b(delivery|release|timeline|schedule|milestone|deadline|plan|"
    r"tien do|phat hanh|moc|han chot|ke hoach)\b",
    r"\b(delivery|release|timeline|schedule|milestone|deadline|plan|tien do|phat hanh|moc|"
    r"han chot|ke hoach).{0,60}\b(threat|threaten|de doa)\b",
)

_HARASSMENT_ENABLEMENT_PATTERNS = (
    r"\b(how to|step by step|write|draft|send|huong dan|cach|viet|gui).{0,80}\b("
    r"harass|bully|threaten|blackmail|coerce|intimidate|quay roi|bat nat|de doa|tong tien|cuong ep)\b",
    r"\b(harass|bully|threaten|blackmail|coerce|intimidate|quay roi|bat nat|de doa|tong tien|cuong ep)"
    r".{0,50}\b(person|coworker|employee|manager|someone|nguoi|dong nghiep|nhan vien)\b",
)


def _evaluate_defensive_reporting_output(text: str) -> GuardrailDecision:
    """Allow defensive work reporting while retaining hard output protections.

    A QA or Delivery brief must be able to name a security finding such as phishing or SQL
    injection. The generic guardrail intentionally blocks those terms early, so
    this narrower policy only relaxes a cyber-abuse decision when the response is
    clearly a report and contains no procedural or enablement language. Secret and
    prompt leakage, and every other sensitive category, remain fail-closed.
    """

    decision = evaluate_output(text)
    if decision.allowed or decision.category != "cyber_abuse":
        return decision
    if _matches_any(text, _CYBER_ENABLEMENT_PATTERNS):
        return decision
    if _matches_any(text, _CYBER_REPORTING_PATTERNS):
        return GuardrailDecision(
            allowed=True,
            category="defensive_security_reporting",
            reason="Phản hồi chỉ báo cáo rủi ro hoặc kết quả kiểm thử phòng thủ.",
            response="",
        )
    return decision


def evaluate_quality_output(text: str) -> GuardrailDecision:
    """Allow defensive QA findings while retaining hard output protections."""

    return _evaluate_defensive_reporting_output(text)


def evaluate_delivery_output(text: str) -> GuardrailDecision:
    """Allow defensive Delivery risk/blocker reporting, never attack enablement."""

    decision = _evaluate_defensive_reporting_output(text)
    if decision.allowed or decision.category != "harassment_abuse":
        return decision
    if _matches_any(text, _HARASSMENT_ENABLEMENT_PATTERNS):
        return decision
    if _matches_any(text, _DELIVERY_BUSINESS_THREAT_PATTERNS):
        return GuardrailDecision(
            allowed=True,
            category="business_risk_reporting",
            reason="Phản hồi mô tả rủi ro đối với tiến độ hoặc phát hành, không nhắm vào con người.",
            response="",
        )
    return decision


def evaluate_workspace_output(text: str, *, profile: str) -> GuardrailDecision:
    """Apply safety and profile-domain checks after model synthesis.

    Business reports may mention an external factor when it is tied to an
    authorized Delivery/QA fact. A standalone general-knowledge answer fails
    closed even if an upstream routing defect allowed a model call.
    """

    decision = (
        evaluate_quality_output(text)
        if profile == "quality_assurance"
        else evaluate_delivery_output(text)
    )
    if not decision.allowed:
        return decision
    domain_patterns = (
        _QUALITY_WORKSPACE_PATTERNS
        if profile == "quality_assurance"
        else _DELIVERY_WORKSPACE_PATTERNS
    )
    if _matches_any(text, _EXPLICIT_NON_WORKSPACE_PATTERNS) and not _matches_any(
        text, domain_patterns
    ):
        return _workspace_domain_refusal(profile)
    return decision


def sanitize_untrusted_text(text: str) -> str:
    """Escape delimiters and redact obvious prompt-injection lines in user data."""
    safe_lines: list[str] = []
    truncated = (text or "")[:MAX_UNTRUSTED_TEXT_CHARS]
    for line in truncated.splitlines():
        if _matches_any(line, _INJECTION_PATTERNS) or _contains_compact_term(
            line, _COMPACT_INJECTION_TERMS
        ):
            safe_lines.append("[Đã ẩn một dòng có dấu hiệu prompt injection]")
            continue
        escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        safe_lines.append(escaped)
    if len(text or "") > MAX_UNTRUSTED_TEXT_CHARS:
        safe_lines.append("[Dữ liệu đã được cắt bớt vì vượt giới hạn an toàn]")
    return "\n".join(safe_lines)


def wrap_untrusted_text(text: str, *, label: str = "conversation_data") -> str:
    safe_label = re.sub(r"[^a-z0-9_-]", "_", label.lower())
    return f"<{safe_label}>\n{sanitize_untrusted_text(text)}\n</{safe_label}>"
