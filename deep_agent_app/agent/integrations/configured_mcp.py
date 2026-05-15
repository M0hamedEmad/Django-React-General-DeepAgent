"""Instantiate optional MCP servers declared in private configuration."""

from django.core.exceptions import ImproperlyConfigured

from deep_agent_app.utilities.constants import MCP_SERVERS

from .persistent_mcp_tools import PersistentMcpTools


def configured_mcp_servers():
    """Create each enabled server once when the integration package loads."""
    integrations = []
    for server_name, config in MCP_SERVERS.items():
        if not config.get("enabled", False):
            continue

        url = config.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ImproperlyConfigured(
                f"MCP server {server_name!r} requires a non-empty url"
            )

        headers = dict(config.get("headers", {}))
        if token := config.get("token"):
            headers.setdefault("Authorization", f"Bearer {token}")

        integrations.append(
            PersistentMcpTools(
                server_name=server_name,
                transport=config.get("transport", "http"),
                url=url,
                headers=headers,
                timeout=config.get("timeout", 60),
                sse_read_timeout=config.get("sse_read_timeout", 3600),
            )
        )
    return tuple(integrations)


MCP_INTEGRATIONS = configured_mcp_servers()
