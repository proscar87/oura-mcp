#!/usr/bin/env python3
"""¿Sigue existiendo cada una de las 19 collections que declara `collections.py`?

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

    $ python tools/check_drift.py
"""

from __future__ import annotations

import os
import sys

os.environ["OURA_SANDBOX"] = "1"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from oura_mcp.client import OuraError, base, fetch          # noqa: E402
from oura_mcp.collections import COLLECTIONS, WITHOUT_SANDBOX, shape   # noqa: E402

# El sandbox sirve 18 de las 19; la que falta se declara en `collections.py`,
# que es de donde también la lee el client. Que falte no es deriva, así que se
# espera explícitamente en vez de tolerarse en silencio.

VENTANA = ("2026-01-01", "2026-01-05")
VENTANA_HORA = ("2026-01-01T00:00:00", "2026-01-02T00:00:00")


def revisar_una(nombre: str) -> tuple[bool, str]:
    f = shape(nombre)
    args = VENTANA if f == "date_range" else VENTANA_HORA if f == "datetime_range" else ()

    if nombre in WITHOUT_SANDBOX:
        # SE PREGUNTA A OURA DIRECTAMENTE, saltándose la guarda del client. Si
        # se usara `fetch()`, esta comprobación estaría verificando nuestro
        # propio mensaje de error en vez de la API — y el día que Oura agregue
        # esta colección al sandbox, nadie se enteraría. Un chequeo que se
        # comprueba a sí mismo no comprueba nada.
        from oura_mcp.client import _request, _token
        try:
            _request(f"{base()}/{nombre}", _token())
        except OuraError as e:
            if "404" in str(e):
                return True, "ausente del sandbox, como se espera"
            return False, str(e)[:90]
        return False, "AHORA SÍ está en el sandbox: actualiza WITHOUT_SANDBOX"

    try:
        r = fetch(nombre, *args)
    except OuraError as e:
        return False, str(e)[:90]
    return True, f"responde, n={r['n']}"


def main() -> int:
    print(f"deriva de collections contra {base()}\n")
    fallas = []
    for nombre in COLLECTIONS:
        ok, detalle = revisar_una(nombre)
        print(f"  {'ok ' if ok else 'MAL'}  {nombre:<26} {detalle}")
        if not ok:
            fallas.append(nombre)
    print()
    if fallas:
        print(f"{len(fallas)} colección(es) derivaron: {', '.join(fallas)}")
        print("Revisa collections.py contra las notas de versión de Oura.")
        return 1
    print(f"Las {len(COLLECTIONS)} collections siguen donde dice collections.py.")
    print("Recuerda: esto NO detecta collections nuevas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
