"""Normalized Quality control-plane APIs with role-scoped writes and OCC.

Leads own governance and approvals. Members may perform bounded operational
work (submit evidence, execute tests and report/advance their own defects)
inside groups in their live authorization scope.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.context_builder import AgentScopeDeniedError
from src.agents.contracts import BusinessRole
from src.agents.policies.resource_guard import AgentResourceDeniedError, enforce_agent_resource_access
from src.agents.profiles.quality_assurance_runner import QualityPreparationError
from src.api.quality_routes import _prepare
from src.auth.dependencies import get_current_user
from src.db.models import (
    AgentWorkspaceMembership,
    ConversationParticipant,
    QualityDefect,
    QualityEvidence,
    QualityPolicy,
    QualityRequirement,
    QualityTestCase,
    QualityTestRun,
    QualityWaiver,
    ReleaseCandidate,
    User,
)
from src.db.session import get_db
from src.models.quality_control_schemas import (
    QualityControlPlaneOut,
    QualityControlRecordOut,
    QualityDefectCreate,
    QualityEvidenceCreate,
    QualityPolicyCreate,
    QualityRecordTransition,
    QualityRequirementCreate,
    QualityTestCaseCreate,
    QualityTestRunCreate,
    QualityWaiverCreate,
)
from src.services.audit_service import record_audit_event
from src.services.quality_control_service import load_quality_control_plane, serialize_record

router = APIRouter()


async def _quality_write_scope(
    db: AsyncSession,
    *,
    actor: User,
    workspace_id: str,
    agent_workspace_id: str,
    release_id: str,
    conversation_id: str | None,
    require_lead: bool,
):
    try:
        prepared, scope = await _prepare(
            db,
            current_user=actor,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            message="Manage normalized Quality control plane",
            release_id=release_id,
            # A member cannot request a group snapshot. Write authorization is
            # instead resolved from the server-owned allowlist below.
            selected_conversation_id=None,
        )
    except (AgentScopeDeniedError, AgentResourceDeniedError, QualityPreparationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Quality control plane is unavailable"
        ) from None
    if require_lead and prepared.context.actor.business_role != BusinessRole.LEAD:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the Quality Lead can change the control plane",
        )
    if conversation_id is not None:
        try:
            await enforce_agent_resource_access(
                db, context=prepared.context, resource_id=conversation_id
            )
        except AgentResourceDeniedError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Quality record group is outside the actor's authorized scope",
            ) from None
        if conversation_id not in scope.effective_group_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Quality record group is outside the actor's authorized scope",
            )
    return prepared, scope


async def _audit(
    db: AsyncSession,
    *,
    actor: User,
    workspace_id: str,
    agent_workspace_id: str,
    action: str,
    record_type: str,
    record_id: str,
    row_version: int,
) -> None:
    await record_audit_event(
        db,
        actor=actor,
        action=action,
        target_type=record_type,
        target_id=record_id,
        workspace_id=workspace_id,
        metadata={"agent_workspace_id": agent_workspace_id, "row_version": row_version},
    )
    await db.commit()


def _result(record_type: str, record: Any) -> QualityControlRecordOut:
    return QualityControlRecordOut(record_type=record_type, record=serialize_record(record))


@router.get(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/quality/control-plane",
    response_model=QualityControlPlaneOut,
)
async def get_quality_control_plane(
    workspace_id: str,
    agent_workspace_id: str,
    release_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QualityControlPlaneOut:
    try:
        _prepared, scope = await _prepare(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=agent_workspace_id,
            message="Read normalized Quality control plane",
            release_id=release_id,
            selected_conversation_id=None,
        )
    except (AgentScopeDeniedError, AgentResourceDeniedError, QualityPreparationError):
        raise HTTPException(status_code=403, detail="Quality control plane is unavailable") from None
    payload = await load_quality_control_plane(
        db,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        release_id=release_id,
        conversation_ids=scope.effective_group_ids,
    )
    return QualityControlPlaneOut.model_validate(payload)


@router.post(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/quality/requirements",
    response_model=QualityControlRecordOut,
    status_code=201,
)
async def create_requirement(
    workspace_id: str,
    agent_workspace_id: str,
    request: QualityRequirementCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QualityControlRecordOut:
    await _quality_write_scope(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        release_id=request.release_id,
        conversation_id=request.conversation_id,
        require_lead=True,
    )
    record = QualityRequirement(
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        conversation_id=request.conversation_id,
        release_id=request.release_id,
        requirement_key=request.requirement_key,
        title=request.title,
        required=request.required,
        created_by_user_id=current_user.id,
    )
    db.add(record)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Requirement key already exists") from None
    await _audit(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        action="quality_requirement.created",
        record_type="quality_requirement",
        record_id=record.id,
        row_version=record.row_version,
    )
    return _result("requirement", record)


@router.post(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/quality/test-cases",
    response_model=QualityControlRecordOut,
    status_code=201,
)
async def create_test_case(
    workspace_id: str,
    agent_workspace_id: str,
    request: QualityTestCaseCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QualityControlRecordOut:
    await _quality_write_scope(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        release_id=request.release_id,
        conversation_id=request.conversation_id,
        require_lead=True,
    )
    if request.requirement_id:
        requirement = await db.get(QualityRequirement, request.requirement_id)
        if requirement is None or (
            requirement.workspace_id,
            requirement.agent_workspace_id,
            requirement.release_id,
            requirement.conversation_id,
        ) != (workspace_id, agent_workspace_id, request.release_id, request.conversation_id):
            raise HTTPException(status_code=422, detail="Requirement is outside the Quality scope")
    record = QualityTestCase(
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        conversation_id=request.conversation_id,
        release_id=request.release_id,
        requirement_id=request.requirement_id,
        test_case_key=request.test_case_key,
        title=request.title,
        test_kind=request.test_kind,
        required=request.required,
        created_by_user_id=current_user.id,
    )
    db.add(record)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Test-case key already exists") from None
    await _audit(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        action="quality_test_case.created",
        record_type="quality_test_case",
        record_id=record.id,
        row_version=record.row_version,
    )
    return _result("test_case", record)


@router.post(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/quality/evidence",
    response_model=QualityControlRecordOut,
    status_code=201,
)
async def create_evidence(
    workspace_id: str,
    agent_workspace_id: str,
    request: QualityEvidenceCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QualityControlRecordOut:
    await _quality_write_scope(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        release_id=request.release_id,
        conversation_id=request.conversation_id,
        require_lead=False,
    )
    record = QualityEvidence(
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        conversation_id=request.conversation_id,
        release_id=request.release_id,
        artifact_type=request.artifact_type,
        uri=request.uri,
        sha256=request.sha256.lower() if request.sha256 else None,
        metadata_json=request.metadata,
        submitted_by_user_id=current_user.id,
    )
    db.add(record)
    await db.flush()
    await _audit(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        action="quality_evidence.created",
        record_type="quality_evidence",
        record_id=record.id,
        row_version=record.row_version,
    )
    return _result("evidence", record)


@router.post(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/quality/test-runs",
    response_model=QualityControlRecordOut,
    status_code=201,
)
async def create_test_run(
    workspace_id: str,
    agent_workspace_id: str,
    request: QualityTestRunCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QualityControlRecordOut:
    await _quality_write_scope(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        release_id=request.release_id,
        conversation_id=request.conversation_id,
        require_lead=False,
    )
    test_case = await db.get(QualityTestCase, request.test_case_id)
    if test_case is None or (
        test_case.workspace_id,
        test_case.agent_workspace_id,
        test_case.release_id,
        test_case.conversation_id,
    ) != (workspace_id, agent_workspace_id, request.release_id, request.conversation_id):
        raise HTTPException(status_code=422, detail="Test case is outside the Quality scope")
    if request.evidence_id:
        artifact = await db.get(QualityEvidence, request.evidence_id)
        if artifact is None or (
            artifact.workspace_id,
            artifact.agent_workspace_id,
            artifact.release_id,
            artifact.conversation_id,
        ) != (workspace_id, agent_workspace_id, request.release_id, request.conversation_id):
            raise HTTPException(status_code=422, detail="Evidence is outside the release scope")
    if request.release_candidate_id:
        candidate = await db.get(ReleaseCandidate, request.release_candidate_id)
        if candidate is None or candidate.quality_agent_workspace_id != agent_workspace_id:
            raise HTTPException(status_code=422, detail="Release candidate is outside the Quality scope")
    now = datetime.now(UTC)
    record = QualityTestRun(
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        conversation_id=request.conversation_id,
        release_id=request.release_id,
        test_case_id=request.test_case_id,
        release_candidate_id=request.release_candidate_id,
        evidence_id=request.evidence_id,
        build_number=request.build_number,
        environment=request.environment,
        status=request.status,
        executed_by_user_id=current_user.id if request.status != "queued" else None,
        started_at=now if request.status != "queued" else None,
        completed_at=now if request.status in {"passed", "failed", "blocked"} else None,
    )
    db.add(record)
    await db.flush()
    await _audit(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        action="quality_test_run.created",
        record_type="quality_test_run",
        record_id=record.id,
        row_version=record.row_version,
    )
    return _result("test_run", record)


@router.post(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/quality/defects",
    response_model=QualityControlRecordOut,
    status_code=201,
)
async def create_defect(
    workspace_id: str,
    agent_workspace_id: str,
    request: QualityDefectCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QualityControlRecordOut:
    prepared, _scope = await _quality_write_scope(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        release_id=request.release_id,
        conversation_id=request.conversation_id,
        require_lead=False,
    )
    is_member = prepared.context.actor.business_role == BusinessRole.MEMBER
    if is_member and request.owner_id not in {None, current_user.id}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Quality members can only assign defects to themselves",
        )
    scoped_references = (
        (QualityTestRun, request.test_run_id),
        (QualityRequirement, request.requirement_id),
        (QualityEvidence, request.evidence_id),
    )
    for model, reference_id in scoped_references:
        if reference_id is None:
            continue
        reference = await db.get(model, reference_id)
        if reference is None or (
            reference.workspace_id,
            reference.agent_workspace_id,
            reference.release_id,
            reference.conversation_id,
        ) != (workspace_id, agent_workspace_id, request.release_id, request.conversation_id):
            raise HTTPException(status_code=422, detail="Defect reference is outside the Quality scope")
    owner_id = current_user.id if is_member and request.owner_id is None else request.owner_id
    if owner_id is not None:
        participant = (
            await db.execute(
                select(ConversationParticipant.user_id).where(
                    ConversationParticipant.conversation_id == request.conversation_id,
                    ConversationParticipant.user_id == owner_id,
                    ConversationParticipant.revoked_at.is_(None),
                    ConversationParticipant.hidden_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        membership = (
            await db.execute(
                select(AgentWorkspaceMembership.id).where(
                    AgentWorkspaceMembership.agent_workspace_id == agent_workspace_id,
                    AgentWorkspaceMembership.user_id == owner_id,
                    AgentWorkspaceMembership.status == "active",
                )
            )
        ).scalar_one_or_none()
        if participant is None or membership is None:
            raise HTTPException(status_code=422, detail="Defect owner is outside the Quality scope")
    record = QualityDefect(
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        conversation_id=request.conversation_id,
        release_id=request.release_id,
        defect_key=request.defect_key,
        title=request.title,
        severity=request.severity,
        test_run_id=request.test_run_id,
        requirement_id=request.requirement_id,
        evidence_id=request.evidence_id,
        owner_id=owner_id,
        created_by_user_id=current_user.id,
    )
    db.add(record)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Defect key already exists") from None
    await _audit(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        action="quality_defect.created",
        record_type="quality_defect",
        record_id=record.id,
        row_version=record.row_version,
    )
    return _result("defect", record)


@router.post(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/quality/policies",
    response_model=QualityControlRecordOut,
    status_code=201,
)
async def create_policy(
    workspace_id: str,
    agent_workspace_id: str,
    request: QualityPolicyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QualityControlRecordOut:
    _prepared, scope = await _quality_write_scope(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        release_id="policy-management",
        conversation_id=None,
        require_lead=True,
    )
    if not scope.effective_group_ids:
        raise HTTPException(status_code=403, detail="Quality workspace has no authorized source")
    if request.activate:
        active = list(
            (
                await db.execute(
                    select(QualityPolicy).where(
                        QualityPolicy.workspace_id == workspace_id,
                        QualityPolicy.agent_workspace_id == agent_workspace_id,
                        QualityPolicy.status == "active",
                    )
                )
            )
            .scalars()
            .all()
        )
        for previous in active:
            previous.status = "retired"
            previous.row_version += 1
    now = datetime.now(UTC)
    record = QualityPolicy(
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        version=request.version,
        status="active" if request.activate else "draft",
        rules={
            "block_severities": request.block_severities,
            "required_test_kinds": request.required_test_kinds,
            "require_verified_evidence": request.require_verified_evidence,
            "allow_waivers": request.allow_waivers,
        },
        created_by_user_id=current_user.id,
        approved_by_user_id=current_user.id if request.activate else None,
        approved_at=now if request.activate else None,
    )
    db.add(record)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Policy version already exists") from None
    await _audit(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        action="quality_policy.created",
        record_type="quality_policy",
        record_id=record.id,
        row_version=record.row_version,
    )
    return _result("policy", record)


@router.post(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/quality/waivers",
    response_model=QualityControlRecordOut,
    status_code=201,
)
async def create_waiver(
    workspace_id: str,
    agent_workspace_id: str,
    request: QualityWaiverCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QualityControlRecordOut:
    await _quality_write_scope(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        release_id=request.release_id,
        conversation_id=None,
        require_lead=True,
    )
    if request.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="Waiver expiry must be in the future")
    target_models = {
        "defect": QualityDefect,
        "test_run": QualityTestRun,
        "requirement": QualityRequirement,
    }
    target = await db.get(target_models[request.target_type], request.target_id)
    if (
        target is None
        or target.workspace_id != workspace_id
        or target.agent_workspace_id != agent_workspace_id
        or target.release_id != request.release_id
    ):
        raise HTTPException(status_code=422, detail="Waiver target is outside the release scope")
    record = QualityWaiver(
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        release_id=request.release_id,
        target_type=request.target_type,
        target_id=request.target_id,
        reason=request.reason,
        expires_at=request.expires_at,
        requested_by_user_id=current_user.id,
    )
    db.add(record)
    await db.flush()
    await _audit(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        action="quality_waiver.created",
        record_type="quality_waiver",
        record_id=record.id,
        row_version=record.row_version,
    )
    return _result("waiver", record)


_TRANSITIONS = {
    "requirement": (QualityRequirement, {"active": {"deprecated"}, "deprecated": {"active"}}),
    "test_case": (QualityTestCase, {"active": {"deprecated"}, "deprecated": {"active"}}),
    "test_run": (
        QualityTestRun,
        {
            "queued": {"running", "cancelled"},
            "running": {"passed", "failed", "blocked", "cancelled"},
            "failed": {"running"},
            "blocked": {"running"},
        },
    ),
    "defect": (
        QualityDefect,
        {
            "open": {"triaged", "in_progress", "closed"},
            "triaged": {"in_progress", "closed"},
            "in_progress": {"resolved", "closed"},
            "resolved": {"verified", "in_progress"},
            "verified": {"closed", "in_progress"},
            "waived": {"in_progress", "closed"},
        },
    ),
    "evidence": (QualityEvidence, {"pending": {"verified", "rejected"}, "rejected": {"pending"}}),
    "waiver": (QualityWaiver, {"pending": {"approved", "rejected"}, "approved": {"revoked", "expired"}}),
}


@router.patch(
    "/workspaces/{workspace_id}/agent-workspaces/{agent_workspace_id}/quality/records/{record_type}/{record_id}",
    response_model=QualityControlRecordOut,
)
async def transition_quality_record(
    workspace_id: str,
    agent_workspace_id: str,
    record_type: str,
    record_id: str,
    request: QualityRecordTransition,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QualityControlRecordOut:
    definition = _TRANSITIONS.get(record_type)
    if definition is None:
        raise HTTPException(status_code=422, detail="Unsupported Quality record type")
    model, transitions = definition
    record = await db.get(model, record_id)
    if record is None or record.workspace_id != workspace_id or record.agent_workspace_id != agent_workspace_id:
        raise HTTPException(status_code=404, detail="Quality record not found")
    member_operational_record = record_type in {"test_run", "defect"}
    prepared, _scope = await _quality_write_scope(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        release_id=getattr(record, "release_id", "record-management"),
        conversation_id=getattr(record, "conversation_id", None),
        require_lead=not member_operational_record,
    )
    if prepared.context.actor.business_role == BusinessRole.MEMBER:
        owns_record = (
            record_type == "test_run"
            and getattr(record, "executed_by_user_id", None) in {None, current_user.id}
        ) or (
            record_type == "defect"
            and current_user.id
            in {
                getattr(record, "owner_id", None),
                getattr(record, "created_by_user_id", None),
            }
        )
        if not owns_record:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Quality members can only transition their own operational records",
            )
    status_field = "verification_status" if record_type == "evidence" else "status"
    current_status = getattr(record, status_field)
    if request.status not in transitions.get(current_status, set()):
        raise HTTPException(status_code=409, detail="Invalid Quality record transition")
    values: dict[str, Any] = {
        status_field: request.status,
        "row_version": model.row_version + 1,
        "updated_at": datetime.now(UTC),
    }
    if record_type == "evidence":
        values.update(
            verified_by_user_id=current_user.id if request.status == "verified" else None,
            verified_at=datetime.now(UTC) if request.status == "verified" else None,
        )
    if record_type == "test_run":
        if request.status == "running":
            values.update(
                executed_by_user_id=current_user.id,
                started_at=getattr(record, "started_at", None) or datetime.now(UTC),
                completed_at=None,
            )
        elif request.status in {"passed", "failed", "blocked", "cancelled"}:
            values.update(completed_at=datetime.now(UTC))
    if record_type == "waiver":
        active_policy = (
            (
                await db.execute(
                    select(QualityPolicy).where(
                        QualityPolicy.workspace_id == workspace_id,
                        QualityPolicy.agent_workspace_id == agent_workspace_id,
                        QualityPolicy.status == "active",
                    )
                )
            )
            .scalars()
            .first()
        )
        if (
            request.status == "approved"
            and active_policy is not None
            and not active_policy.rules.get("allow_waivers", True)
        ):
            raise HTTPException(status_code=409, detail="Active Quality policy forbids waivers")
        values.update(decided_by_user_id=current_user.id, decided_at=datetime.now(UTC))
    result = await db.execute(
        update(model)
        .where(
            model.id == record_id,
            model.workspace_id == workspace_id,
            model.agent_workspace_id == agent_workspace_id,
            model.row_version == request.expected_row_version,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail="Quality record changed; reload before retrying")
    await db.refresh(record)
    await _audit(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        agent_workspace_id=agent_workspace_id,
        action=f"quality_{record_type}.transitioned",
        record_type=f"quality_{record_type}",
        record_id=record.id,
        row_version=record.row_version,
    )
    return _result(record_type, record)
