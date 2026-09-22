import pytest
from sqlalchemy import select

import src.db.session as db_session
from src.agents.context_builder import AgentScopeDeniedError, build_agent_context
from src.agents.contracts import (
    AgentIntent,
    AgentInvocationRequest,
    AgentProfile,
    BusinessRole,
    PolicyDecision,
    PolicyReason,
    RequestedScope,
)
from src.agents.policies.resource_guard import (
    AgentResourceDeniedError,
    enforce_agent_resource_access,
    enforce_agent_workspace_access,
)
from src.agents.policies.scope_resolver import resolve_agent_scope
from src.config import Settings
from src.db.models import AgentWorkspaceConversation, AgentWorkspaceMembership, User, WorkspaceMembership
from src.services.agent_workspace_service import add_agent_workspace_member, create_agent_workspace
from src.services.company_service import get_or_create_company_workspace
from src.services.workspace_service import add_workspace_member


async def _seed_agent_workspaces(client, auth_headers):
    owner = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    async with db_session.async_session_maker() as db:
        company = await get_or_create_company_workspace(db)
        existing = (
            await db.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == company.id,
                    WorkspaceMembership.user_id == owner["id"],
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            await add_workspace_member(db, company.id, owner["id"], "owner", owner["id"])
        await db.commit()
        organization = {"id": company.id}
    for email, name in [
        ("delivery@example.com", "Delivery Lead"),
        ("quality@example.com", "Quality Lead"),
        ("executive@example.com", "Executive"),
    ]:
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "password123", "display_name": name},
        )
        assert response.status_code == 201
        response = await client.post(
            f"/api/v1/workspaces/{organization['id']}/members",
            json={"email": email, "role": "member"},
            headers=auth_headers,
        )
        assert response.status_code == 201

    async with db_session.async_session_maker() as db:
        users = {
            user.email: user
            for user in (
                await db.execute(
                    select(User).where(
                        User.email.in_(
                            ("delivery@example.com", "quality@example.com", "executive@example.com")
                        )
                    )
                )
            )
            .scalars()
            .all()
        }
        delivery = await create_agent_workspace(
            db,
            organization["id"],
            "product-delivery",
            "Product Delivery",
            AgentProfile.PRODUCT_DELIVERY,
        )
        quality = await create_agent_workspace(
            db,
            organization["id"],
            "quality-assurance",
            "Quality Assurance",
            AgentProfile.QUALITY_ASSURANCE,
        )
        executive = await create_agent_workspace(
            db,
            organization["id"],
            "executive",
            "Executive",
            AgentProfile.EXECUTIVE,
        )
        delivery_membership = await add_agent_workspace_member(
            db, delivery.id, users["delivery@example.com"].id, "lead"
        )
        await add_agent_workspace_member(db, quality.id, users["quality@example.com"].id, "lead")
        await add_agent_workspace_member(db, executive.id, users["executive@example.com"].id, "lead")
        await db.commit()
        return {
            "organization_id": organization["id"],
            "delivery_id": delivery.id,
            "quality_id": quality.id,
            "executive_id": executive.id,
            "delivery_user_id": users["delivery@example.com"].id,
            "quality_user_id": users["quality@example.com"].id,
            "executive_user_id": users["executive@example.com"].id,
            "delivery_membership_id": delivery_membership.id,
        }


@pytest.mark.asyncio
async def test_specialist_scope_allows_own_workspace_and_denies_other_workspace(client, auth_headers):
    seed = await _seed_agent_workspaces(client, auth_headers)

    async with db_session.async_session_maker() as db:
        allowed = await resolve_agent_scope(
            db,
            user_id=seed["delivery_user_id"],
            organization_workspace_id=seed["organization_id"],
            agent_profile=AgentProfile.PRODUCT_DELIVERY,
            requested_scope=RequestedScope.WORKSPACE,
            target_agent_workspace_id=seed["delivery_id"],
        )
        denied = await resolve_agent_scope(
            db,
            user_id=seed["delivery_user_id"],
            organization_workspace_id=seed["organization_id"],
            agent_profile=AgentProfile.QUALITY_ASSURANCE,
            requested_scope=RequestedScope.WORKSPACE,
            target_agent_workspace_id=seed["quality_id"],
        )

    assert allowed.decision == PolicyDecision.ALLOW
    assert allowed.business_role == BusinessRole.LEAD
    assert allowed.allowed_agent_workspace_ids == (seed["delivery_id"],)
    assert denied.decision == PolicyDecision.DENY
    assert denied.reason == PolicyReason.NOT_MEMBER
    assert denied.allowed_agent_workspace_ids == ()


@pytest.mark.asyncio
async def test_executive_gets_aggregate_scope_but_not_specialist_scope(client, auth_headers):
    seed = await _seed_agent_workspaces(client, auth_headers)

    async with db_session.async_session_maker() as db:
        aggregate = await resolve_agent_scope(
            db,
            user_id=seed["executive_user_id"],
            organization_workspace_id=seed["organization_id"],
            agent_profile=AgentProfile.EXECUTIVE,
            requested_scope=RequestedScope.AGGREGATE,
        )
        raw_workspace = await resolve_agent_scope(
            db,
            user_id=seed["executive_user_id"],
            organization_workspace_id=seed["organization_id"],
            agent_profile=AgentProfile.PRODUCT_DELIVERY,
            requested_scope=RequestedScope.WORKSPACE,
            target_agent_workspace_id=seed["delivery_id"],
        )

    assert aggregate.decision == PolicyDecision.ALLOW
    assert aggregate.business_role == BusinessRole.EXECUTIVE
    assert set(aggregate.allowed_agent_workspace_ids) == {seed["delivery_id"], seed["quality_id"]}
    assert raw_workspace.decision == PolicyDecision.DENY
    assert raw_workspace.reason == PolicyReason.NOT_MEMBER


@pytest.mark.asyncio
async def test_organization_owner_is_not_implicitly_a_specialist(client, auth_headers):
    seed = await _seed_agent_workspaces(client, auth_headers)
    owner = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()

    async with db_session.async_session_maker() as db:
        resolution = await resolve_agent_scope(
            db,
            user_id=owner["id"],
            organization_workspace_id=seed["organization_id"],
            agent_profile=AgentProfile.PRODUCT_DELIVERY,
            requested_scope=RequestedScope.WORKSPACE,
            target_agent_workspace_id=seed["delivery_id"],
        )

    assert resolution.decision == PolicyDecision.DENY
    assert resolution.reason == PolicyReason.NOT_MEMBER


@pytest.mark.asyncio
async def test_revoked_agent_workspace_membership_is_effective_on_next_resolution(client, auth_headers):
    seed = await _seed_agent_workspaces(client, auth_headers)

    async with db_session.async_session_maker() as db:
        membership = await db.get(AgentWorkspaceMembership, seed["delivery_membership_id"])
        membership.status = "revoked"
        await db.commit()
        resolution = await resolve_agent_scope(
            db,
            user_id=seed["delivery_user_id"],
            organization_workspace_id=seed["organization_id"],
            agent_profile=AgentProfile.PRODUCT_DELIVERY,
            requested_scope=RequestedScope.WORKSPACE,
            target_agent_workspace_id=seed["delivery_id"],
        )

    assert resolution.decision == PolicyDecision.DENY
    assert resolution.reason == PolicyReason.NOT_MEMBER


@pytest.mark.asyncio
async def test_revoked_organization_membership_blocks_agent_workspace_immediately(client, auth_headers):
    seed = await _seed_agent_workspaces(client, auth_headers)

    async with db_session.async_session_maker() as db:
        organization_membership = (
            await db.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == seed["organization_id"],
                    WorkspaceMembership.user_id == seed["delivery_user_id"],
                )
            )
        ).scalar_one()
        organization_membership.status = "revoked"
        await db.commit()
        resolution = await resolve_agent_scope(
            db,
            user_id=seed["delivery_user_id"],
            organization_workspace_id=seed["organization_id"],
            agent_profile=AgentProfile.PRODUCT_DELIVERY,
            requested_scope=RequestedScope.WORKSPACE,
            target_agent_workspace_id=seed["delivery_id"],
        )

    assert resolution.decision == PolicyDecision.DENY
    assert resolution.reason == PolicyReason.NOT_MEMBER


@pytest.mark.asyncio
async def test_context_builder_uses_db_role_and_feature_flags(client, auth_headers):
    seed = await _seed_agent_workspaces(client, auth_headers)
    invocation = AgentInvocationRequest(
        message="Tình hình delivery tuần này?",
        requested_scope=RequestedScope.WORKSPACE,
        target_agent_workspace_id=seed["delivery_id"],
    )
    settings = Settings(
        _env_file=None,
        multi_agent_enabled=True,
        product_delivery_agent_enabled=True,
    )

    async with db_session.async_session_maker() as db:
        context = await build_agent_context(
            db,
            user_id=seed["delivery_user_id"],
            organization_workspace_id=seed["organization_id"],
            invocation=invocation,
            agent_profile=AgentProfile.PRODUCT_DELIVERY,
            intent=AgentIntent.DELIVERY_BRIEF,
            prompt_version="product-delivery-v1",
            settings=settings,
        )

    assert context.actor.business_role == BusinessRole.LEAD
    assert context.authorization.allowed_agent_workspace_ids == (seed["delivery_id"],)
    assert context.runtime.agent_profile == AgentProfile.PRODUCT_DELIVERY


@pytest.mark.asyncio
async def test_context_builder_fails_closed_when_profile_flag_is_disabled(client, auth_headers):
    seed = await _seed_agent_workspaces(client, auth_headers)
    invocation = AgentInvocationRequest(
        message="Tình hình delivery tuần này?",
        requested_scope=RequestedScope.WORKSPACE,
        target_agent_workspace_id=seed["delivery_id"],
    )

    async with db_session.async_session_maker() as db:
        with pytest.raises(AgentScopeDeniedError) as error:
            await build_agent_context(
                db,
                user_id=seed["delivery_user_id"],
                organization_workspace_id=seed["organization_id"],
                invocation=invocation,
                agent_profile=AgentProfile.PRODUCT_DELIVERY,
                intent=AgentIntent.DELIVERY_BRIEF,
                prompt_version="product-delivery-v1",
                settings=Settings(
                    _env_file=None,
                    multi_agent_enabled=False,
                    product_delivery_agent_enabled=False,
                    quality_assurance_agent_enabled=False,
                    executive_agent_enabled=False,
                ),
            )

    assert error.value.resolution.reason == PolicyReason.FEATURE_DISABLED


@pytest.mark.asyncio
async def test_workspace_configuration_api_is_platform_admin_only(
    client, auth_headers, admin_auth_headers
):
    seed = await _seed_agent_workspaces(client, auth_headers)

    denied_owner = await client.get(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces",
        headers=auth_headers,
    )
    assert denied_owner.status_code == 403

    response = await client.get(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces",
        headers=admin_auth_headers,
    )
    assert response.status_code == 200
    assert {item["agent_profile"] for item in response.json()} == {
        "product_delivery",
        "quality_assurance",
        "executive",
    }
    summaries = await client.get("/api/v1/admin/workspaces", headers=admin_auth_headers)
    assert summaries.status_code == 200
    organization_summary = next(
        item for item in summaries.json() if item["id"] == seed["organization_id"]
    )
    assert organization_summary["agent_workspace_count"] == 3

    for email, display_name in (
        ("operations-lead@example.com", "Operations Lead"),
        ("operations-member@example.com", "Operations Member"),
    ):
        registered = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "password123", "display_name": display_name},
        )
        assert registered.status_code == 201
        enrolled = await client.post(
            f"/api/v1/workspaces/{seed['organization_id']}/members",
            json={"email": email, "role": "member"},
            headers=auth_headers,
        )
        assert enrolled.status_code == 201

    created = await client.post(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces",
        json={
            "key": "delivery-operations",
            "name": "Delivery Operations",
            "agent_profile": "product_delivery",
            "lead_email": "operations-lead@example.com",
        },
        headers=admin_auth_headers,
    )
    assert created.status_code == 201
    assert created.json()["lead_email"] == "operations-lead@example.com"
    member = await client.post(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/"
        f"{created.json()['id']}/members",
        json={"email": "operations-member@example.com", "business_role": "member"},
        headers=admin_auth_headers,
    )
    assert member.status_code == 201
    assert member.json()["business_role"] == "member"

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "operations-member@example.com", "password": "password123"},
    )
    member_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    denied = await client.get(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces",
        headers=member_headers,
    )
    assert denied.status_code == 403
    available = await client.get(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/available",
        headers=member_headers,
    )
    assert available.status_code == 200
    assert [(item["id"], item["current_user_business_role"]) for item in available.json()] == [
        (created.json()["id"], "member")
    ]

    duplicate_assignment = await client.post(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/"
        f"{created.json()['id']}/members",
        json={"email": "delivery@example.com", "business_role": "member"},
        headers=admin_auth_headers,
    )
    assert duplicate_assignment.status_code == 409
    assert "already assigned" in duplicate_assignment.json()["detail"]


@pytest.mark.asyncio
async def test_platform_admin_assigns_one_lead_and_explicitly_enrolls_membership(
    client, auth_headers, admin_auth_headers
):
    seed = await _seed_agent_workspaces(client, auth_headers)
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "replacement@example.com",
            "password": "password123",
            "display_name": "Replacement Lead",
        },
    )
    assert registered.status_code == 201

    denied_owner = await client.patch(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/"
        f"{seed['delivery_id']}/lead",
        json={"email": "replacement@example.com"},
        headers=auth_headers,
    )
    assert denied_owner.status_code == 403

    changed = await client.patch(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/"
        f"{seed['delivery_id']}/lead",
        json={"email": "replacement@example.com"},
        headers=admin_auth_headers,
    )
    assert changed.status_code == 200
    assert changed.json()["business_role"] == "lead"

    async with db_session.async_session_maker() as db:
        replacement = (
            await db.execute(select(User).where(User.email == "replacement@example.com"))
        ).scalar_one()
        leads = (
            await db.execute(
                select(AgentWorkspaceMembership).where(
                    AgentWorkspaceMembership.agent_workspace_id == seed["delivery_id"],
                    AgentWorkspaceMembership.business_role == "lead",
                    AgentWorkspaceMembership.status == "active",
                )
            )
        ).scalars().all()
        organization_membership = (
            await db.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == seed["organization_id"],
                    WorkspaceMembership.user_id == replacement.id,
                    WorkspaceMembership.status == "active",
                )
            )
        ).scalar_one_or_none()

    assert [membership.user_id for membership in leads] == [replacement.id]
    assert organization_membership is not None
    assert organization_membership.role == "member"

    cannot_revoke_current_lead = await client.delete(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/"
        f"{seed['delivery_id']}/members/{changed.json()['id']}",
        headers=admin_auth_headers,
    )
    assert cannot_revoke_current_lead.status_code == 409


@pytest.mark.asyncio
async def test_conversation_mapping_enters_scope_only_with_active_group_consent(
    client, auth_headers, admin_auth_headers
):
    seed = await _seed_agent_workspaces(client, auth_headers)
    conversation = await client.post(
        "/api/v1/conversations",
        json={
            "type": "group",
            "participant_ids": [seed["delivery_user_id"]],
            "name": "Delivery Release",
            "workspace_id": seed["organization_id"],
        },
        headers=auth_headers,
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    wrong_classification = await client.post(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/"
        f"{seed['delivery_id']}/conversations",
        json={"conversation_id": conversation_id, "classification": "quality"},
        headers=admin_auth_headers,
    )
    assert wrong_classification.status_code == 422

    linked = await client.post(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/"
        f"{seed['delivery_id']}/conversations",
        json={"conversation_id": conversation_id, "classification": "delivery"},
        headers=admin_auth_headers,
    )
    assert linked.status_code == 201

    async with db_session.async_session_maker() as db:
        before_consent = await resolve_agent_scope(
            db,
            user_id=seed["delivery_user_id"],
            organization_workspace_id=seed["organization_id"],
            agent_profile=AgentProfile.PRODUCT_DELIVERY,
            requested_scope=RequestedScope.WORKSPACE,
            target_agent_workspace_id=seed["delivery_id"],
        )
    assert before_consent.allowed_resource_ids == ()
    assert before_consent.consent_scope_hash is None

    consent = await client.put(
        f"/api/v1/conversations/{conversation_id}/ai-policy",
        json={"enabled": True},
        headers=auth_headers,
    )
    assert consent.status_code == 200

    async with db_session.async_session_maker() as db:
        after_consent = await resolve_agent_scope(
            db,
            user_id=seed["delivery_user_id"],
            organization_workspace_id=seed["organization_id"],
            agent_profile=AgentProfile.PRODUCT_DELIVERY,
            requested_scope=RequestedScope.WORKSPACE,
            target_agent_workspace_id=seed["delivery_id"],
        )
    assert after_consent.allowed_resource_ids == (conversation_id,)
    assert after_consent.consent_scope_hash is not None

    context_settings = Settings(
        _env_file=None,
        multi_agent_enabled=True,
        product_delivery_agent_enabled=True,
    )
    invocation = AgentInvocationRequest(
        message="Tóm tắt release",
        requested_scope=RequestedScope.WORKSPACE,
        target_agent_workspace_id=seed["delivery_id"],
    )
    async with db_session.async_session_maker() as db:
        context = await build_agent_context(
            db,
            user_id=seed["delivery_user_id"],
            organization_workspace_id=seed["organization_id"],
            invocation=invocation,
            agent_profile=AgentProfile.PRODUCT_DELIVERY,
            intent=AgentIntent.DELIVERY_BRIEF,
            prompt_version="product-delivery-v1",
            settings=context_settings,
        )
    assert context.authorization.allowed_resource_ids == (conversation_id,)
    assert context.authorization.consent_scope_hash == after_consent.consent_scope_hash

    async with db_session.async_session_maker() as db:
        await enforce_agent_resource_access(db, context=context, resource_id=conversation_id)
        await enforce_agent_workspace_access(db, context=context, agent_workspace_id=seed["delivery_id"])
        with pytest.raises(AgentResourceDeniedError) as guessed:
            await enforce_agent_resource_access(db, context=context, resource_id="guessed-conversation")
        with pytest.raises(AgentResourceDeniedError) as wrong_workspace:
            await enforce_agent_workspace_access(db, context=context, agent_workspace_id=seed["quality_id"])
    assert guessed.value.reason == PolicyReason.RESOURCE_NOT_ALLOWED
    assert wrong_workspace.value.reason == PolicyReason.WRONG_WORKSPACE

    revoked_consent = await client.put(
        f"/api/v1/conversations/{conversation_id}/ai-policy",
        json={"enabled": False},
        headers=auth_headers,
    )
    assert revoked_consent.status_code == 200
    async with db_session.async_session_maker() as db:
        with pytest.raises(AgentResourceDeniedError) as revoked:
            await enforce_agent_resource_access(db, context=context, resource_id=conversation_id)
        with pytest.raises(AgentResourceDeniedError) as revoked_workspace:
            await enforce_agent_workspace_access(db, context=context, agent_workspace_id=seed["delivery_id"])
    assert revoked.value.reason == PolicyReason.CONSENT_CHANGED
    assert revoked_workspace.value.reason == PolicyReason.CONSENT_CHANGED


@pytest.mark.asyncio
async def test_member_scope_excludes_linked_group_when_the_member_is_not_an_active_participant(
    client, auth_headers, admin_auth_headers
):
    seed = await _seed_agent_workspaces(client, auth_headers)
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "delivery-member@example.com",
            "password": "password123",
            "display_name": "Delivery Member",
        },
    )
    assert registered.status_code == 201
    added_to_organization = await client.post(
        f"/api/v1/workspaces/{seed['organization_id']}/members",
        json={"email": "delivery-member@example.com", "role": "member"},
        headers=auth_headers,
    )
    assert added_to_organization.status_code == 201
    added_to_agent_workspace = await client.post(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/{seed['delivery_id']}/members",
        json={"email": "delivery-member@example.com", "business_role": "member"},
        headers=admin_auth_headers,
    )
    assert added_to_agent_workspace.status_code == 201

    group = await client.post(
        "/api/v1/conversations",
        json={
            "type": "group",
            "participant_ids": [seed["delivery_user_id"]],
            "name": "Lead-only Delivery Group",
            "workspace_id": seed["organization_id"],
        },
        headers=auth_headers,
    )
    assert group.status_code == 200
    group_id = group.json()["id"]
    linked = await client.post(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/{seed['delivery_id']}/conversations",
        json={"conversation_id": group_id, "classification": "delivery"},
        headers=admin_auth_headers,
    )
    assert linked.status_code == 201
    consent = await client.put(
        f"/api/v1/conversations/{group_id}/ai-policy",
        json={"enabled": True},
        headers=auth_headers,
    )
    assert consent.status_code == 200

    async with db_session.async_session_maker() as db:
        member = (
            await db.execute(select(User).where(User.email == "delivery-member@example.com"))
        ).scalar_one()
        resolution = await resolve_agent_scope(
            db,
            user_id=member.id,
            organization_workspace_id=seed["organization_id"],
            agent_profile=AgentProfile.PRODUCT_DELIVERY,
            requested_scope=RequestedScope.WORKSPACE,
            target_agent_workspace_id=seed["delivery_id"],
        )

    assert resolution.decision == PolicyDecision.ALLOW
    assert resolution.business_role == BusinessRole.MEMBER
    assert resolution.allowed_resource_ids == ()
    assert resolution.consent_scope_hash is None


@pytest.mark.asyncio
async def test_delivery_scope_rejects_wrong_classification_even_if_mapping_is_inserted_outside_api(
    client, auth_headers
):
    seed = await _seed_agent_workspaces(client, auth_headers)
    group = await client.post(
        "/api/v1/conversations",
        json={
            "type": "group",
            "participant_ids": [seed["delivery_user_id"]],
            "name": "Incorrectly Classified Group",
            "workspace_id": seed["organization_id"],
        },
        headers=auth_headers,
    )
    assert group.status_code == 200
    group_id = group.json()["id"]
    consent = await client.put(
        f"/api/v1/conversations/{group_id}/ai-policy",
        json={"enabled": True},
        headers=auth_headers,
    )
    assert consent.status_code == 200

    async with db_session.async_session_maker() as db:
        db.add(
            AgentWorkspaceConversation(
                agent_workspace_id=seed["delivery_id"],
                conversation_id=group_id,
                classification="quality",
                linked_by_user_id=seed["delivery_user_id"],
            )
        )
        await db.commit()
        resolution = await resolve_agent_scope(
            db,
            user_id=seed["delivery_user_id"],
            organization_workspace_id=seed["organization_id"],
            agent_profile=AgentProfile.PRODUCT_DELIVERY,
            requested_scope=RequestedScope.WORKSPACE,
            target_agent_workspace_id=seed["delivery_id"],
        )

    assert resolution.decision == PolicyDecision.ALLOW
    assert resolution.allowed_resource_ids == ()
    assert resolution.consent_scope_hash is None


@pytest.mark.asyncio
async def test_agent_workspace_membership_revoke_api_takes_effect_immediately(
    client, auth_headers, admin_auth_headers
):
    seed = await _seed_agent_workspaces(client, auth_headers)
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "revoke-test-lead@example.com",
            "password": "password123",
            "display_name": "Revoke Test Lead",
        },
    )
    assert registered.status_code == 201
    enrolled = await client.post(
        f"/api/v1/workspaces/{seed['organization_id']}/members",
        json={"email": "revoke-test-lead@example.com", "role": "member"},
        headers=auth_headers,
    )
    assert enrolled.status_code == 201
    reassigned = await client.patch(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/"
        f"{seed['delivery_id']}/lead",
        json={"email": "revoke-test-lead@example.com"},
        headers=admin_auth_headers,
    )
    assert reassigned.status_code == 200
    response = await client.delete(
        f"/api/v1/workspaces/{seed['organization_id']}/agent-workspaces/"
        f"{seed['delivery_id']}/members/{seed['delivery_membership_id']}",
        headers=admin_auth_headers,
    )
    assert response.status_code == 204

    async with db_session.async_session_maker() as db:
        resolution = await resolve_agent_scope(
            db,
            user_id=seed["delivery_user_id"],
            organization_workspace_id=seed["organization_id"],
            agent_profile=AgentProfile.PRODUCT_DELIVERY,
            requested_scope=RequestedScope.WORKSPACE,
            target_agent_workspace_id=seed["delivery_id"],
        )
    assert resolution.decision == PolicyDecision.DENY
    assert resolution.reason == PolicyReason.NOT_MEMBER
