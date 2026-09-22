"""Authenticated runtime-to-Core progress callback."""

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError

from src.agents.runtime.contracts import RuntimeProgressEvent
from src.agents.runtime.security import SIGNATURE_HEADER, TIMESTAMP_HEADER, verify_runtime_signature
from src.config import get_settings
from src.websocket.manager import manager

router = APIRouter()


@router.post("/internal/v1/workspace-agent-progress", status_code=status.HTTP_202_ACCEPTED)
async def receive_workspace_agent_progress(request: Request) -> dict[str, bool]:
    settings = get_settings()
    body = await request.body()
    timestamp = request.headers.get(TIMESTAMP_HEADER)
    signature = request.headers.get(SIGNATURE_HEADER)
    trusted_runtime_secrets = {
        settings.workspace_agent_runtime_secret,
        settings.quality_assurance_runtime_secret,
    }
    if not any(
        verify_runtime_signature(
            body,
            secret=secret,
            timestamp_text=timestamp,
            signature=signature,
            max_age_seconds=settings.workspace_agent_runtime_signature_max_age_seconds,
        )
        for secret in trusted_runtime_secrets
        if secret
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid runtime signature")
    try:
        event = RuntimeProgressEvent.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from None
    await manager.broadcast_to_users(
        [event.user_id],
        {
            "type": "workspace_agent_progress",
            **event.model_dump(mode="json"),
        },
    )
    return {"accepted": True}
