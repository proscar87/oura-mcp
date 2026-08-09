# Roadmap

Escrito el **9 de agosto de 2026**, después de revisar los 431 repositorios de
Oura que hay en GitHub y de comprobar contra la API de verdad qué sigue vivo y
qué no.

Tres objetivos, en este orden: **que se pueda instalar sin saber nada**, **que
esté listado en Claude**, **que cubra lo que hay que cubrir**.

El orden de los *hitos*, sin embargo, es otro — primero se arregla lo que hoy
entrega datos incorrectos en silencio, porque empaquetar un bug para instalarlo
de un clic sólo lo distribuye más rápido.

---

## Lo que ya está hecho

| | |
|---|---|
| GitHub | público, MIT, CI verde |
| PyPI | `mcp-oura` 0.1.0 y 0.1.1 |
| Registro de MCP | `io.github.proscar87/oura-mcp` v0.1.1, `active`, buscable |

El registro entró el 9-ago a las 05:28 UTC. Los tres puntos de publicación que
pedía AGENTS.md están cerrados.

---

## Los tres hallazgos que reordenan el mapa

### 1. El rango de fechas estaba roto — **medido, y ya arreglado**

Pedir un solo día devolvía **cero registros** en tres colecciones. Sin error,
sin `truncado`, con `paginas: 1` afirmando que la página venía completa. Es
exactamente el modo de falla que este repositorio existe para no cometer, en la
ruta más común de todas: «¿cómo dormí ayer?».

Medido contra la API real el 9-ago-2026, colección por colección, son **dos
fallas distintas que se suman**:

**a) `end_date` es inconsistente entre colecciones.** No es «exclusivo» a secas,
como dice la nota de `crcatala` — depende de cuál:

| Exclusivas (pierden el último día) | Inclusivas |
|---|---|
| `daily_activity`, `sleep`, `workout` | `daily_sleep`, `daily_readiness`, `daily_stress`, `daily_spo2`, `daily_resilience`, `daily_cardiovascular_age`, `sleep_time` |

**b) `workout` se filtra por la fecha UTC pero reporta `day` en hora local.** Con
`-06:00`, pedir `[16-jul .. 18-jul]` devolvía registros de los días **15 y 16**
— anteriores al inicio pedido. Un entrenamiento de la tarde cae en el día UTC
siguiente.

*(Nota de método: el sandbox no sirve para medir esto. Es un **generador**, no
un filtro: devuelve `n-1` registros para cualquier ventana y 0 para una de una
hora que contiene una muestra. Medido ahí, todo parece exclusivo. La primera
versión de este roadmap decía justo eso, y estaba mal.)*

**El arreglo, ya en el código:** pedir dos días de más de cada lado y recortar
por `day` del lado del cliente. Dos, no uno, porque `workout` es exclusiva *y*
desfasada, y las dos cosas se suman; el desfase horario máximo del mundo es de
±14 h y la exclusividad cuesta otro día. Una tabla por colección no servía —
cinco colecciones no tenían datos con qué medirlas, y una tabla que Oura cambie
vuelve a fallar en silencio. Ensanchar y recortar es correcto en los cuatro
casos y lo sigue siendo cuando cambie.

Verificado en las 13 colecciones con datos, a 1, 7 y 30 días: **todas
correctas**. Los dos días descartados se reportan en
`descartados_fuera_de_rango` en vez de callarse.

No lo encontramos solos: `daveremy` publicó la semana pasada
`fix(client): Oura treats end_date as exclusive — single-day queries returned
empty`. Lo del UTC no lo tiene documentado nadie.

### 2. Oura deprecó los Personal Access Tokens en diciembre de 2025

No se pueden crear nuevos; los que ya existían siguen funcionando. Comprobado
por los dos lados: el token de Oscar **responde hoy**, y la página de creación
ahora redirige al nuevo proveedor de identidad (`moi.ouraring.com`) — la
migración que documenta `crcatala` como «Oura migrated to a new identity
provider». Tres proyectos actualizados esta semana ya migraron a OAuth2.

> **Este servidor se instala a prueba de tontos para una sola persona: Oscar.**
> Cualquier otro llega al README, lee «es un token y ya», abre la página de
> Oura, y no encuentra dónde crearlo.

Es la puerta de entrada, y está tapiada para todos menos para quien ya tenía
llave.

### 3. Oura publica un OpenAPI, y trae dos parámetros que no usamos

El `openapi.json` que `spxrogers` mantiene en su repo —«Oura API
Documentation», v2.0, 452 KB, con chequeo de deriva en CI— dice que cada
colección acepta:

```
fields   Comma-separated list of fields to include in the response,
         in addition to the always returned fields.
latest   If True, returns most recent sample.   (heartrate, ring_battery_level)
```

Eso convierte dos features que había que construir en dos parámetros que hay
que pasar. Del mismo spec salen otras tres confirmaciones:

- **Nuestra tabla de 19 colecciones está completa.** 35 rutas bajo
  `/v2/usercollection`; no falta ninguna.
- **El sandbox es oficial**: 34 rutas espejo bajo `/v2/sandbox`.
- Existen **webhooks** (`/v2/webhook/subscription`) y 32 rutas
  `/{document_id}`.

---

## v0.2 — Lo que está mal, y el sandbox · **COMPLETA**

Nada de esto agregó herramientas. Todo corrige o abarata. Los ocho puntos
cerrados, 46 pruebas, ninguna toca la red.

Lo que no estaba en el plan y salió al medirlo: `end_date` no era «exclusivo»
sino inconsistente por colección; `workout` va desfasada a UTC; `latest` y
`fields` los ignora Oura en silencio cuando no aplican; y el sandbox es un
generador, no un filtro, así que no sirve para medir la semántica de la API.
Cuatro fallas de la misma familia — pides una cosa, recibes otra, nada avisa —
que es la misma que la paginación. Resulta que la tesis del repositorio
aplicaba en más lugares de los que decía.

### 1. `end_date` inclusivo, y una prueba por colección — **hecho**

Dos días de más de cada lado, y recorte por `day` del lado del cliente. Dos y
no uno porque las dos fallas se suman: la exclusividad cuesta un día y el
desfase a UTC otro. Correcto tanto si el endpoint es inclusivo como si es
exclusivo, y tanto si el desfase va hacia adelante como hacia atrás — que es lo
que lo mantiene correcto cuando Oura lo cambie.

Verificado colección por colección contra la API **real**, no contra el sandbox:
arreglarlo en `daily_sleep` no lo arreglaba en `workout`, y el sandbox miente
sobre esto.

Y un parámetro de conveniencia, robado a `spxrogers`: **`dia`**, para una sola
fecha. La trampa no vuelve a existir si la ruta común —«¿cómo dormí ayer?»— no
obliga a escribir un rango.

### 2. Modo sandbox — **hecho**

Verificado: `https://api.ouraring.com/v2/sandbox/usercollection/…` **acepta
cualquier cadena como `Authorization`** y devuelve datos sintéticos.

```
$ curl -H "Authorization: Bearer cualquiercosa" ".../sandbox/…/daily_sleep?…"
{"data":[{"id":"daily_sleep-1-2026-8-1","score":73, …
```

Un `OURA_SANDBOX=1` que cambia la base y nada más. Vale por tres cosas a la vez:

- **Instalación a prueba de tontos**: se instala, se prueba, se ve funcionar, y
  *después* se pelea con la autenticación. Hoy el orden es al revés, y ahí se
  pierde a la gente.
- **El directorio de Claude lo pide**: la revisión exige instrucciones de
  cuenta de prueba «lo bastante detalladas para que un revisor llegue de punta
  a punta». Un modo sandbox es esa respuesta en una línea.
- **CI contra la API real** sin depender del token de nadie — la regla de
  AGENTS.md, respetada.

Lo que el sandbox **no** da: `heartrate` devuelve 2 muestras y sin
`next_token`. Sirve para demostrar, no para probar la paginación. Ésa se sigue
probando con la API falsa de `tests/`.

### 3. `fields` y `latest`, pasados a Oura — **hecho**

- `campos: ["bpm"]` → `fields=bpm`. **Recorta del lado de Oura**: ahorra ancho
  de banda además de contexto.
- `ultimo: true` → `latest=true`. Resuelve de raíz «mi frecuencia cardiaca más
  reciente», que antes sólo se podía contestar bajando la ventana entera.

**Y los dos resultaron traer su propia falla silenciosa**, medida el 9-ago:

| Lo que pides | Lo que hace Oura |
|---|---|
| `fields=no_existe` | Devuelve el registro **completo**. La proyección no ocurre |
| `fields=score,no_existe` | Aplica el bueno, tira el malo, no dice nada |
| `latest=true` en `daily_sleep` | **Lo ignora y devuelve la colección entera** |

Ninguna da error. Es la misma familia que no paginar: pides una cosa, recibes
otra, y nada te avisa. Por eso `ultimo` se **rechaza aquí** para las 17
colecciones que no lo respetan —antes de salir a la red— y los campos que no
aparecieron en ninguna respuesta se reportan en `campos_ignorados`.

Un hallazgo que ayudó: **`fields` siempre devuelve `day` e `id`**, así que el
recorte por fecha del punto 1 no se rompe cuando alguien proyecta columnas.

Y una que la API no da y ya está hecha: **`formato: "csv"`**, la misma tabla sin
repetir las claves 37,000 veces. Medido sobre un día real de `heartrate`:
**56% menos caracteres**. El encabezado sale de la unión de todas las claves, no
del primer registro —sacarlo del primero pierde un campo entero en silencio— y
si los registros no traen las mismas claves la respuesta lo dice, porque una
celda vacía puede ser «campo ausente» o «valor nulo».

*(De la misma medición salió el número que le faltaba al README: un día local de
`heartrate` son **1,231 muestras en 2 páginas**. Quien no pagina recibe 1,000 de
1,231 —el 81%— sin un solo aviso.)*

La línea sigue clara: **elegir columnas no es promediar.** Un `resumen=true`
que devuelva medias sigue prohibido.

### 4. Un 429 no se reintenta — **hecho**

Se rendía al primero. En una consulta que encadena hasta 50 peticiones, eso tira
a la basura todo lo ya traído. Ahora reintenta dos veces, honrando `Retry-After`
en sus dos formas (segundos y fecha HTTP), con backoff exponencial cuando no
viene, y un tope de 8 s para que una cabecera generosa no cuelgue la
conversación. **Sólo el 429**: un 401 no mejora esperando.

Y una medición que conviene tener escrita: **Oura no manda ninguna cabecera de
límite de tasa** en las respuestas buenas — ni `X-RateLimit-Remaining` ni
equivalente. Un cliente no puede saber qué tan cerca está del tope; sólo se
entera cuando ya se lo negaron. Por eso reaccionar bien es lo único que queda.

### 5. `truncado` avisa, pero no deja continuar — **hecho**

Hoy, al toparse con el tope de 50 páginas, la respuesta dice «acorta el rango».
Correcto, pero el modelo no puede hacer más que reintentar a ciegas.
`benngermin` devuelve `{truncated, nextToken}` para que quien llama reanude.

Hay que devolver el cursor: `truncado` + `continuar_desde`, y que
`oura_consultar` lo acepte. **No es análisis** — es transporte, y es la
extensión natural del bucle que es el producto.

### 6. Anotaciones de herramienta — **hecho**

Las tres declaran `title`, `read_only_hint`, `destructive_hint` e
`idempotent_hint`. Y `open_world_hint` en `True`, que es la que casi nadie pone:
los datos vienen de un servicio externo y la misma llamada dos veces puede
diferir si el anillo sincronizó en medio. Decir lo contrario invitaría a
memoizar la respuesta.

Hay además una prueba que **lee el código fuente** buscando `POST`, `PUT`,
`DELETE` y `PATCH`. La anotación de sólo lectura es verdad hoy; esa prueba es la
que se entera el día que deje de serlo.

*(De paso: el README dice «cuatro herramientas» y hay tres. Sigue pendiente.)*

### 7. El token, fuera de cualquier `repr` — **hecho**

`_token()` ya no devuelve un `str`: devuelve un `Secreto`, cuyo `__repr__` y
`__str__` dicen `<secreto de 32 caracteres>`. Sacar el valor exige
`.revelar()` — una llamada explícita, visible en el código y grepeable.

No es paranoia teórica: un `~/.pypirc` mal formado ya hizo que el parser
volcara un token completo a un transcript. La lección no fue «ten más cuidado»,
fue que el cuidado no se sostiene a mano.

### 8. Deriva de colecciones, en CI — **hecho, pero no como estaba escrito**

El plan decía «compara `colecciones.py` contra el `openapi.json` de Oura». **No
se puede: Oura no publica su spec en ninguna URL estable.** Cinco rutas
plausibles, las cinco 404. La única copia pública está vendorizada en el
repositorio de `spxrogers`, y colgar nuestro CI del repositorio de un tercero es
cambiar una dependencia por otra peor.

Lo que sí se puede, y ya corre: `herramientas/revisar_deriva.py` pregunta por
las 19 colecciones **contra el sandbox**, que no pide credenciales. Job semanal
y a mano, nunca en push — una prueba que sale a internet no puede decidir si un
PR entra.

Con sus límites dichos en voz alta, que es la mitad del valor:

| Atrapa | No atrapa |
|---|---|
| Una colección renombrada, movida o retirada | Una colección **nueva** |

El sandbox no se puede enumerar, así que descubrir altas sigue siendo trabajo
humano. Decirlo en el propio script vale más que un chequeo que aparente
cubrir algo que no cubre.

---

## v0.3 — OAuth2, la puerta de entrada · **COMPLETA**

Sin esto el servidor no sirve para nadie nuevo. El PAT se queda soportado y sin
ruido: quien ya tiene uno no debería tener que migrar, y `OURA_PAT` /
`OURA_PAT_FILE` siguen ganando si están puestos.

Endpoints: autorización en `cloud.ouraring.com/oauth/authorize`, token en
`api.ouraring.com/oauth/token`, revocación en `/oauth/revoke`. Ocho alcances:
`email`, `personal`, `daily`, `heartrate`, `workout`, `tag`, `session`, `spo2`.

Tres cosas que los demás ya aprendieron a golpes:

- **El refresh token es de un solo uso.** Hay que rotarlo y **persistirlo antes**
  de consumirlo, o una carrera deja la sesión muerta (`crcatala`).
- **El redirect URI necesita la diagonal final.** El portal rechaza
  `…/callback` con `invalid_redirect_uri` y acepta `…/callback/`.
- **`--manual` para máquinas sin navegador**: imprime la URL, el usuario la abre
  donde sea, y pega de regreso la URL del callback fallido.

Y una cuarta, de `davidmosiah`: los alcances que devuelve la pantalla de
consentimiento no son los que uno pidió — el usuario puede conceder menos. Se
guardan los **concedidos**, no los pedidos, y `oura_revisar` reporta las dos
listas. Es la respuesta a la pregunta que más se hace cuando algo sale vacío:
«¿no hay datos, o no di permiso?».

**Lo que quedó, y una decisión que no estaba en el plan.** El flujo vive en
`oura-mcp --autorizar`, en la terminal, **nunca dentro del servidor MCP**: uno
que habla por stdin/stdout no puede abrir un navegador ni pedirle nada a nadie,
y pretender que sí es cómo se cuelga un cliente MCP para siempre. Con
`--manual` para máquinas sin navegador, y `--olvidar` para revocar localmente.

**El `state` se verifica, y no era opcional.** El callback llega a un servidor
HTTP en localhost que atiende lo que le manden. Sin comparar el `state`,
cualquier página abierta en el navegador del usuario puede mandarle un código de
autorización de **otra cuenta** y dejarlo conectado a datos que no son suyos,
sin que nada se vea raro. Se genera con `secrets` y se compara con
`compare_digest`.

**Y el mensaje de «falta token» cambió**, que era lo que sostenía todo el
hallazgo #2 de este roadmap. Antes mandaba a la página de tokens personales —que
desde diciembre de 2025 ya no emite ninguno— y quien llegaba ahí se quedaba
atorado sin saber por qué. Ahora ofrece tres caminos, de menos a más trámite, y
el primero no exige registrarse en nada:

```
  1. OURA_SANDBOX=1 — datos de ejemplo, sin registrarte en nada
  2. oura-mcp --autorizar — OAuth2, una vez, en el navegador
  3. OURA_PAT / OURA_PAT_FILE — sólo si ya tenías uno
```

**Dónde viven los tokens — con una corrección.** El plan decía «llavero del
sistema con caída a archivo `0600`». Al ir a hacerlo: `keyring` **no es una
dependencia de este paquete y no debe serlo**. Aquí está instalado, pero viene
de `twine`, no de `mcp`; un usuario no lo tendría. Y la lista de dependencias
vacía es justo lo que hace viable empaquetar esto como binario para Claude
Desktop, que es el hito v0.4.

Lo implementado: **archivo `0600`, escrito de forma atómica, en directorio
`0700`** — y el llavero **sólo si resulta estar instalado**, con `try: import
keyring`. Quien lo tenga sale ganando; a quien no, no le cuesta nada. El
principio de AGENTS.md se mantiene: el secreto no va en el JSON de configuración
del cliente MCP, y menos uno que rota solo.

**La rotación es la parte peligrosa, y ya está hecha.** El refresh token de Oura
es de un solo uso: cuando se canjea, Oura lo invalida. Entre la respuesta y el
guardado hay una ventana en la que el viejo ya murió y el nuevo no existe en
disco; caerse ahí pierde la sesión. `refrescar()` guarda **antes de devolver**, y
de forma atómica — no se puede hacer mejor, porque Oura no ofrece un canje en
dos fases, pero sí que la ventana dure lo mínimo y que nunca quede un archivo a
medias.

Y una que no estaba prevista: **dos procesos que refrescan a la vez** es un caso
real —dos herramientas MCP llamadas en paralelo— y el que pierde la carrera
recibe un 400 aunque la sesión esté viva. Antes de darla por perdida, se relee
lo guardado.

---

## v0.4 — Instalar sin terminal

La escalera, del escalón más barato al más caro.

### 1. `uvx` documentado — **hecho, con una corrección**

Todos los competidores son TypeScript y se instalan con `npx -y`. El equivalente
en Python es `uvx --from mcp-oura oura-mcp`, y ya está en el README.

**Pero no como ruta por defecto, y ese fue el error de la primera redacción.**
`uvx` requiere tener `uv` instalado. En esta máquina no lo está, que es cómo se
descubrió: un README que abre con «nada que instalar» y da un comando que
responde `command not found` es exactamente lo contrario del objetivo. `pip
install mcp-oura` es la ruta sin prerrequisitos; `uvx` es la mejora para quien
ya tiene `uv`.

De paso, otra que faltaba: **Claude Desktop no hereda el `PATH` de la
terminal**, así que en su JSON hay que poner la ruta completa que da `which
oura-mcp`. Un nombre pelado ahí falla en silencio, y es de los errores más
comunes al configurar un servidor MCP.

### 2. Plugin de Claude Code — **hecho y validado**

`.claude-plugin/plugin.json` y `.claude-plugin/marketplace.json`, los dos pasan
`claude plugin validate --strict` contra el validador real del CLI, no contra un
esquema supuesto.

```bash
claude plugin marketplace add proscar87/oura-mcp
claude plugin install oura@oura-mcp
```

Sin bloque `env`, a propósito: no verifiqué que este esquema interpole variables,
y un plugin que cayera en sandbox sin decirlo mostraría datos sintéticos como si
fueran tuyos. El mensaje de «no hay credenciales» del propio servidor ya ofrece
los tres caminos.

### 3. MCPB — el `.mcpb` de un clic

Un zip con el servidor y un `manifest.json`; se instala con doble clic en
Claude Desktop, sin terminal ni JSON. `user_config` con `"sensitive": true`
genera la UI del campo solo y guarda el valor en el almacén seguro. Es,
literalmente, la definición de «a prueba de tontos».

**El problema es Python.** La documentación de Anthropic es explícita: Node.js
«ships with Claude Desktop on macOS and Windows, so users need no separate
runtime». Python no.

**Se midió, en vez de suponerlo.** Binario construido con PyInstaller el
9-ago-2026, macOS arm64:

| Variante | Tamaño | Primer arranque | Siguientes |
|---|---|---|---|
| `--onefile` | 22 MB | 7.6 s | **6.5–7.6 s, en cada corrida** |
| `--onedir` | 45 MB | 7.8 s | **0.41 s** |
| `python -m oura_mcp` | — | 0.40 s | 0.40 s |

Dos cosas que cambian la decisión:

1. **`--onefile` queda descartado.** Descomprime los 22 MB en un temporal cada
   vez que arranca. Un servidor MCP que tarda siete segundos en responder al
   *handshake* se ve como colgado, en cada sesión.
2. **`--onedir` sí sirve** — 0.41 s tras la primera vez, igual que Python. Los
   7.8 s iniciales son Gatekeeper verificando un binario **firmado sólo
   ad-hoc** (`flags=0x2(adhoc)`, verificado con `codesign`).

Y ahí está el costo que no se ve en la tabla: distribuir eso en serio pide
**Developer ID y notarización de Apple**, más *runners* de macOS y Windows en
CI, y ~45 MB por plataforma. Todo para que Claude Desktop arranque un intérprete
de Python que sólo corre nuestras 1,281 líneas.

| | Qué implica | Veredicto |
|---|---|---|
| `type: "python"` | Depende del Python del usuario | No cumple el objetivo |
| `type: "binary"` (`--onedir`) | 45 MB × 3 plataformas, notarización de Apple, CI en macOS y Windows | Viable, pero el precio es alto |
| Portar a TypeScript | Reescribir 1,281 líneas de fuente y 936 de pruebas | Node ya viene incluido: sin binario, sin firma, sin CI por plataforma |

**La medición invirtió la recomendación.** Antes decía «binario, porque conserva
el trabajo hecho». Con los números en la mano, el binario cuesta notarización +
tres compilaciones + 135 MB de artefactos, y todo eso *para el hito cuyo punto
es que instalar sea trivial*. Si el `.mcpb` se quiere de verdad, **TypeScript**.

**Pero hay una tercera vía, y probablemente es la correcta:** el plugin de
Claude Code (§2, ya hecho y validado) da instalación de un comando a los
usuarios de Claude Code sin nada de esto. La pregunta que decide no es técnica
sino de alcance — *¿hace falta Claude **Desktop**, o basta Claude **Code**?* Si
basta, v0.4 ya está completa y el `.mcpb` no se construye.

---

## v0.5 — Listado en Claude

Hay dos puertas y no son intercambiables.

### Puerta A — Extensión de escritorio (MCPB) · **la viable**

Formulario aparte, en `clau.de/desktop-extention-submission`. **No requiere
organización Team ni Enterprise.**

- [ ] Un `.mcpb` que funcione (v0.4)
- [ ] Anotaciones en las tres herramientas (v0.2)
- [ ] **Política de privacidad** — sección «Privacy Policy» en el README,
      arreglo `privacy_policies` en el `manifest.json`, URLs HTTPS. Debe cubrir
      recolección, uso, almacenamiento, terceros, retención y contacto.
      *«Missing or incomplete privacy policies result in immediate rejection.»*
- [ ] Ícono PNG 512×512
- [ ] Documentación de instalación y uso
- [ ] Ejemplos que ejerciten cada herramienta (el sandbox los da gratis)

La política de privacidad aquí es fácil y además es un argumento: el servidor no
guarda nada, no manda nada a ningún lado que no sea Oura, y el token no sale de
la máquina. Se escribe en veinte líneas y todas son ciertas.

### Puerta B — Conector remoto · **cerrada por ahora**

El portal vive en los ajustes de administración de Claude.ai y **exige una
organización Team o Enterprise**; en planes individuales no aparece. Además
pide servidor HTTPS hospedado (streamable HTTP o SSE), OAuth 2.0, y declarar
que maneja datos personales de salud — que los maneja.

Es el camino a Claude web y móvil, y hospedar datos de salud de terceros es un
compromiso serio, no un fin de semana. Va como opción consciente, no como
pendiente.

---

## La competencia, al 9 de agosto de 2026

431 repositorios buscando «oura ring». La mayoría es ruido —dos repos `.github`
de SEO, un tamagotchi, tests de Adobe— pero abajo del ruido pasó algo que hay
que decir claro.

### Uno por uno, y qué se le roba a cada quién

**[spxrogers/oura-toolkit](https://github.com/spxrogers/oura-toolkit)** · Rust ·
1★ · el mejor ingenierilmente, y el más parecido a ti en criterio.

CLI + cinco SDKs generados + MCP + plugin, todo desde un `openapi.json` con
`spec-drift.yml` en CI. Publica a crates.io **y** a npm **por OIDC con Trusted
Publishing y provenance** — tu postura de «ningún secreto que rotar», aplicada a
dos registros más. Sus commits son una lista de compras:

- `Rate-limit handling: honor 429 + Retry-After, one bounded retry, typed error`
- `Headless auth: --no-browser login, OURA_ACCESS_TOKEN, OURA_API_BASE_URL`
- `MCP + CLI: single-day date convenience parameter`
- `Auth: redact TokenResponse Debug`

**Robar:** las cuatro. Ya están repartidas en v0.2 y v0.3.

---

**[davidmosiah/oura-mcp](https://github.com/davidmosiah/oura-mcp)** · TS ·
0.4.11 · la superficie MCP más completa del conjunto.

Resources (`oura://capabilities`, `oura://latest/readiness`), prompts,
`OURA_CACHE=sqlite`, tres modos de privacidad, `oura_demo` con datos sintéticos
etiquetados `is_demo: true`, `smithery.yaml`, `glama.json`, `llms.txt`. Parte de
un **registro de nueve conectores** de salud con instalador único.

Sus fixes son una confesión útil: `stop all_pages truncating data` (tenían
nuestro bug), `latest/readiness is the newest record by construction`, `doctor
accepts full Oura consent scopes`. Y documenta la trampa que nadie más vio:
**Oura sirve de más viejo a más nuevo y no acepta orden**, así que `limit: 1`
devuelve el registro **más viejo**.

**Robar:** los tres archivos de descubrimiento, los resources, el modo demo.
**No robar:** el `"recommendation": "green light for moderate-to-high
intensity"` — plantilla sobre un puntaje, presentada como consejo. Es el número
sin su método.

---

**[benngermin/oura-mcp](https://github.com/benngermin/oura-mcp)** · TS · 12
herramientas · stdio + HTTP multi-tenant.

El único que compite en lo que creíamos nuestro: **pagina bien y devuelve cursor
reanudable** (`{records, truncated, nextToken}` con `maxRecords`). Se anuncia
«first-party» pero es de su propio LifeOS, no de Oura — 3 commits, 0 estrellas.

**Robar:** el cursor reanudable.

---

**[crcatala/oura-cli](https://github.com/crcatala/oura-cli)** · TS · CLI, no MCP
· la mejor documentación de rarezas de la API.

Llavero del SO con caída a 0600, `--sandbox`, `oura doctor`, JSON automático al
hacer pipe, códigos de salida disciplinados (0/1/2/130), live tests opt-in y
read-only disparados por un comentario `/run-live-tests`. Su sección «Notes &
quirks» son tres párrafos que valen semanas.

**Robar:** las tres rarezas, y el patrón de live tests que nunca bloquean un PR.

---

**[daveremy/oura-mcp](https://github.com/daveremy/oura-mcp)** · TS · 4★ · el más
instalado de los MCP.

`claude plugin marketplace add`, `npx -y`, y un skill `/oura` que «orquesta las
herramientas MCP en respuestas conversacionales en vez de JSON crudo» — que es
exactamente la separación que este roadmap propone. Su commit de la semana
pasada es nuestro bug confirmado.

**Robar:** la estructura de plugin, y el skill como capa de interpretación
separada del servidor.

---

**[echocharlie/oura-mcp-server](https://github.com/echocharlie/oura-mcp-server)**
· Python · FastMCP · read-only.

Ocho herramientas, **todas devuelven CSV compacto con las unidades en el nombre
de la columna**, y está diseñado para *componerse con un conector de Strava*:
todo llaveado por fecha ISO para que el modelo pueda unir carga de entrenamiento
contra recuperación en un solo paso de razonamiento. Sigue usando PAT — otra
confirmación de que los tokens viejos siguen vivos.

**Robar:** el CSV con unidades, y sobre todo **la composición por fecha**.

---

**El resto, en una línea cada uno:**

| | |
|---|---|
| [Th0rgal/open_oura](https://github.com/Th0rgal/open_oura) · Rust · **475★** | BLE por ingeniería inversa: ni toca la nube. El centro de gravedad del ecosistema. **Sin licencia** — no se puede reutilizar nada |
| [louispires/…Home-Assistant](https://github.com/louispires/Oura-Home-Assistant-Integration) · 58★ | OAuth2. La migración es general, no una moda de los MCP |
| [entorb/analyze-oura](https://github.com/entorb/analyze-oura) · 10★ · desde 2022 | El más viejo y sigue vivo. Streamlit + pandas: análisis, y honesto sobre serlo |
| [kesslerio/oura-analytics-openclaw-skill](https://github.com/kesslerio/oura-analytics-openclaw-skill) · 6★ | El form factor «skill», no servidor. Hay demanda de esa capa |
| [legnoh/oura-exporter](https://github.com/legnoh/oura-exporter) · 6★ · desde 2023 | Prometheus. Otro consumidor de los mismos datos crudos |
| [narwhaldc/TA-oura](https://github.com/narwhaldc/TA-oura) | Normaliza Oura a un modelo canónico de wearables. La idea de esquema común, en Splunk |
| [Schimmilab/oura-mcp-server](https://github.com/Schimmilab/oura-mcp-server) | «intelligent analysis and recovery insights». 0★ desde dic-2025 |
| `oura-ring/.github`, `oura-portable-charger/.github` | SEO puro. Ruido |

### Lo que esto significa

**La paginación ya no es un diferenciador.** AGENTS.md dice que «de los siete
servidores MCP de Oura, el más completo no pagina». Era cierto y hoy no lo es:
`benngermin` pagina con cursor reanudable, un escalón por encima de nosotros.
Esa línea del README y de AGENTS.md hay que actualizarla antes de que alguien la
verifique.

Lo que sí sigue siendo nuestro, y conviene defender:

- **Tres herramientas, no doce ni diecinueve.** Todos los demás están en 8–12.
- **No analiza, a propósito, y lo argumenta.** Es la única postura editorial del
  conjunto.
- **Cero dependencias** fuera del SDK de MCP. Es lo que hace viable el binario.
- **Grita cuando entrega de menos.** Nadie más tiene un `truncado` con esa
  intención — y después de v0.2, con cursor para continuar.

El lugar natural del análisis es un **skill de Claude Code** —como el de
`daveremy`— que cargue el método y lo cite, mientras el servidor sigue
entregando el dato. Así «más funciones» y «no analiza» dejan de estar en
conflicto: se separan en dos artefactos, cada uno honesto sobre lo que hace.

---

## Lo que NO va en el roadmap

Sostenido de AGENTS.md, y ahora con más razón porque todos los competidores
hacen lo contrario:

- Herramientas de análisis, correlaciones, detección de anomalías, comparación
  de periodos.
- Una herramienta por colección.
- **Webhooks.** Existen en el spec, pero exigen un endpoint público y rompen el
  modelo local. Un servidor que corre en tu máquina no puede recibir un POST de
  Oura sin dejar de ser local.
- Un token de PyPI en `secrets` — las dos publicaciones van por OIDC.
- Pruebas que salgan a internet en el CI obligatorio. Sandbox y deriva del spec
  entran como trabajo *opcional*, nunca como requisito para que pase un PR.

### Con condiciones: caché

Los datos históricos de Oura no cambian; volver a pedir el mismo mes de
`heartrate` tira 37,000 registros de red a la basura. `davidmosiah` usa
`OURA_CACHE=sqlite`, opcional. Aquí entra sólo si no traiciona dos cosas: cero
dependencias (sqlite es biblioteca estándar, así que se puede) y **que nunca
sirva un dato viejo sin decirlo**. Un caché que responde en silencio con lo de
ayer es el mismo pecado que no paginar. Si se hace, la respuesta lleva
`de_cache` y la fecha en que se trajo.

---

## Una nota de estrategia, fuera del código

`davidmosiah` no publicó un conector: publicó **nueve** —Oura, WHOOP, Garmin,
Strava, Fitbit, Withings, Apple Health, Polar, nutrición— bajo un registro con
su propio estándar de calidad, más un instalador que los configura todos de un
comando.

Vale la pena mirarlo porque **ya tienes la mitad de esa constelación**:
`oura-mcp`, un MCP de Withings, `cotejo` para biomarcadores de sangre, y
`panel-salud` como el lugar donde todo se junta. La diferencia es que los suyos
comparten instalación, documentación y una postura declarada; los tuyos son
cuatro repositorios sueltos que resuelven el mismo problema con el mismo
criterio.

Y hay algo que ninguno de los nueve tiene: **una postura sobre el método**. Los
suyos prometen «insights» y consejos generados por plantilla a partir de un
puntaje, sin decir cuánto oscila solo ese puntaje. Un registro de conectores que
entregan el dato crudo y mandan el análisis a donde se pueda citar el método
sería una respuesta directa, y de las pocas defendibles.

El puente técnico ya lo señaló `echocharlie`: **componer por fecha**. Que
`oura-mcp` y el MCP de Withings hablen `AAAA-MM-DD` con el mismo esquema de
llave es lo que deja al modelo cruzarlos sin que ninguno de los dos analice
nada.

No es trabajo de v0.2. Pero si algún día se agrupan, el argumento ya está
escrito.

---

## Orden de ejecución

1. **v0.2** — `end_date` primero (bug confirmado, en silencio, en la ruta más
   común), luego sandbox, `fields`/`latest`, 429, cursor, anotaciones,
   redacción del token, deriva del spec.
2. **v0.3** — OAuth2. Sin esto no hay usuarios nuevos.
3. **v0.4** — `uvx` en el README hoy mismo; plugin; y decidir binario vs. port.
4. **v0.5** — enviar el MCPB al directorio.

Y aparte, gratis y para ayer — cuatro archivos y dos PRs: `smithery.yaml` y
`glama.json` en la raíz, `llms.txt` con la lista de herramientas y variables de
entorno, y PRs a `awesome-mcp-servers` y a mcp.so.
