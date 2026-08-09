/**
 * Pruebas del cliente. NO TOCAN LA RED: `fetch` se sustituye por uno falso.
 *
 * Lo que se prueba aquí son las cuatro fallas silenciosas de Oura y los tres
 * finales del bucle de paginación. Un CI que necesita el token de alguien para
 * pasar no es un CI: es una dependencia de esa persona.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ErrorOura, Secreto, aCsv, avisoDeTamano, camposIgnorados, correrDias, diaDe,
  esperaPedida, detalleDe, obtener,
} from "../src/cliente.js";

type Pagina = Record<string, unknown>[];

/** Una API falsa que sirve `paginas`, cada una con su next_token. */
function ouraFalso(paginas: Pagina[], registrar?: string[]) {
  vi.stubGlobal("fetch", async (url: string) => {
    registrar?.push(url);
    const m = /next_token=([^&]*)/.exec(url);
    const i = m ? Number(m[1]) : 0;
    const cuerpo: Record<string, unknown> = { data: paginas[i] ?? [] };
    if (i + 1 < paginas.length) cuerpo["next_token"] = String(i + 1);
    return new Response(JSON.stringify(cuerpo), { status: 200 });
  });
}

beforeEach(() => {
  process.env.OURA_PAT = "token-de-prueba";
  delete process.env.OURA_SANDBOX;
  delete process.env.OURA_PAT_FILE;
});
afterEach(() => vi.unstubAllGlobals());

// ── Paginación: la razón de existir del paquete ────────────────────────────
describe("paginación", () => {
  it("sigue el next_token hasta el final", async () => {
    // LA CICATRIZ QUE JUSTIFICA EL PAQUETE. Quien no persigue el token recibe la
    // primera página sin que nada se lo diga: un JSON válido que se ve completo.
    ouraFalso(Array.from({ length: 5 }, () =>
      Array.from({ length: 100 }, (_, n) => ({ i: n }))));
    const r = await obtener("heartrate", {
      inicio: "2026-08-01T00:00:00Z", fin: "2026-08-02T00:00:00Z" });
    expect(r["n"]).toBe(500);
    expect(r["paginas"]).toBe(5);
    expect(r["truncado"]).toBeUndefined();
  });

  it("al truncar lo dice y deja el cursor", async () => {
    ouraFalso(Array.from({ length: 20 }, (_, n) => [{ i: n }]));
    const r = await obtener("heartrate", {
      inicio: "2026-08-01T00:00:00Z", fin: "2026-08-02T00:00:00Z", limitePaginas: 3 });
    expect(r["paginas"]).toBe(3);
    expect(String(r["truncado"])).toContain("acorta");
    expect(r["continuar_desde"]).toBe("3");
  });

  it("detecta un next_token repetido como ciclo, no como truncamiento", async () => {
    // Sin esto se hacían 50 peticiones idénticas y el aviso decía «acorta el
    // rango» — consejo inútil, porque acortar no arregla que la API se repita.
    const llamadas: string[] = [];
    vi.stubGlobal("fetch", async (url: string) => {
      llamadas.push(url);
      return new Response(JSON.stringify({
        data: [{ day: "2026-08-01" }], next_token: "SIEMPRE-EL-MISMO" }), { status: 200 });
    });
    const r = await obtener("daily_sleep", { inicio: "2026-08-01", fin: "2026-08-01" });
    expect(llamadas).toHaveLength(2);
    expect(r["ciclo_de_paginacion"]).toBeDefined();
    expect(r["truncado"]).toBeUndefined();
  });
});

// ── El rango de fechas: la segunda cicatriz ────────────────────────────────
describe("rango de fechas", () => {
  it("pide dos días de más de cada lado", async () => {
    // No es margen de cortesía: `workout` es exclusiva Y va desfasada a UTC, y
    // las dos cosas se suman. Un día no alcanzaba.
    const urls: string[] = [];
    ouraFalso([[{}]], urls);
    await obtener("daily_sleep", { inicio: "2026-08-10", fin: "2026-08-20" });
    expect(urls[0]).toContain("start_date=2026-08-08");
    expect(urls[0]).toContain("end_date=2026-08-22");
  });

  it("no ensancha los rangos con hora", async () => {
    const urls: string[] = [];
    ouraFalso([[{}]], urls);
    await obtener("heartrate", {
      inicio: "2026-08-10T00:00:00Z", fin: "2026-08-10T06:00:00Z" });
    expect(urls[0]).toContain("start_datetime=2026-08-10T00%3A00%3A00Z");
  });

  it("recorta los días de más y lo dice", async () => {
    ouraFalso([["2026-08-08", "2026-08-09", "2026-08-10", "2026-08-11", "2026-08-12"]
      .map((day) => ({ day }))]);
    const r = await obtener("daily_sleep", { inicio: "2026-08-09", fin: "2026-08-11" });
    expect(r["n"]).toBe(3);
    expect(r["descartados_fuera_de_rango"]).toBe(2);
  });

  it("un solo día devuelve ese día", async () => {
    // El caso que estaba roto: [d..d] devolvía cero en daily_activity, sleep y
    // workout.
    ouraFalso([[{ day: "2026-08-09" }, { day: "2026-08-10" }, { day: "2026-08-11" }]]);
    const r = await obtener("workout", { inicio: "2026-08-10", fin: "2026-08-10" });
    expect(r["n"]).toBe(1);
  });

  it("saca el día de start_day cuando no hay day", async () => {
    ouraFalso([[{ start_day: "2026-08-09" }, { start_day: "2026-08-30" }]]);
    expect((await obtener("enhanced_tag", {
      inicio: "2026-08-09", fin: "2026-08-09" }))["n"]).toBe(1);
  });

  it("conserva lo que no se puede fechar", async () => {
    // Descartar lo que no se entiende es la forma más rápida de entregar de
    // menos, que es lo que este paquete existe para no hacer.
    ouraFalso([[{ day: "2026-08-09" }, { sin_fecha: true }, { day: "2026-09-30" }]]);
    const r = await obtener("daily_sleep", { inicio: "2026-08-09", fin: "2026-08-09" });
    expect(r["n"]).toBe(2);
  });

  it("atrapa el rango al revés aquí, citando las fechas que se escribieron", async () => {
    // Con el margen, Oura devolvería un 400 citando dos fechas que quien
    // preguntó nunca escribió.
    ouraFalso([[{}]]);
    await expect(obtener("daily_sleep", { inicio: "2026-08-10", fin: "2026-08-01" }))
      .rejects.toThrow(/2026-08-10.*2026-08-01/s);
  });

  it("diaDe reconoce las claves con hora", () => {
    expect(diaDe({ timestamp: "2026-08-09T12:00:00-06:00" })).toBe("2026-08-09");
    expect(diaDe({ bedtime_start: "2026-08-09T23:10:00-06:00" })).toBe("2026-08-09");
    expect(diaDe({ nada: 1 })).toBeNull();
    expect(diaDe("no es un objeto")).toBeNull();
  });

  it("correrDias devuelve la entrada intacta si no parsea", () => {
    expect(correrDias("2026-08-10", 2)).toBe("2026-08-12");
    expect(correrDias("ayer", 2)).toBe("ayer");
  });
});

// ── Lo que Oura ignora en silencio ─────────────────────────────────────────
describe("`ultimo` y `campos`", () => {
  it("rechaza `ultimo` donde Oura lo ignoraría", async () => {
    // Pedir el último registro y recibir diez creyendo que es uno es peor que
    // un error.
    ouraFalso([[{}]]);
    await expect(obtener("daily_sleep", {
      inicio: "2026-08-01", fin: "2026-08-10", ultimo: true })).rejects.toThrow(/lo ignora/);
  });

  it("manda latest donde sí lo respetan, y no exige rango", async () => {
    const urls: string[] = [];
    ouraFalso([[{ bpm: 60 }]], urls);
    expect((await obtener("heartrate", { ultimo: true }))["n"]).toBe(1);
    expect(urls[0]).toContain("latest=true");
  });

  it("avisa de los campos que no aparecieron", () => {
    expect(camposIgnorados(["score", "no_existe"], [{ day: "x", score: 1 }]))
      .toEqual(["no_existe"]);
    expect(camposIgnorados(undefined, [{ day: "x" }])).toEqual([]);
  });
});

// ── Formas de respuesta ────────────────────────────────────────────────────
describe("formas de respuesta", () => {
  it("denuncia un `data` que no es lista", async () => {
    // Envolver el sobre entero convertiría eso en «un registro» con forma
    // `{data: …}` que se ve legítimo.
    vi.stubGlobal("fetch", async () =>
      new Response(JSON.stringify({ data: { day: "2026-08-01" } }), { status: 200 }));
    await expect(obtener("daily_sleep", { inicio: "2026-08-01", fin: "2026-08-01" }))
      .rejects.toThrow(/no se inventa una interpretación/);
  });

  it("las colecciones sin sobre siguen funcionando", async () => {
    vi.stubGlobal("fetch", async () =>
      new Response(JSON.stringify({ email: "x", age: 1 }), { status: 200 }));
    expect((await obtener("personal_info"))["n"]).toBe(1);
  });

  it("una respuesta vacía son cero registros, no uno", async () => {
    vi.stubGlobal("fetch", async () => new Response("{}", { status: 200 }));
    expect((await obtener("personal_info"))["n"]).toBe(0);
  });
});

// ── CSV ────────────────────────────────────────────────────────────────────
describe("CSV", () => {
  it("saca el encabezado de la unión, no del primer registro", () => {
    // Basta un registro con un campo extra para que ese campo desaparezca sin
    // dejar rastro.
    const { columnas, texto, desiguales } = aCsv([
      { day: "2026-08-10", score: 1 }, { day: "2026-08-11", score: 2, extra: 9 }]);
    expect(columnas).toContain("extra");
    expect(texto).toContain("9");
    expect(desiguales).toBe(true);
  });

  it("pone la fecha primero", () => {
    // Es la columna con la que un modelo cruza contra otra fuente.
    expect(aCsv([{ score: 1, day: "2026-08-10", aaa: 2 }]).columnas[0]).toBe("day");
  });

  it("escribe lo anidado como JSON en su celda", () => {
    // Aplanar inventaría columnas que Oura no tiene; omitir sería perder datos.
    expect(aCsv([{ day: "x", contributors: { deep: 91 } }]).texto).toContain('{""deep"":91}');
  });
});

// ── Tamaño y vacío ─────────────────────────────────────────────────────────
describe("avisos", () => {
  it("una respuesta enorme se comenta a sí misma", () => {
    const gordo = { day: "2026-08-01", met: Array.from({ length: 6000 }, (_, i) => i) };
    const aviso = avisoDeTamano([gordo, { ...gordo }], undefined);
    expect(aviso?.campo_mas_pesado).toBe("met");
    expect(aviso!.porcentaje).toBeGreaterThan(90);
  });

  it("no insiste si ya eligió columnas", () => {
    const gordo = { met: Array.from({ length: 6000 }, (_, i) => i) };
    expect(avisoDeTamano([gordo, { ...gordo }], ["met"])).toBeNull();
  });

  it("una consulta vacía explica lo que se sabe", async () => {
    // `n: 0` no distingue entre no llevar el anillo, que no haya sincronizado,
    // pedir una fecha futura, o no tener el permiso.
    ouraFalso([[]]);
    const r = await obtener("daily_sleep", { inicio: "2026-01-01", fin: "2026-01-02" });
    const vacio = r["vacio"] as Record<string, string>;
    expect(vacio["no_confundir"]).toContain("no dormiste");
  });

  it("dice cuando el rango está en el futuro", async () => {
    const manana = new Date(Date.now() + 30 * 86400_000).toISOString().slice(0, 10);
    ouraFalso([[]]);
    const r = await obtener("daily_sleep", { inicio: manana, fin: manana });
    expect((r["vacio"] as { lo_que_se_sabe: string[] }).lo_que_se_sabe.join())
      .toContain("futuro");
  });
});

// ── El 429 y los errores ───────────────────────────────────────────────────
describe("errores", () => {
  it("honra Retry-After y lo acota", () => {
    expect(esperaPedida("3", 0)).toBe(3000);
    expect(esperaPedida("1800", 0)).toBe(8000);   // una cabecera generosa no cuelga nada
    expect(esperaPedida(null, 1)).toBe(2000);     // backoff exponencial
  });

  it("traduce el detail de pydantic a algo legible", () => {
    // Recortado en crudo dejaba `{"detail":[{"type":"datetime_from_date_pars` y
    // nada más.
    const m = detalleDe(JSON.stringify({ detail: [{
      type: "datetime_from_date_parsing",
      loc: ["query", "start_date", "datetime"],
      msg: "Input should be a valid datetime or date",
      input: "ayer" }] }));
    expect(m).toContain("start_date");
    expect(m).toContain('"ayer"');
    expect(m).not.toContain("datetime_from_date_parsing");
  });

  it("lee también el detail de cadena", () => {
    expect(detalleDe(JSON.stringify({ detail: "Start time is greater" })))
      .toContain("Start time is greater");
  });

  it("un cuerpo ilegible no tumba nada", () => {
    expect(detalleDe("<html>")).toBe("");
  });
});

// ── El token ───────────────────────────────────────────────────────────────
describe("Secreto", () => {
  it("no se imprime por accidente", () => {
    const s = new Secreto("abcdefghij");
    expect(String(s)).not.toContain("abcdefghij");
    expect(`${s}`).not.toContain("abcdefghij");
    expect(JSON.stringify({ s })).not.toContain("abcdefghij");
    expect(String(s)).toContain("10");            // la longitud sí, que es lo que diagnostica
    expect(s.revelar()).toBe("abcdefghij");       // revelarlo es explícito
  });
});

// ── Sandbox ────────────────────────────────────────────────────────────────
describe("sandbox", () => {
  it("el perfil explica en vez de devolver un 404 crudo", async () => {
    process.env.OURA_SANDBOX = "1";
    await expect(obtener("personal_info")).rejects.toThrow(/no existe en el sandbox/);
    await expect(obtener("personal_info")).rejects.toThrow(/Todo lo demás sí funciona/);
  });

  it("una colección inventada truena antes de salir a la red", async () => {
    await expect(obtener("daily_vibraciones", { inicio: "2026-01-01", fin: "2026-01-01" }))
      .rejects.toThrow(/no es una colección/);
  });
});
