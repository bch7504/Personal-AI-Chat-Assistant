import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.agents.runtime.security import SIGNATURE_HEADER, TIMESTAMP_HEADER, sign_runtime_body


@pytest.mark.asyncio
@pytest.mark.parametrize("secret", ["product-secret", "quality-secret"])
async def test_runtime_progress_accepts_each_provisioned_runtime_secret(client, monkeypatch, secret):
    settings = SimpleNamespace(
        workspace_agent_runtime_secret="product-secret",
        quality_assurance_runtime_secret="quality-secret",
        workspace_agent_runtime_signature_max_age_seconds=60,
    )
    broadcast = AsyncMock()
    monkeypatch.setattr("src.api.runtime_progress_routes.get_settings", lambda: settings)
    monkeypatch.setattr("src.api.runtime_progress_routes.manager.broadcast_to_users", broadcast)
    body = json.dumps(
        {
            "request_id": "request-1",
            "run_id": "run-1",
            "workflow_id": "workflow-1",
            "user_id": "user-1",
            "workspace_id": "workspace-1",
            "agent_workspace_id": "agent-workspace-1",
            "phase": "specialist_started",
            "total_steps": 1,
            "occurred_at": "2026-08-31T12:00:00Z",
        },
        separators=(",", ":"),
    ).encode()
    timestamp = int(time.time())

    response = await client.post(
        "/internal/v1/workspace-agent-progress",
        content=body,
        headers={
            "Content-Type": "application/json",
            TIMESTAMP_HEADER: str(timestamp),
            SIGNATURE_HEADER: sign_runtime_body(body, secret=secret, timestamp=timestamp),
        },
    )

    assert response.status_code == 202
    assert response.json() == {"accepted": True}
    broadcast.assert_awaited_once()


@pytest.mark.asyncio
async def test_runtime_progress_rejects_an_unknown_runtime_secret(client, monkeypatch):
    settings = SimpleNamespace(
        workspace_agent_runtime_secret="product-secret",
        quality_assurance_runtime_secret="quality-secret",
        workspace_agent_runtime_signature_max_age_seconds=60,
    )
    monkeypatch.setattr("src.api.runtime_progress_routes.get_settings", lambda: settings)
    body = b"{}"
    timestamp = int(time.time())

    response = await client.post(
        "/internal/v1/workspace-agent-progress",
        content=body,
        headers={
            "Content-Type": "application/json",
            TIMESTAMP_HEADER: str(timestamp),
            SIGNATURE_HEADER: sign_runtime_body(body, secret="unknown-secret", timestamp=timestamp),
        },
    )

    assert response.status_code == 401
