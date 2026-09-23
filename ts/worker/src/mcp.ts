/**
 * The MCP endpoint. The OAuth provider has already checked the bearer token by
 * the time a request gets here; `ctx.props` says whose it is.
 *
 * STATELESS: a fresh server and transport per request, no session id. Every
 * tool here is a read with its whole answer in one response, so there is
 * nothing a session would hold — and nothing to lose when an isolate is
 * recycled mid-conversation.
 */

import { WebStandardStreamableHTTPServerTransport } from
  "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";

import { createServer } from "../../src/server.js";
import { OuraError, Secret, type Auth } from "../../src/client.js";
import pkg from "../../package.json" with { type: "json" };
import { type Env, sandbox, tokens } from "./env.js";
import type { Props } from "./authorize.js";

/**
 * The core reads a few settings from `process.env`, as it does on stdio. In a
 * Worker they arrive as bindings; copied in here, per request, from this
 * deployment's own configuration and nothing else.
 */
function applySettings(env: Env): void {
  // Widened: `wrangler types` types process.env from wrangler.jsonc's defaults.
  const pe = process.env as Record<string, string | undefined>;
  pe.OURA_TIMEZONE = env.OURA_TIMEZONE ?? "";
  if (sandbox(env)) pe.OURA_SANDBOX = "1";
  else delete pe.OURA_SANDBOX;
}

function authFor(env: Env, props: Props): Auth {
  if (sandbox(env) || props.identity === "sandbox") {
    return { identity: "sandbox", token: async () => new Secret("sandbox") };
  }
  const t = tokens(env);
  return {
    identity: props.identity,
    token: async () => {
      try {
        return new Secret(await t.accessToken());
      } catch (e) {
        // An error crossing the Durable Object boundary arrives as a plain
        // Error. Re-typed so the tools report it as an answer, not a crash.
        throw new OuraError((e as Error).message);
      }
    },
  };
}

export async function handleMcp(request: Request, env: Env,
                                ctx: ExecutionContext & { props?: Props }): Promise<Response> {
  if (!(env.OURA_TIMEZONE ?? "").trim()) {
    // Refused rather than defaulted to UTC: the cache would hold the person's
    // today as a closed day. See `today()` in the core.
    return Response.json({ error: "OURA_TIMEZONE is not set on this deployment" },
                         { status: 500 });
  }
  applySettings(env);
  const props = ctx.props ?? { identity: "" };
  const auth = authFor(env, props);
  if (!sandbox(env)) {
    // Read per request, so a re-login that granted more is seen at once.
    auth.scopes = await tokens(env).scopes();
  }

  const server = createServer({ auth, version: pkg.version });
  const transport = new WebStandardStreamableHTTPServerTransport({
    sessionIdGenerator: undefined,
    enableJsonResponse: true,
  });
  await server.connect(transport);
  return transport.handleRequest(request);
}
