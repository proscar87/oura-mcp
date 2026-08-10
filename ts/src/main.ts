#!/usr/bin/env node
/**
 * The command line: with no flags it starts the MCP server; with them, it
 * doesn't.
 *
 * A FLAG THAT DOESN'T EXIST HAS TO FAIL. It used to be ignored, falling through
 * to starting the server, silently and with exit code 0. Anyone who typo'd
 * `--authorize` got a process waiting for JSON-RPC on stdin: in a terminal it
 * looks hung, and in a script it passes for success. That's the same family of
 * failure this whole package chases, committed by us, on the first line a new
 * user sees.
 */

import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { OuraError } from "./client.js";
import { createServer, check } from "./server.js";

// In order of precedence. The first one present wins, regardless of the order
// they're typed in: `--check --authorize` runs the self-check. Deterministic on
// purpose.
const ACTIONS = ["--help", "--help", "-h", "--check", "--authorize", "--forget"];
const MODIFIERS = ["--manual"];

const HELP = `oura-mcp — the Oura v2 API as an MCP server

  oura-mcp                    start the server (JSON-RPC over stdin/stdout)
  oura-mcp --check            self-check: which credential you're using, which
                              scopes you have, and whether Oura responds. Shows
                              neither the token nor any health value.
  oura-mcp --authorize        OAuth2 in the browser. Once.
  oura-mcp --authorize --manual   headless machines.
  oura-mcp --forget           erase the stored credentials.
  oura-mcp --help             this.

To try it with no credentials of any kind:

  OURA_SANDBOX=1 oura-mcp --check

Variables: OURA_SANDBOX, OURA_CLIENT_ID, OURA_CLIENT_SECRET, OURA_CREDENTIALS,
OURA_PAT, OURA_PAT_FILE, OURA_API_BASE_URL.
`;

const print = (x: unknown) => process.stdout.write(JSON.stringify(x, null, 2) + "\n");

export async function cli(argv: string[] = process.argv.slice(2)): Promise<number> {
  const unknown = argv.filter((a) => !ACTIONS.includes(a) && !MODIFIERS.includes(a));
  if (unknown.length) {
    // To stderr and with exit code 2, not to stdout: if this ever ran as the
    // server, anything on stdout that isn't JSON-RPC breaks the channel.
    process.stderr.write(`oura-mcp: I don't know ${unknown.join(", ")}\n\n${HELP}`);
    return 2;
  }
  if (argv.some((a) => ["--help", "--help", "-h"].includes(a))) {
    process.stdout.write(HELP);
    return 0;
  }
  if (argv.includes("--check")) {
    print(await check());
    return 0;
  }
  if (argv.includes("--authorize")) {
    const { authorize } = await import("./authorize.js");
    try {
      print(await authorize(argv.includes("--manual")));
    } catch (e) {
      if (!(e instanceof OuraError)) throw e;
      print({ autorizado: false, error: e.message });
      return 1;
    }
    return 0;
  }
  if (argv.includes("--forget")) {
    const { forget, credentialsPath } = await import("./credentials.js");
    const archivo = credentialsPath();
    await forget();
    print({ olvidado: true, archivo });
    return 0;
  }
  if (argv.includes("--manual")) {
    // `--manual` on its own means nothing, and starting the server because of
    // it would be the old silence all over again.
    process.stderr.write(`oura-mcp: \`--manual\` only accompanies \`--authorize\`\n\n${HELP}`);
    return 2;
  }
  await createServer().connect(new StdioServerTransport());
  return 0;
}

const thisFile = new URL(import.meta.url).pathname;
if (process.argv[1] && thisFile.endsWith(process.argv[1].replace(/^.*\//, ""))) {
  cli().then((c) => { if (c) process.exit(c); }).catch((e) => {
    process.stderr.write(`oura-mcp: ${(e as Error).message}\n`);
    process.exit(1);
  });
}
