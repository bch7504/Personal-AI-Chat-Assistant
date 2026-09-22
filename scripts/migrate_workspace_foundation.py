import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from src.config import get_settings  # noqa: E402
from src.db.models import MigrationState  # noqa: E402
from src.db.session import async_session_maker, engine  # noqa: E402
from src.services.migration_service import (  # noqa: E402
    preflight_workspace_migration,
    set_workspace_migration_state,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preflight and run the workspace foundation migration")
    parser.add_argument("--dry-run", action="store_true", help="Validate migration inputs without writing data")
    parser.add_argument("--bootstrap-owner-user-id", help="Explicit active legacy admin to become workspace owner")
    return parser.parse_args()


async def _preflight(bootstrap_owner_user_id: str | None):
    async with async_session_maker() as db:
        return await preflight_workspace_migration(db, bootstrap_owner_user_id)


async def _prepare_state(status: str, error_code: str | None = None) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(MigrationState.__table__.create, checkfirst=True)
    async with async_session_maker() as db:
        await set_workspace_migration_state(db, status=status, error_code=error_code)
        await db.commit()


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    configured_owner = (args.bootstrap_owner_user_id or settings.bootstrap_owner_user_id).strip() or None
    report = asyncio.run(_preflight(configured_owner))
    print(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True))
    if not report.can_run:
        return 2
    if args.dry_run:
        return 0

    os.environ["BOOTSTRAP_OWNER_USER_ID"] = report.owner_user_id or ""
    asyncio.run(_prepare_state("running"))
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    try:
        command.upgrade(config, "head")
    except Exception:  # noqa: BLE001
        asyncio.run(_prepare_state("failed", error_code="alembic_upgrade_failed"))
        raise
    asyncio.run(_prepare_state("completed"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
