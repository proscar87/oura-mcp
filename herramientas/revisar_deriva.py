#!/usr/bin/env python3
"""¿Sigue existiendo cada una de las 19 colecciones que declara `colecciones.py`?

CORRE CONTRA EL SANDBOX DE OURA, QUE NO PIDE CREDENCIALES. Por eso puede vivir
en CI sin depender del token de nadie — que es la regla de este repositorio: un
CI que necesita el token de alguien para pasar no es un CI, es una dependencia
de esa persona.

QUÉ ATRAPA Y QUÉ NO
    Sí   una colección que Oura renombró, movió o retiró.
    No   una colección NUEVA. El sandbox no se puede enumerar, así que descubrir
         altas sigue siendo trabajo humano — hoy, leer las notas de versión.

POR QUÉ NO SE COMPARA CONTRA EL OPENAPI
Sería lo correcto y no se puede: Oura no publica su `openapi.json` en ninguna
URL estable. Se probaron cinco rutas plausibles el 9-ago-2026 y las cinco dan
404. La única copia pública que encontramos está vendorizada en el repositorio
de un tercero (`spxrogers/oura-toolkit`), y colgar nuestro CI del repositorio de
alguien más es cambiar una dependencia por otra peor.

    $ python herramientas/revisar_deriva.py
"""

from __future__ import annotations

import os
import sys

os.environ["OURA_SANDBOX"] = "1"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from oura_mcp.cliente import ErrorOura, base, obtener          # noqa: E402
from oura_mcp.colecciones import COLECCIONES, forma            # noqa: E402

# El sandbox sirve 18 de las 19. `personal_info` es la que falta, y tiene
# sentido: es la única que devuelve correo, edad, peso y estatura. Que falte no
# es deriva, así que se espera explícitamente en vez de tolerarse en silencio.
SIN_SANDBOX = {"personal_info"}

VENTANA = ("2026-01-01", "2026-01-05")
VENTANA_HORA = ("2026-01-01T00:00:00", "2026-01-02T00:00:00")


def revisar_una(nombre: str) -> tuple[bool, str]:
    f = forma(nombre)
    args = VENTANA if f == "rango_fecha" else VENTANA_HORA if f == "rango_datetime" else ()
    try:
        r = obtener(nombre, *args)
    except ErrorOura as e:
        if nombre in SIN_SANDBOX and "404" in str(e):
            return True, "ausente del sandbox, como se espera"
        return False, str(e)[:90]
    if nombre in SIN_SANDBOX:
        return False, "AHORA SÍ está en el sandbox: actualiza SIN_SANDBOX"
    return True, f"responde, n={r['n']}"


def main() -> int:
    print(f"deriva de colecciones contra {base()}\n")
    fallas = []
    for nombre in COLECCIONES:
        ok, detalle = revisar_una(nombre)
        print(f"  {'ok ' if ok else 'MAL'}  {nombre:<26} {detalle}")
        if not ok:
            fallas.append(nombre)
    print()
    if fallas:
        print(f"{len(fallas)} colección(es) derivaron: {', '.join(fallas)}")
        print("Revisa colecciones.py contra las notas de versión de Oura.")
        return 1
    print(f"Las {len(COLECCIONES)} colecciones siguen donde dice colecciones.py.")
    print("Recuerda: esto NO detecta colecciones nuevas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
