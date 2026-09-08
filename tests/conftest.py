"""Shared fixtures.

THE CACHE IS PROCESS-GLOBAL, which is exactly what it is for: an MCP server is
one process per session, and holding a closed day across the tool calls of that
session is the whole point. In a test run that same property makes every test
after the first a liar — it would answer from what an earlier test's fake
returned, and the fake set up in front of it would never be consulted.

Four tests found this the moment the cache landed: each passed alone and failed
in sequence. That is not a flaw in the cache, it is what shared state does, and
the fix belongs here rather than in each test remembering to clean up after the
one before it.
"""

import pytest

from oura_mcp import client


@pytest.fixture(autouse=True)
def _sin_cache_entre_tests():
    """Every test starts with an empty cache, and leaves one behind."""
    client.cache_clear()
    yield
    client.cache_clear()
