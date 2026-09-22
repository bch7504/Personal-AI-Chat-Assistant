from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Protocol

import httpx

from src.agents.runtime.contracts import AgentRuntimeRequest, AgentRuntimeResponse, RuntimeProgressEvent
from src.agents.runtime.executor import execute_product_delivery, execute_quality_assurance
from src.agents.runtime.security import SIGNATURE_HEADER, TIMESTAMP_HEADER, sign_runtime_body
from src.config import get_settings
from src.websocket.manager import manager


class ProductDeliveryRuntime(Protocol):
    async def run(self, request: AgentRuntimeRequest) -> AgentRuntimeResponse: ...


class EmbeddedProductDeliveryRuntime:
    async def run(self, request: AgentRuntimeRequest) -> AgentRuntimeResponse:
        progress_callback = None
        if request.progress_request_id:

            async def report(payload: dict) -> None:
                event = RuntimeProgressEvent(
                    request_id=request.progress_request_id,
                    run_id=request.run_id,
                    workflow_id=(
                        request.orchestration.workflow_id if request.orchestration else request.run_id
                    ),
                    user_id=request.actor.user_id,
                    workspace_id=request.target.organization_workspace_id,
                    agent_workspace_id=request.target.agent_workspace_id,
                    occurred_at=datetime.now(UTC),
                    **payload,
                )
                await manager.broadcast_to_users(
                    [event.user_id],
                    {"type": "workspace_agent_progress", **event.model_dump(mode="json")},
                )

            progress_callback = report
        return await execute_product_delivery(request, progress_callback=progress_callback)


class EmbeddedQualityAssuranceRuntime:
    async def run(self, request: AgentRuntimeRequest) -> AgentRuntimeResponse:
        return await execute_quality_assurance(request)


class RemoteProductDeliveryRuntime:
    def __init__(self, *, base_url: str, secret: str, timeout_seconds: float) -> None:
        self._url = f"{base_url.rstrip('/')}/internal/v1/agent-runs"
        self._secret = secret
        self._timeout = timeout_seconds

    async def run(self, request: AgentRuntimeRequest) -> AgentRuntimeResponse:
        body = request.model_dump_json().encode("utf-8")
        timestamp = int(time.time())
        headers = {
            "Content-Type": "application/json",
            TIMESTAMP_HEADER: str(timestamp),
            SIGNATURE_HEADER: sign_runtime_body(body, secret=self._secret, timestamp=timestamp),
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(self._url, content=body, headers=headers)
        response.raise_for_status()
        return AgentRuntimeResponse.model_validate_json(response.content)


class WorkspaceRuntimeBusyError(RuntimeError):
    """Raised when one workspace has exhausted its own local bulkhead."""


class BulkheadedProductDeliveryRuntime:
    _semaphores: dict[tuple[str, int], asyncio.Semaphore] = {}

    def __init__(
        self,
        inner: ProductDeliveryRuntime,
        *,
        max_concurrency: int,
        queue_timeout_seconds: float,
        run_timeout_seconds: float,
    ) -> None:
        self._inner = inner
        self._max_concurrency = max_concurrency
        self._queue_timeout = queue_timeout_seconds
        self._run_timeout = run_timeout_seconds

    async def run(self, request: AgentRuntimeRequest) -> AgentRuntimeResponse:
        key = (request.target.agent_workspace_id, self._max_concurrency)
        semaphore = self._semaphores.setdefault(key, asyncio.Semaphore(self._max_concurrency))
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=self._queue_timeout)
        except TimeoutError:
            raise WorkspaceRuntimeBusyError("Workspace runtime concurrency limit reached") from None
        try:
            async with asyncio.timeout(self._run_timeout):
                return await self._inner.run(request)
        finally:
            semaphore.release()


def get_product_delivery_runtime() -> ProductDeliveryRuntime:
    settings = get_settings()
    if settings.workspace_agent_runtime_mode == "remote":
        inner: ProductDeliveryRuntime = RemoteProductDeliveryRuntime(
            base_url=settings.workspace_agent_runtime_url,
            secret=settings.workspace_agent_runtime_secret,
            timeout_seconds=settings.workspace_agent_runtime_timeout_seconds,
        )
    else:
        inner = EmbeddedProductDeliveryRuntime()
    return BulkheadedProductDeliveryRuntime(
        inner,
        max_concurrency=settings.workspace_agent_max_concurrency,
        queue_timeout_seconds=settings.workspace_agent_runtime_queue_timeout_seconds,
        run_timeout_seconds=settings.workspace_agent_runtime_timeout_seconds,
    )


def get_quality_assurance_runtime() -> ProductDeliveryRuntime:
    settings = get_settings()
    if settings.workspace_agent_runtime_mode == "remote":
        inner: ProductDeliveryRuntime = RemoteProductDeliveryRuntime(
            base_url=settings.quality_assurance_runtime_url,
            secret=settings.quality_assurance_runtime_secret,
            timeout_seconds=settings.workspace_agent_runtime_timeout_seconds,
        )
    else:
        inner = EmbeddedQualityAssuranceRuntime()
    return BulkheadedProductDeliveryRuntime(
        inner,
        max_concurrency=settings.workspace_agent_max_concurrency,
        queue_timeout_seconds=settings.workspace_agent_runtime_queue_timeout_seconds,
        run_timeout_seconds=settings.workspace_agent_runtime_timeout_seconds,
    )


async def _remote_runtime_ready(*, enabled: bool, base_url: str) -> tuple[bool, str]:
    settings = get_settings()
    if not settings.multi_agent_enabled or not enabled:
        return True, "feature disabled"
    if settings.workspace_agent_runtime_mode == "embedded":
        return True, "embedded adapter ready"
    try:
        async with httpx.AsyncClient(timeout=min(2.0, settings.workspace_agent_runtime_timeout_seconds)) as client:
            response = await client.get(f"{base_url.rstrip('/')}/internal/v1/health/ready")
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - health must convert dependency failures to state.
        return False, f"remote runtime unavailable ({type(exc).__name__})"
    return True, "remote runtime ready"


async def product_delivery_runtime_ready() -> tuple[bool, str]:
    settings = get_settings()
    return await _remote_runtime_ready(
        enabled=settings.product_delivery_agent_enabled,
        base_url=settings.workspace_agent_runtime_url,
    )


async def quality_assurance_runtime_ready() -> tuple[bool, str]:
    settings = get_settings()
    return await _remote_runtime_ready(
        enabled=settings.quality_assurance_agent_enabled,
        base_url=settings.quality_assurance_runtime_url,
    )
