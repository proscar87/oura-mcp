"""oura-mcp — the Oura v2 API as an MCP server, with the pagination done right."""

from .client import OuraError, fetch
from .collections import COLLECTIONS

# READ FROM THE INSTALLED METADATA, never typed here. This said 0.1.0 for three
# releases while `pyproject.toml` was at 0.3.2, and nothing caught it: no test
# read it and no code did either, so `import oura_mcp; oura_mcp.__version__` —
# the conventional way to ask a Python package what it is — answered with a
# version that had not existed since 0.2.0. The same fix the handshake got in
# Python and `VERSION` got in TypeScript, on the third copy of the number.
try:
    from importlib.metadata import version

    __version__ = version("mcp-oura")
except Exception:  # not installed (a source checkout), the same fallback as the handshake
    __version__ = "unknown"

__all__ = ["fetch", "COLLECTIONS", "OuraError"]
