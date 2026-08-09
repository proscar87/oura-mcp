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

## v0.2 — Lo que está mal, y el sandbox

Nada de esto agrega herramientas. Todo corrige o abarata.

### 1. `end_date` inclusivo, y una prueba por colección

El arreglo tiene dos mitades y la segunda es la que importa:

1. Sumar un día a `end_date` antes de la petición, y filtrar del lado del
   cliente los registros cuyo `day` se pase de `fin`. El filtro no es
   redundante: cubre el caso de que algún endpoint sí sea inclusivo, que es lo
   que `crcatala` reporta como «inconsistente por endpoint».
2. **Una prueba por colección contra el sandbox.** Arreglarlo en `daily_sleep`
   no lo arregla en `workout`.

Y un parámetro de conveniencia, robado a `spxrogers`: **`dia`**, para una sola
fecha. La trampa no vuelve a existir si la ruta común no obliga a escribir un
rango.

### 2. Modo sandbox

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

### 3. `fields` y `latest`, pasados a Oura

- `campos: ["bpm"]` → `fields=bpm`. **Recorta del lado de Oura**: ahorra ancho
  de banda además de contexto. Muy superior a filtrar después de bajar 37,000
  registros.
- `ultimo: true` → `latest=true`. Resuelve de raíz «mi frecuencia cardiaca más
  reciente», que hoy sólo se puede contestar bajando la ventana entera.

Y una que la API no da y hay que hacer: **`formato: "csv"`**, la misma tabla sin
repetir las claves 37,000 veces. `echocharlie` ya entrega todo en CSV «con las
unidades en el nombre de la columna», y es la decisión correcta para un
servidor que le habla a un modelo.

La línea sigue clara: **elegir columnas no es promediar.** Un `resumen=true`
que devuelva medias sigue prohibido.

### 4. Un 429 no se reintenta

`_pedir()` traduce el 429 a un mensaje amable y se rinde. En una consulta de un
mes de `heartrate` —hasta 50 peticiones seguidas— rendirse a la mitad tira a la
basura las 30 páginas ya traídas. Falta backoff honrando `Retry-After`, con un
reintento acotado y un error tipado. `spxrogers` ya lo tiene resuelto así.

### 5. `truncado` avisa, pero no deja continuar

Hoy, al toparse con el tope de 50 páginas, la respuesta dice «acorta el rango».
Correcto, pero el modelo no puede hacer más que reintentar a ciegas.
`benngermin` devuelve `{truncated, nextToken}` para que quien llama reanude.

Hay que devolver el cursor: `truncado` + `continuar_desde`, y que
`oura_consultar` lo acepte. **No es análisis** — es transporte, y es la
extensión natural del bucle que es el producto.

### 6. Anotaciones de herramienta

El directorio de Claude las exige: `title` y `readOnlyHint` / `destructiveHint`
en cada herramienta. Aquí **las tres son de sólo lectura**, así que es una tarde
y además es verdad: no hay una sola escritura en todo el código. Conviene
hacerlo aunque nunca se mandara al directorio — es la señal que evita que un
cliente MCP pida confirmación en cada llamada.

*(De paso: el README dice «cuatro herramientas» y hay tres.)*

### 7. El token, fuera de cualquier `repr`

`spxrogers`: `Auth: redact TokenResponse Debug`. Que el token no pueda salir en
una traza ni en un volcado de excepción. Es la preocupación de Garita resuelta
en el tipo, y ya costó un token una vez —el `~/.pypirc` mal formado del 9-ago.

### 8. Deriva del spec, en CI

Un job **opcional** que compare `colecciones.py` contra el `openapi.json` de
Oura y falle si aparece una colección nueva o cambia una forma de parámetros.
Es la versión automática de la línea de AGENTS.md: «si Oura agrega una
colección, se toca aquí y nada más». Opcional, nunca bloqueante — el CI
obligatorio sigue sin tocar la red.

---

## v0.3 — OAuth2, la puerta de entrada

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

Y una cuarta, de `davidmosiah`: los alcances que devuelve la pantalla de consentimiento
no se llaman igual que los que uno pidió (`fix(#8): doctor accepts full Oura
consent scopes`). El autodiagnóstico tiene que aceptar ambas formas.

**Dónde viven los tokens.** El principio de AGENTS.md —el secreto no va en el
JSON de configuración del cliente MCP— se mantiene y se refuerza: llavero del
sistema con caída a archivo `0600`. Un refresh token que rota no puede vivir en
un archivo que el usuario editó a mano.

---

## v0.4 — Instalar sin terminal

La escalera, del escalón más barato al más caro.

### 1. `uvx` como forma documentada por defecto — hoy mismo

Todos los competidores son TypeScript y se instalan con `npx -y`. El
equivalente en Python existe y no está en el README:

```bash
claude mcp add -s user oura --env OURA_PAT_FILE=$HOME/.oura_pat \
  -- uvx --from mcp-oura oura-mcp
```

Nada que instalar, nada que mantener actualizado. El `--from` es obligatorio
porque la distribución se llama `mcp-oura` y el ejecutable `oura-mcp`.

### 2. Plugin de Claude Code

`daveremy` publica el suyo con `claude plugin marketplace add` +
`claude plugin install`. Es un `.claude-plugin/marketplace.json` y un
repositorio. Barato, y pone el servidor donde la gente ya busca.

### 3. MCPB — el `.mcpb` de un clic

Un zip con el servidor y un `manifest.json`; se instala con doble clic en
Claude Desktop, sin terminal ni JSON. `user_config` con `"sensitive": true`
genera la UI del campo solo y guarda el valor en el almacén seguro. Es,
literalmente, la definición de «a prueba de tontos».

**El problema es Python.** La documentación de Anthropic es explícita: Node.js
«ships with Claude Desktop on macOS and Windows, so users need no separate
runtime». Python no. El spec admite `type: "python"`, pero eso apunta al
`python` del sistema — que es justo lo que estamos tratando de eliminar.

| | Qué implica | Veredicto |
|---|---|---|
| `type: "python"` | Depende del Python del usuario | No cumple el objetivo |
| `type: "binary"` | PyInstaller, un binario por plataforma (darwin arm64/x64, win32), CI que los construya | **Recomendada.** Sin dependencias fuera del SDK, congela limpio |
| Portar a TypeScript | ~320 líneas. Un día. Node incluido, cero fricción | La opción honesta si el `.mcpb` es la prioridad real |

La recomendación es el binario: conserva el trabajo hecho y el CI ya existe.
Pero conviene decirlo sin adorno — **si el objetivo final es el listado en
Claude, TypeScript es el camino que el propio Anthropic recomienda.**

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
