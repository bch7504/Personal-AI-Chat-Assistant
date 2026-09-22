from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from pydantic import ValidationError

from src.agents.contracts import AgentProfile
from src.agents.runtime.contracts import AgentRuntimeRequest, AgentRuntimeResponse, RuntimeProgressEvent
from src.agents.runtime.executor import execute_product_delivery, execute_workspace_agent
from src.agents.runtime.security import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    sign_runtime_body,
    verify_runtime_signature,
)
from src.config import get_settings

app = FastAPI(
    title="Orbit Workspace Agent Runtime",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
logger = logging.getLogger(__name__)


def _progress_reporter(invocation: AgentRuntimeRequest):
    if not invocation.progress_request_id:
        return None
    settings = get_settings()
    callback_url = settings.workspace_agent_progress_callback_url.strip()
    if not callback_url:
        return None

    async def report(payload: dict) -> None:
        event = RuntimeProgressEvent(
            request_id=invocation.progress_request_id,
            run_id=invocation.run_id,
            workflow_id=invocation.orchestration.workflow_id if invocation.orchestration else invocation.run_id,
            user_id=invocation.actor.user_id,
            workspace_id=invocation.target.organization_workspace_id,
            agent_workspace_id=invocation.target.agent_workspace_id,
            occurred_at=datetime.now(UTC),
            **payload,
        )
        body = event.model_dump_json().encode("utf-8")
        timestamp = int(time.time())
        headers = {
            "Content-Type": "application/json",
            TIMESTAMP_HEADER: str(timestamp),
            SIGNATURE_HEADER: sign_runtime_body(
                body,
                secret=settings.workspace_agent_runtime_secret,
                timestamp=timestamp,
            ),
        }
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.post(callback_url, content=body, headers=headers)
            response.raise_for_status()
        except Exception:  # noqa: BLE001 - telemetry cannot fail a business run.
            logger.exception("Unable to report specialist progress")

    return report


@app.get("/internal/v1/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/internal/v1/health/ready")
async def ready() -> dict[str, str]:
    settings = get_settings()
    if not settings.workspace_agent_runtime_workspace_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WORKSPACE_AGENT_RUNTIME_WORKSPACE_ID is not configured",
        )
    if not settings.workspace_agent_runtime_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal runtime authentication is not configured",
        )
    return {
        "status": "ready",
        "workspace_id": settings.workspace_agent_runtime_workspace_id,
        "profile": settings.workspace_agent_runtime_profile,
        "runtime_version": settings.workspace_agent_runtime_version,
    }


@app.post("/internal/v1/agent-runs", response_model=AgentRuntimeResponse)
async def run_agent(request: Request) -> AgentRuntimeResponse:
    settings = get_settings()
    body = await request.body()
    if not verify_runtime_signature(
        body,
        secret=settings.workspace_agent_runtime_secret,
        timestamp_text=request.headers.get(TIMESTAMP_HEADER),
        signature=request.headers.get(SIGNATURE_HEADER),
        max_age_seconds=settings.workspace_agent_runtime_signature_max_age_seconds,
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid runtime signature")
    try:
        invocation = AgentRuntimeRequest.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from None

    if invocation.authorization.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Runtime authorization expired")
    expected = (
        settings.workspace_agent_runtime_workspace_id,
        AgentProfile(settings.workspace_agent_runtime_profile),
        settings.workspace_agent_runtime_version,
    )
    actual = (
        invocation.target.agent_workspace_id,
        invocation.target.profile,
        invocation.target.runtime_version,
    )
    if not expected[0]:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Runtime is not provisioned")
    if actual != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Runtime target mismatch")
    # Keep the Product Delivery entrypoint explicit for backward-compatible deployment/tests;
    # every additional profile uses the shared dispatcher.
    if invocation.target.profile == AgentProfile.PRODUCT_DELIVERY:
        reporter = _progress_reporter(invocation)
        if reporter is not None:
            return await execute_product_delivery(invocation, progress_callback=reporter)
        return await execute_product_delivery(invocation)
    return await execute_workspace_agent(invocation)
