/**
 * El flujo interactivo de OAuth2: del navegador al primer par de tokens.
 *
 * Corre UNA VEZ, a mano, desde la terminal. No es parte del servidor MCP — uno
 * que habla por stdin/stdout no puede abrir un navegador ni pedirle nada a
 * nadie, y pretender que sí es cómo se cuelga un cliente MCP para siempre.
 *
 *     oura-mcp --autorizar             # abre el navegador y espera el callback
 *     oura-mcp --autorizar --manual    # imprime la URL; tú pegas la de vuelta
 *
 * EL `state` NO ES OPCIONAL. El callback llega a un servidor HTTP en localhost
 * que atiende lo que le manden; sin compararlo, cualquier página abierta en el
 * navegador del usuario puede mandarle un código de autorización de OTRA cuenta
 * y dejarlo conectado a datos que no son suyos.
 */

import { createServer } from "node:http";
import { timingSafeEqual } from "node:crypto";
import { randomBytes } from "node:crypto";

import { ErrorOura } from "./cliente.js";
import { ALCANCES, AUTORIZAR_URL, REDIRECT_POR_DEFECTO, canjearCodigo } from "./credenciales.js";

export const ESPERA_CALLBACK = 300_000;   // cinco minutos para autorizar

const PAGINA = (titulo: string, cuerpo: string) =>
  `<!doctype html><html lang="es"><meta charset="utf-8"><title>oura-mcp</title>` +
  `<body style="font-family:system-ui;max-width:32rem;margin:6rem auto;line-height:1.5">` +
  `<h1>${titulo}</h1><p>${cuerpo}</p></body></html>`;

/** El client_id y el client_secret de la aplicación de Oura. */
export function credencialesDeApp(): [string, string] {
  const cid = (process.env.OURA_CLIENT_ID ?? "").trim();
  const csec = (process.env.OURA_CLIENT_SECRET ?? "").trim();
  if (!cid || !csec) {
    throw new ErrorOura(
      "faltan OURA_CLIENT_ID y OURA_CLIENT_SECRET. Registra una aplicación en " +
      "https://cloud.ouraring.com/oauth/applications con el redirect " +
      `${REDIRECT_POR_DEFECTO} (la diagonal final es obligatoria)`);
  }
  return [cid, csec];
}

export function urlDeAutorizacion(clientId: string, estado: string,
                                  redirectUri = REDIRECT_POR_DEFECTO,
                                  alcances: readonly string[] = ALCANCES): string {
  const q = new URLSearchParams({
    response_type: "code",
    client_id: clientId,
    redirect_uri: redirectUri,
    scope: alcances.join(" "),
    state: estado,
  });
  return `${AUTORIZAR_URL}?${q.toString()}`;
}

function mismoEstado(a: string, b: string): boolean {
  const ba = Buffer.from(a), bb = Buffer.from(b);
  return ba.length === bb.length && timingSafeEqual(ba, bb);
}

/**
 * Saca el `code` de la URL del callback. Verifica el `state` si se le da.
 *
 * ¿Es una URL o un código pelado? Se decide por la FORMA, no por los
 * caracteres: los códigos de OAuth son base64url y traen `-`, `_` y `=` de
 * relleno con toda normalidad. La heurística anterior miraba si el texto tenía
 * `=` o `/` y rechazaba `abc=` como «eso no trae un code», que es de las cosas
 * más desconcertantes que le pueden pasar a quien pegó justo lo que se le pidió.
 */
export function extraerCodigo(urlOCodigo: string, estadoEsperado?: string): string {
  const texto = urlOCodigo.trim();
  const pareceUrl = /^https?:\/\//.test(texto) || texto.includes("?");
  if (!pareceUrl) return texto;

  let q: URLSearchParams;
  try {
    q = new URL(texto, "http://localhost").searchParams;
  } catch {
    throw new ErrorOura("no se pudo leer esa URL; pega la del callback completa");
  }
  if (![...q.keys()].length) {
    throw new ErrorOura("esa URL no trae parámetros; pega la del callback completa");
  }
  const error = q.get("error");
  if (error) {
    throw new ErrorOura(`Oura rechazó la autorización: ${q.get("error_description") ?? error}`);
  }
  const codigo = q.get("code");
  if (!codigo) throw new ErrorOura("la URL no trae `code`");
  if (estadoEsperado !== undefined) {
    if (!mismoEstado(q.get("state") ?? "", estadoEsperado)) {
      throw new ErrorOura(
        "el `state` no coincide: ese callback no salió de esta sesión. " +
        "No se canjeó nada. Vuelve a empezar.");
    }
  }
  return codigo;
}

/**
 * Levanta el servidor local y espera EL CALLBACK, no la primera petición.
 *
 * La diferencia costó el flujo entero. Un navegador de verdad no manda una sola
 * petición: pide `/favicon.ico` por su cuenta. Atendiendo sólo una, el favicon
 * se llevaba el turno, el servidor se cerraba, y el callback bueno recibía
 * *connection refused*. Desde afuera se veía «no llegó ningún callback», sin
 * ninguna pista de por qué.
 */
export function esperarCallback(puerto: number, estado: string,
                                espera = ESPERA_CALLBACK): Promise<string> {
  return new Promise((resolver, rechazar) => {
    let listo = false;
    const servidor = createServer((req, res) => {
      const ruta = new URL(req.url ?? "/", "http://localhost").pathname.replace(/\/+$/, "");
      if (ruta !== "/callback") {
        res.writeHead(404).end();
        return;   // el favicon y compañía NO cierran el servidor
      }
      let titulo: string, cuerpo: string, codigo: string | null = null;
      try {
        codigo = extraerCodigo(req.url ?? "", estado);
        titulo = "Listo";
        cuerpo = "Ya puedes cerrar esta pestaña y volver a la terminal.";
      } catch (e) {
        titulo = "No se pudo";
        cuerpo = (e as Error).message;
      }
      const pagina = PAGINA(titulo, cuerpo);
      res.writeHead(200, {
        "Content-Type": "text/html; charset=utf-8",
        "Content-Length": Buffer.byteLength(pagina),
      }).end(pagina);

      if (listo) return;
      listo = true;
      clearTimeout(reloj);
      servidor.close();
      if (codigo) resolver(codigo);
      else rechazar(new ErrorOura(cuerpo));
    });

    servidor.on("error", (e: NodeJS.ErrnoException) => {
      rechazar(new ErrorOura(
        `no se pudo escuchar en el puerto ${puerto} (${e.code}). ` +
        `¿Hay otra autorización corriendo? Prueba con --manual`));
    });

    const reloj = setTimeout(() => {
      if (listo) return;
      listo = true;
      servidor.close();
      rechazar(new ErrorOura(
        `no llegó ningún callback en ${Math.round(espera / 1000)}s. ` +
        `Si la máquina no tiene navegador, usa --manual`));
    }, espera);

    servidor.listen(puerto, "127.0.0.1");
  });
}

export function puertoDe(redirect: string): number {
  const p = new URL(redirect).port;
  return p ? Number(p) : 80;
}

async function abrirNavegador(url: string): Promise<void> {
  const { spawn } = await import("node:child_process");
  const cmd = process.platform === "darwin" ? "open"
            : process.platform === "win32" ? "start" : "xdg-open";
  try {
    spawn(cmd, [url], { detached: true, stdio: "ignore" }).unref();
  } catch { /* que no se abra no es fatal: la URL ya se imprimió */ }
}

async function leerLinea(): Promise<string> {
  const { createInterface } = await import("node:readline/promises");
  const rl = createInterface({ input: process.stdin, output: process.stderr });
  try {
    return await rl.question("URL del callback: ");
  } finally {
    rl.close();
  }
}

/** El flujo completo. Devuelve un resumen SIN tokens. */
export async function autorizar(manual = false,
                                redirect = REDIRECT_POR_DEFECTO): Promise<Record<string, unknown>> {
  const [cid, csec] = credencialesDeApp();
  const estado = randomBytes(24).toString("base64url");
  const url = urlDeAutorizacion(cid, estado, redirect);

  let codigo: string;
  if (manual) {
    // Para máquinas sin navegador. El callback a localhost fallará en el
    // navegador de la otra máquina —es lo esperado— y lo que sirve es la URL
    // que queda en la barra de direcciones.
    process.stderr.write(
      `\nAbre esta URL en cualquier navegador:\n\n${url}\n\n` +
      `Al aceptar, el navegador intentará ir a localhost y fallará.\n` +
      `Eso es normal: copia la URL COMPLETA de la barra y pégala aquí.\n\n`);
    codigo = extraerCodigo(await leerLinea(), estado);
  } else {
    process.stderr.write(
      `\nAbriendo el navegador. Si no se abre, entra a:\n\n${url}\n\nEsperando el callback…\n`);
    void abrirNavegador(url);
    codigo = await esperarCallback(puertoDe(redirect), estado);
  }

  const cred = await canjearCodigo(codigo, cid, csec, redirect);
  return {
    autorizado: true,
    alcances_concedidos: [...cred.alcances],
    caduca_en_segundos: Math.round((cred.expiraEn - Date.now()) / 1000),
    siguiente_paso: "ya puedes usar el servidor; el token se renueva solo",
  };
}
