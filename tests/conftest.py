import os
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Tests must not inherit a developer's local PostgreSQL configuration. Set this before
# importing application modules so the agent uses its isolated in-memory checkpointer.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-only-secret-key-with-at-least-32-bytes"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["ALLOW_SELF_SERVICE_ORGANIZATION_CREATION"] = "true"
os.environ["OPEN_TEST_CHAT_ENABLED"] = "false"
os.environ["CREDENTIAL_ENCRYPTION_KEY"] = "T3WGf3PaqPii2yO527bMcShobRNF3TpJ4sA3f9lkJkU="

import src.db.session as db_session
from src.db.base import Base
from src.db.models import User
from src.db.session import get_db
from src.main import app


@pytest_asyncio.fixture
async def client(monkeypatch):
    """Async HTTP client backed by an isolated in-memory database."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    test_session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with test_session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("src.db.session.async_session_maker", test_session_maker)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


@pytest_asyncio.fixture
async def auth_headers(client):
    """Registers a test user and returns an Authorization header for it."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": "password123", "display_name": "Alice"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "password123"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def personal_workspace(client, auth_headers):
    """Returns the personal workspace created automatically at registration."""
    resp = await client.get("/api/v1/workspaces", headers=auth_headers)
    assert resp.status_code == 200
    return next(workspace for workspace in resp.json() if workspace["type"] == "personal")


@pytest_asyncio.fixture
async def admin_auth_headers(client):
    """Registers a test user with both legacy and platform admin roles."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "admin@example.com", "password": "password123", "display_name": "Admin"},
    )

    async with db_session.async_session_maker() as session:
        user = (await session.execute(select(User).where(User.email == "admin@example.com"))).scalar_one()
        user.role = "admin"
        user.platform_role = "platform_admin"
        await session.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password123"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def platform_admin_headers(client):
    """Registers a platform admin without granting any workspace role."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "platform@example.com", "password": "password123", "display_name": "Platform Admin"},
    )

    async with db_session.async_session_maker() as session:
        user = (await session.execute(select(User).where(User.email == "platform@example.com"))).scalar_one()
        user.platform_role = "platform_admin"
        await session.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "platform@example.com", "password": "password123"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def legacy_admin_headers(client):
    """Registers an account carrying only the deprecated global admin role."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "legacy-admin@example.com", "password": "password123", "display_name": "Legacy Admin"},
    )

    async with db_session.async_session_maker() as session:
        user = (await session.execute(select(User).where(User.email == "legacy-admin@example.com"))).scalar_one()
        user.role = "admin"
        await session.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "legacy-admin@example.com", "password": "password123"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def other_auth_headers(client):
    """Registers a second test user and returns an Authorization header for it."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "bob@example.com", "password": "password123", "display_name": "Bob"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": "password123"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mock_llm():
    """Mock LLM to avoid calling OpenAI during tests.

    Usage in test:
        def test_something(mock_llm):
            # LLM calls will return mock response instead of hitting OpenAI
            ...
    """
    mock = AsyncMock()
    mock.ainvoke.return_value = AsyncMock(content="Mocked LLM response")
    return mock


class FakeToolCallingLLM:
    """Stand-in for a ChatOpenAI instance bound to tools.

    `.bind_tools(...)` returns self (mirroring the real API), and each `.ainvoke(...)`
    call pops the next scripted response off a queue - lets a test script an exact
    AIMessage(tool_calls=[...]) -> AIMessage(content=...) sequence without a live LLM.
    """

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.invocations: list = []

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.invocations.append(messages)
        if not self._responses:
            raise AssertionError("FakeToolCallingLLM ran out of scripted responses")
        return self._responses.pop(0)


@pytest.fixture
def fake_llm_factory():
    def _make(responses: list) -> FakeToolCallingLLM:
        return FakeToolCallingLLM(responses)

    return _make
