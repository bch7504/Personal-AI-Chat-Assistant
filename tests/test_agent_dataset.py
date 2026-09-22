from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.seed_agent_dataset import namespaced_email, resolve_relative_date, stable_id, validate_seed_database_url
from scripts.validate_agent_dataset import validate_dataset
from src.models.auth_schemas import LoginRequest

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "eval" / "datasets" / "user_agent_acceptance_v1.json"


def _dataset() -> dict:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def test_canonical_agent_dataset_is_valid_and_has_required_coverage():
    data = _dataset()

    assert validate_dataset(data) == []
    assert len(data["seed"]["users"]) == 4
    assert len(data["evaluation_cases"]) == 17
    assert data["evaluation_policy"]["release_thresholds"]["case_pass_rate"] == 0.8
    assert {
        "conversation_summary",
        "task_extraction",
        "memory_retrieval",
        "memory_isolation",
        "prompt_injection_resistance",
        "human_in_the_loop",
    } <= {case["capability"] for case in data["evaluation_cases"]}


def test_validator_rejects_dangling_actor_reference():
    data = copy.deepcopy(_dataset())
    data["evaluation_cases"][0]["actor_id"] = "usr_missing"

    errors = validate_dataset(data)

    assert any("actor_id không hợp lệ" in error for error in errors)


def test_namespaces_produce_stable_isolated_ids_and_test_emails():
    member01 = stable_id("dataset", "member01", "usr_minh")

    assert member01 == stable_id("dataset", "member01", "usr_minh")
    assert member01 != stable_id("dataset", "member02", "usr_minh")
    email = namespaced_email("member01", "minh.pm")
    assert email == "member01.minh.pm@example.com"
    assert str(LoginRequest(email=email, password="Orbit-Test-2026!").email) == email


def test_relative_dates_use_dataset_timezone_and_strict_next_weekday():
    timezone = ZoneInfo("Asia/Ho_Chi_Minh")
    anchor = datetime(2026, 8, 14, 14, 20, tzinfo=timezone)  # Friday

    tomorrow = resolve_relative_date(
        {"type": "offset_days", "days": 1, "hour": 16, "minute": 0},
        anchor,
        timezone,
    )
    next_monday = resolve_relative_date(
        {"type": "next_weekday", "weekday": 0, "hour": 10, "minute": 0},
        anchor,
        timezone,
    )

    assert tomorrow.astimezone(timezone).isoformat() == "2026-08-15T16:00:00+07:00"
    assert next_monday.astimezone(timezone).isoformat() == "2026-08-17T10:00:00+07:00"


def test_seed_database_guard_accepts_only_local_postgres_with_test_marker():
    safe_url = "postgresql+asyncpg://orbit:secret@localhost:5432/orbit_agent_test"

    assert validate_seed_database_url(safe_url) == "orbit_agent_test"

    for unsafe_url in (
        "postgresql+asyncpg://orbit:secret@localhost:5432/orbit",
        "postgresql+asyncpg://orbit:secret@db.example.com:5432/orbit_agent_test",
        "sqlite:///agent_test.db",
    ):
        try:
            validate_seed_database_url(unsafe_url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Unsafe seed URL was accepted: {unsafe_url}")
