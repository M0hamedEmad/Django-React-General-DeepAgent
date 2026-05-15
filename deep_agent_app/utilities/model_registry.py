"""Immutable model-provider catalog shared by the API and agent runtime."""

from collections.abc import Mapping
from numbers import Real
from types import MappingProxyType
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from .constants import DEEP_AGENT, LLM_PROVIDERS

AUTO_MODEL = "auto"
DEFAULT_PROVIDER = DEEP_AGENT["llm_provider"]


def _optional_text(provider, key):
    value = provider.get(key)
    return value is None or (isinstance(value, str) and bool(value.strip()))


def _valid_base_url(provider):
    value = provider.get("base_url")
    if value is None:
        return True
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlsplit(value)
    try:
        parsed.port
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def _valid_timeout(provider):
    value = provider.get("timeout")
    return value is None or (
        isinstance(value, Real) and not isinstance(value, bool) and value > 0
    )


def _valid_optional_boolean(provider, key):
    value = provider.get(key)
    return value is None or isinstance(value, bool)


def _valid_temperature(provider):
    value = provider.get("temperature")
    return value is None or (isinstance(value, Real) and not isinstance(value, bool))


def _usable_provider(provider_id, provider):
    """Validate the network-free configuration contract for one provider."""
    return (
        isinstance(provider_id, str)
        and bool(provider_id.strip())
        and provider_id != AUTO_MODEL
        and isinstance(provider, Mapping)
        and isinstance(provider.get("model"), str)
        and bool(provider["model"].strip())
        and isinstance(provider.get("api_key"), str)
        and bool(provider["api_key"].strip())
        and _optional_text(provider, "model_provider")
        and _optional_text(provider, "provider_family")
        and _valid_base_url(provider)
        and _valid_timeout(provider)
        and _valid_temperature(provider)
        and _valid_optional_boolean(provider, "stream_usage")
        and (
            provider.get("thinking") is None
            or isinstance(provider.get("thinking"), (bool, Mapping))
        )
    )


def provider_registry(providers):
    """Return only usable providers as recursively immutable mappings."""
    registry = {}
    for provider_id, provider in providers.items():
        if not _usable_provider(provider_id, provider):
            continue

        # Production input is already recursively frozen by constants.py.
        # Freeze nested test/plain-dict input too so the function fulfils the
        # same contract for every caller.
        registry[provider_id] = _freeze_mapping(provider)
    return registry


def _freeze_value(value):
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_value(item) for item in value)
    return value


def _freeze_mapping(value):
    return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})


PROVIDERS = MappingProxyType(provider_registry(LLM_PROVIDERS))
if DEFAULT_PROVIDER not in PROVIDERS:
    raise ImproperlyConfigured(
        f"deep_agent.llm_provider '{DEFAULT_PROVIDER}' is missing a model or api_key"
    )


def model_choices():
    """Return public metadata only; credentials and endpoints stay server-side."""
    return [{"id": AUTO_MODEL, "label": "Auto"}] + [
        {
            "id": provider_id,
            "label": provider.get("label")
            or f"{provider_id}/{provider['model'].removeprefix('openai/')}",
        }
        for provider_id, provider in PROVIDERS.items()
    ]
