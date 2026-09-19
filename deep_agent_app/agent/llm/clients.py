"""Build and cache provider chat clients without making network calls."""

from functools import lru_cache

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from deep_agent_app.utilities import model_registry
from deep_agent_app.utilities.validation import resolve_provider

from .openai_compatible import GatewayChatOpenAI

MODEL_CLIENT_CACHE_SIZE = 32


def _client_options(provider, temperature: float) -> dict:
    """Translate immutable app configuration into integration arguments."""
    model_provider = provider.get("model_provider", "openai")
    options = {"api_key": provider["api_key"]}
    if provider.get("send_temperature", True):
        options["temperature"] = temperature
    if provider.get("base_url"):
        options["base_url"] = provider["base_url"]
    if provider.get("timeout"):
        timeout_key = (
            "request_timeout" if model_provider == "google_genai" else "timeout"
        )
        options[timeout_key] = provider["timeout"]
    if model_provider in {"openai", "azure_openai"}:
        options["stream_usage"] = provider.get("stream_usage", True)
    return options


@lru_cache(maxsize=MODEL_CLIENT_CACHE_SIZE)
def _build_llm(provider_id: str, temperature: float) -> BaseChatModel:
    provider = model_registry.PROVIDERS[provider_id]
    model_provider = provider.get("model_provider", "openai")
    options = _client_options(provider, temperature)
    if model_provider == "openai" and provider.get("base_url"):
        return GatewayChatOpenAI(
            model=provider["model"],
            configured_provider_id=provider_id,
            **options,
        )
    return init_chat_model(provider["model"], model_provider=model_provider, **options)


def build_llm(provider_id: str, temperature: float | None = None) -> BaseChatModel:
    """Return the shared client for a validated provider and temperature.

    Main and subagent callers pass their role-specific temperatures. Other
    callers use the provider's configured default, or zero when it is absent.
    """
    provider_id = resolve_provider(provider_id)
    if temperature is None:
        temperature = model_registry.PROVIDERS[provider_id].get("temperature", 0)
    return _build_llm(provider_id, temperature)
