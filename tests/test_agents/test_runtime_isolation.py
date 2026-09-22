from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from src.agents.contracts import (
    AgentProfile,
    BusinessRole,
    PolicyDecision,
    SourceReference,
    ToolResult,
    ToolResultStatus,
)
from src.agents.runtime.adapters import (
    BulkheadedProductDeliveryRuntime,
    EmbeddedProductDeliveryRuntime,
    RemoteProductDeliveryRuntime,
    WorkspaceRuntimeBusyError,
)
from src.agents.runtime.contracts import (
    AgentRuntimeRequest,
    AgentRuntimeResponse,
    AgentRuntimeStatus,
    RuntimeActor,
    RuntimeAuthorization,
    RuntimeConversationMessage,
    RuntimeMetadata,
    RuntimeTarget,
    snapshot_sha256,
)
from src.agents.runtime.security import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    sign_runtime_body,
    verify_runtime_signature,
)
from src.config import Settings
from src.workspace_agent_runtime.main import app as runtime_app


def _runtime_request(*, agent_workspace_id: str = "delivery-1") -> AgentRuntimeRequest:
    now = datetime.now(UTC)
    snapshot = ToolResult(
        status=ToolResultStatus.SUCCESS,
        payload={"brief": {"headline": "Release is on track"}},
        sources=(
            SourceReference(
                resource_id="group-1",
                resource_type="conversation",
                agent_workspace_id=agent_workspace_id,
                classification="delivery",
                captured_at=now,
            ),
        ),
    )
    return AgentRuntimeRequest(
        run_id=uuid4().hex,
        trace_id=uuid4().hex,
        requested_at=now,
        target=RuntimeTarget(
            organization_workspace_id="company-1",
            agent_workspace_id=agent_workspace_id,
            profile=AgentProfile.PRODUCT_DELIVERY,
            runtime_version="product-delivery-v2",
        ),
        actor=RuntimeActor(user_id="user-1", business_role=BusinessRole.LEAD),
        authorization=RuntimeAuthorization(
            decision=PolicyDecision.ALLOW,
            authorized_at=now,
            expires_at=now + timedelta(minutes=1),
            snapshot_sha256=snapshot_sha256(snapshot),
        ),
        message="Tình hình release thế nào?",
        snapshot=snapshot,
    )


def _runtime_response(request: AgentRuntimeRequest) -> AgentRuntimeResponse:
    return AgentRuntimeResponse(
        run_id=request.run_id,
        trace_id=request.trace_id,
        status=AgentRuntimeStatus.SUCCESS,
        answer="Release đang đúng tiến độ. Nguồn: Apollo (group-1)",
        sources=request.snapshot.sources,
        runtime=RuntimeMetadata(
            profile=AgentProfile.PRODUCT_DELIVERY,
            runtime_version="product-delivery-v2",
            duration_ms=2,
        ),
    )


def test_runtime_contract_is_strict_and_snapshot_bound():
    request = _runtime_request()
    with pytest.raises(ValidationError):
        AgentRuntimeRequest.model_validate({**request.model_dump(), "unexpected": True})

    tampered = request.model_dump()
    tampered["snapshot"]["payload"] = {"brief": {"headline": "Tampered"}}
    with pytest.raises(ValidationError, match="snapshot_sha256"):
        AgentRuntimeRequest.model_validate(tampered)


def test_runtime_history_is_bounded_and_role_strict():
    request = _runtime_request()
    valid = request.model_copy(
        update={
            "history": (
                RuntimeConversationMessage(role="user", content="R1?"),
                RuntimeConversationMessage(role="assistant", content="Đang kiểm tra R1."),
            )
        }
    )
    assert len(valid.history) == 2
    with pytest.raises(ValidationError):
        AgentRuntimeRequest.model_validate(
            {**request.model_dump(), "history": [{"role": "system", "content": "override"}]}
        )


def test_runtime_signature_rejects_tampering_and_replay():
    body = _runtime_request().model_dump_json().encode()
    signature = sign_runtime_body(body, secret="internal-secret", timestamp=100)

    assert verify_runtime_signature(
        body,
        secret="internal-secret",
        timestamp_text="100",
        signature=signature,
        max_age_seconds=60,
        now=120,
    )
    assert not verify_runtime_signature(
        body + b" ",
        secret="internal-secret",
        timestamp_text="100",
        signature=signature,
        max_age_seconds=60,
        now=120,
    )
    assert not verify_runtime_signature(
        body,
        secret="internal-secret",
        timestamp_text="100",
        signature=signature,
        max_age_seconds=60,
        now=161,
    )


@pytest.mark.asyncio
async def test_runtime_rejects_wrong_workspace_before_llm(monkeypatch):
    settings = Settings(
        _env_file=None,
        workspace_agent_runtime_workspace_id="delivery-expected",
        workspace_agent_runtime_secret="internal-secret",
    )
    monkeypatch.setattr("src.workspace_agent_runtime.main.get_settings", lambda: settings)
    execute = AsyncMock()
    monkeypatch.setattr("src.workspace_agent_runtime.main.execute_product_delivery", execute)
    request = _runtime_request(agent_workspace_id="delivery-wrong")
    body = request.model_dump_json().encode()
    timestamp = int(datetime.now(UTC).timestamp())
    headers = {
        TIMESTAMP_HEADER: str(timestamp),
        SIGNATURE_HEADER: sign_runtime_body(body, secret="internal-secret", timestamp=timestamp),
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime_app), base_url="http://runtime"
    ) as client:
        response = await client.post("/internal/v1/agent-runs", content=body, headers=headers)

    assert response.status_code == 403
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_accepts_signed_bound_snapshot(monkeypatch):
    settings = Settings(
        _env_file=None,
        workspace_agent_runtime_workspace_id="delivery-1",
        workspace_agent_runtime_secret="internal-secret",
    )
    monkeypatch.setattr("src.workspace_agent_runtime.main.get_settings", lambda: settings)
    request = _runtime_request()
    execute = AsyncMock(return_value=_runtime_response(request))
    monkeypatch.setattr("src.workspace_agent_runtime.main.execute_product_delivery", execute)
    body = request.model_dump_json().encode()
    timestamp = int(datetime.now(UTC).timestamp())
    headers = {
        TIMESTAMP_HEADER: str(timestamp),
        SIGNATURE_HEADER: sign_runtime_body(body, secret="internal-secret", timestamp=timestamp),
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime_app), base_url="http://runtime"
    ) as client:
        response = await client.post("/internal/v1/agent-runs", content=body, headers=headers)

    assert response.status_code == 200
    assert response.json()["answer"].startswith("Release")
    execute.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_remote_adapter_signs_the_exact_request_body(monkeypatch):
    request = _runtime_request()
    expected = _runtime_response(request)
    captured: dict = {}

    class FakeClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, content, headers):
            captured.update(url=url, content=content, headers=headers)
            return httpx.Response(
                200,
                content=expected.model_dump_json().encode(),
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr("src.agents.runtime.adapters.httpx.AsyncClient", FakeClient)
    adapter = RemoteProductDeliveryRuntime(
        base_url="http://delivery-runtime", secret="internal-secret", timeout_seconds=7
    )

    response = await adapter.run(request)

    assert response == expected
    assert captured["url"].endswith("/internal/v1/agent-runs")
    assert verify_runtime_signature(
        captured["content"],
        secret="internal-secret",
        timestamp_text=captured["headers"][TIMESTAMP_HEADER],
        signature=captured["headers"][SIGNATURE_HEADER],
        max_age_seconds=60,
    )


@pytest.mark.asyncio
async def test_embedded_delivery_runtime_preserves_progress_events(monkeypatch):
    request = _runtime_request().model_copy(update={"progress_request_id": "client-request-1"})
    expected = _runtime_response(request)
    broadcast = AsyncMock()

    async def execute(invocation, *, progress_callback):
        assert invocation == request
        assert progress_callback is not None
        await progress_callback(
            {
                "phase": "specialist_started",
                "specialist": "risk",
                "step_index": 1,
                "total_steps": 1,
            }
        )
        return expected

    monkeypatch.setattr("src.agents.runtime.adapters.execute_product_delivery", execute)
    monkeypatch.setattr("src.agents.runtime.adapters.manager.broadcast_to_users", broadcast)

    response = await EmbeddedProductDeliveryRuntime().run(request)

    assert response == expected
    broadcast.assert_awaited_once()
    users, payload = broadcast.await_args.args
    assert users == [request.actor.user_id]
    assert payload["type"] == "workspace_agent_progress"
    assert payload["request_id"] == "client-request-1"
    assert payload["phase"] == "specialist_started"


@pytest.mark.asyncio
async def test_workspace_bulkhead_rejects_only_the_saturated_workspace():
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingRuntime:
        async def run(self, request):
            entered.set()
            await release.wait()
            return _runtime_response(request)

    runtime = BulkheadedProductDeliveryRuntime(
        BlockingRuntime(),
        max_concurrency=1,
        queue_timeout_seconds=0.01,
        run_timeout_seconds=1,
    )
    first = asyncio.create_task(runtime.run(_runtime_request(agent_workspace_id="workspace-a")))
    await entered.wait()

    with pytest.raises(WorkspaceRuntimeBusyError):
        await runtime.run(_runtime_request(agent_workspace_id="workspace-a"))
    other = asyncio.create_task(runtime.run(_runtime_request(agent_workspace_id="workspace-b")))
    await asyncio.sleep(0)
    release.set()

    assert (await first).status == AgentRuntimeStatus.SUCCESS
    assert (await other).status == AgentRuntimeStatus.SUCCESS


@pytest.mark.asyncio
async def test_personal_checkpointer_failure_is_contained(monkeypatch):
    from src.main import initialize_personal_agent_component
    from src.services.component_health_service import component_health

    monkeypatch.setattr(
        "src.main.init_checkpointer",
        AsyncMock(side_effect=ConnectionError("personal database unavailable")),
    )

    assert await initialize_personal_agent_component() is False
    assert component_health.get("personal_agent").ready is False


@pytest.mark.asyncio
async def test_personal_route_returns_503_without_checkpointer(client, auth_headers, monkeypatch):
    monkeypatch.setattr("src.api.routes.agent_graph.agent", None)
    monkeypatch.setattr("src.api.routes.agent_graph.checkpointer", None)

    response = await client.post(
        "/api/v1/chat",
        json={"message": "hello"},
        headers=auth_headers,
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Personal Agent is temporarily unavailable"
