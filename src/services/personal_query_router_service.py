"""Hybrid intent routing helpers for the Personal Agent.

The router deliberately separates intent classification from authorization and
safety.  Deterministic rules cover high-confidence commands; the existing
semantic domain classifier supplies the fallback intent for natural phrasing.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

PersonalIntent = Literal[
    "capability_help",
    "memory_write",
    "memory_search",
    "task_management",
    "calendar",
    "reminder",
    "chat_analysis",
    "people_search",
    "small_talk",
    "general_work",
    "unclear",
]
RoutingStrategy = Literal["deterministic", "semantic"]


@dataclass(frozen=True)
class PersonalQueryRoute:
    intent: PersonalIntent
    routing_strategy: RoutingStrategy
    confidence: float
    reason_code: str


@dataclass(frozen=True)
class PersonalMemoryDraft:
    category: str
    title: str
    detail: str


def normalize_for_routing(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    without_marks = without_marks.replace("đ", "d").replace("Đ", "D")
    return re.sub(r"[^a-z0-9]+", " ", without_marks.casefold()).strip()


_EXPLICIT_MEMORY_WRITE_PATTERNS = (
    r"\b(hay|vui long|lam on)?\s*(goi|xung ho voi)\s+(toi|min[h]?)\s+la\b",
    r"\b(call me|address me as|refer to me as)\b",
    r"\b(hay|vui long|lam on|toi muon)?\s*(ban\s+)?(ghi nho|nho rang|nho giup|remember that)\b",
    r"\b(muon|can)\s+ban\s+(ghi nho|nho)\b",
    r"\bban\s+nho\s+(toi|minh)\s+(la|rat|thich|khong thich|muon|uu tien)\b",
    r"\b(hay|vui long|lam on)\s+nho\s+(toi|minh)\s+(la|rat|thich|khong thich|muon|uu tien)\b",
    r"\b(tu gio|ke tu bay gio|from now on)\b.{0,100}\b(goi toi|xung ho|tra loi|phan hoi|call me)\b",
)


def is_explicit_personal_memory_request(text: str) -> bool:
    normalized = normalize_for_routing(text)
    return any(re.search(pattern, normalized) for pattern in _EXPLICIT_MEMORY_WRITE_PATTERNS)


_PERSONAL_MEMORY_LOOKUP_PATTERNS = (
    r"\b(ban|orbit)\s+co\s+nho\b.{0,100}\b(toi|ve toi|cach xung ho|goi toi|so thich)\b",
    r"\b(ban|orbit)\s+nho\s+gi\s+ve\s+toi\b",
    r"\b(cach xung ho|goi toi la gi|toi da bao ban goi toi|ten toi|so thich cua toi)\b",
    r"\b(do you remember|what do you remember)\b.{0,100}\b(me|about me|call me|my preference)\b",
    r"\b(memory|ghi nho|ky uc)\s+(cua|ve)\s+toi\b",
    r"\b(tom tat|liet ke|cho toi biet).{0,80}\b(nhung gi )?(ban|orbit)\s+(da\s+)?nho\b",
    r"\b(nhung gi )?(ban|orbit)\s+(da\s+)?nho\s+ve\b",
    r"\bnho\s+ve\s+(cach|phong cach|thoi quen|quy trinh)\s+toi\s+lam\s+viec\b",
)


def is_personal_memory_lookup_request(text: str) -> bool:
    normalized = normalize_for_routing(text)
    return any(re.search(pattern, normalized) for pattern in _PERSONAL_MEMORY_LOOKUP_PATTERNS)


def _matches(text: str, *patterns: str) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


_CAPABILITY_PATTERNS = (
    r"\b(ban|orbit)\s+(la ai|lam duoc (?:nhung )?gi|co the lam (?:nhung )?gi|"
    r"giup (?:toi )?(?:duoc )?(?:nhung )?gi|co the giup|co (?:kha nang|chuc nang) gi)\b",
    r"\b(nhung viec gi|viec gi|nhung gi)\s+(ban|orbit)\s+(lam duoc|co the lam|co the giup)\b",
    r"\b(kha nang|chuc nang|pham vi ho tro)\s+(cua\s+)?(ban|orbit)\b",
    r"\b(who are you|what can you do|how can you help|what can orbit do|your capabilities)\b",
)


def is_capability_request(text: str) -> bool:
    """Recognize natural questions about Orbit itself without an LLM round trip."""

    return _matches(normalize_for_routing(text), *_CAPABILITY_PATTERNS)


def classify_personal_query(
    text: str,
    *,
    semantic_intent: str | None = None,
) -> PersonalQueryRoute:
    """Return a stable Personal intent without making an authorization decision."""

    normalized = normalize_for_routing(text)
    if is_capability_request(text):
        return PersonalQueryRoute("capability_help", "deterministic", 1.0, "CAPABILITY_HELP")
    if is_personal_memory_lookup_request(text):
        return PersonalQueryRoute("memory_search", "deterministic", 1.0, "PERSONAL_MEMORY_LOOKUP")
    if is_explicit_personal_memory_request(text):
        return PersonalQueryRoute("memory_write", "deterministic", 1.0, "EXPLICIT_MEMORY_WRITE")
    if _matches(normalized, r"\b(tim|xem|liet ke|search|find|show)\b.{0,60}\b(memory|ghi nho|ky uc)\b"):
        return PersonalQueryRoute("memory_search", "deterministic", 0.98, "MEMORY_SEARCH")
    if _matches(normalized, r"\b(task|tasks|nhiem vu|cong viec|to do|deadline|han chot)\b"):
        return PersonalQueryRoute("task_management", "deterministic", 0.96, "TASK_KEYWORD")
    if _matches(normalized, r"\b(lich|calendar|cuoc hop|meeting|su kien|event|dat lich)\b"):
        return PersonalQueryRoute("calendar", "deterministic", 0.96, "CALENDAR_KEYWORD")
    if _matches(normalized, r"\b(nhac toi|nhac nho|remind|reminder)\b"):
        return PersonalQueryRoute("reminder", "deterministic", 0.96, "REMINDER_KEYWORD")
    if _matches(normalized, r"\b(tom tat|summar|hoi thoai|conversation|tin nhan|message|chat)\b"):
        return PersonalQueryRoute("chat_analysis", "deterministic", 0.94, "CHAT_ANALYSIS_KEYWORD")
    if _matches(normalized, r"\b(dong nghiep|coworker|cong tac|ai nen tham gia|who should)\b"):
        return PersonalQueryRoute("people_search", "deterministic", 0.92, "PEOPLE_KEYWORD")
    if _matches(normalized, r"^(xin chao|chao|hello|hi|hey|cam on|thanks)\b"):
        return PersonalQueryRoute("small_talk", "deterministic", 0.99, "SMALL_TALK")

    semantic_map: dict[str, PersonalIntent] = {
        "task_management": "task_management",
        "calendar_reminder": "calendar",
        "memory": "memory_search",
        "authorized_chat_analysis": "chat_analysis",
        "professional_communication": "general_work",
        "technical_work": "general_work",
        "small_talk": "small_talk",
        "unclear": "unclear",
        "out_of_scope": "unclear",
    }
    if semantic_intent:
        return PersonalQueryRoute(
            semantic_map.get(semantic_intent, "general_work"),
            "semantic",
            0.85,
            f"SEMANTIC_{semantic_intent.upper()}",
        )
    # This router only runs after the guardrail has allowed the request.  A
    # broad but valid work request is therefore a governed deterministic route,
    # not a provider failure or an answer fallback.
    return PersonalQueryRoute("general_work", "deterministic", 0.75, "GUARDRAIL_ALLOWED_WORK")


def extract_explicit_memory_drafts(text: str) -> tuple[PersonalMemoryDraft, ...]:
    """Extract only user-explicit, low-risk preferences; never infer hidden traits."""

    stripped = " ".join((text or "").strip().split())
    drafts: list[PersonalMemoryDraft] = []

    alias_match = re.search(
        r"(?:hãy\s+|vui\s+lòng\s+|làm\s+ơn\s+)?(?:gọi|xưng\s+hô\s+với)\s+"
        r"(?:tôi|mình|người\s+dùng)\s+là\s+[\"“”']?(.+?)[\"“”']?"
        r"(?=\s+(?:mỗi\s+khi|khi|từ\s+giờ|nhé|nha)\b|[,.!?]|$)",
        stripped,
        flags=re.IGNORECASE,
    )
    if alias_match is None:
        alias_match = re.search(
            r"\b(?:call me|address me as|refer to me as)\s+[\"“”']?(.+?)[\"“”']?"
            r"(?=\s+(?:from now on|when)\b|[,.!?]|$)",
            stripped,
            flags=re.IGNORECASE,
        )
    if alias_match is not None:
        alias = re.sub(
            r"(?:\s+(?:đi|nhé|nha|thôi))+$",
            "",
            alias_match.group(1),
            flags=re.IGNORECASE,
        ).strip()
        if alias:
            drafts.append(
                PersonalMemoryDraft(
                    category="interaction",
                    title="Cách xưng hô",
                    detail=f'Gọi người dùng là “{alias[:80]}”.',
                )
            )

    normalized = normalize_for_routing(stripped)
    if "can than" in normalized and "cach lam viec" in normalized:
        drafts.append(
            PersonalMemoryDraft(
                category="work_style",
                title="Phong cách làm việc",
                detail="Người dùng rất cẩn thận trong cách làm việc.",
            )
        )

    if not drafts:
        # The caller already proved this was an explicit remember request. Keep the user's own
        # wording rather than inventing a trait, and bound it to the Memory schema limit.
        drafts.append(
            PersonalMemoryDraft(
                category="preference",
                title="Ghi nhớ do người dùng yêu cầu",
                detail=stripped[:10_000],
            )
        )
    return tuple(drafts)
