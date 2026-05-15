"""Immutable runtime configuration for the whole deep-agent application.

This is the only application module that reads project settings directly.
Agent code, streaming code, views, composer metadata, and management commands
import named values from here instead of reaching into ``django.conf.settings``.

Django model declarations and migrations intentionally remain exceptions:
``AUTH_USER_MODEL`` is Django schema metadata, not runtime app configuration.
"""

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from django.conf import settings

from .secrets import secret_section


def freeze(value):
    """Recursively freeze JSON-shaped settings shared by concurrent requests."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(freeze(item) for item in value)
    return value


def thaw(value):
    """Return a JSON-ready copy without exposing mutable shared settings."""
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [thaw(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [thaw(item) for item in value]
    return value


BASE_DIR = Path(settings.BASE_DIR)
APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = APP_DIR / "config"
SKILLS_ROOT = BASE_DIR / "agent_skills"

DEEP_AGENT = freeze(secret_section("deep_agent"))
LLM_PROVIDERS = freeze(secret_section("llm")["providers"])
TOOLS = freeze(secret_section("tools"))
AGENT_RUNTIME = freeze(secret_section("runtime"))
MCP_SERVERS = freeze(DEEP_AGENT.get("mcp_servers", {}))
CONNECTED_SYSTEM_ENABLED = any(
    server.get("enabled", False) for server in MCP_SERVERS.values()
)
_AGENTS = [{"id": "general", "label": "General"}]
if CONNECTED_SYSTEM_ENABLED:
    _AGENTS.append({"id": "connected", "label": "Connected systems"})
AGENT_UI = freeze(
    {
        "agents": _AGENTS,
        "tools": [
            {"id": "web_search", "label": "Web search"},
        ],
    }
)

TAVILY_API_KEY = TOOLS.get("tavily_api_key", "")
CHECKPOINT_DB = BASE_DIR / DEEP_AGENT["checkpoint_db"]
MAX_CONCURRENT_RUNS = int(AGENT_RUNTIME.get("max_concurrent_runs", 4))
RUN_TIMEOUT_SECONDS = float(AGENT_RUNTIME.get("run_timeout_seconds", 1800))
SSE_HEARTBEAT_SECONDS = float(AGENT_RUNTIME.get("sse_heartbeat_seconds", 15))
# Bound per-turn token/tool events when a browser or proxy reads slowly.
STREAM_EVENT_BUFFER_SIZE = int(AGENT_RUNTIME.get("event_buffer_size", 256))
# Maximum number of tool-output characters sent to the browser per call.
TOOL_OUTPUT_LIMIT = 20_000
