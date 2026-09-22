from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import AuditLog, User

_SENSITIVE_METADATA_KEYS = {"content", "message", "memory", "token", "secret"}


async def record_audit_event(
    db: AsyncSession,
    actor: User | None,
    action: str,
    target_type: str,
    target_id: str | None,
    workspace_id: str | None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    metadata = metadata or {}
    if _SENSITIVE_METADATA_KEYS.intersection(metadata):
        raise ValueError("Audit metadata contains sensitive content")
    actor_type = "system"
    if actor is not None:
        actor_type = "platform_admin" if actor.platform_role == "platform_admin" else "user"
    record = AuditLog(
        workspace_id=workspace_id,
        actor_user_id=actor.id if actor is not None else None,
        actor_type=actor_type,
        action=action,
        target_type=target_type,
        target_id=target_id,
        metadata_json=metadata,
        ip_address=ip_address,
    )
    db.add(record)
    await db.flush()
    return record
