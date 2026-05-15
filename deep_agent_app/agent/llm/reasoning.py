"""Translate UI reasoning effort into provider-specific call settings."""

import logging
from collections.abc import Mapping
from functools import lru_cache
from types import MappingProxyType

from deep_agent_app.utilities import model_registry
from deep_agent_app.utilities.validation import (
    ReasoningEffort,
    resolve_provider,
    validate_thinking_effort,
)

from .provider_profiles import provider_family

log = logging.getLogger(__name__)

THINKING_SETTINGS_CACHE_SIZE = 64
ReasoningProfile = tuple[bool, tuple[str, ...]]


def model_reasoning_profile(model) -> ReasoningProfile:
    """Return the hashable reasoning capability subset used by the cache."""
    profile = model.profile or {}
    if not isinstance(profile, Mapping):
        return False, ()
    configured_levels = profile.get("reasoning_effort_levels") or ()
    if isinstance(configured_levels, str):
        configured_levels = (configured_levels,)
    levels = tuple(level for level in configured_levels if isinstance(level, str))
    return bool(profile.get("reasoning_output")), levels


def mutable_settings(value):
    if isinstance(value, Mapping):
        return {key: mutable_settings(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [mutable_settings(item) for item in value]
    return value


def merge_settings(base, override):
    merged = mutable_settings(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = merge_settings(merged[key], value)
        else:
            merged[key] = mutable_settings(value)
    return merged


def closest_profile_effort(requested, levels):
    levels = list(levels)
    if requested in levels:
        return requested
    preferences = {
        "medium": ("medium", "low", "minimal", "high"),
        "high": ("high", "medium", "low", "minimal"),
        "max": ("max", "xhigh", "high", "medium", "low", "minimal"),
    }
    return next((level for level in preferences[requested] if level in levels), None)


@lru_cache(maxsize=THINKING_SETTINGS_CACHE_SIZE)
def thinking_model_settings(
    provider_id: str,
    effort: ReasoningEffort = "high",
    profile: ReasoningProfile = (False, ()),
):
    provider_id = resolve_provider(provider_id)
    effort = validate_thinking_effort(effort)
    provider = model_registry.PROVIDERS[provider_id]
    configured = provider.get("thinking")
    family = provider_family(provider_id)
    model_name = provider["model"].lower()
    enabled = configured is True or isinstance(configured, Mapping)
    base = mutable_settings(configured) if isinstance(configured, Mapping) else {}

    if configured is False:
        if effort != "instant":
            log.info(
                "thinking %s requested for provider %s model %s, but it is disabled; continuing normally",
                effort,
                provider_id,
                provider["model"],
            )
        return MappingProxyType({})
    if enabled and family == "openrouter_gateway":
        dynamic = {
            "extra_body": {
                "reasoning": {
                    "effort": "none" if effort == "instant" else effort,
                    "exclude": False,
                }
            }
        }
        return MappingProxyType(
            merge_settings(base if effort != "instant" else {}, dynamic)
        )
    if enabled and family == "ollama_gateway":
        selected = (
            "none" if effort == "instant" else ("high" if effort == "max" else effort)
        )
        return MappingProxyType(
            merge_settings(
                base if effort != "instant" else {}, {"reasoning_effort": selected}
            )
        )
    if enabled and family == "groq_gateway":
        if effort == "instant":
            if "qwen" in model_name:
                return MappingProxyType({"reasoning_effort": "none"})
            log.info(
                "instant requested for provider %s model %s, but this Groq model always reasons; using its default",
                provider_id,
                provider["model"],
            )
            return MappingProxyType({})
        selected = "high" if effort == "max" else effort
        return MappingProxyType(
            merge_settings(
                base,
                {
                    "reasoning_effort": selected,
                    "extra_body": {"include_reasoning": True},
                },
            )
        )
    if enabled and family == "nvidia_gateway":
        if "deepseek-v4" in model_name:
            chat_template = {"thinking": effort != "instant"}
            if effort in {"high", "max"}:
                chat_template["reasoning_effort"] = effort
        else:
            chat_template = {"enable_thinking": effort != "instant"}
        return MappingProxyType(
            merge_settings(
                base if effort != "instant" else {},
                {"extra_body": {"chat_template_kwargs": chat_template}},
            )
        )
    if provider.get("model_provider") == "google_genai":
        if "gemini-2.5" in model_name:
            budget = {"instant": 0, "medium": 8192, "high": 24576, "max": 24576}[effort]
            dynamic = {
                "thinking_budget": budget,
                "include_thoughts": effort != "instant",
            }
        else:
            selected = (
                "minimal"
                if effort == "instant"
                else ("high" if effort == "max" else effort)
            )
            dynamic = {
                "thinking_level": selected,
                "include_thoughts": effort != "instant",
            }
        return MappingProxyType(
            merge_settings(base if effort != "instant" else {}, dynamic)
        )
    if base:
        if effort == "instant":
            return MappingProxyType({})
        if "reasoning_effort" in base:
            base["reasoning_effort"] = effort
        return MappingProxyType(base)
    if effort == "instant":
        return MappingProxyType({})

    reasoning_output, levels = profile
    if reasoning_output or levels:
        call_settings = {}
        if selected := closest_profile_effort(effort, levels):
            call_settings["reasoning_effort"] = selected
        return MappingProxyType(call_settings)
    log.info(
        "thinking %s requested for provider %s model %s, but no support is configured; continuing normally",
        effort,
        provider_id,
        provider["model"],
    )
    return MappingProxyType({})


def is_unsupported_thinking_error(exc):
    message = str(exc).lower()
    return any(
        word in message
        for word in (
            "reasoning",
            "thinking",
            "include_thoughts",
            "chat_template_kwargs",
        )
    ) and any(
        phrase in message
        for phrase in (
            "not support",
            "unsupported",
            "unknown parameter",
            "unrecognized",
            "invalid parameter",
            "extra inputs",
            "extra_forbidden",
        )
    )


REJECTED_THINKING_MODELS: set[tuple[str, str, ReasoningEffort]] = set()
