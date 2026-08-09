/**
 * Las 19 colecciones de la API v2 de Oura, y sólo eso.
 *
 * Toda la complejidad de hablarle a Oura vive en estas tablas. El resto —el
 * cliente, el servidor MCP— es presentación. Por eso está en su propio archivo:
 * si Oura agrega una colección, se toca aquí y nada más.
 *
 * CUATRO FORMAS DE PARÁMETROS, no diecinueve:
 *
 *     rangoFecha      start_date / end_date          (la mayoría)
 *     rangoDatetime   start_datetime / end_datetime  (heartrate, batería)
 *     unica           sin parámetros                 (personal_info)
 *     soloToken       sin parámetros, sin fecha      (ring_configuration)
 */

export const BASE = "https://api.ouraring.com/v2/usercollection";

export type Forma = "rangoFecha" | "rangoDatetime" | "unica" | "soloToken";

export const COLECCIONES: Record<string, { forma: Forma; queTrae: string }> = {
  // Los resúmenes diarios: lo que se consulta a diario.
  daily_sleep: { forma: "rangoFecha", queTrae: "puntaje de sueño y sus contribuyentes" },
  daily_readiness: { forma: "rangoFecha", queTrae: "puntaje de preparación y sus contribuyentes" },
  daily_activity: { forma: "rangoFecha", queTrae: "pasos, calorías, tiempo por intensidad" },
  daily_stress: { forma: "rangoFecha", queTrae: "minutos de estrés y de recuperación" },
  daily_spo2: { forma: "rangoFecha", queTrae: "saturación de oxígeno promedio nocturna" },
  daily_resilience: { forma: "rangoFecha", queTrae: "resiliencia (limited…exceptional)" },
  daily_cardiovascular_age: { forma: "rangoFecha", queTrae: "edad cardiovascular estimada" },
  vO2_max: { forma: "rangoFecha", queTrae: "VO2 máx estimado" },

  // El detalle que los puntajes esconden.
  sleep: { forma: "rangoFecha", queTrae: "sesiones de sueño: etapas, HRV, temperatura, latencia" },
  sleep_time: { forma: "rangoFecha", queTrae: "ventana de sueño recomendada" },
  workout: { forma: "rangoFecha", queTrae: "entrenamientos con tipo, duración e intensidad" },
  session: { forma: "rangoFecha", queTrae: "sesiones de respiración, meditación, siesta" },
  rest_mode_period: { forma: "rangoFecha", queTrae: "periodos de modo descanso" },
  tag: { forma: "rangoFecha", queTrae: "etiquetas (obsoleta: Oura recomienda enhanced_tag)" },
  enhanced_tag: { forma: "rangoFecha", queTrae: "etiquetas con hora de inicio y fin" },

  // Alta resolución. Las únicas que OBLIGAN a paginar.
  heartrate: { forma: "rangoDatetime", queTrae: "frecuencia cardiaca cada 5 min" },
  ring_battery_level: { forma: "rangoDatetime", queTrae: "batería del anillo" },

  // Sin rango.
  personal_info: { forma: "unica", queTrae: "edad, peso, estatura, sexo biológico" },
  ring_configuration: { forma: "soloToken", queTrae: "modelo, talla y color del anillo" },
};

export const CON_FECHA: ReadonlySet<Forma> = new Set<Forma>(["rangoFecha", "rangoDatetime"]);

/**
 * Las únicas dos que respetan `latest=true`. Medido contra la API el
 * 9-ago-2026: en las demás Oura NO devuelve un error, devuelve la colección
 * entera. Pedir el último registro y recibir diez, sin aviso, es la misma
 * familia de falla que no paginar — por eso aquí se rechaza antes de la red.
 */
export const CON_ULTIMO: ReadonlySet<string> = new Set(["heartrate", "ring_battery_level"]);

/**
 * Las que el sandbox de Oura NO sirve. Es una sola, y tiene sentido: es la
 * única que devuelve correo, edad, peso y estatura. Sin esto, pedir el perfil
 * en modo sandbox devolvía un `404: Not Found` crudo, y quien acabara de
 * instalar concluiría que el servidor está roto.
 */
export const SIN_SANDBOX: ReadonlySet<string> = new Set(["personal_info"]);

/**
 * Qué alcance de OAuth necesita cada colección. Sirve para una sola cosa, y es
 * importante: cuando una consulta vuelve VACÍA, distinguir «no hay dato» de «no
 * diste ese permiso». Las dos se ven idénticas —n=0— y llevan a conclusiones
 * opuestas.
 */
export const ALCANCE_DE: Record<string, string> = {
  daily_sleep: "daily", daily_readiness: "daily", daily_activity: "daily",
  daily_stress: "daily", daily_resilience: "daily",
  daily_cardiovascular_age: "daily", vO2_max: "daily",
  sleep: "daily", sleep_time: "daily", rest_mode_period: "daily",
  ring_battery_level: "daily", ring_configuration: "daily",
  daily_spo2: "spo2",
  heartrate: "heartrate",
  workout: "workout",
  session: "session",
  tag: "tag", enhanced_tag: "tag",
  personal_info: "personal",
};

/**
 * Forma de parámetros de la colección. Lanza si no existe — a propósito.
 *
 * Un nombre inventado tiene que tronar aquí y no convertirse en una petición a
 * una URL que no existe, cuyo 404 después hay que interpretar.
 */
export function forma(coleccion: string): Forma {
  const c = COLECCIONES[coleccion];
  if (!c) throw new Error(`«${coleccion}» no es una colección de Oura`);
  return c.forma;
}
