import pytest


async def _personal_workspace(client, headers):
    response = await client.get("/api/v1/workspaces", headers=headers)
    assert response.status_code == 200
    return next(item for item in response.json() if item["type"] == "personal")


@pytest.mark.asyncio
async def test_personal_external_relationship_round_trip(client, auth_headers):
    workspace = await _personal_workspace(client, auth_headers)
    contact_response = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/external-contacts",
        json={
            "email": "CLIENT@Example.com",
            "display_name": "  Client One  ",
            "organization": "  Acme  ",
        },
        headers=auth_headers,
    )
    assert contact_response.status_code == 201
    contact = contact_response.json()
    assert contact["email"] == "client@example.com"
    assert contact["display_name"] == "Client One"
    assert contact["organization"] == "Acme"

    relationship_response = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/relationships",
        json={
            "subject_kind": "external_contact",
            "subject_id": contact["id"],
            "relationship_type": "client",
            "strength": 4,
            "notes": "  Prefers concise weekly updates.  ",
        },
        headers=auth_headers,
    )
    assert relationship_response.status_code == 201
    relationship = relationship_response.json()
    assert relationship["status"] == "active"
    assert relationship["source"] == "manual"
    assert relationship["notes"] == "Prefers concise weekly updates."

    listed = await client.get(
        f"/api/v1/workspaces/{workspace['id']}/relationships",
        headers=auth_headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [relationship["id"]]

    archived = await client.delete(
        f"/api/v1/workspaces/{workspace['id']}/relationships/{relationship['id']}",
        headers=auth_headers,
    )
    assert archived.status_code == 204
    active_only = await client.get(
        f"/api/v1/workspaces/{workspace['id']}/relationships",
        headers=auth_headers,
    )
    assert active_only.json() == []


@pytest.mark.asyncio
async def test_internal_relationship_is_private_to_owner(
    client,
    auth_headers,
    other_auth_headers,
):
    bob = (await client.get("/api/v1/auth/me", headers=other_auth_headers)).json()
    workspace = (
        await client.post(
            "/api/v1/workspaces",
            json={"name": "Relationship Team"},
            headers=auth_headers,
        )
    ).json()
    added = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/members",
        json={"email": bob["email"], "role": "member"},
        headers=auth_headers,
    )
    assert added.status_code == 201

    created = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/relationships",
        json={
            "subject_kind": "workspace_user",
            "subject_id": bob["id"],
            "relationship_type": "colleague",
            "strength": 3,
            "notes": "Private context",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201

    bob_list = await client.get(
        f"/api/v1/workspaces/{workspace['id']}/relationships",
        headers=other_auth_headers,
    )
    assert bob_list.status_code == 200
    assert bob_list.json() == []


@pytest.mark.asyncio
async def test_relationship_validation_and_duplicate_protection(client, auth_headers):
    workspace = await _personal_workspace(client, auth_headers)
    contact = (
        await client.post(
            f"/api/v1/workspaces/{workspace['id']}/external-contacts",
            json={"email": "advisor@example.com", "display_name": "Advisor"},
            headers=auth_headers,
        )
    ).json()
    invalid = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/relationships",
        json={
            "subject_kind": "external_contact",
            "subject_id": contact["id"],
            "relationship_type": "other",
            "strength": 6,
        },
        headers=auth_headers,
    )
    assert invalid.status_code == 422

    payload = {
        "subject_kind": "external_contact",
        "subject_id": contact["id"],
        "relationship_type": "other",
        "custom_label": "Advisor",
        "strength": 5,
    }
    assert (
        await client.post(
            f"/api/v1/workspaces/{workspace['id']}/relationships",
            json=payload,
            headers=auth_headers,
        )
    ).status_code == 201
    duplicate = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/relationships",
        json=payload,
        headers=auth_headers,
    )
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_regular_member_cannot_add_other_workspace_members(
    client,
    auth_headers,
    other_auth_headers,
):
    bob = (await client.get("/api/v1/auth/me", headers=other_auth_headers)).json()
    workspace = (
        await client.post(
            "/api/v1/workspaces",
            json={"name": "Managed Team"},
            headers=auth_headers,
        )
    ).json()
    await client.post(
        f"/api/v1/workspaces/{workspace['id']}/members",
        json={"email": bob["email"], "role": "member"},
        headers=auth_headers,
    )
    denied = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/members",
        json={"email": "alice@example.com", "role": "member"},
        headers=other_auth_headers,
    )
    assert denied.status_code == 403
