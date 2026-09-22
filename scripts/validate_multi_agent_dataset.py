"""Validate the canonical Orbit multi-agent workspace JSONL dataset."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "eval" / "datasets" / "multi_agent_workspace_v1.jsonl"

EXPECTED_CATEGORIES = {
    "delivery_summary",
    "quality_readiness",
    "executive_aggregate",
    "routing",
    "workspace_permission",
    "prompt_injection",
    "hitl",
    "stale_partial_brief",
    "membership_consent_revoke",
    "cross_workspace_dependency",
}
EXPECTED_PROFILES = {"product_delivery", "quality_assurance", "executive", "none"}
EXPECTED_POLICIES = {"ALLOW", "DENY", "MASK", "REQUIRE_APPROVAL"}
EXPECTED_SCOPES = {"personal", "workspace", "aggregate"}
EXPECTED_READINESS = {None, "READY", "AT_RISK", "NOT_READY"}
EXPECTED_CLASSIFICATIONS = {"public", "internal", "restricted", "secret", "aggregate"}
CASE_ID_RE = re.compile(r"^[A-Z]{3}-\d{3}$")
REQUIRED_TOP_LEVEL = {
    "schema_version",
    "case_id",
    "category",
    "title",
    "tags",
    "actor",
    "request",
    "context",
    "expected",
}
REQUIRED_ACTOR = {
    "user_id",
    "organization_workspace_id",
    "workspace_role",
    "business_role",
    "agent_workspace_ids",
}
REQUIRED_REQUEST = {"text", "requested_scope", "target_agent_workspace_id", "intent"}
REQUIRED_CONTEXT = {
    "membership_state",
    "consent_state",
    "consent_scope_hash",
    "brief_freshness",
    "resources",
}
REQUIRED_EXPECTED = {
    "agent_profile",
    "policy_decision",
    "policy_reason",
    "expected_action",
    "required_source_ids",
    "forbidden_source_ids",
    "requires_hitl",
    "expected_facts",
    "data_gaps",
    "release_readiness",
}


def load_cases(path: Path = DEFAULT_DATASET) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    cases: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], [f"Không đọc được dataset: {exc}"]
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"Dòng {line_number}: JSON không hợp lệ: {exc}")
            continue
        if not isinstance(value, dict):
            errors.append(f"Dòng {line_number}: case phải là JSON object")
            continue
        cases.append(value)
    return cases, errors


def _missing(required: set[str], value: dict[str, Any]) -> set[str]:
    return required - value.keys()


def _resource_ids(case: dict[str, Any]) -> tuple[set[str], list[str]]:
    errors: list[str] = []
    ids: list[str] = []
    for resource in case.get("context", {}).get("resources", []):
        if not isinstance(resource, dict):
            errors.append("resource phải là object")
            continue
        resource_id = resource.get("id")
        if not isinstance(resource_id, str) or not resource_id:
            errors.append("resource thiếu id")
            continue
        ids.append(resource_id)
        if resource.get("classification") not in EXPECTED_CLASSIFICATIONS:
            errors.append(f"{resource_id}: classification không hợp lệ")
        if not str(resource.get("type", "")).strip():
            errors.append(f"{resource_id}: type không được rỗng")
        if not str(resource.get("content", "")).strip():
            errors.append(f"{resource_id}: content không được rỗng")
        if not isinstance(resource.get("metadata"), dict):
            errors.append(f"{resource_id}: metadata phải là object")
    duplicates = sorted(resource_id for resource_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        errors.append(f"resource id trùng: {', '.join(duplicates)}")
    return set(ids), errors


def validate_cases(cases: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if len(cases) != 150:
        errors.append(f"Dataset phải có đúng 150 case, hiện có {len(cases)}")
    case_ids = [case.get("case_id") for case in cases]
    duplicate_ids = sorted(case_id for case_id, count in Counter(case_ids).items() if count > 1)
    if duplicate_ids:
        errors.append(f"Case ID bị trùng: {', '.join(duplicate_ids)}")
    counts = Counter(case.get("category") for case in cases)
    if counts != Counter({category: 15 for category in EXPECTED_CATEGORIES}):
        errors.append(f"Mỗi category phải có đúng 15 case, hiện tại: {dict(sorted(counts.items()))}")

    for index, case in enumerate(cases, 1):
        case_id = str(case.get("case_id", f"line-{index}"))
        missing_top = _missing(REQUIRED_TOP_LEVEL, case)
        if missing_top:
            errors.append(f"{case_id}: thiếu top-level fields {sorted(missing_top)}")
            continue
        if case["schema_version"] != "1.0":
            errors.append(f"{case_id}: schema_version phải là 1.0")
        if not CASE_ID_RE.fullmatch(case_id):
            errors.append(f"{case_id}: case_id không đúng PREFIX-000")
        if case["category"] not in EXPECTED_CATEGORIES:
            errors.append(f"{case_id}: category không hợp lệ")
        if not str(case["title"]).strip() or not isinstance(case["tags"], list) or not case["tags"]:
            errors.append(f"{case_id}: title/tags không hợp lệ")

        actor = case["actor"]
        request = case["request"]
        context = case["context"]
        expected = case["expected"]
        for label, required, value in (
            ("actor", REQUIRED_ACTOR, actor),
            ("request", REQUIRED_REQUEST, request),
            ("context", REQUIRED_CONTEXT, context),
            ("expected", REQUIRED_EXPECTED, expected),
        ):
            if not isinstance(value, dict):
                errors.append(f"{case_id}: {label} phải là object")
                continue
            missing_fields = _missing(required, value)
            if missing_fields:
                errors.append(f"{case_id}: thiếu {label} fields {sorted(missing_fields)}")
        if any(not isinstance(value, dict) for value in (actor, request, context, expected)):
            continue

        if not str(actor["user_id"]).strip() or not str(actor["organization_workspace_id"]).strip():
            errors.append(f"{case_id}: actor identity không được rỗng")
        if not isinstance(actor["agent_workspace_ids"], list):
            errors.append(f"{case_id}: actor.agent_workspace_ids phải là array")
        if request["requested_scope"] not in EXPECTED_SCOPES:
            errors.append(f"{case_id}: requested_scope không hợp lệ")
        if not str(request["text"]).strip() or not str(request["intent"]).strip():
            errors.append(f"{case_id}: request text/intent không được rỗng")
        if not isinstance(context["resources"], list):
            errors.append(f"{case_id}: context.resources phải là array")
            continue

        resource_ids, resource_errors = _resource_ids(case)
        errors.extend(f"{case_id}: {error}" for error in resource_errors)
        required_sources = expected["required_source_ids"]
        forbidden_sources = expected["forbidden_source_ids"]
        if not isinstance(required_sources, list) or not isinstance(forbidden_sources, list):
            errors.append(f"{case_id}: source lists phải là array")
            continue
        unknown_sources = (set(required_sources) | set(forbidden_sources)) - resource_ids
        if unknown_sources:
            errors.append(f"{case_id}: expected tham chiếu source không tồn tại {sorted(unknown_sources)}")
        overlap = set(required_sources) & set(forbidden_sources)
        if overlap:
            errors.append(f"{case_id}: source vừa required vừa forbidden {sorted(overlap)}")
        if expected["agent_profile"] not in EXPECTED_PROFILES:
            errors.append(f"{case_id}: agent_profile không hợp lệ")
        if expected["policy_decision"] not in EXPECTED_POLICIES:
            errors.append(f"{case_id}: policy_decision không hợp lệ")
        if expected["release_readiness"] not in EXPECTED_READINESS:
            errors.append(f"{case_id}: release_readiness không hợp lệ")
        if not str(expected["policy_reason"]).strip() or not str(expected["expected_action"]).strip():
            errors.append(f"{case_id}: policy_reason/expected_action không được rỗng")
        if not isinstance(expected["requires_hitl"], bool):
            errors.append(f"{case_id}: requires_hitl phải là boolean")

        if expected["policy_decision"] == "DENY":
            if required_sources or expected["requires_hitl"] or expected["agent_profile"] != "none":
                errors.append(f"{case_id}: DENY phải không có required sources/HITL/profile")
        if expected["requires_hitl"]:
            if expected["policy_decision"] != "REQUIRE_APPROVAL":
                errors.append(f"{case_id}: HITL phải có REQUIRE_APPROVAL")
            if not expected["expected_action"].startswith("preview_"):
                errors.append(f"{case_id}: HITL action phải bắt đầu bằng preview_")
        if case["category"] == "hitl" and not expected["requires_hitl"]:
            errors.append(f"{case_id}: hitl category bắt buộc requires_hitl")
        if case["category"] == "stale_partial_brief" and not expected["data_gaps"]:
            errors.append(f"{case_id}: stale/partial case phải có data_gaps")
        if case["category"] == "quality_readiness" and expected["release_readiness"] is None:
            errors.append(f"{case_id}: quality case phải có release_readiness")
        if expected["agent_profile"] == "executive" and expected["policy_decision"] != "DENY":
            raw_required = [
                resource["id"]
                for resource in context["resources"]
                if resource["id"] in required_sources and resource["type"] in {"message", "memory", "secret"}
            ]
            if raw_required:
                errors.append(f"{case_id}: Executive không được require raw sources {raw_required}")
        if context["consent_state"] == "active" and context["consent_scope_hash"] is None:
            errors.append(f"{case_id}: active consent phải có scope hash")
        if context["consent_state"] != "active" and context["consent_scope_hash"] is not None:
            errors.append(f"{case_id}: inactive consent không được có scope hash")

    return errors


def load_and_validate(path: Path = DEFAULT_DATASET) -> tuple[list[dict[str, Any]], list[str]]:
    cases, errors = load_cases(path)
    if errors:
        return cases, errors
    return cases, validate_cases(cases)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", nargs="?", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    cases, errors = load_and_validate(args.dataset)
    if errors:
        print(f"INVALID: {args.dataset}")
        for error in errors:
            print(f"- {error}")
        return 1
    counts = Counter(case["category"] for case in cases)
    print(f"VALID: {args.dataset} | {len(cases)} cases | {len(counts)} categories")
    for category, count in sorted(counts.items()):
        print(f"- {category}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
