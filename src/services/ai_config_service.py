import logging

from src.config import get_settings
from src.db import session as db_session
from src.db.models import SystemConfig

logger = logging.getLogger(__name__)

MODEL_OPTIONS: dict[str, list[dict[str, str]]] = {
    "google": [
        {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
        {"id": "gemini-2.5-flash-lite", "label": "Gemini 2.5 Flash-Lite"},
    ],
    "openai": [
        {"id": "gpt-4.1-mini", "label": "GPT-4.1 mini"},
        {"id": "gpt-4o-mini", "label": "GPT-4o mini"},
    ],
    "groq": [
        {"id": "openai/gpt-oss-120b", "label": "GPT-OSS 120B"},
        {"id": "openai/gpt-oss-20b", "label": "GPT-OSS 20B"},
        {"id": "qwen/qwen3.6-27b", "label": "Qwen 3.6 27B"},
        {"id": "groq/compound-mini", "label": "Groq Compound Mini"},
    ],
}


def configured_providers() -> list[str]:
    settings = get_settings()
    keys = {
        "google": settings.google_api_key,
        "openai": settings.openai_api_key,
        "groq": settings.groq_api_key,
    }
    return [provider for provider, api_key in keys.items() if api_key]


def is_supported_model(provider: str, model: str) -> bool:
    return any(option["id"] == model for option in MODEL_OPTIONS.get(provider, []))


def apply_ai_configuration(provider: str, model: str, temperature: float) -> None:
    settings = get_settings()
    object.__setattr__(settings, "llm_provider", provider)
    object.__setattr__(settings, "model_name", model)
    object.__setattr__(settings, "llm_temperature", temperature)


async def load_saved_ai_configuration() -> None:
    try:
        async with db_session.async_session_maker() as db:
            config = await db.get(SystemConfig, "default")
        if not config or not config.llm_provider or not config.model_name:
            return
        temperature = config.llm_temperature
        if temperature is None:
            temperature = get_settings().llm_temperature
        if config.llm_provider in MODEL_OPTIONS and is_supported_model(config.llm_provider, config.model_name):
            apply_ai_configuration(config.llm_provider, config.model_name, float(temperature))
        else:
            logger.warning(
                "Ignored unsupported saved AI configuration: %s / %s",
                config.llm_provider,
                config.model_name,
            )
    except Exception:  # noqa: BLE001 - invalid persistence must not block startup
        logger.exception("Could not load saved AI configuration; using environment defaults")
