"""oura-mcp — la API v2 de Oura como servidor MCP, con la paginación bien hecha."""

from .cliente import ErrorOura, obtener
from .colecciones import COLECCIONES

__version__ = "0.1.0"
__all__ = ["obtener", "COLECCIONES", "ErrorOura"]
