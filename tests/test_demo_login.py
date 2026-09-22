from types import SimpleNamespace

import pytest

import src.db.session as db_session
from scripts.seed_delivery_demo import seed_demo


@pytest.mark.asyncio
async def test_demo_accounts_are_public_click_to_login_identities(client, monkeypatch):
    monkeypatch.setattr("scripts.seed_delivery_demo.async_session_maker", db_session.async_session_maker)
    monkeypatch.setattr(
        "src.api.auth_routes.get_settings",
        lambda: SimpleNamespace(
            demo_login_enabled=True,
            allow_demo_login_in_production=False,
            app_env="test",
        ),
    )
    await seed_demo()

    listed = await client.get("/api/v1/auth/demo-accounts")
    assert listed.status_code == 200
    accounts = listed.json()
    assert [(item["account_key"], item["business_role"], item["channel_name"]) for item in accounts] == [
        ("delivery_lead", "lead", None),
        ("apollo_member", "member", "Apollo Platform"),
        ("release_member", "member", "Release 34"),
        ("portal_member", "member", "Customer Portal"),
    ]

    expected_emails = {
        "delivery_lead": "delivery-demo-lead@example.com",
        "apollo_member": "delivery-demo-member@example.com",
        "release_member": "delivery-demo-mai@example.com",
        "portal_member": "delivery-demo-an@example.com",
    }
    for account in accounts:
        login = await client.post(
            "/api/v1/auth/demo-login",
            json={"account_key": account["account_key"]},
        )
        assert login.status_code == 200
        payload = login.json()
        assert payload["user"]["email"] == expected_emails[account["account_key"]]
        me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {payload['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["email"] == expected_emails[account["account_key"]]


@pytest.mark.asyncio
async def test_demo_login_requires_explicit_production_opt_in(client, monkeypatch):
    monkeypatch.setattr(
        "src.api.auth_routes.get_settings",
        lambda: SimpleNamespace(
            demo_login_enabled=False,
            allow_demo_login_in_production=False,
            app_env="development",
        ),
    )
    assert (await client.get("/api/v1/auth/demo-accounts")).status_code == 404

    monkeypatch.setattr(
        "src.api.auth_routes.get_settings",
        lambda: SimpleNamespace(
            demo_login_enabled=True,
            allow_demo_login_in_production=False,
            app_env="production",
        ),
    )
    assert (await client.get("/api/v1/auth/demo-accounts")).status_code == 404

    monkeypatch.setattr(
        "src.api.auth_routes.get_settings",
        lambda: SimpleNamespace(
            demo_login_enabled=True,
            allow_demo_login_in_production=True,
            app_env="production",
        ),
    )
    assert (await client.get("/api/v1/auth/demo-accounts")).status_code == 200
