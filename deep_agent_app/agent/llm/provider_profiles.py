"""Resolve provider-specific runtime behavior without network checks."""

from types import MappingProxyType
from urllib.parse import urlsplit

from deep_agent_app.utilities import model_registry


# Known application provider ids remain stable even when their endpoint is
# replaced by a company proxy. A configured ``provider_family`` can describe
# aliases; hostname detection preserves compatibility with older settings.
PROVIDER_ID_FAMILIES = MappingProxyType(
    {
        "groq": "groq_gateway",
        "nvidia": "nvidia_gateway",
        "ollama": "ollama_gateway",
        "openrouter": "openrouter_gateway",
    }
)
HOST_FAMILIES = MappingProxyType(
    {
        "api.groq.com": "groq_gateway",
        "integrate.api.nvidia.com": "nvidia_gateway",
        "ollama.com": "ollama_gateway",
        "openrouter.ai": "openrouter_gateway",
    }
)


def provider_family(provider_id: str) -> str:
    """Return the explicit/native family, with safe legacy fallbacks."""
    provider = model_registry.PROVIDERS[provider_id]
    if configured := provider.get("provider_family"):
        return configured

    model_provider = provider.get("model_provider", "openai")
    if model_provider != "openai":
        return model_provider

    # Provider ids are more reliable than public hostnames when a company
    # routes traffic through its own gateway. Require a base URL so a test or
    # unrelated provider merely named "groq" is not silently reclassified.
    if provider.get("base_url") and provider_id in PROVIDER_ID_FAMILIES:
        return PROVIDER_ID_FAMILIES[provider_id]

    endpoint = urlsplit(str(provider.get("base_url") or ""))
    hostname = (endpoint.hostname or "").lower()
    if hostname in {"localhost", "127.0.0.1"} and endpoint.port == 11434:
        return "ollama_gateway"
    for known_host, family in HOST_FAMILIES.items():
        if hostname == known_host or hostname.endswith(f".{known_host}"):
            return family
    return "openai"
