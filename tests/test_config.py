import pytest
from pydantic import ValidationError

from src.config import Settings


def _production_settings(**overrides):
    values = {
        "app_env": "production",
        "secret_key": "x" * 32,
        "database_url": "postgresql://orbit:secret@db/orbit",
        "cors_origins": "https://app.example.com",
        "cors_origin_regex": "",
        "llm_provider": "google",
        "google_api_key": "test-api-key",
        # Never inherit a developer's real Calendar credentials from the process environment.
        # Individual tests opt in with a complete fake OAuth configuration below.
        "google_calendar_client_id": "",
        "google_calendar_client_secret": "",
        "google_calendar_redirect_uri": "http://localhost:8000/api/v1/calendar/oauth/callback",
        "credential_encryption_key": "",
        "frontend_origin": "http://localhost:5173",
        "multi_agent_enabled": False,
        "product_delivery_agent_enabled": False,
        "quality_assurance_agent_enabled": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_valid_production_settings_are_accepted():
    settings = _production_settings()
    assert settings.app_env == "production"


def test_production_calendar_oauth_requires_complete_https_configuration():
    with pytest.raises(ValidationError, match="configured together"):
        _production_settings(google_calendar_client_id="calendar-client")

    with pytest.raises(ValidationError, match="CREDENTIAL_ENCRYPTION_KEY"):
        _production_settings(
            google_calendar_client_id="calendar-client",
            google_calendar_client_secret="calendar-secret",
        )

    with pytest.raises(ValidationError, match="public HTTPS URL"):
        _production_settings(
            google_calendar_client_id="calendar-client",
            google_calendar_client_secret="calendar-secret",
            credential_encryption_key="encrypted-token-key",
        )

    settings = _production_settings(
        google_calendar_client_id="calendar-client",
        google_calendar_client_secret="calendar-secret",
        credential_encryption_key="encrypted-token-key",
        google_calendar_redirect_uri="https://api.example.com/api/v1/calendar/oauth/callback",
        frontend_origin="https://app.example.com",
    )
    assert settings.frontend_origin == "https://app.example.com"


def test_openrouter_requires_its_own_key_in_production():
    with pytest.raises(ValidationError, match="OPENROUTER_API_KEY"):
        _production_settings(llm_provider="openrouter", google_api_key="", openrouter_api_key="")

    settings = _production_settings(
        llm_provider="openrouter",
        google_api_key="",
        openrouter_api_key="test-openrouter-key",
        model_name="openai/gpt-5.6-luna",
    )
    assert settings.openrouter_base_url == "https://openrouter.ai/api/v1"
    assert settings.model_name == "openai/gpt-5.6-luna"


def test_multi_agent_feature_flags_default_to_disabled(monkeypatch):
    for name in (
        "MULTI_AGENT_ENABLED",
        "PRODUCT_DELIVERY_AGENT_ENABLED",
        "QUALITY_ASSURANCE_AGENT_ENABLED",
        "EXECUTIVE_AGENT_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)

    assert settings.multi_agent_enabled is False
    assert settings.product_delivery_agent_enabled is False
    assert settings.quality_assurance_agent_enabled is False
    assert settings.executive_agent_enabled is False


def test_multi_agent_feature_flags_can_be_enabled_explicitly():
    settings = Settings(
        _env_file=None,
        multi_agent_enabled=True,
        product_delivery_agent_enabled=True,
        quality_assurance_agent_enabled=True,
        executive_agent_enabled=True,
    )

    assert settings.multi_agent_enabled is True
    assert settings.product_delivery_agent_enabled is True
    assert settings.quality_assurance_agent_enabled is True
    assert settings.executive_agent_enabled is True


def test_render_private_service_references_are_converted_to_runtime_urls():
    settings = _production_settings(
        multi_agent_enabled=True,
        product_delivery_agent_enabled=True,
        quality_assurance_agent_enabled=True,
        workspace_agent_runtime_mode="remote",
        workspace_agent_runtime_secret="p" * 32,
        quality_assurance_runtime_secret="q" * 32,
        workspace_agent_runtime_hostport="delivery-agent-ab12:8010",
        quality_assurance_runtime_hostport="quality-agent-cd34:8011",
        workspace_agent_progress_callback_hostport="orbit-backend-ef56:8000",
    )

    assert settings.workspace_agent_runtime_url == "http://delivery-agent-ab12:8010"
    assert settings.quality_assurance_runtime_url == "http://quality-agent-cd34:8011"
    assert settings.workspace_agent_progress_callback_url == (
        "http://orbit-backend-ef56:8000/internal/v1/workspace-agent-progress"
    )


@pytest.mark.parametrize(
    "override",
    [
        {"secret_key": "too-short"},
        {"database_url": "sqlite:///./data/app.db"},
        {"cors_origins": "*"},
        {"google_api_key": ""},
    ],
)
def test_unsafe_production_settings_are_rejected(override):
    with pytest.raises(ValidationError):
        _production_settings(**override)
