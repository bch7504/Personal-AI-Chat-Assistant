"""Normalized, policy-versioned Quality control plane and readiness engine."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    QualityDefect,
    QualityEvidence,
    QualityPolicy,
    QualityRequirement,
    QualityTestCase,
    QualityTestRun,
    QualityWaiver,
    ReleaseCandidate,
)

DEFAULT_POLICY_VERSION = "quality-gate-v2"
DEFAULT_POLICY_RULES: dict[str, Any] = {
    "block_severities": ["critical", "high"],
    "required_test_kinds": ["functional", "security"],
    "require_verified_evidence": True,
    "allow_waivers": True,
}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def serialize_record(record: Any) -> dict[str, Any]:
    return {column.name: getattr(record, column.name) for column in record.__table__.columns}


async def load_quality_control_plane(
    db: AsyncSession,
    *,
    workspace_id: str,
    agent_workspace_id: str,
    release_id: str,
    conversation_ids: tuple[str, ...],
) -> dict[str, Any]:
    def scope(model):
        return (
            model.workspace_id == workspace_id,
            model.agent_workspace_id == agent_workspace_id,
            model.release_id == release_id,
            model.conversation_id.in_(conversation_ids),
        )

    requirements = list(
        (await db.execute(select(QualityRequirement).where(*scope(QualityRequirement)))).scalars().all()
    )
    test_cases = list((await db.execute(select(QualityTestCase).where(*scope(QualityTestCase)))).scalars().all())
    test_runs = list((await db.execute(select(QualityTestRun).where(*scope(QualityTestRun)))).scalars().all())
    defects = list((await db.execute(select(QualityDefect).where(*scope(QualityDefect)))).scalars().all())
    evidence = list((await db.execute(select(QualityEvidence).where(*scope(QualityEvidence)))).scalars().all())
    waivers = list(
        (
            await db.execute(
                select(QualityWaiver).where(
                    QualityWaiver.workspace_id == workspace_id,
                    QualityWaiver.agent_workspace_id == agent_workspace_id,
                    QualityWaiver.release_id == release_id,
                )
            )
        )
        .scalars()
        .all()
    )
    policy = (
        (
            await db.execute(
                select(QualityPolicy)
                .where(
                    QualityPolicy.workspace_id == workspace_id,
                    QualityPolicy.agent_workspace_id == agent_workspace_id,
                    QualityPolicy.status == "active",
                )
                .order_by(QualityPolicy.approved_at.desc(), QualityPolicy.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    candidate = (
        (
            await db.execute(
                select(ReleaseCandidate)
                .where(
                    ReleaseCandidate.organization_workspace_id == workspace_id,
                    ReleaseCandidate.quality_agent_workspace_id == agent_workspace_id,
                    ReleaseCandidate.release_key == release_id,
                )
                .order_by(ReleaseCandidate.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    rules = {**DEFAULT_POLICY_RULES, **(policy.rules if policy else {})}
    policy_version = policy.version if policy else DEFAULT_POLICY_VERSION
    now = datetime.now(UTC)
    valid_waiver_targets = {
        (waiver.target_type, waiver.target_id)
        for waiver in waivers
        if waiver.status == "approved" and _aware(waiver.expires_at) > now
    }
    evidence_by_id = {item.id: item for item in evidence}
    active_requirements = [item for item in requirements if item.status == "active"]
    active_cases = [item for item in test_cases if item.status == "active"]
    cases_by_requirement: dict[str, list[QualityTestCase]] = {}
    for case in active_cases:
        if case.requirement_id:
            cases_by_requirement.setdefault(case.requirement_id, []).append(case)
    latest_runs: dict[str, QualityTestRun] = {}
    for run in sorted(test_runs, key=lambda item: item.created_at):
        latest_runs[run.test_case_id] = run

    blockers: list[str] = []
    risks: list[str] = []
    uncovered = [
        requirement.requirement_key
        for requirement in active_requirements
        if requirement.required
        and not cases_by_requirement.get(requirement.id)
        and ("requirement", requirement.id) not in valid_waiver_targets
    ]
    if uncovered:
        blockers.append("REQUIRED_REQUIREMENT_WITHOUT_TEST")
    kinds = {case.test_kind for case in active_cases}
    missing_kinds = sorted(set(rules["required_test_kinds"]) - kinds)
    if missing_kinds:
        blockers.append("REQUIRED_TEST_KIND_MISSING")

    required_cases = [
        case for case in active_cases if case.required or case.test_kind in set(rules["required_test_kinds"])
    ]
    blocked_case_ids: list[str] = []
    for case in required_cases:
        run = latest_runs.get(case.id)
        # A waiver is bound to a concrete test-run id. It cannot replace the
        # execution itself, so a required case with no run is always blocking.
        if run is None:
            blocked_case_ids.append(case.id)
            continue
        if candidate and (run.build_number != candidate.build_number or run.environment != candidate.environment):
            blockers.append("TEST_RUN_BUILD_OR_ENVIRONMENT_MISMATCH")
        if run.status != "passed" and ("test_run", run.id) not in valid_waiver_targets:
            blocked_case_ids.append(case.id)
        if rules["require_verified_evidence"]:
            artifact = evidence_by_id.get(run.evidence_id or "")
            if artifact is None or artifact.verification_status != "verified":
                blockers.append("VERIFIED_TEST_EVIDENCE_REQUIRED")
    if blocked_case_ids:
        blockers.append("REQUIRED_TEST_NOT_PASSED")

    open_defects = [defect for defect in defects if defect.status not in {"resolved", "verified", "waived", "closed"}]
    blocking_severities = set(rules["block_severities"])
    blocking_defects = [
        defect
        for defect in open_defects
        if defect.severity in blocking_severities and ("defect", defect.id) not in valid_waiver_targets
    ]
    if blocking_defects:
        blockers.append("BLOCKING_DEFECT_ACTIVE")
    if any(defect not in blocking_defects for defect in open_defects):
        risks.append("NON_BLOCKING_DEFECT_ACTIVE")
    if any(waiver.status == "pending" for waiver in waivers):
        risks.append("WAIVER_DECISION_PENDING")

    domain_present = bool(requirements or test_cases or test_runs or defects or evidence or waivers or policy)
    if candidate is None:
        blockers.append("RELEASE_CANDIDATE_NOT_FOUND")
    elif candidate.quality_policy_version != policy_version:
        blockers.append("QUALITY_POLICY_VERSION_MISMATCH")
    unique_blockers = list(dict.fromkeys(blockers))
    unique_risks = list(dict.fromkeys(risks))
    readiness = "NOT_READY" if unique_blockers else "AT_RISK" if unique_risks else "READY"
    if not domain_present:
        readiness = "INSUFFICIENT_DATA"
    traceability = {
        "requirement_count": len(active_requirements),
        "required_requirement_count": sum(item.required for item in active_requirements),
        "covered_requirement_count": sum(bool(cases_by_requirement.get(item.id)) for item in active_requirements),
        "uncovered_requirement_keys": uncovered,
        "coverage_percent": (
            round(
                sum(bool(cases_by_requirement.get(item.id)) for item in active_requirements)
                / len(active_requirements)
                * 100
            )
            if active_requirements
            else 0
        ),
    }
    return {
        "domain_present": domain_present,
        "release_id": release_id,
        "policy": {
            "version": policy_version,
            "status": policy.status if policy else "default",
            "rules": rules,
        },
        "assessment": {
            "release_readiness": readiness,
            "reasons": [*unique_blockers, *unique_risks],
            "blockers": unique_blockers,
            "risks": unique_risks,
            "test_progress": {
                "total": len(active_cases),
                "completed": sum(
                    latest_runs.get(case.id) is not None and latest_runs[case.id].status in {"passed", "failed"}
                    for case in active_cases
                ),
            },
            "critical_defects": [serialize_record(item) for item in open_defects if item.severity == "critical"],
            "blocked_tests": blocked_case_ids,
            "release_candidate_id": candidate.id if candidate else None,
            "build_number": candidate.build_number if candidate else None,
            "environment": candidate.environment if candidate else None,
        },
        "traceability": traceability,
        "requirements": [serialize_record(item) for item in requirements],
        "test_cases": [serialize_record(item) for item in test_cases],
        "test_runs": [serialize_record(item) for item in test_runs],
        "defects": [serialize_record(item) for item in defects],
        "evidence": [serialize_record(item) for item in evidence],
        "waivers": [serialize_record(item) for item in waivers],
    }
