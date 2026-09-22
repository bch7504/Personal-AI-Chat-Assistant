from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.config import get_settings
from src.db.base import Base

settings = get_settings()


def _async_url(url: str) -> str:
    if url.startswith("sqlite:///") and "+aiosqlite" not in url:
        db_path = url.removeprefix("sqlite:///")
        if db_path not in (":memory:", ""):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


async_database_url = _async_url(settings.database_url)
_is_sqlite = async_database_url.startswith("sqlite+")
engine_options = {"pool_pre_ping": True}
if _is_sqlite:
    engine_options["connect_args"] = {"check_same_thread": False}
elif settings.app_env == "test":
    engine_options["poolclass"] = NullPool
else:
    engine_options.update(
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
    )
engine = create_async_engine(async_database_url, **engine_options)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session_maker() as session:
        yield session


async def _add_missing_user_columns(conn) -> None:
    """Patch legacy SQLite files; PostgreSQL schema changes go through Alembic.

    `create_all` only creates missing tables and never alters an existing one.
    """
    if conn.dialect.name != "sqlite":
        return
    result = await conn.execute(text("PRAGMA table_info(users)"))
    existing_columns = {row[1] for row in result.fetchall()}
    if "role" not in existing_columns:
        await conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR NOT NULL DEFAULT 'user'"))
    if "is_active" not in existing_columns:
        await conn.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))
    if "job_title" not in existing_columns:
        await conn.execute(text("ALTER TABLE users ADD COLUMN job_title VARCHAR NOT NULL DEFAULT ''"))
    if "timezone" not in existing_columns:
        await conn.execute(text("ALTER TABLE users ADD COLUMN timezone VARCHAR NOT NULL DEFAULT 'Asia/Ho_Chi_Minh'"))
    if "preferences" not in existing_columns:
        await conn.execute(text("ALTER TABLE users ADD COLUMN preferences JSON NOT NULL DEFAULT '{}'"))


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
