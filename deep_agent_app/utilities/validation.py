"""Shared validation for API requests and immutable agent turn context."""

from typing import Literal

from . import model_registry
from .constants import AGENT_UI

AUTO_MODEL = model_registry.AUTO_MODEL
AgentChoice = Literal["general", "connected"]
ReasoningEffort = Literal["instant", "medium", "high", "max"]
REASONING_EFFORTS = frozenset({"instant", "medium", "high", "max"})
AGENT_CHOICES = frozenset(choice["id"] for choice in AGENT_UI["agents"])
TOOL_CHOICES = frozenset(choice["id"] for choice in AGENT_UI["tools"])


def validated_options(raw_options):
    """Normalize persistent composer choices without provider I/O."""
    if not isinstance(raw_options, dict):
        raise ValueError("options must be an object")
    return {
        "model": validate_model_choice(raw_options.get("model")),
        "agent": validate_agent_choice(raw_options.get("agent")),
        "tools": validate_tool_choices(raw_options.get("tools")),
        "thinking": validate_thinking_effort(raw_options.get("thinking")),
        "plan": validate_plan_mode(raw_options.get("plan")),
    }


def validate_model_choice(model):
    """Return an advertised model id, defaulting missing values to Auto."""
    if model in (None, ""):
        return AUTO_MODEL
    if not isinstance(model, str) or (
        model != AUTO_MODEL
        and model not in model_registry.MODEL_ROLES
        and model not in model_registry.PROVIDERS
    ):
        raise ValueError("unknown or unavailable model")
    return model


def resolve_provider(model=AUTO_MODEL):
    """Resolve Auto to the configured provider after validating the choice."""
    model = validate_model_choice(model)
    if model == AUTO_MODEL:
        model = "main"
    return model_registry.MODEL_ROLES.get(model, model)


def validate_agent_choice(value) -> AgentChoice:
    """Return the general agent when the older API omits the selection."""
    if value in (None, ""):
        return "general"
    if not isinstance(value, str) or value not in AGENT_CHOICES:
        raise ValueError(f"unknown agent: {value}")
    return value


def validate_tool_choices(value) -> list[str]:
    """Validate optional capability groups while preserving UI order."""
    if value is None:
        return [choice["id"] for choice in AGENT_UI["tools"]]
    if not isinstance(value, list) or not all(isinstance(tool, str) for tool in value):
        raise ValueError("tools must be a list of tool ids")
    if unknown := set(value) - TOOL_CHOICES:
        raise ValueError(f"unknown tool: {sorted(unknown)[0]}")
    return list(dict.fromkeys(tool for tool in value if tool in TOOL_CHOICES))


def validate_thinking_effort(value) -> ReasoningEffort:
    """Normalize current choices and the legacy boolean API shape."""
    if value is None or value is False:
        return "instant"
    if value is True:
        return "high"
    if isinstance(value, str) and value in REASONING_EFFORTS:
        return value
    raise ValueError("thinking must be instant, medium, high, or max")


def validate_plan_mode(value) -> bool:
    """Accept only real booleans; truthy strings must not enable planning."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    raise ValueError("plan must be true or false")
