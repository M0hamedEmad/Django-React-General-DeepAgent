"""Lazy public API for the deep-agent subsystem.

Application code imports focused submodules. These compatibility exports keep
older callers working without loading every provider and integration whenever
Python first touches the ``deep_agent_app.agent`` package.
"""

from importlib import import_module

_EXPORTS = {
    "AUTO_MODEL": ("deep_agent_app.utilities.model_registry", "AUTO_MODEL"),
    "DEFAULT_PROVIDER": (
        "deep_agent_app.utilities.model_registry",
        "DEFAULT_PROVIDER",
    ),
    "CONNECTED_SKILL_SOURCES": (
        "deep_agent_app.agent.skills",
        "CONNECTED_SKILL_SOURCES",
    ),
    "PersistentMcpTools": (
        "deep_agent_app.agent.integrations.persistent_mcp_tools",
        "PersistentMcpTools",
    ),
    "GatewayChatOpenAI": (
        "deep_agent_app.agent.llm.openai_compatible",
        "GatewayChatOpenAI",
    ),
    "MAIN_SKILL_SOURCES": ("deep_agent_app.agent.skills", "MAIN_SKILL_SOURCES"),
    "PROVIDERS": ("deep_agent_app.utilities.model_registry", "PROVIDERS"),
    "PlanModeMiddleware": (
        "deep_agent_app.agent.middleware.planning",
        "PlanModeMiddleware",
    ),
    "REJECTED_THINKING_MODELS": (
        "deep_agent_app.agent.llm.reasoning",
        "REJECTED_THINKING_MODELS",
    ),
    "TurnContext": ("deep_agent_app.agent.context", "TurnContext"),
    "ask_user": ("deep_agent_app.agent.tools.ask_user", "ask_user"),
    "build_agent": ("deep_agent_app.agent.agent", "build_agent"),
    "build_llm": ("deep_agent_app.agent.llm.clients", "build_llm"),
    "command_system_message": (
        "deep_agent_app.agent.llm.routing",
        "command_system_message",
    ),
    "model_choices": ("deep_agent_app.utilities.model_registry", "model_choices"),
    "model_selector": ("deep_agent_app.agent.llm.routing", "model_selector"),
    "parse_ask_user_markup": (
        "deep_agent_app.agent.middleware.ask_user_recovery",
        "parse_ask_user_markup",
    ),
    "provider_registry": (
        "deep_agent_app.utilities.model_registry",
        "provider_registry",
    ),
    "repair_ask_user_response": (
        "deep_agent_app.agent.middleware.ask_user_recovery",
        "repair_ask_user_response",
    ),
    "resolve_provider": ("deep_agent_app.utilities.validation", "resolve_provider"),
    "thinking_model_settings": (
        "deep_agent_app.agent.llm.reasoning",
        "thinking_model_settings",
    ),
    "timestamp_model_response": (
        "deep_agent_app.agent.llm.routing",
        "timestamp_model_response",
    ),
    "validate_model_choice": (
        "deep_agent_app.utilities.validation",
        "validate_model_choice",
    ),
    "validate_plan_mode": (
        "deep_agent_app.utilities.validation",
        "validate_plan_mode",
    ),
    "validate_thinking_effort": (
        "deep_agent_app.utilities.validation",
        "validate_thinking_effort",
    ),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


def __dir__():
    return sorted({*globals(), *_EXPORTS})
