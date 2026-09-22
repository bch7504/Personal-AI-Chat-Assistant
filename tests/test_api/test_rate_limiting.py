import pytest

from src.api.rate_limit import request_limiter
from src.services import usage_service


@pytest.fixture(autouse=True)
def _enable_rate_limiting(monkeypatch):
    monkeypatch.setattr(request_limiter, "enabled", True)
    request_limiter.reset()
    yield
    request_limiter.reset()


@pytest.mark.asyncio
async def test_register_is_rate_limited_per_ip(client):
    for index in range(5):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"rate-register-{index}@example.com",
                "password": "password123",
                "display_name": "Rate Test",
            },
        )
        assert response.status_code == 201
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "rate-register-overflow@example.com",
            "password": "password123",
            "display_name": "Rate Test",
        },
    )
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


@pytest.mark.asyncio
async def test_chat_is_rate_limited_per_user(client, auth_headers, monkeypatch):
    async def _over_budget(user_id):
        assert user_id
        return True

    monkeypatch.setattr(usage_service, "is_over_budget", _over_budget)
    for _ in range(15):
        response = await client.post("/api/v1/chat", json={"message": "hello"}, headers=auth_headers)
        assert response.status_code == 200
    response = await client.post("/api/v1/chat", json={"message": "hello"}, headers=auth_headers)
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_health_is_exempt(client):
    for _ in range(70):
        assert (await client.get("/health")).status_code == 200


def test_read_and_mutation_requests_use_separate_rate_limit_tiers(monkeypatch):
    settings = type("Settings", (), {
        "rate_limit_register": "5/minute",
        "rate_limit_auth": "10/minute",
        "rate_limit_chat": "15/minute",
        "rate_limit_read": "300/minute",
        "rate_limit_crud": "60/minute",
    })()
    monkeypatch.setattr("src.api.rate_limit.get_settings", lambda: settings)

    from starlette.requests import Request

    read_request = Request({"type": "http", "method": "GET", "path": "/api/v1/tasks", "headers": []})
    write_request = Request({"type": "http", "method": "PATCH", "path": "/api/v1/tasks/1", "headers": []})

    assert request_limiter._tier(read_request) == ("read", "300/minute")
    assert request_limiter._tier(write_request) == ("crud", "60/minute")
