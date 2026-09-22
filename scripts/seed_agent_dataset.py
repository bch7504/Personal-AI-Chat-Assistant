"""Seed the canonical user-agent dataset into a local/test database.

The command is preview-only unless ``--apply`` is supplied. Logical fixture IDs are
converted to deterministic UUID5 values, making repeated runs for one namespace
idempotent and allowing multiple team members to share one database safely.
"""

# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_agent_dataset import DEFAULT_DATASET, load_and_validate  # noqa: E402


NAMESPACE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")


def validate_seed_database_url(database_url: str) -> str:
    from sqlalchemy.engine import make_url

    try:
        parsed = make_url(database_url)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"DATABASE_URL không hợp lệ: {exc}") from exc
    database_name = (parsed.database or "").lower()
    host = (parsed.host or "").lower()
    forbidden_names = {"orbit", "postgres", "template0", "template1"}
    if not parsed.drivername.startswith("postgresql"):
        raise ValueError("Acceptance dataset chỉ được seed vào PostgreSQL test, không chấp nhận SQLite")
    if database_name in forbidden_names or not re.search(r"(?:test|eval)", database_name):
        raise ValueError("Tên database seed phải chứa 'test' hoặc 'eval' và không được là orbit/postgres")
    if host not in {"localhost", "127.0.0.1", "postgres"}:
        raise ValueError("Vì an toàn, acceptance dataset chỉ được seed vào PostgreSQL local/Docker local")
    return database_name


def stable_id(dataset_id: str, namespace: str, logical_id: str) -> str:
    key = f"{dataset_id}:{namespace}:{logical_id}"
    return uuid5(NAMESPACE_URL, key).hex


def namespaced_email(namespace: str, email_local: str) -> str:
    return f"{namespace}.{email_local}@example.com"


def resolve_relative_date(
    rule: dict[str, Any] | None,
    anchor: datetime,
    timezone: ZoneInfo,
) -> datetime | None:
    if rule is None:
        return None
    local_anchor = anchor.astimezone(timezone)
    if rule["type"] == "offset_days":
        if "hour" not in rule:
            return (local_anchor + timedelta(days=rule["days"])).astimezone(UTC)
        target_date = local_anchor.date() + timedelta(days=rule["days"])
    elif rule["type"] == "next_weekday":
        days_ahead = (rule["weekday"] - local_anchor.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        target_date = local_anchor.date() + timedelta(days=days_ahead)
    else:  # protected by the validator
        raise ValueError(f"Unsupported relative date rule: {rule['type']}")
    target_time = time(rule.get("hour", 0), rule.get("minute", 0), tzinfo=timezone)
    return datetime.combine(target_date, target_time).astimezone(UTC)


async def _upsert(session: Any, model: Any, identity: str | dict[str, str], values: dict[str, Any]) -> Any:
    obj = await session.get(model, identity)
    if obj is None:
        identity_values = {"id": identity} if isinstance(identity, str) else identity
        obj = model(**identity_values, **values)
        session.add(obj)
    else:
        for key, value in values.items():
            setattr(obj, key, value)
    return obj


async def seed_dataset(data: dict[str, Any], namespace: str) -> dict[str, Any]:
    # Imports are intentionally delayed so preview mode does not open/configure a database.
    from src.auth.security import hash_password
    from src.config import get_settings
    from src.db.models import (
        AIPermission,
        Conversation,
        ConversationParticipant,
        Memory,
        Message,
        Task,
        User,
        Workspace,
        WorkspaceMembership,
    )
    from src.db.session import async_session_maker, init_db

    settings = get_settings()
    if settings.app_env == "production":
        raise RuntimeError("Refusing to seed synthetic acceptance data into APP_ENV=production")
    validate_seed_database_url(settings.database_url)

    await init_db()
    seed = data["seed"]
    timezone = ZoneInfo(data["timezone"])
    anchor = datetime.now(timezone).replace(second=0, microsecond=0)
    dataset_id = data["dataset_id"]
    version = data["version"]
    actual_id = lambda logical: stable_id(dataset_id, namespace, logical)  # noqa: E731
    password_hash = hash_password(seed["default_password"])

    async with async_session_maker() as session:
        for user in seed["users"]:
            await _upsert(
                session,
                User,
                actual_id(user["id"]),
                {
                    "email": namespaced_email(namespace, user["email_local"]),
                    "password_hash": password_hash,
                    "display_name": user["display_name"],
                    "role": "user",
                    "platform_role": "user",
                    "is_active": True,
                    "job_title": user["job_title"],
                    "timezone": user["timezone"],
                    "preferences": {"fixture_namespace": namespace, "dataset_version": version},
                    "created_at": anchor.astimezone(UTC) - timedelta(days=7),
                },
            )
        await session.flush()

        workspace = seed["workspace"]
        workspace_id = actual_id(workspace["id"])
        await _upsert(
            session,
            Workspace,
            workspace_id,
            {
                "type": workspace["type"],
                "name": f"{workspace['name']} [{namespace}]",
                "slug": f"qa-{namespace}-novacrm",
                "personal_owner_user_id": None,
                "status": "active",
                "created_at": anchor.astimezone(UTC) - timedelta(days=7),
                "updated_at": anchor.astimezone(UTC),
            },
        )
        await session.flush()

        for member in workspace["members"]:
            membership_id = actual_id(f"membership:{member['user_id']}")
            inviter = None if member["role"] == "owner" else actual_id(data["coverage"]["primary_user_id"])
            await _upsert(
                session,
                WorkspaceMembership,
                membership_id,
                {
                    "workspace_id": workspace_id,
                    "user_id": actual_id(member["user_id"]),
                    "role": member["role"],
                    "status": "active",
                    "invited_by_user_id": inviter,
                    "joined_at": anchor.astimezone(UTC) - timedelta(days=7),
                    "created_at": anchor.astimezone(UTC) - timedelta(days=7),
                    "updated_at": anchor.astimezone(UTC),
                },
            )
        await session.flush()

        for conversation in seed["conversations"]:
            conversation_id = actual_id(conversation["id"])
            policy = conversation["ai_policy"]
            group_ai_enabled = conversation["type"] == "group" and policy["enabled"]
            first_offset = min(message["offset_minutes"] for message in conversation["messages"])
            created_at = anchor + timedelta(minutes=first_offset - 5)
            await _upsert(
                session,
                Conversation,
                conversation_id,
                {
                    "workspace_id": workspace_id,
                    "type": conversation["type"],
                    "name": conversation["name"],
                    "created_by": actual_id(conversation["created_by"]),
                    "ai_enabled": group_ai_enabled,
                    "ai_policy_version": 1 if group_ai_enabled else 0,
                    "ai_enabled_by_user_id": actual_id(policy["enabled_by"]) if group_ai_enabled else None,
                    "ai_enabled_at": anchor.astimezone(UTC) if group_ai_enabled else None,
                    "created_at": created_at.astimezone(UTC),
                    "updated_at": anchor.astimezone(UTC),
                },
            )
        await session.flush()

        for conversation in seed["conversations"]:
            conversation_id = actual_id(conversation["id"])
            for participant in conversation["participants"]:
                user_id = actual_id(participant["user_id"])
                participant_id = actual_id(f"participant:{conversation['id']}:{participant['user_id']}")
                await _upsert(
                    session,
                    ConversationParticipant,
                    participant_id,
                    {
                        "conversation_id": conversation_id,
                        "principal_kind": "workspace_user",
                        "user_id": user_id,
                        "external_contact_id": None,
                        "resource_role": participant["resource_role"],
                        "invited_by_user_id": actual_id(conversation["created_by"]),
                        "joined_at": anchor.astimezone(UTC) - timedelta(days=1),
                        "last_read_at": anchor.astimezone(UTC),
                        "revoked_at": None,
                        "hidden_at": None,
                    },
                )
                if conversation["type"] == "direct":
                    permission_identity = {"conversation_id": conversation_id, "user_id": user_id}
                    await _upsert(
                        session,
                        AIPermission,
                        permission_identity,
                        {
                            "granted": conversation["ai_policy"]["enabled"],
                            "contribution_allowed": conversation["ai_policy"]["enabled"],
                            "updated_at": anchor.astimezone(UTC),
                        },
                    )
            for message in conversation["messages"]:
                await _upsert(
                    session,
                    Message,
                    actual_id(message["id"]),
                    {
                        "conversation_id": conversation_id,
                        "sender_id": actual_id(message["sender_id"]),
                        "content": message["content"],
                        "created_at": (anchor + timedelta(minutes=message["offset_minutes"])).astimezone(UTC),
                    },
                )
        await session.flush()

        for task in seed["tasks"]:
            await _upsert(
                session,
                Task,
                actual_id(task["id"]),
                {
                    "workspace_id": workspace_id,
                    "owner_id": actual_id(task["owner_id"]),
                    "conversation_id": actual_id(task["conversation_id"]) if task.get("conversation_id") else None,
                    "title": task["title"],
                    "due_at": resolve_relative_date(task["due"], anchor, timezone),
                    "priority": task["priority"],
                    "status": task["status"],
                    "source": task["source"],
                    "source_message_ids": None,
                    "source_sender_id": None,
                    "consent_scope_hash": None,
                    "invalidated_reason": None,
                    "created_at": anchor.astimezone(UTC),
                    "updated_at": anchor.astimezone(UTC),
                },
            )

        for memory in seed["memories"]:
            await _upsert(
                session,
                Memory,
                actual_id(memory["id"]),
                {
                    "workspace_id": workspace_id,
                    "owner_id": actual_id(memory["owner_id"]),
                    "category": memory["category"],
                    "title": memory["title"],
                    "detail": memory["detail"],
                    "memory_type": memory["memory_type"],
                    "source_conversation_id": None,
                    "source_message_ids": [],
                    "consent_scope_hash": None,
                    "sensitivity": memory["sensitivity"],
                    "confidence": memory["confidence"],
                    "expires_at": resolve_relative_date(memory["expires"], anchor, timezone),
                    "last_accessed_at": None,
                    "created_at": anchor.astimezone(UTC),
                    "updated_at": anchor.astimezone(UTC),
                },
            )

        await session.commit()

    return {
        "namespace": namespace,
        "anchor": anchor.isoformat(),
        "workspace_id": workspace_id,
        "users": {
            user["id"]: {
                "id": actual_id(user["id"]),
                "email": namespaced_email(namespace, user["email_local"]),
            }
            for user in seed["users"]
        },
        "conversations": {conversation["id"]: actual_id(conversation["id"]) for conversation in seed["conversations"]},
        "default_password": seed["default_password"],
    }


def preview(data: dict[str, Any], namespace: str) -> None:
    seed = data["seed"]
    print(f"Dataset : {data['dataset_id']} v{data['version']}")
    print(f"Namespace: {namespace}")
    print(f"Workspace: {seed['workspace']['name']} [{namespace}]")
    print("Accounts:")
    for user in seed["users"]:
        marker = " (primary)" if user["id"] == data["coverage"]["primary_user_id"] else ""
        print(f"- {user['display_name']}: {namespaced_email(namespace, user['email_local'])}{marker}")
    print(
        f"Objects : {len(seed['conversations'])} conversations, "
        f"{sum(len(item['messages']) for item in seed['conversations'])} messages, "
        f"{len(seed['tasks'])} tasks, {len(seed['memories'])} memories"
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--namespace", required=True, help="Ví dụ: member01, tuan, hau")
    parser.add_argument("--apply", action="store_true", help="Thực sự ghi vào database đã cấu hình")
    args = parser.parse_args()

    if not NAMESPACE_RE.fullmatch(args.namespace):
        print("Namespace chỉ gồm chữ thường, số, dấu gạch ngang; dài tối đa 31 ký tự.", file=sys.stderr)
        return 2
    data, errors = load_and_validate(args.dataset)
    if errors:
        print("Dataset không hợp lệ:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    preview(data, args.namespace)
    if not args.apply:
        print("PREVIEW ONLY: thêm --apply để ghi dữ liệu.")
        return 0

    try:
        manifest = asyncio.run(seed_dataset(data, args.namespace))
    except Exception as exc:  # CLI boundary: report database/configuration errors clearly
        print(f"SEED FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("SEED COMPLETE")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
