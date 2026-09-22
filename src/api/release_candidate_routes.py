"""Structured, durable handoff between Product Delivery and Quality Assurance."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.context_builder import AgentScopeDeniedError
from src.agents.contracts import AgentProfile, BusinessRole
from src.agents.policies.resource_guard import AgentResourceDeniedError, enforce_agent_resource_access
from src.agents.profiles.product_delivery_runner import ProductDeliveryPreparationError
from src.agents.profiles.quality_assurance_runner import QualityPreparationError
from src.agents.schemas.quality import QualityWorkItem
from src.agents.tools.quality_work_items import get_quality_work_items, get_release_test_status
from src.api.delivery_routes import _prepare_delivery_scope
from src.api.quality_routes import _prepare as _prepare_quality_scope
from src.auth.dependencies import get_current_user
from src.db.models import AgentWorkspace, DeliveryMilestone, QualityPolicy, ReleaseCandidate, Task, User
from src.db.session import get_db
from src.models.release_candidate_schemas import (
    DeliveryReleaseCandidateStatusRequest,
    ReleaseCandidateCreateRequest,
    ReleaseCandidateOut,
    ReleaseCandidateStatusRequest,
)
from src.services.audit_service import record_audit_event
from src.services.quality_control_service import DEFAULT_POLICY_VERSION, load_quality_control_plane
from src.services.workspace_outbox_service import enqueue_workspace_event

router = APIRouter()

_QA_TRANSITIONS = {
    "qa_requested": frozenset({"qa_in_progress", "rejected"}),
    "qa_in_progress": frozenset({"approved", "rejected"}),
    "rejected": frozenset({"qa_in_progress"}),
}
_DELIVERY_TRANSITIONS = {
    "draft": frozenset({"qa_requested", "cancelled"}),
    "qa_requested": frozenset({"cancelled"}),
    "rejected": frozenset({"qa_requested", "cancelled"}),
    "approved": frozenset({"released", "cancelled"}),
}


def _out(candidate: ReleaseCandidate) -> ReleaseCandidateOut:
    return ReleaseCandidateOut.model_validate(candidate, from_attributes=True)


async def _audit(
    db: AsyncSession,
    *,
    actor: User,
    workspace_id: str,
    candidate: ReleaseCandidate,
    action: str,
) -> None:
    await record_audit_event(
        db,
        actor=actor,
        action=action,
        target_type="release_candidate",
        target_id=candidate.id,
        workspace_id=workspace_id,
        metadata={
            "delivery_agent_workspace_id": candidate.delivery_agent_workspace_id,
            "quality_agent_workspace_id": candidate.quality_agent_workspace_id,
            "release_key": candidate.release_key,
            "status": candidate.status,
            "row_version": candidate.row_version,
        },
    )


def _event_payload(candidate: ReleaseCandidate) -> dict[str, object]:
    return {
        "release_candidate_id": candidate.id,
        "delivery_agent_workspace_id": candidate.delivery_agent_workspace_id,
        "quality_agent_workspace_id": candidate.quality_agent_workspace_id,
        "source_conversation_id": candidate.source_conversation_id,
        "release_key": candidate.release_key,
        "version": candidate.version,
        "build_number": candidate.build_number,
        "environment": candidate.environment,
        "status": candidate.status,
        "quality_policy_version": candidate.quality_policy_version,
        "row_version": candidate.row_version,
    }


async def _enqueue_candidate_event(
    db: AsyncSession,
    *,
    candidate: ReleaseCandidate,
    event_type: str,
) -> None:
    await enqueue_workspace_event(
        db,
        workspace_id=candidate.organization_workspace_id,
        aggregate_type="release_candidate",
        aggregate_id=candidate.id,
        event_type=event_type,
        payload=_event_payload(candidate),
        idempotency_key=f"release-candidate:{candidate.id}:{candidate.row_version}:{event_type}",
    )


@router.post(
    "/workspaces/{workspace_id}/agent-workspaces/{delivery_workspace_id}/delivery/release-candidates",
    response_model=ReleaseCandidateOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_release_candidate(
    workspace_id: str,
    delivery_workspace_id: str,
    request: ReleaseCandidateCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReleaseCandidateOut:
    try:
        prepared, scope = await _prepare_delivery_scope(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=delivery_workspace_id,
            message=f"Create release candidate {request.release_key}",
            selected_conversation_id=request.source_conversation_id,
        )
        if prepared.context.actor.business_role != BusinessRole.LEAD:
            raise HTTPException(status_code=403, detail="Release handoff is unavailable")
        await enforce_agent_resource_access(db, context=prepared.context, resource_id=request.source_conversation_id)
        if request.source_conversation_id not in scope.effective_group_ids:
            raise AgentResourceDeniedError("Source group is outside Delivery scope")
    except (AgentScopeDeniedError, AgentResourceDeniedError, ProductDeliveryPreparationError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Release handoff is unavailable") from None

    quality_workspace = (
        await db.execute(
            select(AgentWorkspace).where(
                AgentWorkspace.id == request.quality_agent_workspace_id,
                AgentWorkspace.organization_workspace_id == workspace_id,
                AgentWorkspace.agent_profile == AgentProfile.QUALITY_ASSURANCE.value,
                AgentWorkspace.status == "active",
            )
        )
    ).scalar_one_or_none()
    if quality_workspace is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Quality workspace is invalid")

    if request.delivery_milestone_id is not None:
        milestone = (
            await db.execute(
                select(DeliveryMilestone).where(
                    DeliveryMilestone.id == request.delivery_milestone_id,
                    DeliveryMilestone.workspace_id == workspace_id,
                    DeliveryMilestone.agent_workspace_id == delivery_workspace_id,
                    DeliveryMilestone.conversation_id == request.source_conversation_id,
                )
            )
        ).scalar_one_or_none()
        if milestone is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Milestone is invalid")

    now = datetime.now(UTC)
    active_policy = (
        (
            await db.execute(
                select(QualityPolicy)
                .where(
                    QualityPolicy.workspace_id == workspace_id,
                    QualityPolicy.agent_workspace_id == quality_workspace.id,
                    QualityPolicy.status == "active",
                )
                .order_by(QualityPolicy.approved_at.desc(), QualityPolicy.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    candidate = ReleaseCandidate(
        organization_workspace_id=workspace_id,
        delivery_agent_workspace_id=delivery_workspace_id,
        quality_agent_workspace_id=quality_workspace.id,
        source_conversation_id=request.source_conversation_id,
        delivery_milestone_id=request.delivery_milestone_id,
        release_key=request.release_key,
        version=request.version,
        build_number=request.build_number,
        commit_sha=request.commit_sha.lower() if request.commit_sha else None,
        environment=request.environment,
        status="qa_requested" if request.submit_to_qa else "draft",
        quality_policy_version=(active_policy.version if active_policy is not None else DEFAULT_POLICY_VERSION),
        created_by_user_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(candidate)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Release candidate already exists") from None
    await _enqueue_candidate_event(db, candidate=candidate, event_type="release_candidate.created")
    await _audit(
        db, actor=current_user, workspace_id=workspace_id, candidate=candidate, action="release_candidate.created"
    )
    await db.commit()
    await db.refresh(candidate)
    return _out(candidate)


@router.get(
    "/workspaces/{workspace_id}/agent-workspaces/{delivery_workspace_id}/delivery/release-candidates",
    response_model=list[ReleaseCandidateOut],
)
async def list_delivery_release_candidates(
    workspace_id: str,
    delivery_workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ReleaseCandidateOut]:
    """Expose only the structured QA handoff state back to the owning Delivery Lead."""

    try:
        prepared, scope = await _prepare_delivery_scope(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=delivery_workspace_id,
            message="List release candidates and Quality gate states",
            selected_conversation_id=None,
        )
        if prepared.context.actor.business_role != BusinessRole.LEAD:
            raise HTTPException(status_code=403, detail="Release handoff is unavailable")
    except (AgentScopeDeniedError, AgentResourceDeniedError, ProductDeliveryPreparationError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Release handoff is unavailable") from None

    candidates = list(
        (
            await db.execute(
                select(ReleaseCandidate)
                .where(
                    ReleaseCandidate.organization_workspace_id == workspace_id,
                    ReleaseCandidate.delivery_agent_workspace_id == delivery_workspace_id,
                    ReleaseCandidate.source_conversation_id.in_(scope.effective_group_ids),
                )
                .order_by(ReleaseCandidate.updated_at.desc(), ReleaseCandidate.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return [_out(candidate) for candidate in candidates]


@router.patch(
    "/workspaces/{workspace_id}/agent-workspaces/{delivery_workspace_id}/delivery/release-candidates/{candidate_id}/status",
    response_model=ReleaseCandidateOut,
)
async def update_delivery_release_candidate_status(
    workspace_id: str,
    delivery_workspace_id: str,
    candidate_id: str,
    request: DeliveryReleaseCandidateStatusRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReleaseCandidateOut:
    try:
        prepared, scope = await _prepare_delivery_scope(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=delivery_workspace_id,
            message="Update Delivery release handoff",
            selected_conversation_id=None,
        )
        if prepared.context.actor.business_role != BusinessRole.LEAD:
            raise HTTPException(status_code=403, detail="Release handoff is unavailable")
    except (AgentScopeDeniedError, AgentResourceDeniedError, ProductDeliveryPreparationError):
        raise HTTPException(status_code=403, detail="Release handoff is unavailable") from None
    candidate = (
        await db.execute(
            select(ReleaseCandidate).where(
                ReleaseCandidate.id == candidate_id,
                ReleaseCandidate.organization_workspace_id == workspace_id,
                ReleaseCandidate.delivery_agent_workspace_id == delivery_workspace_id,
                ReleaseCandidate.source_conversation_id.in_(scope.effective_group_ids),
            )
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise HTTPException(status_code=404, detail="Release candidate not found")
    await enforce_agent_resource_access(db, context=prepared.context, resource_id=candidate.source_conversation_id)
    if candidate.row_version != request.expected_row_version:
        raise HTTPException(status_code=409, detail="Release candidate was updated concurrently")
    if request.status not in _DELIVERY_TRANSITIONS.get(candidate.status, frozenset()):
        raise HTTPException(status_code=409, detail="Invalid Delivery state transition")
    if request.status == "qa_requested":
        active_policy = (
            (
                await db.execute(
                    select(QualityPolicy)
                    .where(
                        QualityPolicy.workspace_id == workspace_id,
                        QualityPolicy.agent_workspace_id == candidate.quality_agent_workspace_id,
                        QualityPolicy.status == "active",
                    )
                    .order_by(QualityPolicy.approved_at.desc(), QualityPolicy.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        candidate.quality_policy_version = (
            active_policy.version if active_policy is not None else DEFAULT_POLICY_VERSION
        )
    candidate.status = request.status
    candidate.row_version += 1
    candidate.updated_at = datetime.now(UTC)
    await _enqueue_candidate_event(db, candidate=candidate, event_type=f"release_candidate.{request.status}")
    await _audit(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        candidate=candidate,
        action="release_candidate.delivery_status_updated",
    )
    await db.commit()
    await db.refresh(candidate)
    return _out(candidate)


@router.get(
    "/workspaces/{workspace_id}/agent-workspaces/{quality_workspace_id}/quality/release-candidates",
    response_model=list[ReleaseCandidateOut],
)
async def list_quality_release_candidates(
    workspace_id: str,
    quality_workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ReleaseCandidateOut]:
    try:
        prepared, scope = await _prepare_quality_scope(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=quality_workspace_id,
            message="List assigned release candidates",
            release_id="handoff-index",
            selected_conversation_id=None,
        )
    except (AgentScopeDeniedError, AgentResourceDeniedError, QualityPreparationError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Quality handoff is unavailable") from None
    statement = select(ReleaseCandidate).where(
        ReleaseCandidate.organization_workspace_id == workspace_id,
        ReleaseCandidate.quality_agent_workspace_id == quality_workspace_id,
        ReleaseCandidate.status != "draft",
    )
    if prepared.context.actor.business_role == BusinessRole.MEMBER:
        assigned_release_keys = select(Task.release_target).where(
            Task.workspace_id == workspace_id,
            Task.agent_workspace_id == quality_workspace_id,
            Task.conversation_id.in_(scope.effective_group_ids),
            Task.owner_id == current_user.id,
            Task.release_target.is_not(None),
        )
        statement = statement.where(ReleaseCandidate.release_key.in_(assigned_release_keys))
    candidates = list(
        (
            await db.execute(
                statement.order_by(ReleaseCandidate.updated_at.desc(), ReleaseCandidate.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return [_out(candidate) for candidate in candidates]


@router.patch(
    "/workspaces/{workspace_id}/agent-workspaces/{quality_workspace_id}/quality/release-candidates/{candidate_id}/status",
    response_model=ReleaseCandidateOut,
)
async def update_quality_release_candidate_status(
    workspace_id: str,
    quality_workspace_id: str,
    candidate_id: str,
    request: ReleaseCandidateStatusRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReleaseCandidateOut:
    candidate = (
        await db.execute(
            select(ReleaseCandidate).where(
                ReleaseCandidate.id == candidate_id,
                ReleaseCandidate.organization_workspace_id == workspace_id,
                ReleaseCandidate.quality_agent_workspace_id == quality_workspace_id,
            )
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release candidate not found")
    try:
        prepared, scope = await _prepare_quality_scope(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            agent_workspace_id=quality_workspace_id,
            message=f"Update quality decision for {candidate.release_key}",
            release_id=candidate.release_key,
            selected_conversation_id=None,
        )
        if prepared.context.actor.business_role != BusinessRole.LEAD:
            raise HTTPException(status_code=403, detail="Quality decision is unavailable")
    except (AgentScopeDeniedError, AgentResourceDeniedError, QualityPreparationError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Quality decision is unavailable") from None

    allowed = _QA_TRANSITIONS.get(candidate.status, frozenset())
    if request.status not in allowed:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invalid Quality state transition")
    if candidate.row_version != request.expected_row_version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Release candidate was updated concurrently")

    if request.status == "approved":

        async def revalidate_resource(resource_id: str) -> None:
            await enforce_agent_resource_access(db, context=prepared.context, resource_id=resource_id)

        control_plane = await load_quality_control_plane(
            db,
            workspace_id=workspace_id,
            agent_workspace_id=quality_workspace_id,
            release_id=candidate.release_key,
            conversation_ids=scope.effective_group_ids,
        )
        if control_plane["domain_present"]:
            readiness = str(control_plane["assessment"]["release_readiness"])
        else:
            work_result = await get_quality_work_items(
                scope=scope,
                db=db,
                revalidate_resource=revalidate_resource,
            )
            items = tuple(QualityWorkItem.model_validate(item) for item in work_result.payload["items"])
            gate_result = await get_release_test_status(scope=scope, items=items)
            readiness = str(gate_result.payload["assessment"]["release_readiness"])
        if readiness != "READY":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Release cannot be approved while readiness is {readiness}",
            )

    candidate.status = request.status
    candidate.row_version += 1
    candidate.updated_at = datetime.now(UTC)
    await _enqueue_candidate_event(db, candidate=candidate, event_type=f"release_candidate.{request.status}")
    await _audit(
        db,
        actor=current_user,
        workspace_id=workspace_id,
        candidate=candidate,
        action="release_candidate.quality_status_updated",
    )
    await db.commit()
    await db.refresh(candidate)
    return _out(candidate)
