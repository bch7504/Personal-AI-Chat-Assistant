from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cloud_and_grading_hook_files_are_not_part_of_local_project():
    removed_files = (
        "render.yaml",
        "render.production.yaml",
        "Frontend/user/vercel.json",
        "Frontend/admin/vercel.json",
        ".github/workflows/keep-alive.yml",
        ".codex/hooks.json",
        "scripts/submit_log.py",
    )

    assert all(not (ROOT / path).exists() for path in removed_files)


def test_docker_local_build_is_preserved():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert (ROOT / "Dockerfile").is_file()
    assert (ROOT / ".dockerignore").is_file()
    assert '"127.0.0.1:8000:8000"' in compose
    assert '"127.0.0.1:55432:5432"' in compose
    assert "postgres:16-alpine" in compose


def test_evaluation_assets_are_preserved():
    required_assets = (
        "eval/datasets/user_agent_acceptance_v1.json",
        "eval/datasets/multi_agent_workspace_v1.jsonl",
        "eval/results/report.md",
        "scripts/eval_extract_tasks.py",
        "scripts/eval_user_agent.py",
        "scripts/validate_agent_dataset.py",
        "scripts/validate_multi_agent_dataset.py",
    )

    assert all((ROOT / path).is_file() for path in required_assets)


def test_default_configuration_is_local_only():
    environment = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "APP_HOST=127.0.0.1" in environment
    assert "DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/orbit" in environment
    assert "APP_ENV=development" in environment
    assert "AI_LOG_SERVER" not in environment
