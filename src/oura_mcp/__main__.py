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
    if "--autorizar" in sys.argv:
        # El flujo de OAuth va en la terminal, NUNCA dentro del servidor: uno que
        # habla por stdin/stdout no puede abrir un navegador ni pedirle nada a
        # nadie, y pretender que sí es cómo se cuelga un cliente MCP para siempre.
        from .autorizar import autorizar
        from .cliente import ErrorOura
        try:
            print(json.dumps(autorizar(manual="--manual" in sys.argv),
                             ensure_ascii=False, indent=2))
        except ErrorOura as e:
            print(json.dumps({"autorizado": False, "error": str(e)},
                             ensure_ascii=False, indent=2))
            return 1
        return 0
    if "--olvidar" in sys.argv:
        from .credenciales import olvidar, ruta_credenciales
        olvidar()
        print(json.dumps({"olvidado": True, "archivo": ruta_credenciales()},
                         ensure_ascii=False, indent=2))
        return 0
    asyncio.run(main())
    return 0


if __name__ == "__main__":
    sys.exit(cli())
