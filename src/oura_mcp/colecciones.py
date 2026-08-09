"""Las 19 colecciones de la API v2 de Oura, y sólo eso.

Toda la complejidad de hablarle a Oura vive en esta tabla. El resto —el cliente,
el servidor MCP— es presentación. Por eso está en su propio archivo: si Oura
agrega una colección, se toca aquí y nada más.

CUATRO FORMAS DE PARÁMETROS, no diecinueve:

    rango_fecha      start_date / end_date        (la mayoría)
    rango_datetime   start_datetime / end_datetime (heartrate, batería)
    unica            sin parámetros                (personal_info)
    solo_token       sin parámetros, sin fecha     (ring_configuration)
"""

from __future__ import annotations

BASE = "https://api.ouraring.com/v2/usercollection"

# {nombre: (forma, para qué sirve)}
COLECCIONES: dict[str, tuple[str, str]] = {
    # Los resúmenes diarios: lo que se consulta a diario.
    "daily_sleep":              ("rango_fecha", "puntaje de sueño y sus contribuyentes"),
    "daily_readiness":          ("rango_fecha", "puntaje de preparación y sus contribuyentes"),
    "daily_activity":           ("rango_fecha", "pasos, calorías, tiempo por intensidad"),
    "daily_stress":             ("rango_fecha", "minutos de estrés y de recuperación"),
    "daily_spo2":               ("rango_fecha", "saturación de oxígeno promedio nocturna"),
    "daily_resilience":         ("rango_fecha", "resiliencia (limited…exceptional)"),
    "daily_cardiovascular_age": ("rango_fecha", "edad cardiovascular estimada"),
    "vO2_max":                  ("rango_fecha", "VO2 máx estimado"),

    # El detalle que los puntajes esconden.
    "sleep":        ("rango_fecha", "sesiones de sueño: etapas, HRV, temperatura, latencia"),
    "sleep_time":   ("rango_fecha", "ventana de sueño recomendada"),
    "workout":      ("rango_fecha", "entrenamientos con tipo, duración e intensidad"),
    "session":      ("rango_fecha", "sesiones de respiración, meditación, siesta"),
    "rest_mode_period": ("rango_fecha", "periodos de modo descanso"),
    "tag":          ("rango_fecha", "etiquetas (obsoleta: Oura recomienda enhanced_tag)"),
    "enhanced_tag": ("rango_fecha", "etiquetas con hora de inicio y fin"),

    # Alta resolución. El único que OBLIGA a paginar.
    "heartrate":          ("rango_datetime", "frecuencia cardiaca cada 5 min"),
    "ring_battery_level": ("rango_datetime", "batería del anillo"),

    # Sin rango.
    "personal_info":      ("unica", "edad, peso, estatura, sexo biológico"),
    "ring_configuration": ("solo_token", "modelo, talla y color del anillo"),
}

CON_FECHA = {"rango_fecha", "rango_datetime"}

# Las que el sandbox de Oura NO sirve. Es una sola, y tiene sentido: es la única
# que devuelve correo, edad, peso y estatura. Vive aquí y no en el script de
# deriva porque el cliente también la necesita — sin esto, pedir el perfil en
# modo sandbox devolvía un `404: Not Found` crudo, y quien acabara de instalar
# concluiría que el servidor está roto.
SIN_SANDBOX = {"personal_info"}

# Qué alcance de OAuth necesita cada colección. Sirve para una sola cosa, y es
# importante: cuando una consulta vuelve VACÍA, distinguir «no hay dato» de «no
# diste ese permiso». Las dos se ven idénticas —n=0— y llevan a conclusiones
# opuestas.
ALCANCE_DE = {
    "daily_sleep": "daily", "daily_readiness": "daily", "daily_activity": "daily",
    "daily_stress": "daily", "daily_resilience": "daily",
    "daily_cardiovascular_age": "daily", "vO2_max": "daily",
    "sleep": "daily", "sleep_time": "daily", "rest_mode_period": "daily",
    "ring_battery_level": "daily", "ring_configuration": "daily",
    "daily_spo2": "spo2",
    "heartrate": "heartrate",
    "workout": "workout",
    "session": "session",
    "tag": "tag", "enhanced_tag": "tag",
    "personal_info": "personal",
}

# Las únicas dos que respetan `latest=true`. Medido contra la API el 9-ago-2026:
# en las demás Oura NO devuelve un error, devuelve la colección entera. Pedir el
# último registro y recibir diez, sin aviso, es la misma familia de falla que no
# paginar — por eso aquí se rechaza antes de salir a la red.
CON_ULTIMO = {"heartrate", "ring_battery_level"}


def forma(coleccion: str) -> str:
    """Forma de parámetros de la colección. KeyError si no existe — a propósito.

    Un nombre inventado tiene que tronar aquí y no convertirse en una petición a
    una URL que no existe, cuyo 404 después hay que interpretar.
    """
    return COLECCIONES[coleccion][0]


def describir() -> str:
    """Las 19 colecciones con su descripción, para el prompt de la herramienta."""
    return "\n".join(
        f"  {n:<24} {d}" for n, (_f, d) in COLECCIONES.items()
    )
