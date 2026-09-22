from __future__ import annotations

import copy
from collections import Counter

from scripts.generate_multi_agent_dataset import OUTPUT_PATH, build_cases, render_cases
from scripts.validate_multi_agent_dataset import EXPECTED_CATEGORIES, load_and_validate, validate_cases


def test_multi_agent_dataset_is_current_valid_and_balanced():
    generated = build_cases()
    stored, errors = load_and_validate(OUTPUT_PATH)

    assert errors == []
    assert len(stored) == 150
    assert Counter(case["category"] for case in stored) == {
        category: 15 for category in EXPECTED_CATEGORIES
    }
    assert render_cases(generated) == OUTPUT_PATH.read_text(encoding="utf-8")


def test_dataset_covers_all_three_profiles_and_security_decisions():
    cases = build_cases()

    assert {case["expected"]["agent_profile"] for case in cases} >= {
        "product_delivery",
        "quality_assurance",
        "executive",
        "none",
    }
    assert {case["expected"]["policy_decision"] for case in cases} == {
        "ALLOW",
        "DENY",
        "MASK",
        "REQUIRE_APPROVAL",
    }
    assert any(case["expected"]["forbidden_source_ids"] for case in cases)
    assert all(case["expected"]["requires_hitl"] for case in cases if case["category"] == "hitl")


def test_executive_never_requires_raw_message_memory_or_secret():
    cases = build_cases()

    for case in cases:
        expected = case["expected"]
        if expected["agent_profile"] != "executive" or expected["policy_decision"] == "DENY":
            continue
        required = set(expected["required_source_ids"])
        required_types = {
            resource["type"] for resource in case["context"]["resources"] if resource["id"] in required
        }
        assert not required_types & {"message", "memory", "secret"}, case["case_id"]


def test_quality_readiness_rules_have_not_ready_at_risk_and_ready_cases():
    cases = [case for case in build_cases() if case["category"] == "quality_readiness"]

    assert Counter(case["expected"]["release_readiness"] for case in cases) == {
        "NOT_READY": 5,
        "AT_RISK": 5,
        "READY": 5,
    }
    for case in cases:
        resource = case["context"]["resources"][0]
        if resource["metadata"]["severity"] == "critical":
            assert case["expected"]["release_readiness"] == "NOT_READY"


def test_validator_rejects_cross_reference_and_hitl_policy_regressions():
    cases = copy.deepcopy(build_cases())
    cases[0]["expected"]["required_source_ids"] = ["missing-source"]
    hitl_case = next(case for case in cases if case["category"] == "hitl")
    hitl_case["expected"]["policy_decision"] = "ALLOW"

    errors = validate_cases(cases)

    assert any("source không tồn tại" in error for error in errors)
    assert any("HITL phải có REQUIRE_APPROVAL" in error for error in errors)


def test_permission_and_revoke_cases_fail_closed():
    cases = build_cases()
    security_cases = [
        case
        for case in cases
        if case["category"] in {"workspace_permission", "membership_consent_revoke"}
    ]

    assert len(security_cases) == 30
    assert all(case["expected"]["policy_decision"] == "DENY" for case in security_cases)
    assert all(case["expected"]["agent_profile"] == "none" for case in security_cases)
    assert all(case["expected"]["required_source_ids"] == [] for case in security_cases)
