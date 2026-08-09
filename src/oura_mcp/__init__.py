"""oura-mcp — la API v2 de Oura como server MCP, con la paginación bien hecha."""

from .client import OuraError, fetch
from .collections import COLLECTIONS

__version__ = "0.1.0"
__all__ = ["fetch", "COLLECTIONS", "OuraError"]
