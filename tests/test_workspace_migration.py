import importlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from src.db import session as db_session
from src.db.models import MigrationState, User, Workspace


def _migration_service():
    try:
        return importlib.import_module("src.services.migration_service")
    except ModuleNotFoundError:
        pytest.fail("workspace migration service is not implemented")


async def _register(client, email: str) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_preflight_rejects_multiple_admins_without_config(client):
    first = await _register(client, "first-admin@example.com")
    second = await _register(client, "second-admin@example.com")
    async with db_session.async_session_maker() as db:
        for user_id in (first["id"], second["id"]):
            user = await db.get(User, user_id)
            user.role = "admin"
        await db.commit()

        report = await _migration_service().preflight_workspace_migration(db, bootstrap_owner_user_id=None)

    assert report.can_run is False
    assert report.owner_user_id is None
    assert report.error_code == "ambiguous_bootstrap_owner"


@pytest.mark.asyncio
async def test_preflight_selects_only_active_admin(client):
    admin = await _register(client, "only-admin@example.com")
    async with db_session.async_session_maker() as db:
        user = await db.get(User, admin["id"])
        user.role = "admin"
        await db.commit()

        report = await _migration_service().preflight_workspace_migration(db, bootstrap_owner_user_id=None)

    assert report.can_run is True
    assert report.owner_user_id == admin["id"]
    assert report.error_code is None


@pytest.mark.asyncio
async def test_workspace_migration_dry_run_does_not_write(client):
    admin = await _register(client, "dry-run-admin@example.com")
    async with db_session.async_session_maker() as db:
        user = await db.get(User, admin["id"])
        user.role = "admin"
        personal_workspaces = (
            (await db.execute(select(Workspace).where(Workspace.personal_owner_user_id == admin["id"]))).scalars().all()
        )
        for workspace in personal_workspaces:
            await db.delete(workspace)
        await db.commit()

        report = await _migration_service().run_workspace_foundation_backfill(
            db,
            bootstrap_owner_user_id=None,
            dry_run=True,
        )
        workspace_count = (await db.execute(select(func.count()).select_from(Workspace))).scalar_one()

    assert report.can_run is True
    assert report.owner_user_id == admin["id"]
    assert workspace_count == 0


def _create_legacy_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE users (
            id VARCHAR PRIMARY KEY,
            email VARCHAR NOT NULL UNIQUE,
            password_hash VARCHAR NOT NULL,
            display_name VARCHAR NOT NULL,
            role VARCHAR NOT NULL DEFAULT 'user',
            is_active BOOLEAN NOT NULL DEFAULT 1,
            created_at DATETIME NOT NULL
        );
        CREATE TABLE conversations (
            id VARCHAR PRIMARY KEY,
            type VARCHAR NOT NULL,
            name VARCHAR,
            created_by VARCHAR NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        );
        CREATE TABLE conversation_participants (
            conversation_id VARCHAR NOT NULL,
            user_id VARCHAR NOT NULL,
            joined_at DATETIME NOT NULL,
            last_read_at DATETIME NOT NULL,
            PRIMARY KEY (conversation_id, user_id)
        );
        CREATE TABLE messages (
            id VARCHAR PRIMARY KEY,
            conversation_id VARCHAR NOT NULL,
            sender_id VARCHAR NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME NOT NULL
        );
        INSERT INTO users VALUES
            ('admin-1', 'admin@example.com', 'hash', 'Admin', 'admin', 1, '2026-08-01 00:00:00'),
            ('member-1', 'member@example.com', 'hash', 'Member', 'user', 1, '2026-08-01 00:00:00');
        INSERT INTO conversations VALUES
            ('conversation-1', 'direct', NULL, 'admin-1', '2026-08-01 00:00:00', '2026-08-01 00:00:00');
        INSERT INTO conversation_participants VALUES
            ('conversation-1', 'admin-1', '2026-08-01 00:00:00', '2026-08-01 00:00:00'),
            ('conversation-1', 'member-1', '2026-08-01 00:00:00', '2026-08-01 00:00:00');
        """
    )
    connection.commit()
    connection.close()


def test_alembic_upgrade_backfills_workspace_foundation_idempotently(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy.db"
    _create_legacy_database(database_path)
    monkeypatch.setenv("BOOTSTRAP_OWNER_USER_ID", "admin-1")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    connection = sqlite3.connect(database_path)
    personal_count = connection.execute("SELECT COUNT(*) FROM workspaces WHERE type = 'personal'").fetchone()[0]
    organization = connection.execute(
        "SELECT id FROM workspaces WHERE type = 'organization' AND slug = 'legacy-organization'"
    ).fetchone()
    assert organization is not None
    owner_role = connection.execute(
        "SELECT role FROM workspace_memberships WHERE workspace_id = ? AND user_id = 'admin-1'",
        (organization[0],),
    ).fetchone()[0]
    conversation_workspace = connection.execute(
        "SELECT workspace_id FROM conversations WHERE id = 'conversation-1'"
    ).fetchone()[0]
    platform_role = connection.execute("SELECT platform_role FROM users WHERE id = 'admin-1'").fetchone()[0]
    connection.close()

    assert personal_count == 2
    assert owner_role == "owner"
    assert conversation_workspace == organization[0]
    assert platform_role == "platform_admin"


def test_alembic_upgrade_builds_fresh_database(tmp_path):
    database_path = tmp_path / "fresh.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")

    connection = sqlite3.connect(database_path)
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    membership_indexes = {
        row[1]: row[2]
        for row in connection.execute("PRAGMA index_list('agent_workspace_memberships')")
    }
    task_columns = {row[1] for row in connection.execute("PRAGMA table_info('tasks')")}
    reminder_columns = {row[1] for row in connection.execute("PRAGMA table_info('reminders')")}
    reminder_indexes = {row[1] for row in connection.execute("PRAGMA index_list('reminders')")}
    workspace_agent_message_columns = {
        row[1] for row in connection.execute("PRAGMA table_info('workspace_agent_messages')")
    }
    workspace_agent_message_indexes = {
        row[1] for row in connection.execute("PRAGMA index_list('workspace_agent_messages')")
    }
    connection.close()

    assert {
        "users",
        "workspaces",
        "workspace_memberships",
        "external_contacts",
        "contact_relationships",
        "conversations",
        "conversation_participants",
        "messages",
    }.issubset(tables)
    assert {
        "tasks",
        "usage_logs",
        "memories",
        "calendar_sync_state",
        "reminders",
        "event_candidates",
        "event_extraction_cursors",
        "assistant_threads",
    }.issubset(tables)
    assert "people_preferences" in tables
    assert {
        "agent_workspaces",
        "agent_workspace_memberships",
        "agent_workspace_conversations",
    }.issubset(tables)
    assert {
        "workspace_agent_threads",
        "workspace_agent_messages",
        "release_candidates",
        "delivery_dependencies",
        "delivery_decisions",
        "quality_requirements",
        "quality_test_cases",
        "quality_test_runs",
        "quality_defects",
        "quality_evidence",
        "quality_policies",
        "quality_waivers",
            "workspace_action_proposals",
            "workspace_outbox_events",
            "delivery_agent_workflows",
            "delivery_agent_runs",
            "delivery_specialist_results",
            "delivery_workflow_events",
            "delivery_event_inbox",
            "delivery_checkpoint_tasks",
            "delivery_group_schedules",
        }.issubset(tables)
    assert revision == "20260831_33"
    assert {"calendar_event_id", "lead_minutes"}.issubset(reminder_columns)
    assert "uq_reminders_owner_calendar_event" in reminder_indexes
    assert "workflow_id" in workspace_agent_message_columns
    assert "ix_workspace_agent_messages_workflow_id" in workspace_agent_message_indexes
    assert "row_version" in task_columns
    assert "completed_at" in task_columns
    assert "started_at" in task_columns
    assert "auto_reminder_enabled" in task_columns
    assert {
        "requires_review",
        "submission_note",
        "evidence_urls",
        "submitted_by_user_id",
        "submitted_at",
        "reviewed_by_user_id",
        "reviewed_at",
        "review_note",
    }.issubset(task_columns)
    assert membership_indexes["uq_agent_workspace_active_lead"] == 1
    assert "agent_threads" in tables
    assert {"google_identities", "ai_permissions"}.issubset(tables)


def test_audit_log_repair_migration_handles_existing_legacy_table(tmp_path):
    database_path = tmp_path / "legacy-audit-log.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260822_17")
    connection = sqlite3.connect(database_path)
    connection.execute("DROP TABLE audit_logs")
    connection.executescript(
        """
        CREATE TABLE audit_logs (
            id VARCHAR PRIMARY KEY,
            actor_user_id VARCHAR,
            actor_type VARCHAR NOT NULL,
            action VARCHAR NOT NULL,
            target_type VARCHAR NOT NULL,
            target_id VARCHAR,
            metadata_json JSON NOT NULL,
            created_at DATETIME NOT NULL
        );
        """
    )
    connection.close()

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    connection = sqlite3.connect(database_path)
    columns = {row[1] for row in connection.execute("PRAGMA table_info('audit_logs')")}
    indexes = {row[1] for row in connection.execute("PRAGMA index_list('audit_logs')")}
    revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    connection.close()

    assert {"workspace_id", "ip_address"}.issubset(columns)
    assert {
        "ix_audit_logs_workspace_id",
        "ix_audit_logs_actor_user_id",
        "ix_audit_logs_created_at",
    }.issubset(indexes)
    assert revision == "20260831_33"


def test_personal_space_repair_migration_backfills_post_foundation_users_idempotently(tmp_path):
    database_path = tmp_path / "missing-personal-space.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260824_18")
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        INSERT INTO users
            (id, email, password_hash, display_name, role, platform_role, is_active,
             job_title, timezone, preferences, created_at)
        VALUES
            ('direct-user', 'direct@example.com', 'hash', 'Direct User', 'user', 'user', 1,
             '', 'Asia/Ho_Chi_Minh', '{}', '2026-08-24 00:00:00')
        """
    )
    connection.commit()
    connection.close()

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    connection = sqlite3.connect(database_path)
    rows = connection.execute(
        "SELECT type, status, personal_owner_user_id FROM workspaces WHERE personal_owner_user_id = 'direct-user'"
    ).fetchall()
    revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    connection.close()

    assert rows == [("personal", "active", "direct-user")]
    assert revision == "20260831_33"


def test_agent_workspace_migration_downgrades_cleanly(tmp_path):
    database_path = tmp_path / "agent-workspace-downgrade.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")
    command.downgrade(config, "20260813_12")

    connection = sqlite3.connect(database_path)
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    connection.close()

    assert "agent_workspaces" not in tables
    assert "agent_workspace_memberships" not in tables
    assert "agent_workspace_conversations" not in tables
    assert revision == "20260813_12"


@pytest.mark.asyncio
async def test_migration_state_updates_one_record_across_transitions(client):
    async with db_session.async_session_maker() as db:
        running = await _migration_service().set_workspace_migration_state(db, status="running")
        await db.commit()
        migration_state_id = running.id

        failed = await _migration_service().set_workspace_migration_state(
            db,
            status="failed",
            error_code="alembic_upgrade_failed",
        )
        await db.commit()
        assert failed.id == migration_state_id
        assert failed.completed_at is None

        completed = await _migration_service().set_workspace_migration_state(db, status="completed")
        await db.commit()
        states = (await db.execute(select(MigrationState))).scalars().all()

    assert completed.id == migration_state_id
    assert completed.error_code is None
    assert completed.completed_at is not None
    assert len(states) == 1


def test_workspace_migration_cli_dry_run_reports_without_writing(tmp_path):
    database_path = tmp_path / "legacy-cli.db"
    _create_legacy_database(database_path)
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    environment["BOOTSTRAP_OWNER_USER_ID"] = "admin-1"

    result = subprocess.run(
        [sys.executable, "scripts/migrate_workspace_foundation.py", "--dry-run"],
        cwd=Path(__file__).parent.parent,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["can_run"] is True
    assert report["owner_user_id"] == "admin-1"
    connection = sqlite3.connect(database_path)
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    connection.close()
    assert "workspaces" not in tables
    assert "migration_states" not in tables
