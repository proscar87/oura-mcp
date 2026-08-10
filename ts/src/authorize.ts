/**
 * El flujo interactivo de OAuth2: del navegador al primer par de tokens.
 *
 * Runs ONCE, by hand, from the terminal. It is not part of the MCP server — one
 * that speaks over stdin/stdout can't open a browser or ask anyone anything, and
 * pretending otherwise is how you hang an MCP client forever.
 *
 *     oura-mcp --authorize             # opens the browser, waits for the callback
 *     oura-mcp --authorize --manual    # prints the URL; you paste the reply
 *
 * EL `state` NO ES OPCIONAL. El callback llega a un srv HTTP en localhost
 * that serves whatever it's sent; without comparing it, any page open in the
 * user's browser can hand them an authorization code from ANOTHER account and
 * leave them connected to data that isn't theirs.
 */

import { createServer } from "node:http";
import { timingSafeEqual } from "node:crypto";
import { randomBytes } from "node:crypto";

import { OuraError } from "./client.js";
import { SCOPES, AUTHORIZE_URL, DEFAULT_REDIRECT, exchangeCode } from "./credentials.js";

export const CALLBACK_WAIT = 300_000;   // cinco minutos para authorize

const PAGE = (title: string, body: string) =>
  `<!doctype html><html lang="es"><meta charset="utf-8"><title>oura-mcp</title>` +
  `<body style="font-family:system-ui;max-width:32rem;margin:6rem auto;line-height:1.5">` +
  `<h1>${title}</h1><p>${body}</p></body></html>`;

/** The client_id and client_secret of the Oura application. */
export function appCredentials(): [string, string] {
  const cid = (process.env.OURA_CLIENT_ID ?? "").trim();
  const csec = (process.env.OURA_CLIENT_SECRET ?? "").trim();
  if (!cid || !csec) {
    throw new OuraError(
      "OURA_CLIENT_ID and OURA_CLIENT_SECRET are missing. Register an application at " +
      "https://cloud.ouraring.com/oauth/applications with the redirect " +
      `${DEFAULT_REDIRECT} (the trailing slash is required)`);
  }
  return [cid, csec];
}

export function authorizationUrl(clientId: string, state: string,
                                  redirectUri = DEFAULT_REDIRECT,
                                  scopes: readonly string[] = SCOPES): string {
  const q = new URLSearchParams({
    response_type: "code",
    client_id: clientId,
    redirect_uri: redirectUri,
    scope: scopes.join(" "),
    state: state,
  });
  return `${AUTHORIZE_URL}?${q.toString()}`;
}

function sameState(a: string, b: string): boolean {
  const ba = Buffer.from(a), bb = Buffer.from(b);
  return ba.length === bb.length && timingSafeEqual(ba, bb);
}

/**
 * Extracts the `code` from the callback URL. Verifies the `state` when given.
 *
 * Is it a URL or a bare code? That's decided by SHAPE, not by characters: OAuth
 * codes are base64url and carry `-`, `_` and `=` padding perfectly normally. The
 * earlier heuristic looked for `=` or `/` and rejected `abc=` as "that carries no
 * code" — one of the most baffling things that can happen to someone who pasted
 * exactly what they were asked for.
 */
export function extractCode(urlOCodigo: string, estadoEsperado?: string): string {
  const texto = urlOCodigo.trim();
  const pareceUrl = /^https?:\/\//.test(texto) || texto.includes("?");
  if (!pareceUrl) return texto;

  let q: URLSearchParams;
  try {
    q = new URL(texto, "http://localhost").searchParams;
  } catch {
    throw new OuraError("that URL could not be read; paste the full callback URL");
  }
  if (![...q.keys()].length) {
    throw new OuraError("that URL has no parameters; paste the full callback URL");
  }
  const error = q.get("error");
  if (error) {
    throw new OuraError(`Oura rejected the authorization: ${q.get("error_description") ?? error}`);
  }
  const code = q.get("code");
  if (!code) throw new OuraError("the URL carries no `code`");
  if (estadoEsperado !== undefined) {
    if (!sameState(q.get("state") ?? "", estadoEsperado)) {
      throw new OuraError(
        "the `state` does not match: that callback did not come from this session. " +
        "Nothing was exchanged. Start over.");
    }
  }
  return code;
}

/**
 * Starts the local server and waits for THE CALLBACK, not the first request.
 *
 * The difference cost the entire flow. A real browser doesn't send one request:
 * it asks for `/favicon.ico` on its own. Serving only one, the favicon took the
 * turn, the server closed, and the good callback got *connection refused*. From
 * outside it looked like "no callback arrived", with no clue why.
 */
export function waitForCallback(port: number, state: string,
                                wait = CALLBACK_WAIT): Promise<string> {
  return new Promise((resolver, rechazar) => {
    let done = false;
    const srv = createServer((req, res) => {
      const path = new URL(req.url ?? "/", "http://localhost").pathname.replace(/\/+$/, "");
      if (path !== "/callback") {
        res.writeHead(404).end();
        return;   // the favicon and friends do NOT close the server
      }
      let title: string, body: string, code: string | null = null;
      try {
        code = extractCode(req.url ?? "", state);
        title = "Listo";
        body = "You can close this tab and go back to the terminal.";
      } catch (e) {
        title = "No se pudo";
        body = (e as Error).message;
      }
      const page = PAGE(title, body);
      res.writeHead(200, {
        "Content-Type": "text/html; charset=utf-8",
        "Content-Length": Buffer.byteLength(page),
      }).end(page);

      if (done) return;
      done = true;
      clearTimeout(timer);
      srv.close();
      if (code) resolver(code);
      else rechazar(new OuraError(body));
    });

    srv.on("error", (e: NodeJS.ErrnoException) => {
      rechazar(new OuraError(
        `no se pudo escuchar en el port ${port} (${e.code}). ` +
        `Is another authorization running? Try --manual`));
    });

    const timer = setTimeout(() => {
      if (done) return;
      done = true;
      srv.close();
      rechazar(new OuraError(
        `no callback arrived within ${Math.round(wait / 1000)}s. ` +
        `If the machine has no browser, use --manual`));
    }, wait);

    srv.listen(port, "127.0.0.1");
  });
}

export function portOf(redirect: string): number {
  const p = new URL(redirect).port;
  return p ? Number(p) : 80;
}

async function openBrowser(url: string): Promise<void> {
  const { spawn } = await import("node:child_process");
  const cmd = process.platform === "darwin" ? "open"
            : process.platform === "win32" ? "start" : "xdg-open";
  try {
    spawn(cmd, [url], { detached: true, stdio: "ignore" }).unref();
  } catch { /* failing to open isn't fatal: the URL was already printed */ }
}

async function readLine(): Promise<string> {
  const { createInterface } = await import("node:readline/promises");
  const rl = createInterface({ input: process.stdin, output: process.stderr });
  try {
    return await rl.question("Callback URL: ");
  } finally {
    rl.close();
  }
}

/** The full flow. Returns a summary with NO tokens. */
export async function authorize(manual = false,
                                redirect = DEFAULT_REDIRECT): Promise<Record<string, unknown>> {
  const [cid, csec] = appCredentials();
  const state = randomBytes(24).toString("base64url");
  const url = authorizationUrl(cid, state, redirect);

  let code: string;
  if (manual) {
    // For machines with no browser. The localhost callback will fail in the
    // other machine's browser — that's expected — and what's useful is the URL
    // left in the address bar.
    process.stderr.write(
      `\nOpen this URL in any browser:\n\n${url}\n\n` +
      `On approval the browser will try to reach localhost and fail.\n` +
      `That is normal: copy the FULL URL from the bar and paste it here.\n\n`);
    code = extractCode(await readLine(), state);
  } else {
    process.stderr.write(
      `\nOpening the browser. If it does not open, go to:\n\n${url}\n\nWaiting for the callback…\n`);
    void openBrowser(url);
    code = await waitForCallback(portOf(redirect), state);
  }

  const cred = await exchangeCode(code, cid, csec, redirect);
  return {
    authorized: true,
    alcances_concedidos: [...cred.scopes],
    expires_in_seconds: Math.round((cred.expiresAt - Date.now()) / 1000),
    next_step: "you can use the server now; the token refreshes itself",
  };
}
