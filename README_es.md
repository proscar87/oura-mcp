# oura-mcp

[![PyPI](https://img.shields.io/pypi/v/mcp-oura?label=PyPI)](https://pypi.org/project/mcp-oura/)
[![Glama score](https://glama.ai/mcp/servers/proscar87/oura-mcp/badges/score.svg)](https://glama.ai/mcp/servers/proscar87/oura-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[English](https://github.com/proscar87/oura-mcp/blob/main/README.md) | [简体中文](https://github.com/proscar87/oura-mcp/blob/main/README_zh_CN.md) | [한국어](https://github.com/proscar87/oura-mcp/blob/main/README_ko.md) | Español

<!-- La insignia de Glama es en vivo, no una captura: muestra la puntuación que
     ese índice independiente le da hoy a este servidor. Una insignia que solo
     puede subir es decoración; una que puede bajar es evidencia. -->

La API v2 de [Oura](https://ouraring.com) como servidor
[MCP](https://modelcontextprotocol.io). Las 19 colecciones, cinco herramientas,
ninguna dependencia más allá del SDK de MCP.

### Un día local de frecuencia cardiaca son 1,231 muestras repartidas en 2 páginas

Un cliente que no sigue el `next_token` de Oura devuelve **1,000 de ellas: el
81%, con aspecto de estar completo y sin nada que indique lo contrario.** Medido
contra la API real el 9 de agosto de 2026: una persona, un anillo, 24 horas.

**La prueba que conviene aplicarle a cualquier servidor MCP de Oura, este
incluido:** ¿acepta `next_token` —o un `cursor`, o un `limit`— como parámetro de
la herramienta? Si lo acepta, la paginación es tarea del modelo, y un modelo que
se olvida de volver a preguntar produce una respuesta segura de sí misma sobre
datos parciales. Este servidor pagina hasta agotar el rango antes de devolver
nada, y te dice cuántas páginas hicieron falta.

Esa es una de las **cuatro** formas en que Oura entrega de menos sin decirlo.
Las cuatro están medidas más abajo y las cuatro están corregidas aquí.

### Instalar

Descarga **`oura-mcp.mcpb`** de la
[última versión publicada](https://github.com/proscar87/oura-mcp/releases/latest)
y haz doble clic. Claude Desktop se encarga del resto: sin terminal, sin Python,
sin Node. Funciona de entrada con los datos de muestra oficiales de Oura, y cada
respuesta de muestra lo declara, así que nada puede hacerse pasar por tu propio
sueño.

¿Prefieres la línea de comandos? `uvx --from mcp-oura oura-mcp`.

¿Prefieres no tener Python en tu máquina?

```
docker run -i --rm -e OURA_SANDBOX=1 ghcr.io/proscar87/oura-mcp
```

`-i` no es opcional: un servidor MCP habla por stdin y stdout, no por un puerto.
Sin esa opción el contenedor no tiene stdin, el saludo inicial nunca llega y el
cliente informa de un servidor que no aparece.

¿Usas **claude.ai** o **ChatGPT** en el navegador? Esos se conectan por URL, así
que el servidor tiene que vivir en algún lugar público: despliégalo como Worker
en tu propia cuenta de Cloudflare — gratis, unos diez minutos, solo tuyo. Consulta
[Remoto: claude.ai y ChatGPT](#remoto-claudeai-y-chatgpt).

---

## El problema, medido

Oura no devuelve errores cuando no puede darte lo que pediste. Devuelve otra
cosa, con la forma de una respuesta correcta. Estas son las cuatro que
encontramos midiendo contra la API real el 9 de agosto de 2026:

### 1. Sáltate la paginación y te llevas una fracción

```json
{ "data": [ ... ], "next_token": "eyJ0eXAiOi..." }
```

Si vuelve un `next_token` y no lo sigues, recibes la primera página y **nada te
avisa**. Un día local de `heartrate` —una persona, un anillo, 24 horas— son
**1,231 muestras repartidas en 2 páginas**. Un cliente que no pagina obtiene
1,000 de 1,231: el 81%, con aspecto de estar completo. Un mes son ~37,000.

### 2. Pedir un solo día devolvía cero registros

`end_date` **no se comporta igual en todas las colecciones**:

| Excluyen el último día pedido | Lo incluyen |
|---|---|
| `daily_activity`, `sleep`, `workout` | `daily_sleep`, `daily_readiness`, `daily_stress`, `daily_spo2`, `daily_resilience`, `daily_cardiovascular_age`, `sleep_time` |

Y encima, **`workout` filtra por fecha UTC mientras informa el `day` en hora
local**: en `-06:00`, pedir del 16 al 18 de julio devolvió registros del 15 y del
16, *antes* del inicio solicitado.

Aquí el rango es inclusivo por ambos extremos, siempre. Se piden dos días de más
a cada lado y luego se recortan, lo cual es correcto se comporte como se comporte
cada colección, y sigue siendo correcto cuando Oura lo cambie.

### 3. `latest=true` se ignora donde no aplica

Solo `heartrate` y `ring_battery_level` lo respetan. En las otras diecisiete Oura
no da error: **devuelve la colección entera**. Pides el último registro, recibes
diez y crees que es uno. Aquí se rechaza antes de que salga la petición.

### 4. Un campo que no existe se ignora en silencio

`fields=does_not_exist` devuelve el registro **completo** —la proyección no
ocurre nunca— y `fields=score,does_not_exist` aplica el bueno y descarta el malo
sin decir una palabra. Aquí, los campos que no aparecieron nunca se informan en
`ignored_fields`.

**El patrón siempre es el mismo:** pides una cosa, recibes otra y nada te avisa.
Por eso este paquete prefiere gritar antes que entregar de menos en silencio.

## Instalación

### Pruébalo sin credenciales

```bash
pip install mcp-oura
OURA_SANDBOX=1 oura-mcp --check
```

El entorno de pruebas es oficial —está en la especificación OpenAPI de Oura, con
34 rutas espejo— y sirve datos sintéticos sin autenticación. Ahí funcionan 18 de
las 19 colecciones: `personal_info` no, lo cual tiene sentido, porque es la que
devuelve correo, edad, peso y estatura.

Este es el orden correcto: primero ves funcionar el servidor y aprendes la forma
de los datos, y después vas por las credenciales.

### Con tus propios datos

**Oura dejó de emitir Personal Access Tokens en diciembre de 2025.** Los que ya
existían siguen funcionando; no se pueden crear nuevos. Así que hay dos caminos:

**a) OAuth2, el que funciona hoy.** Registra una aplicación en
[cloud.ouraring.com/oauth/applications](https://cloud.ouraring.com/oauth/applications)
con el redirect `http://localhost:9876/callback/`: **la barra final es
obligatoria**, el portal rechaza la otra forma con `invalid_redirect_uri`.

> **Si en cambio te registraste en `developer.ouraring.com`**, tu aplicación
> pertenece al portal más nuevo de Oura, cuyo endpoint de tokens es otro. El
> endpoint antiguo rechaza esas aplicaciones en **cada** refresco, de modo que el
> registro funciona exactamente una vez, hasta que caduca el primer token de
> acceso, y a partir de ahí falla para siempre sin que nada explique por qué.
> Este servidor prueba el endpoint antiguo y cae al nuevo automáticamente; no hay
> nada que configurar en ninguno de los dos casos.


```bash
export OURA_CLIENT_ID="…"
export OURA_CLIENT_SECRET="…"
oura-mcp --authorize             # opens the browser, waits for the callback
oura-mcp --authorize --manual    # headless machines: you paste the URL back
```

El token se guarda en `~/.config/oura-mcp/credenciales.json` con modo 600 —o en
el llavero del sistema si resulta que tienes `keyring` instalado, que no es una
dependencia de este paquete— y se refresca solo. `oura-mcp --forget` lo borra.

**b) Un token personal, si ya tenías uno.**

```bash
export OURA_PAT="your-token"
oura-mcp --check
```

`--check` es el autodiagnóstico: informa qué credencial estás usando, qué scopes
se concedieron y cuánto le queda al acceso, **sin devolver el token ni un solo
valor de salud**. Informa la longitud del token, nunca el token. Los mensajes de
error se copian y se pegan en chats y en issues; no tienen por qué llevar nada
más.

### Conectarlo a Claude Code

Con el paquete instalado (`pip install mcp-oura`):

```bash
claude mcp add -s user oura --env OURA_SANDBOX=1 -- oura-mcp
```

Quita `OURA_SANDBOX` en cuanto hayas ejecutado `oura-mcp --authorize`.

**Si usas [uv](https://docs.astral.sh/uv/)**, no hace falta instalar nada de
forma permanente:

```bash
claude mcp add -s user oura --env OURA_SANDBOX=1 -- uvx --from mcp-oura oura-mcp
```

El `--from` es obligatorio porque la distribución se llama `mcp-oura` y el
ejecutable `oura-mcp`. *(Esto requiere `uv`; sin él el comando de arriba falla
con «command not found», y `pip install` es el camino a tomar.)*

Como plugin de Claude Code:

```bash
claude plugin marketplace add proscar87/oura-mcp
claude plugin install oura@oura-mcp
```

### Conectarlo a Claude Desktop

**Un clic:** descarga `oura-mcp.mcpb` de la
[página de releases](https://github.com/proscar87/oura-mcp/releases) y haz doble
clic. Claude Desktop lo instala: sin terminal, sin JSON, sin Python. Viene con
los datos de muestra activados, así que funciona antes de que tengas ninguna
credencial.

Cuando quieras tus propios datos, basta con que le pidas algo: abre la página de
autorización de Oura a través de Claude, espera el callback y reintenta lo que
pediste. Sin terminal. Eso funciona porque MCP tiene un modo pensado justo para
esto —la elicitación de URL— y es el cliente quien abre.

Lo único que Oura sigue exigiendo es que toda aplicación esté registrada, así que
necesitas un client ID y un secret de
[cloud.ouraring.com/oauth/applications](https://cloud.ouraring.com/oauth/applications)
una sola vez. Esa es una regla de Oura, no de este servidor.
`oura-mcp --authorize` sigue ahí para quien use la terminal y para los clientes
que no pueden mostrar una URL.

**O a mano,** en `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "oura": {
      "command": "/full/path/to/oura-mcp",
      "env": { "OURA_SANDBOX": "1" }
    }
  }
}
```

`which oura-mcp` te da la ruta completa. Claude Desktop no hereda el `PATH` de tu
terminal, así que poner ahí solo el nombre falla en silencio: uno de los errores
más comunes al configurar un servidor MCP.

### Remoto: claude.ai y ChatGPT

claude.ai llega a un conector desde la nube de Anthropic y ChatGPT desde la de
OpenAI, no desde tu computadora — así que un servidor en tu máquina es invisible
para ambos. [`ts/worker`](ts/worker/README.md) es el mismo servidor como un
Worker de Cloudflare que **tú despliegas en tu propia cuenta, solo para tu propia
cuenta de Oura**. Nadie corre una instancia compartida, así que tus tokens y tus
datos no pasan por nadie más.

Agrega tres cosas que el servidor local no necesita: su propia página de
consentimiento, que muestra qué app está pidiendo acceso y adónde irá el
resultado; una verificación, después del login de Oura, de que la cuenta es la
que configuraste — a cualquier otra se le rechaza, y sin dueño configurado no
entra nadie; y un único lugar donde se renueva el refresh token de un solo uso de
Oura, una solicitud a la vez.

El despliegue, paso a paso, y exactamente qué se ha verificado y qué no:
[ts/worker/README.md](ts/worker/README.md).

## Las herramientas

| | |
|---|---|
| `oura_collections` | Las 19, qué lleva cada una y qué parámetros acepta |
| `oura_query` | Una colección entera sobre un rango, paginando hasta el final |
| `oura_today` | El sueño de anoche y la preparación de hoy, con los días previos |
| `oura_compare` | Si dos periodos difieren más que el ruido propio de la métrica |
| `oura_check` | Autodiagnóstico que no expone nada |

**Cinco, no diecinueve.** Un servidor con una herramienta por colección obliga al
modelo a elegir entre 19 nombres parecidos antes de saber qué contiene ninguno.
Aquí la colección es un parámetro y el catálogo se consulta cuando hace falta.

Las cinco se declaran de solo lectura, y eso no es una promesa: no hay ningún
`POST`, `PUT` ni `DELETE` en todo el paquete, y hay un test que lee el código
fuente para que siga siendo así.

`oura_today` es la única que existe por comodidad y no por corrección:
«¿qué tal dormí?» necesita los dos registros de hoy más suficiente historia para
saber si son inusuales, lo que antes eran cuatro viajes de ida y vuelta y cuatro
oportunidades de detenerse antes de tiempo. **No calcula nada**: ni promedios,
ni diferencias, ni «tu HRV subió 12%». Los días vuelven en crudo y la
comparación ocurre donde se puede citar el método. A lo largo de nueve años de
datos reales, tres de cada cuatro cambios entre mediciones consecutivas caen
dentro de la oscilación normal de la propia métrica, así que un porcentaje sin
ese contexto fabrica una señal en vez de informar de una. Su único parámetro es
`days`, de 1 a 30, con 7 por defecto.

### `oura_compare`: el único cálculo, con su método

«¿Subió mi HRV desde que dejé de tomar?» es la pregunta que la gente trae de
verdad, y entregar dos promedios la contesta mal: las métricas diarias oscilan
solas, y una buena noche suele venir después de otra buena noche, así que una
comparación de libro de texto **llama cambio al ruido ordinario como una de cada
tres veces** (medido: 34–38% con la autocorrelación que suelen tener estas
métricas).

`oura_compare` recibe una `metric` —`collection.field`, como
`daily_readiness.score`, `sleep.average_hrv` o `daily_activity.steps`— y dos
periodos, `a_start`/`a_end` y `b_start`/`b_end`. Responde con los dos promedios,
la diferencia y la **banda en la que esta métrica se mueve sola en periodos de
ese largo**, medida con **tus propios 120 días anteriores** y corregida por esa
dependencia de un día al siguiente. Luego, uno de tres veredictos:

- `outside_noise`: la diferencia es mayor que la banda. El nivel es distinto;
  no por qué, ni que vaya a durar.
- `within_noise`: no lo es. **Esto no es «no hubo cambio»**: la banda también es
  la diferencia más chica que esos días podían detectar, y la respuesta lo dice.
- `cannot_tell`: menos de 7 días con valor en un periodo, o menos de 60 días de
  historia para medir la banda, o una métrica que nunca varió (como pasa con los
  datos de muestra de Oura). No se adivina ninguna banda.

El método se eligió por simulación, no antes de ella: con la banda estimada a
partir de tu historia y un valor crítico de t, el ruido se llama cambio **como
mucho una vez de cada veinte, más o menos**, en todas las autocorrelaciones
probadas, y la suite de tests lo mantiene ahí. Hoy queda fuera, porque todavía
se está acumulando. `sleep` usa el sueño principal más largo de cada día, y la
respuesta dice esa regla. Hacer muchas comparaciones y quedarte con la que cruza
encuentra un cruce por azar, y la respuesta también lo dice.

### Parámetros de `oura_query`

| | |
|---|---|
| `collection` | Cuál de las 19. `oura_collections` las lista |
| `day` | Un solo día. Atajo de `start=end=day` |
| `start`, `end` | El rango, **inclusivo por ambos extremos** |
| `fields` | Solo estos campos. Oura recorta de su lado, así que baja menos |
| `latest` | El registro más reciente. Solo `heartrate` y `ring_battery_level` |
| `format` | `json` o `csv`. El ahorro varía por colección: 55% en `heartrate`, 10% en `daily_sleep` |

Y lo que la respuesta te dice cuando algo no salió limpio:
`truncated` con `continue_from` nombrando el último día alcanzado,
`pagination_cycle` si Oura repite un token, `ignored_fields`,
`discarded_out_of_range`, `uneven_columns`, `empty` cuando una consulta vuelve
vacía y `large_response` cuando lo devuelto pesa lo suficiente como para
importar.

Otras cuatro cuentan que pasó algo de lo que, si no, nunca te enterarías:

- **`synthetic`**: estos son los datos de muestra de Oura, no los tuyos. Viaja en
  todas las respuestas en modo muestra, que es como se distribuye la extensión,
  de modo que un modelo no puede presentar números inventados como tu sueño.
- **`rate_limited`**: Oura rechazó con un 429 y un reintento sí pasó. **Los datos
  están completos**; el aviso es sobre la *siguiente* consulta. Oura no envía
  cabeceras de límite de tasa en las respuestas correctas, así que que te
  rechacen es la única señal que existe de que estás cerca del techo.
- **`fields_split`**: `fields` llegó como `"day,score"` en vez de
  `["day","score"]` y se dividió. Ningún nombre de campo de Oura contiene una
  coma, así que dividir no es ambiguo; pero reinterpretar tu entrada en silencio
  sería exactamente el pecado del que trata todo este paquete.
- **`cached`**: la respuesta vino de la memoria de esta sesión y no de Oura. Solo
  ocurre con un rango que cerró **antes de hoy**, porque un día que ya terminó no
  puede ganar registros; hoy nunca se guarda, porque el anillo sincroniza cuando
  le da la gana. Una respuesta vacía tampoco se guarda nunca: nada distingue «no
  hay datos» de «el anillo aún no había sincronizado», y congelar lo segundo
  convertiría un hueco temporal en uno permanente. Vive en memoria y muere con el
  proceso: **nunca se escriben datos de salud en disco.**

Esa última sale de medir: **30 días de `daily_activity` son 252,000 caracteres**,
y el 87% es un solo campo, `met`, una serie de MET por minuto. Pedir tres
columnas con `fields` deja esos mismos 30 días en 5,000 caracteres: **un 99%
menos**. El servidor no recorta por su cuenta —eso sería entregar de menos—, pero
sí dice qué pesa y cómo pedir menos.

*(Los nombres de los parámetros son estables, están documentados aquí, y las
descripciones de las herramientas que lee el modelo llevan la misma información.
Estuvieron en español hasta la 0.2.0; el cambio a inglés llegó en la 0.3.0 y está
registrado en el CHANGELOG como un cambio incompatible.)*

## Lo que este servidor NO hace

**No analiza más allá de `oura_compare`.** Ni correlaciones, ni tendencias, ni
detección de anomalías, que es justamente donde otros servidores ponen su valor.

La razón: un promedio calculado aquí dentro le llega al modelo como un número sin
su método. A lo largo de nueve años de datos reales, **tres de cada cuatro
cambios entre dos mediciones consecutivas caen dentro de la oscilación normal de
la propia métrica**. Un servidor que te suelta «tu HRV subió 12%» sin decir
cuánto oscila esa métrica por sí sola no te está informando: te está fabricando
una señal.

`oura_compare` existe porque responde a esa objeción en vez de ignorarla: la
banda viene con el número. Lo demás todavía no tiene aquí un método que
sobreviva a las mismas simulaciones, así que no está. La correlación es la
siguiente candidata, y tiene más formas de engañar: patrones semanales
compartidos, tendencias compartidas y probar varios desfases hasta que uno cruce.

Todo lo demás lo obtienes en crudo. El análisis pertenece a donde se pueda citar el método;
por ejemplo a [cotejo](https://github.com/proscar87/cotejo), que hace exactamente
esa distinción para los biomarcadores en sangre.

## Las 19 colecciones

**Resúmenes diarios** — `daily_sleep`, `daily_readiness`, `daily_activity`,
`daily_stress`, `daily_spo2`, `daily_resilience`, `daily_cardiovascular_age`,
`vO2_max`

**El detalle que esconden las puntuaciones** — `sleep` (fases, HRV, temperatura,
latencia), `sleep_time`, `workout`, `session`, `rest_mode_period`, `tag`,
`enhanced_tag`

**Alta resolución** — `heartrate`, `ring_battery_level`

**Sin rango** — `personal_info`, `ring_configuration`

Las colecciones con rango de fechas usan `YYYY-MM-DD`. `heartrate` y
`ring_battery_level` usan ISO 8601 con hora.

## Otros servidores MCP de Oura

Hay varios a fecha de agosto de 2026, y conviene ser preciso sobre las
diferencias. [`benngermin/oura-mcp`](https://github.com/benngermin/oura-mcp)
**pagina correctamente**, con un cursor reanudable.
[`daveremy/oura-mcp`](https://github.com/daveremy/oura-mcp) publicó el arreglo de
`end_date` la misma semana que nosotros.
[`davidmosiah/oura-mcp`](https://github.com/davidmosiah/oura-mcp) tiene la
superficie MCP más completa. La paginación ya no distingue a nadie.

Lo que sí, hasta donde pudimos verificar: **el desfase UTC de `workout` no está
documentado en ninguno**, ni el rechazo de `latest` donde Oura lo ignora, ni el
aviso sobre campos que nunca se aplicaron. Y ninguno trata el no analizar como
una postura declarada.

## Política de privacidad

Esta sección existe porque el directorio de conectores de Claude exige una. Es
corta porque hay poco que describir: el servidor corre en tu máquina y habla con
un solo servicio, la API de Oura.

**Qué se recopila.** Nada, por nuestra parte. Los datos de salud que pides van de
la API de Oura a tu cliente MCP y no pasan por ningún servidor nuestro, porque no
lo hay.

**Qué se almacena, y dónde.** Solo tus credenciales, y solo en tu máquina:

| | |
|---|---|
| Tokens de OAuth2 | `~/.config/oura-mcp/credenciales.json`, modo `600` — o el llavero del sistema si tienes `keyring` |
| Token personal | Donde tú lo pongas: `OURA_PAT`, o el archivo al que apunte `OURA_PAT_FILE` |

No se escriben datos de salud en disco, y esa es la restricción alrededor de la
cual se diseñó la caché, no una afirmación hecha después. Las respuestas de un
día que ya cerró se guardan **solo en memoria**, mientras dure el proceso, y
`--forget` las borra. Nada relativo a tu sueño sobrevive al cierre del servidor.

**Si despliegas el Worker remoto**, vale lo mismo con una diferencia: corre en
*tu* cuenta de Cloudflare en vez de en tu máquina, así que ahí es donde viven tus
tokens de Oura — en un Durable Object — y los tokens que las apps usan para
hablar con él se guardan en KV con hash, con lo que llevan cifrado. Los datos de
salud siguen sin almacenarse nunca: se traen en cada solicitud y solo se
mantienen en la memoria del Worker. Nadie más que tú lo opera. Detalles:
[ts/worker/README.md](ts/worker/README.md#what-is-stored-and-where).

**Con quién se comparte.** Con nadie. La única conexión saliente es a
`api.ouraring.com`, con tu token, para traer lo que pediste. El uso que Oura hace
de tus datos se rige por [su política de
privacidad](https://ouraring.com/privacy-policy), no por esta.

**Cuánto tiempo se conserva.** Las credenciales, hasta que las borres:
`oura-mcp --forget`, o eliminando el archivo. Los datos de salud no se conservan
en absoluto: viven en la respuesta y ya.

**El diagnóstico no expone nada.** `oura_check` informa la longitud del token,
nunca el token; los nombres de los campos del perfil, nunca sus valores. El token
va envuelto en un tipo que no se imprime ni siquiera en un stack trace.

**Contacto.** [Los issues del repositorio](https://github.com/proscar87/oura-mcp/issues).

## Una nota sobre el idioma

El repositorio está en inglés: el código, sus comentarios, los tests y los
documentos internos (`AGENTS.md`, `ROADMAP.md`, `CHANGELOG.md`). Este documento
es la traducción del README en inglés.

Estuvo escrito en español hasta la 0.2.0. Los parámetros de las herramientas se
renombraron en la 0.3.0 —un cambio incompatible, registrado como tal en el
CHANGELOG— y la prosa fue detrás. Lo que sigue en español es alguna clave de
almacenamiento que no se puede renombrar sin dejar huérfanas credenciales que
alguien ya guardó, y hay un test que lo dice por su nombre.

## Licencia

MIT.

---

*Traducción asistida por máquina. Si algo está mal o suena raro, las correcciones
por pull request son bienvenidas:
[issues del repositorio](https://github.com/proscar87/oura-mcp/issues).*
