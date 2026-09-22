import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from src.agents.contracts import AgentProfile
from src.config import Settings
from src.services.llm import (
    LLMConfiguration,
    get_llm,
    get_workspace_llm,
    get_workspace_llm_configuration,
    invoke_workspace_llm_with_failover,
)


def test_personal_llm_accepts_deterministic_temperature_override(monkeypatch):
    captured = {}
    sentinel = object()

    def build(config):
        captured["config"] = config
        return sentinel

    monkeypatch.setattr("src.services.llm._build_llm", build)

    result = get_llm(temperature=0)

    assert result is sentinel
    assert captured["config"].temperature == 0


def test_workspace_profiles_resolve_independent_model_configuration(monkeypatch):
    settings = Settings(
        _env_file=None,
        llm_provider="google",
        model_name="shared-model",
        product_delivery_llm_provider="groq",
        product_delivery_model_name="delivery-model",
        product_delivery_specialist_llm_provider="groq",
        product_delivery_specialist_model_name="delivery-small-model",
        product_delivery_specialist_llm_max_output_tokens=384,
        quality_assurance_llm_provider="openai",
        quality_assurance_model_name="quality-model",
        workspace_agent_verifier_provider="google",
        workspace_agent_verifier_model_name="verifier-model",
    )
    monkeypatch.setattr("src.services.llm.get_settings", lambda: settings)

    delivery = get_workspace_llm_configuration(AgentProfile.PRODUCT_DELIVERY)
    quality = get_workspace_llm_configuration(AgentProfile.QUALITY_ASSURANCE)
    verifier = get_workspace_llm_configuration(AgentProfile.QUALITY_ASSURANCE, purpose="verification")
    specialist = get_workspace_llm_configuration(AgentProfile.PRODUCT_DELIVERY, purpose="specialist")
    routing = get_workspace_llm_configuration(AgentProfile.PRODUCT_DELIVERY, purpose="routing")

    assert (delivery.provider, delivery.model, delivery.temperature) == (
        "groq",
        "delivery-model",
        0.2,
    )
    assert (quality.provider, quality.model, quality.temperature) == (
        "openai",
        "quality-model",
        0.1,
    )
    assert (verifier.provider, verifier.model, verifier.temperature) == (
        "google",
        "verifier-model",
        0.0,
    )
    assert (specialist.provider, specialist.model, specialist.max_output_tokens) == (
        "groq",
        "delivery-small-model",
        384,
    )
    assert (routing.provider, routing.model, routing.temperature) == (
        "groq",
        "delivery-model",
        0.0,
    )


def test_workspace_profiles_accept_openrouter_luna_configuration(monkeypatch):
    settings = Settings(
        _env_file=None,
        llm_provider="openrouter",
        openrouter_api_key="test-key",
        model_name="openai/gpt-5.6-luna",
        product_delivery_llm_provider="openrouter",
        product_delivery_model_name="openai/gpt-5.6-luna",
        product_delivery_specialist_llm_provider="openrouter",
        product_delivery_specialist_model_name="openai/gpt-5.6-luna",
        product_delivery_llm_max_output_tokens=1024,
        openrouter_reasoning_effort="medium",
    )
    monkeypatch.setattr("src.services.llm.get_settings", lambda: settings)

    synthesis = get_workspace_llm_configuration(AgentProfile.PRODUCT_DELIVERY)
    specialist = get_workspace_llm_configuration(AgentProfile.PRODUCT_DELIVERY, purpose="specialist")

    assert (synthesis.provider, synthesis.model) == ("openrouter", "openai/gpt-5.6-luna")
    assert (specialist.provider, specialist.model) == ("openrouter", "openai/gpt-5.6-luna")

    client = get_workspace_llm(AgentProfile.PRODUCT_DELIVERY)
    assert str(client.openai_api_base) == "https://openrouter.ai/api/v1"
    assert client.default_headers["X-OpenRouter-Title"] == "Orbit"
    assert client._default_params["max_completion_tokens"] == 1024
    assert client._default_params["extra_body"]["reasoning"] == {
        "effort": "low",
        "exclude": True,
    }


@pytest.mark.asyncio
async def test_specialist_llm_fails_over_to_profile_synthesis_model(monkeypatch):
    primary = LLMConfiguration("groq", "specialist-primary", 0.1, 384)
    fallback = LLMConfiguration("openrouter", "delivery-fallback", 0.1, 384)

    class Candidate:
        def __init__(self, should_fail):
            self.should_fail = should_fail

        async def ainvoke(self, _messages):
            if self.should_fail:
                raise RuntimeError("429 quota exhausted")
            return AIMessage(content="Phân tích từ model dự phòng.")

    monkeypatch.setattr(
        "src.services.llm.get_workspace_llm_candidate_configurations",
        lambda *_args, **_kwargs: (("specialist", primary), ("synthesis", fallback)),
    )
    monkeypatch.setattr(
        "src.services.llm.get_workspace_llm",
        lambda *_args, purpose, **_kwargs: Candidate(purpose == "specialist"),
    )

    result = await invoke_workspace_llm_with_failover(
        AgentProfile.PRODUCT_DELIVERY,
        purpose="specialist",
        messages=[],
        timeout_seconds=1,
    )

    assert result.configuration == fallback
    assert [attempt["status"] for attempt in result.attempts] == ["failed", "succeeded"]
    assert result.attempts[0]["error_code"] == "LLM_RATE_LIMITED"


def test_production_rejects_embedded_runtime_when_workspace_agents_are_enabled():
    with pytest.raises(ValidationError, match="WORKSPACE_AGENT_RUNTIME_MODE=remote"):
        Settings(
            _env_file=None,
            app_env="production",
            secret_key="s" * 32,
            database_url="postgresql+asyncpg://orbit:test@db/orbit",
            cors_origins="https://orbit.example",
            cors_origin_regex="",
            llm_provider="google",
            google_api_key="test-key",
            multi_agent_enabled=True,
            product_delivery_agent_enabled=True,
            workspace_agent_runtime_mode="embedded",
            workspace_agent_runtime_secret="d" * 32,
            quality_assurance_runtime_secret="q" * 32,
        )


def test_production_accepts_explicit_demo_embedded_runtime_opt_in():
    settings = Settings(
        _env_file=None,
        app_env="production",
        secret_key="s" * 32,
        database_url="postgresql+asyncpg://orbit:test@db/orbit",
        cors_origins="https://orbit.example",
        cors_origin_regex="",
        llm_provider="google",
        google_api_key="test-key",
        multi_agent_enabled=True,
        product_delivery_agent_enabled=True,
        quality_assurance_agent_enabled=True,
        workspace_agent_runtime_mode="embedded",
        allow_embedded_workspace_agents_in_production=True,
    )

    assert settings.workspace_agent_runtime_mode == "embedded"
    assert settings.allow_embedded_workspace_agents_in_production is True
