"""oura-mcp — the Oura v2 API as an MCP server, with the pagination done right."""

from .client import OuraError, fetch
from .collections import COLLECTIONS

__version__ = "0.1.0"
__all__ = ["fetch", "COLLECTIONS", "OuraError"]
