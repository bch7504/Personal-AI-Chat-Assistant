from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import select

import src.db.session as db_session
from src.agents.contracts import (
    ActorContext,
    AgentContext,
    AgentIntent,
    AgentProfile,
    AgentRequestContext,
    AgentRuntimeContext,
    AuthorizationContext,
    BusinessRole,
    PolicyDecision,
    PolicyReason,
    RequestedScope,
    SourceReference,
)
from src.agents.schemas.quality import (
    QualityReadScope,
    QualityStatus,
    QualityViewScope,
    QualityWorkItem,
    QualityWorkItemType,
    evaluate_release_readiness,
)
from src.config import Settings
from src.db.models import (
    AgentWorkspaceConversation,
    Conversation,
    ConversationParticipant,
    QualityTestCase,
    ReleaseCandidate,
    Task,
    User,
)
from src.services.agent_workspace_service import add_agent_workspace_member
from src.services.workspace_service import add_workspace_member
from tests.test_agent_workspaces import _seed_agent_workspaces


def _item(item_id: str, *, release_id: str = "R1", **changes) -> QualityWorkItem:
    values = {
        "id": item_id,
        "title": item_id,
        "work_item_type": QualityWorkItemType.RELEASE_CHECK,
        "severity": None,
        "quality_status": QualityStatus.PASSED,
        "release_id": release_id,
        "required": True,
        "sources": (
            SourceReference(
                resource_id="quality-group",
                resource_type="conversation",
                agent_workspace_id="quality-workspace",
                classification="quality",
                captured_at=datetime.now(UTC),
            ),
        ),
    }
    values.update(changes)
    return QualityWorkItem(**values)


def test_readiness_is_release_scoped_and_ready_rejects_data_gaps():
    ready = evaluate_release_readiness((_item("regression"),), release_id="R1")
    assert ready.release_readiness == "READY"

    with pytest.raises(ValueError, match="cannot mix releases"):
        evaluate_release_readiness((_item("r1"), _item("r2", release_id="R2")), release_id="R1")

    incomplete = evaluate_release_readiness(
        (_item("regression"),), release_id="R1", extra_data_gaps=("Malformed source row",)
    )
    assert incomplete.release_readiness == "AT_RISK"

    no_gate = evaluate_release_readiness(
        (
            _item(
                "non-required-check",
                required=False,
                work_item_type=QualityWorkItemType.TEST_CASE,
            ),
        ),
        release_id="R1",
    )
    assert no_gate.release_readiness == "AT_RISK"
    assert "no_required_release_checks_declared" in no_gate.reasons

    running = evaluate_release_readiness(
        (
            _item("required-gate"),
            _item(
                "regression-running",
                required=False,
                work_item_type=QualityWorkItemType.TEST_CASE,
                quality_status=QualityStatus.TESTING,
            ),
        ),
        release_id="R1",
    )
    assert running.release_readiness == "AT_RISK"
    assert "test_execution_incomplete" in running.reasons


def test_quality_scope_cannot_expand_group_or_member_capability():
    context = AgentContext(
        trace_id="quality-trace",
        actor=ActorContext(
            user_id="member",
            organization_workspace_id="company",
            business_role=BusinessRole.MEMBER,
            agent_workspace_ids=("quality-workspace",),
        ),
        request=AgentRequestContext(
            text="Quality status",
            intent=AgentIntent.QUALITY_BRIEF,
            requested_scope=RequestedScope.WORKSPACE,
            target_agent_workspace_id="quality-workspace",
        ),
        authorization=AuthorizationContext(
            decision=PolicyDecision.ALLOW,
            reason=PolicyReason.ALLOWED,
            allowed_agent_workspace_ids=("quality-workspace",),
            allowed_resource_ids=("quality-group",),
        ),
        runtime=AgentRuntimeContext(
            agent_profile=AgentProfile.QUALITY_ASSURANCE,
            prompt_version="quality-assurance-v1",
        ),
    )
    QualityReadScope(
        context=context,
        release_id="R1",
        view_scope=QualityViewScope.MEMBER,
        effective_group_ids=("quality-group",),
    )
    with pytest.raises(ValidationError, match="exceeds"):
        QualityReadScope(
            context=context,
            release_id="R1",
            view_scope=QualityViewScope.MEMBER,
            effective_group_ids=("delivery-group",),
        )


@pytest.mark.asyncio
async def test_quality_brief_is_scoped_and_survives_quality_runtime_failure(
    client, auth_headers, monkeypatch
):
    seed = await _seed_agent_workspaces(client, auth_headers)
    monkeypatch.setattr(
        "src.api.quality_routes.get_settings",
        lambda: Settings(
            _env_file=None,
            multi_agent_enabled=True,
            quality_assurance_agent_enabled=True,
        ),
    )
    async with db_session.async_session_maker() as db:
        lead = await db.get(User, seed["quality_user_id"])
        group = Conversation(
            workspace_id=seed["organization_id"],
            type="group",
            name="QA Release",
            created_by=lead.id,
            ai_enabled=True,
            ai_policy_version=1,
        )
        db.add(group)
        await db.flush()
        db.add(
            AgentWorkspaceConversation(
                agent_workspace_id=seed["quality_id"],
                conversation_id=group.id,
                classification="quality",
                linked_by_user_id=lead.id,
            )
        )
        db.add_all(
            [
                Task(
                    workspace_id=seed["organization_id"],
                    agent_workspace_id=seed["quality_id"],
                    owner_id=lead.id,
                    conversation_id=group.id,
                    title="R1 regression gate",
                    source="manual",
                    work_item_type="release_check",
                    quality_status="passed",
                    release_target="R1",
                    quality_required=True,
                ),
                Task(
                    workspace_id=seed["organization_id"],
                    agent_workspace_id=seed["quality_id"],
                    owner_id=lead.id,
                    conversation_id=group.id,
                    title="R2 critical bug",
                    source="manual",
                    work_item_type="bug",
                    severity="critical",
                    quality_status="open",
                    release_target="R2",
                ),
            ]
        )
        await db.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "quality@example.com", "password": "password123"},
    )

    class UnavailableQualityRuntime:
        async def run(self, request):
            raise ConnectionError("Quality runtime is unavailable")

    monkeypatch.setattr(
        "src.api.quality_routes.get_quality_assurance_runtime",
        lambda: UnavailableQualityRuntime(),
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = await client.post(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-router/invoke",
        headers=headers,
        json={
            "target_agent_workspace_id": seed["quality_id"],
            "message": "R1 ready?",
            "release_id": "R1",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    payload = body["payload"]
    assert body["status"] == "partial"
    assert "QUALITY_AGENT_RUNTIME_FAILED" in body["data_gaps"]
    assert "REQUIREMENT_TRACEABILITY_NOT_CAPTURED" in body["data_gaps"]
    assert payload["thread_id"]
    assert payload["assessment"]["release_readiness"] == "READY"
    serialized = str(payload)
    assert "R1 regression gate" in serialized
    assert "R2 critical bug" not in serialized

    outside_domain = await client.post(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-router/invoke",
        headers=headers,
        json={
            "target_agent_workspace_id": seed["quality_id"],
            "message": "Hoàng Sa Trường Sa thuộc nước nào?",
            "release_id": "R1",
        },
    )
    assert outside_domain.status_code == 200
    outside_body = outside_domain.json()
    assert outside_body["status"] == "success"
    assert outside_body["sources"] == []
    assert outside_body["data_gaps"] == []
    assert outside_body["payload"]["policy"] == {
        "category": "out_of_domain",
        "data_accessed": False,
        "llm_calls": 0,
    }
    assert "assessment" not in outside_body["payload"]
    assert "Hoàng Sa" not in outside_body["payload"]["agent_response"]


@pytest.mark.asyncio
async def test_quality_brief_rejects_only_the_account_over_its_ai_allowance(
    client, auth_headers, monkeypatch
):
    seed = await _seed_agent_workspaces(client, auth_headers)
    monkeypatch.setattr(
        "src.api.quality_routes.get_settings",
        lambda: Settings(
            _env_file=None,
            multi_agent_enabled=True,
            quality_assurance_agent_enabled=True,
        ),
    )
    checked_user_ids: list[str] = []

    async def account_is_over_budget(user_id: str) -> bool:
        checked_user_ids.append(user_id)
        return True

    monkeypatch.setattr(
        "src.api.quality_routes.usage_service.is_over_budget",
        account_is_over_budget,
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "quality@example.com", "password": "password123"},
    )

    response = await client.post(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-router/invoke",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={
            "target_agent_workspace_id": seed["quality_id"],
            "message": "R1 ready?",
            "release_id": "R1",
        },
    )

    assert response.status_code == 429
    assert response.json()["detail"] == "Daily AI token allowance exceeded for this account"
    assert checked_user_ids == [seed["quality_user_id"]]


@pytest.mark.asyncio
async def test_quality_lead_can_create_and_update_a_source_bound_work_item(
    client, auth_headers, monkeypatch
):
    seed = await _seed_agent_workspaces(client, auth_headers)
    monkeypatch.setattr(
        "src.api.quality_routes.get_settings",
        lambda: Settings(
            _env_file=None,
            multi_agent_enabled=True,
            quality_assurance_agent_enabled=True,
        ),
    )
    async with db_session.async_session_maker() as db:
        lead = await db.get(User, seed["quality_user_id"])
        group = Conversation(
            workspace_id=seed["organization_id"],
            type="group",
            name="Quality Triage",
            created_by=lead.id,
            ai_enabled=True,
            ai_policy_version=1,
        )
        db.add(group)
        await db.flush()
        db.add_all(
            [
                AgentWorkspaceConversation(
                    agent_workspace_id=seed["quality_id"],
                    conversation_id=group.id,
                    classification="quality",
                    linked_by_user_id=lead.id,
                ),
                ConversationParticipant(
                    conversation_id=group.id,
                    principal_kind="workspace_user",
                    user_id=lead.id,
                    resource_role="manager",
                    invited_by_user_id=lead.id,
                ),
            ]
        )
        await db.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "quality@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    base = f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/{seed['quality_id']}/quality"
    created = await client.post(
        f"{base}/work-items",
        headers=headers,
        json={
            "conversation_id": group.id,
            "release_id": "R7",
            "title": "Regression gate",
            "work_item_type": "release_check",
            "quality_status": "open",
            "required": True,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["quality_status"] == "open"
    assert created.json()["row_version"] == 1

    testing = await client.patch(
        f"{base}/work-items/{created.json()['id']}/status",
        headers=headers,
        json={"quality_status": "testing", "expected_row_version": 1},
    )
    assert testing.status_code == 200, testing.text
    updated = await client.patch(
        f"{base}/work-items/{created.json()['id']}/status",
        headers=headers,
        json={"quality_status": "passed", "expected_row_version": 2},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["quality_status"] == "passed"
    assert updated.json()["row_version"] == 3

    stale = await client.patch(
        f"{base}/work-items/{created.json()['id']}/status",
        headers=headers,
        json={"quality_status": "blocked", "expected_row_version": 1},
    )
    assert stale.status_code == 409


@pytest.mark.asyncio
async def test_quality_member_has_scoped_operational_permissions_but_not_governance(
    client, auth_headers, monkeypatch
):
    seed = await _seed_agent_workspaces(client, auth_headers)
    monkeypatch.setattr(
        "src.api.quality_routes.get_settings",
        lambda: Settings(
            _env_file=None,
            multi_agent_enabled=True,
            quality_assurance_agent_enabled=True,
        ),
    )
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "quality-member@example.com",
            "password": "password123",
            "display_name": "Quality Member",
        },
    )
    assert registered.status_code == 201

    async with db_session.async_session_maker() as db:
        lead = await db.get(User, seed["quality_user_id"])
        member = (
            await db.execute(select(User).where(User.email == "quality-member@example.com"))
        ).scalar_one()
        await add_workspace_member(db, seed["organization_id"], member.id, "member", lead.id)
        await add_agent_workspace_member(db, seed["quality_id"], member.id, "member")
        allowed_group = Conversation(
            workspace_id=seed["organization_id"],
            type="group",
            name="Member QA scope",
            created_by=lead.id,
            ai_enabled=True,
            ai_policy_version=1,
        )
        hidden_group = Conversation(
            workspace_id=seed["organization_id"],
            type="group",
            name="Lead-only QA scope",
            created_by=lead.id,
            ai_enabled=True,
            ai_policy_version=1,
        )
        db.add_all([allowed_group, hidden_group])
        await db.flush()
        db.add_all(
            [
                AgentWorkspaceConversation(
                    agent_workspace_id=seed["quality_id"],
                    conversation_id=allowed_group.id,
                    classification="quality",
                    linked_by_user_id=lead.id,
                ),
                AgentWorkspaceConversation(
                    agent_workspace_id=seed["quality_id"],
                    conversation_id=hidden_group.id,
                    classification="quality",
                    linked_by_user_id=lead.id,
                ),
                ConversationParticipant(
                    conversation_id=allowed_group.id,
                    principal_kind="workspace_user",
                    user_id=lead.id,
                    resource_role="manager",
                    invited_by_user_id=lead.id,
                ),
                ConversationParticipant(
                    conversation_id=allowed_group.id,
                    principal_kind="workspace_user",
                    user_id=member.id,
                    resource_role="participant",
                    invited_by_user_id=lead.id,
                ),
                ConversationParticipant(
                    conversation_id=hidden_group.id,
                    principal_kind="workspace_user",
                    user_id=lead.id,
                    resource_role="manager",
                    invited_by_user_id=lead.id,
                ),
            ]
        )
        test_case = QualityTestCase(
            workspace_id=seed["organization_id"],
            agent_workspace_id=seed["quality_id"],
            conversation_id=allowed_group.id,
            release_id="R-MEMBER",
            test_case_key="TC-MEMBER",
            title="Member-executable regression",
            test_kind="regression",
            required=True,
            created_by_user_id=lead.id,
        )
        hidden_handoff = ReleaseCandidate(
            organization_workspace_id=seed["organization_id"],
            delivery_agent_workspace_id=seed["delivery_id"],
            quality_agent_workspace_id=seed["quality_id"],
            source_conversation_id=hidden_group.id,
            release_key="R-HIDDEN",
            version="1.0.0",
            build_number="hidden-1",
            status="qa_requested",
            created_by_user_id=lead.id,
        )
        db.add_all([test_case, hidden_handoff])
        await db.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "quality-member@example.com", "password": "password123"},
    )
    member_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    base = (
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/"
        f"{seed['quality_id']}/quality"
    )
    capabilities = await client.get(f"{base}/capabilities", headers=member_headers)
    assert capabilities.status_code == 200, capabilities.text
    assert capabilities.json() == {
        "current_user_business_role": "member",
        "view_scope": "member",
        "can_select_group": False,
        "can_manage_control_plane": False,
        "can_execute_tests": True,
        "can_submit_evidence": True,
        "can_report_defects": True,
        "can_verify_evidence": False,
        "can_decide_release": False,
        "can_update_own_work_items": True,
        "can_propose_actions": True,
        "groups": [{"id": allowed_group.id, "name": "Member QA scope"}],
        "release_ids": [],
    }
    member_handoffs = await client.get(
        f"{base}/release-candidates", headers=member_headers
    )
    assert member_handoffs.status_code == 200, member_handoffs.text
    assert member_handoffs.json() == []

    evidence = await client.post(
        f"{base}/evidence",
        headers=member_headers,
        json={
            "conversation_id": allowed_group.id,
            "release_id": "R-MEMBER",
            "artifact_type": "report",
            "uri": "https://ci.example.test/member-report",
        },
    )
    assert evidence.status_code == 201, evidence.text
    run = await client.post(
        f"{base}/test-runs",
        headers=member_headers,
        json={
            "conversation_id": allowed_group.id,
            "release_id": "R-MEMBER",
            "test_case_id": test_case.id,
            "evidence_id": evidence.json()["record"]["id"],
            "build_number": "101",
            "environment": "staging",
            "status": "running",
        },
    )
    assert run.status_code == 201, run.text
    defect = await client.post(
        f"{base}/defects",
        headers=member_headers,
        json={
            "conversation_id": allowed_group.id,
            "release_id": "R-MEMBER",
            "defect_key": "BUG-MEMBER-1",
            "title": "Regression failure reported by member",
            "severity": "high",
            "test_run_id": run.json()["record"]["id"],
        },
    )
    assert defect.status_code == 201, defect.text
    assert defect.json()["record"]["owner_id"] == member.id

    lead_only_requirement = await client.post(
        f"{base}/requirements",
        headers=member_headers,
        json={
            "conversation_id": allowed_group.id,
            "release_id": "R-MEMBER",
            "requirement_key": "REQ-DENIED",
            "title": "Member must not govern requirements",
            "required": True,
        },
    )
    assert lead_only_requirement.status_code == 403
    hidden_evidence = await client.post(
        f"{base}/evidence",
        headers=member_headers,
        json={
            "conversation_id": hidden_group.id,
            "release_id": "R-MEMBER",
            "artifact_type": "report",
            "uri": "https://ci.example.test/hidden-report",
        },
    )
    assert hidden_evidence.status_code == 403
    self_verification = await client.patch(
        f"{base}/records/evidence/{evidence.json()['record']['id']}",
        headers=member_headers,
        json={"status": "verified", "expected_row_version": 1},
    )
    assert self_verification.status_code == 403

    transitioned = await client.patch(
        f"{base}/records/test_run/{run.json()['record']['id']}",
        headers=member_headers,
        json={"status": "passed", "expected_row_version": 1},
    )
    assert transitioned.status_code == 200, transitioned.text

    lead_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "quality@example.com", "password": "password123"},
    )
    lead_headers = {"Authorization": f"Bearer {lead_login.json()['access_token']}"}
    lead_verification = await client.patch(
        f"{base}/records/evidence/{evidence.json()['record']['id']}",
        headers=lead_headers,
        json={"status": "verified", "expected_row_version": 1},
    )
    assert lead_verification.status_code == 200, lead_verification.text
