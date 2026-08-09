"""The command line: with no flags it starts the MCP server; with them, it doesn't.

A FLAG THAT DOESN'T EXIST HAS TO FAIL. It used to be ignored, falling through to
starting the server, silently and with exit code 0. Anyone who typo'd
`--authorize` got a process waiting for JSON-RPC on stdin: in a terminal it looks
hung, and in a script it passes for success. That's the same family of failure
this whole package chases, committed by us, on the first line a new user sees.
"""

import asyncio
import json
import sys

from .server import check, main

# In order of precedence. The first one present wins, regardless of the order
# they're typed in: `--check --authorize` runs the self-check. Deterministic on
# purpose, so it doesn't depend on how the user types them.
ACTIONS = ("--help", "-h", "--check", "--authorize", "--forget")
MODIFIERS = ("--manual",)

HELP = """oura-mcp — the Oura v2 API as an MCP server

  oura-mcp                    start the server (JSON-RPC over stdin/stdout)
  oura-mcp --check            self-check: which credential you're using, which
                              scopes you have, and whether Oura responds. Shows
                              neither the token nor any health value.
  oura-mcp --authorize        OAuth2 in the browser. Once.
  oura-mcp --authorize --manual   headless machines: prints the URL, you paste
                              the callback back.
  oura-mcp --forget           erase the stored credentials.
  oura-mcp --help             this.

To try it with no credentials of any kind:

  OURA_SANDBOX=1 oura-mcp --check

Variables: OURA_SANDBOX, OURA_CLIENT_ID, OURA_CLIENT_SECRET, OURA_CREDENTIALS,
OURA_PAT, OURA_PAT_FILE, OURA_API_BASE_URL.
"""


def cli(argv: list[str] | None = None) -> int:
    """Entry point. `--check` only touches the network for a pulse."""
    args = list(sys.argv[1:] if argv is None else argv)

    unknown = [a for a in args if a not in ACTIONS + MODIFIERS]
    if unknown:
        # To stderr and with exit code 2, not to stdout: if this ever ran as the
        # server, anything on stdout that isn't JSON-RPC breaks the channel.
        print(f"oura-mcp: I don't know {', '.join(unknown)}\n", file=sys.stderr)
        print(HELP, file=sys.stderr)
        return 2

    if any(a in args for a in ("--help", "-h")):
        print(HELP)
        return 0

    if "--check" in args:
        print(json.dumps(check(), ensure_ascii=False, indent=2))
        return 0

    if "--authorize" in args:
        # The OAuth flow belongs in the terminal, NEVER inside the server: one
        # that speaks over stdin/stdout can't open a browser or ask anyone
        # anything, and pretending otherwise is how you hang an MCP client
        # forever.
        from .authorize import authorize
        from .client import OuraError
        try:
            print(json.dumps(authorize(manual="--manual" in args),
                             ensure_ascii=False, indent=2))
        except OuraError as e:
            print(json.dumps({"authorized": False, "error": str(e)},
                             ensure_ascii=False, indent=2))
            return 1
        return 0

    if "--forget" in args:
        from .credentials import credentials_path, forget
        path = credentials_path()
        forget()
        print(json.dumps({"forgotten": True, "file": path},
                         ensure_ascii=False, indent=2))
        return 0

    if "--manual" in args:
        # `--manual` on its own means nothing, and starting the server because of
        # it would be the old silence all over again.
        print("oura-mcp: `--manual` only accompanies `--authorize`\n", file=sys.stderr)
        print(HELP, file=sys.stderr)
        return 2

    asyncio.run(main())
    return 0


if __name__ == "__main__":
    sys.exit(cli())
