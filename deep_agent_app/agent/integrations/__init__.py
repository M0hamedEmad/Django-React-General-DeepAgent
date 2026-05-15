"""External agent integrations."""

from .persistent_mcp_tools import PersistentMcpTools

# Import configured MCPs once. PersistentMcpTools then discovers and owns the
# lifecycle of these process-scoped instances.
from .configured_mcp import MCP_INTEGRATIONS as MCP_INTEGRATIONS

__all__ = ["MCP_INTEGRATIONS", "PersistentMcpTools"]
