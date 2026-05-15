"""Django system checks for the agent runtime and deployment configuration."""

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

from deep_agent_app.utilities.constants import (
    MAX_CONCURRENT_RUNS,
    MCP_SERVERS,
    RUN_TIMEOUT_SECONDS,
    STREAM_EVENT_BUFFER_SIZE,
)
from deep_agent_app.utilities.model_registry import (
    DEFAULT_PROVIDER,
    PROVIDERS,
)


def _placeholder(value) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().upper()
    return normalized.startswith(("YOUR_", "CHANGE_ME", "CHANGE-ME"))


@register()
def runtime_contract(app_configs, **kwargs):
    """Catch settings that would break streaming before serving requests."""
    issues = []
    if not getattr(settings, "ASGI_APPLICATION", ""):
        issues.append(
            Error(
                "ASGI_APPLICATION is required by the streaming agent runtime.",
                id="deep_agent.E001",
            )
        )
    if MAX_CONCURRENT_RUNS < 1:
        issues.append(
            Error(
                "runtime.max_concurrent_runs must be at least 1.",
                id="deep_agent.E002",
            )
        )
    if RUN_TIMEOUT_SECONDS <= 0:
        issues.append(
            Error(
                "runtime.run_timeout_seconds must be positive.",
                id="deep_agent.E003",
            )
        )
    if STREAM_EVENT_BUFFER_SIZE < 1:
        issues.append(
            Error(
                "runtime.event_buffer_size must be at least 1.",
                id="deep_agent.E004",
            )
        )
    if DEFAULT_PROVIDER not in PROVIDERS:
        issues.append(
            Error(
                "deep_agent.llm_provider must name a configured provider.",
                hint="Set a real model and API key in the private secrets file.",
                id="deep_agent.E005",
            )
        )
    return issues


@register(Tags.security, deploy=True)
def deployment_contract(app_configs, **kwargs):
    """Reject placeholder credentials and flag single-process persistence."""
    issues = []
    for provider_id, provider in PROVIDERS.items():
        if _placeholder(provider.get("api_key")):
            issues.append(
                Error(
                    f"LLM provider {provider_id!r} still uses a placeholder key.",
                    id="deep_agent.E101",
                )
            )

    for server_name, server in MCP_SERVERS.items():
        if not server.get("enabled", False):
            continue
        if _placeholder(server.get("token")):
            issues.append(
                Error(
                    f"MCP server {server_name!r} still uses a placeholder token.",
                    id="deep_agent.E102",
                )
            )

    if settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
        issues.append(
            Warning(
                "SQLite is intended for local development only.",
                hint="Use PostgreSQL before running multiple application workers.",
                id="deep_agent.W101",
            )
        )
    return issues
