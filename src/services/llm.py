import asyncio
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel

from src.agents.contracts import AgentProfile
from src.config import get_settings

LLMProvider = Literal["google", "groq", "openai", "openrouter"]
LLMPurpose = Literal["synthesis", "verification", "specialist", "routing", "conversation"]


@dataclass(frozen=True)
class LLMConfiguration:
    provider: LLMProvider
    model: str
    temperature: float
    max_output_tokens: int
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] = "low"


@dataclass(frozen=True)
class WorkspaceLLMInvocationResult:
    message: Any
    configuration: LLMConfiguration
    attempts: tuple[dict[str, Any], ...]


class WorkspaceLLMUnavailableError(RuntimeError):
    def __init__(self, attempts: tuple[dict[str, Any], ...]):
        super().__init__("All configured Workspace LLM providers failed")
        self.attempts = attempts


def _build_llm(config: LLMConfiguration) -> BaseChatModel:
    settings = get_settings()
    if config.provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=config.model,
            api_key=settings.groq_api_key,
            temperature=config.temperature,
            max_tokens=config.max_output_tokens,
        )
    if config.provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=config.model,
            api_key=settings.openai_api_key,
            temperature=config.temperature,
            max_tokens=config.max_output_tokens,
        )
    if config.provider == "openrouter":
        from langchain_openai import ChatOpenAI

        headers = {"X-OpenRouter-Title": settings.openrouter_app_name}
        if settings.openrouter_site_url:
            headers["HTTP-Referer"] = settings.openrouter_site_url
        return ChatOpenAI(
            model=config.model,
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            default_headers=headers,
            temperature=config.temperature,
            max_tokens=config.max_output_tokens,
            extra_body={
                "reasoning": {
                    "effort": config.reasoning_effort,
                    "exclude": True,
                }
            },
        )
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=config.model,
        google_api_key=settings.google_api_key,
        temperature=config.temperature,
        max_output_tokens=config.max_output_tokens,
    )


def get_llm(
    *,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
) -> BaseChatModel:
    """Return the shared Personal Agent model with optional per-call overrides.

    Routing/classification should be deterministic even when conversational
    generation uses a non-zero temperature.  Keeping the overrides here avoids
    callers passing unsupported keyword arguments to the factory.
    """

    settings = get_settings()
    return _build_llm(
        LLMConfiguration(
            provider=settings.llm_provider,
            model=settings.model_name,
            temperature=settings.llm_temperature if temperature is None else temperature,
            max_output_tokens=(
                settings.llm_max_output_tokens
                if max_output_tokens is None
                else max_output_tokens
            ),
            reasoning_effort=settings.openrouter_reasoning_effort,
        )
    )


def get_workspace_llm_configuration(profile: AgentProfile, *, purpose: LLMPurpose = "synthesis") -> LLMConfiguration:
    """Resolve a profile-owned model configuration without exposing credentials."""

    settings = get_settings()
    if purpose == "verification":
        return LLMConfiguration(
            provider=settings.workspace_agent_verifier_provider or settings.llm_provider,
            model=settings.workspace_agent_verifier_model_name or settings.model_name,
            temperature=settings.workspace_agent_verifier_temperature,
            max_output_tokens=settings.workspace_agent_verifier_max_output_tokens,
            reasoning_effort="low",
        )
    if purpose == "specialist":
        if profile != AgentProfile.PRODUCT_DELIVERY:
            raise ValueError("Specialist model policy currently supports Product Delivery only")
        return LLMConfiguration(
            provider=(
                settings.product_delivery_specialist_llm_provider
                or settings.product_delivery_llm_provider
                or settings.llm_provider
            ),
            model=(
                settings.product_delivery_specialist_model_name
                or settings.product_delivery_model_name
                or settings.model_name
            ),
            temperature=settings.product_delivery_specialist_llm_temperature,
            max_output_tokens=settings.product_delivery_specialist_llm_max_output_tokens,
            reasoning_effort=settings.product_delivery_specialist_llm_reasoning_effort,
        )
    if purpose == "routing":
        if profile != AgentProfile.PRODUCT_DELIVERY:
            raise ValueError("Routing model policy currently supports Product Delivery only")
        return LLMConfiguration(
            provider=(
                settings.product_delivery_routing_llm_provider
                or settings.product_delivery_llm_provider
                or settings.llm_provider
            ),
            model=(
                settings.product_delivery_routing_model_name
                or settings.product_delivery_model_name
                or settings.model_name
            ),
            temperature=settings.product_delivery_routing_llm_temperature,
            max_output_tokens=settings.product_delivery_routing_llm_max_output_tokens,
            reasoning_effort=settings.product_delivery_routing_llm_reasoning_effort,
        )
    if purpose == "conversation":
        if profile != AgentProfile.PRODUCT_DELIVERY:
            raise ValueError("Conversation model policy currently supports Product Delivery only")
        # Conversation uses the profile-owned synthesis model. Keeping this as
        # an explicit purpose prevents callers from silently selecting the
        # specialist provider again.
        purpose = "synthesis"
    if profile == AgentProfile.PRODUCT_DELIVERY:
        return LLMConfiguration(
            provider=settings.product_delivery_llm_provider or settings.llm_provider,
            model=settings.product_delivery_model_name or settings.model_name,
            temperature=settings.product_delivery_llm_temperature,
            max_output_tokens=settings.product_delivery_llm_max_output_tokens,
            reasoning_effort=settings.product_delivery_llm_reasoning_effort,
        )
    if profile == AgentProfile.QUALITY_ASSURANCE:
        return LLMConfiguration(
            provider=settings.quality_assurance_llm_provider or settings.llm_provider,
            model=settings.quality_assurance_model_name or settings.model_name,
            temperature=settings.quality_assurance_llm_temperature,
            max_output_tokens=settings.quality_assurance_llm_max_output_tokens,
            reasoning_effort=settings.openrouter_reasoning_effort,
        )
    raise ValueError(f"Workspace LLM is not configured for profile {profile.value}")


def get_workspace_llm(profile: AgentProfile, *, purpose: LLMPurpose = "synthesis") -> BaseChatModel:
    return _build_llm(get_workspace_llm_configuration(profile, purpose=purpose))


def get_workspace_llm_candidate_configurations(
    profile: AgentProfile,
    *,
    purpose: LLMPurpose,
) -> tuple[tuple[LLMPurpose, LLMConfiguration], ...]:
    """Return a de-duplicated primary/failover chain without credentials.

    Product Delivery routing and safe conversation turns start with their
    profile-owned model and may fail over to the independently configured
    specialist provider. Other purposes retain their single-provider policy.
    """

    purposes: tuple[LLMPurpose, ...]
    if profile == AgentProfile.PRODUCT_DELIVERY and purpose in {"routing", "conversation"}:
        purposes = (purpose, "synthesis", "specialist")
    elif profile == AgentProfile.PRODUCT_DELIVERY and purpose == "specialist":
        purposes = ("specialist", "synthesis")
    else:
        purposes = (purpose,)
    candidates: list[tuple[LLMPurpose, LLMConfiguration]] = []
    seen: set[tuple[str, str]] = set()
    for candidate_purpose in purposes:
        config = get_workspace_llm_configuration(profile, purpose=candidate_purpose)
        identity = (config.provider, config.model)
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append((candidate_purpose, config))
    return tuple(candidates)


def classify_llm_failure(exc: BaseException) -> str:
    """Map provider exceptions to safe, stable telemetry codes."""

    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if "timeout" in name or "timeout" in message:
        return "LLM_TIMEOUT"
    if "rate" in name or "429" in message or "quota" in message:
        return "LLM_RATE_LIMITED"
    if "auth" in name or "401" in message or "403" in message or "api key" in message:
        return "LLM_AUTHENTICATION_FAILED"
    if "validation" in name or "structured" in message or "parse" in message:
        return "LLM_INVALID_RESPONSE"
    return "LLM_PROVIDER_ERROR"


async def invoke_workspace_llm_with_failover(
    profile: AgentProfile,
    *,
    purpose: LLMPurpose,
    messages: list[Any],
    timeout_seconds: float,
) -> WorkspaceLLMInvocationResult:
    """Invoke a plain chat model through the configured provider chain."""

    attempts: list[dict[str, Any]] = []
    for candidate_purpose, config in get_workspace_llm_candidate_configurations(
        profile,
        purpose=purpose,
    ):
        try:
            message = await asyncio.wait_for(
                get_workspace_llm(profile, purpose=candidate_purpose).ainvoke(messages),
                timeout=timeout_seconds,
            )
            attempts.append({
                "provider": config.provider,
                "model": config.model,
                "status": "succeeded",
                "error_code": "",
            })
            return WorkspaceLLMInvocationResult(message, config, tuple(attempts))
        except Exception as exc:  # noqa: BLE001 - bounded provider failover.
            attempts.append({
                "provider": config.provider,
                "model": config.model,
                "status": "failed",
                "error_code": classify_llm_failure(exc),
            })
    raise WorkspaceLLMUnavailableError(tuple(attempts))
