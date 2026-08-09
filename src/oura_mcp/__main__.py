"""`oura-mcp` arranca el servidor; `oura-mcp --revisar` hace el autodiagnóstico."""

import asyncio
import json
import sys

from .servidor import main, revisar


def cli() -> int:
    """Punto de entrada. `--revisar` NO toca la red más que para un pulso."""
    if "--revisar" in sys.argv:
        print(json.dumps(revisar(), ensure_ascii=False, indent=2))
        return 0
    asyncio.run(main())
    return 0


if __name__ == "__main__":
    sys.exit(cli())
