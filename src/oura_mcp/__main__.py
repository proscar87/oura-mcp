"""La línea de comandos: sin banderas arranca el servidor MCP; con ellas, no.

UNA BANDERA QUE NO EXISTE TIENE QUE FALLAR. Antes se ignoraba y se caía al
arranque del servidor, en silencio y con código 0. Quien escribiera `--autorize`
por un dedazo obtenía un proceso que espera JSON-RPC por stdin: en una terminal
parece colgado, y en un script pasa por éxito. Es la misma familia de falla que
persigue todo este paquete —parece que funcionó— cometida por nosotros y en la
primera línea que ve un usuario nuevo.
"""

import asyncio
import json
import sys

from .servidor import main, revisar

# En orden de precedencia. La primera que aparezca gana, y da igual el orden en
# que se escriban: `--revisar --autorizar` hace el autodiagnóstico. Es
# determinista a propósito, para que no dependa de cómo el usuario las teclee.
ACCIONES = ("--ayuda", "--help", "-h", "--revisar", "--autorizar", "--olvidar")
MODIFICADORES = ("--manual",)

AYUDA = """oura-mcp — la API v2 de Oura como servidor MCP

  oura-mcp                    arranca el servidor (habla JSON-RPC por stdin/stdout)
  oura-mcp --revisar          autodiagnóstico: con qué te autenticas, qué alcances
                              tienes y si Oura responde. No muestra el token ni
                              ningún dato de salud.
  oura-mcp --autorizar        OAuth2 en el navegador. Una sola vez.
  oura-mcp --autorizar --manual   para máquinas sin navegador: imprime la URL y
                              tú pegas la del callback.
  oura-mcp --olvidar          borra las credenciales guardadas.
  oura-mcp --ayuda            esto.

Para probarlo sin credenciales de ningún tipo:

  OURA_SANDBOX=1 oura-mcp --revisar

Variables: OURA_SANDBOX, OURA_CLIENT_ID, OURA_CLIENT_SECRET, OURA_CREDENCIALES,
OURA_PAT, OURA_PAT_FILE, OURA_API_BASE_URL.
"""


def cli(argv: list[str] | None = None) -> int:
    """Punto de entrada. `--revisar` NO toca la red más que para un pulso."""
    args = list(sys.argv[1:] if argv is None else argv)

    desconocidas = [a for a in args if a not in ACCIONES + MODIFICADORES]
    if desconocidas:
        # A stderr y con código 2, no a stdout: si esto llegara a correr como
        # servidor, cualquier cosa en stdout que no sea JSON-RPC rompe el canal.
        print(f"oura-mcp: no conozco {', '.join(desconocidas)}\n", file=sys.stderr)
        print(AYUDA, file=sys.stderr)
        return 2

    if any(a in args for a in ("--ayuda", "--help", "-h")):
        print(AYUDA)
        return 0

    if "--revisar" in args:
        print(json.dumps(revisar(), ensure_ascii=False, indent=2))
        return 0

    if "--autorizar" in args:
        # El flujo de OAuth va en la terminal, NUNCA dentro del servidor: uno que
        # habla por stdin/stdout no puede abrir un navegador ni pedirle nada a
        # nadie, y pretender que sí es cómo se cuelga un cliente MCP para siempre.
        from .autorizar import autorizar
        from .cliente import ErrorOura
        try:
            print(json.dumps(autorizar(manual="--manual" in args),
                             ensure_ascii=False, indent=2))
        except ErrorOura as e:
            print(json.dumps({"autorizado": False, "error": str(e)},
                             ensure_ascii=False, indent=2))
            return 1
        return 0

    if "--olvidar" in args:
        from .credenciales import olvidar, ruta_credenciales
        olvidar()
        print(json.dumps({"olvidado": True, "archivo": ruta_credenciales()},
                         ensure_ascii=False, indent=2))
        return 0

    if "--manual" in args:
        # `--manual` solo no significa nada, y arrancar el servidor por él sería
        # otra vez el silencio de antes.
        print("oura-mcp: `--manual` sólo acompaña a `--autorizar`\n", file=sys.stderr)
        print(AYUDA, file=sys.stderr)
        return 2

    asyncio.run(main())
    return 0


if __name__ == "__main__":
    sys.exit(cli())
