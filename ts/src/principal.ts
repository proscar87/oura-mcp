#!/usr/bin/env node
/**
 * La línea de comandos: sin banderas arranca el servidor MCP; con ellas, no.
 *
 * UNA BANDERA QUE NO EXISTE TIENE QUE FALLAR. Antes se ignoraba y se caía al
 * arranque del servidor, en silencio y con código 0. Quien escribiera
 * `--autorize` por un dedazo obtenía un proceso que espera JSON-RPC por stdin:
 * en una terminal parece colgado, y en un script pasa por éxito. Es la misma
 * familia de falla que persigue todo este paquete, cometida por nosotros y en
 * la primera línea que ve un usuario nuevo.
 */

import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { ErrorOura } from "./cliente.js";
import { crearServidor, revisar } from "./servidor.js";

// En orden de precedencia. La primera que aparezca gana, y da igual el orden en
// que se escriban: `--revisar --autorizar` hace el autodiagnóstico. Es
// determinista a propósito.
const ACCIONES = ["--ayuda", "--help", "-h", "--revisar", "--autorizar", "--olvidar"];
const MODIFICADORES = ["--manual"];

const AYUDA = `oura-mcp — la API v2 de Oura como servidor MCP

  oura-mcp                    arranca el servidor (JSON-RPC por stdin/stdout)
  oura-mcp --revisar          autodiagnóstico: con qué te autenticas, qué
                              alcances tienes y si Oura responde. No muestra el
                              token ni ningún dato de salud.
  oura-mcp --autorizar        OAuth2 en el navegador. Una sola vez.
  oura-mcp --autorizar --manual   para máquinas sin navegador.
  oura-mcp --olvidar          borra las credenciales guardadas.
  oura-mcp --ayuda            esto.

Para probarlo sin credenciales de ningún tipo:

  OURA_SANDBOX=1 oura-mcp --revisar

Variables: OURA_SANDBOX, OURA_CLIENT_ID, OURA_CLIENT_SECRET, OURA_CREDENCIALES,
OURA_PAT, OURA_PAT_FILE, OURA_API_BASE_URL.
`;

const imprimir = (x: unknown) => process.stdout.write(JSON.stringify(x, null, 2) + "\n");

export async function cli(argv: string[] = process.argv.slice(2)): Promise<number> {
  const desconocidas = argv.filter((a) => !ACCIONES.includes(a) && !MODIFICADORES.includes(a));
  if (desconocidas.length) {
    // A stderr y con código 2, no a stdout: si esto llegara a correr como
    // servidor, cualquier cosa en stdout que no sea JSON-RPC rompe el canal.
    process.stderr.write(`oura-mcp: no conozco ${desconocidas.join(", ")}\n\n${AYUDA}`);
    return 2;
  }
  if (argv.some((a) => ["--ayuda", "--help", "-h"].includes(a))) {
    process.stdout.write(AYUDA);
    return 0;
  }
  if (argv.includes("--revisar")) {
    imprimir(await revisar());
    return 0;
  }
  if (argv.includes("--autorizar")) {
    const { autorizar } = await import("./autorizar.js");
    try {
      imprimir(await autorizar(argv.includes("--manual")));
    } catch (e) {
      if (!(e instanceof ErrorOura)) throw e;
      imprimir({ autorizado: false, error: e.message });
      return 1;
    }
    return 0;
  }
  if (argv.includes("--olvidar")) {
    const { olvidar, rutaCredenciales } = await import("./credenciales.js");
    const archivo = rutaCredenciales();
    await olvidar();
    imprimir({ olvidado: true, archivo });
    return 0;
  }
  if (argv.includes("--manual")) {
    // `--manual` solo no significa nada, y arrancar el servidor por él sería
    // otra vez el silencio de antes.
    process.stderr.write(`oura-mcp: \`--manual\` sólo acompaña a \`--autorizar\`\n\n${AYUDA}`);
    return 2;
  }
  await crearServidor().connect(new StdioServerTransport());
  return 0;
}

const esteArchivo = new URL(import.meta.url).pathname;
if (process.argv[1] && esteArchivo.endsWith(process.argv[1].replace(/^.*\//, ""))) {
  cli().then((c) => { if (c) process.exit(c); }).catch((e) => {
    process.stderr.write(`oura-mcp: ${(e as Error).message}\n`);
    process.exit(1);
  });
}
